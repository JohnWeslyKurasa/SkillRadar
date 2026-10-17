"""
services/skill_extractor.py
---------------------------
Keyword-based skill extraction engine. No NLP libraries. No spaCy.

Architecture
============
The extractor works in two stages that are deliberately separated:

  Stage A — load_taxonomy(db)
    Called ONCE per analysis (or at app startup).
    Fetches all skill documents from MongoDB `skill_taxonomy` collection,
    compiles one regex pattern per alias, and stores everything in a
    module-level cache. Subsequent calls hit the cache (no DB round-trip).

  Stage B — extract_skills(job_descriptions)
    Called with a list of raw job description strings.
    Runs against the in-memory compiled pattern cache.
    Returns one set of canonical skill names per description.

Why a module-level cache instead of passing db everywhere?
  The function signature is fixed to `list[str] -> list[set[str]]`.
  Taxonomy rarely changes (seeded once, updated infrequently).
  Compiling 400+ regexes per call would be wasteful.
  The cache makes the hot path (extract_skills) pure CPU — no I/O.

Regex boundary strategy
=======================
We use TWO boundary approaches depending on the alias:

  1. For purely alphanumeric aliases  ("python", "docker", "java"):
       pattern = r'(?i)\\b{alias}\\b'
     \\b matches between a word char (\\w = [a-zA-Z0-9_]) and a non-word char.
     This correctly prevents "java" matching inside "javascript" because 's'
     follows 'a' — there is no word boundary between them.

  2. For aliases containing special characters (".net", "c++", "node.js"):
       pattern = r'(?i)(?<![\\w.+#])alias_escaped(?![\\w.+#])'
     \\b fails for non-\\w chars (a + after "c" is not a word char, so \\b
     would fire incorrectly). We use negative lookahead/lookbehind with a
     custom character class that includes the symbols likely to appear in
     tech names: ., +, #.

Normalization pipeline
======================
Before matching, each description is:
  1. Lowercased (but we use (?i) in regex too — belt and braces)
  2. Punctuation collapsed to spaces (commas, colons, semicolons, parens)
     EXCEPT: ., +, #, / which appear in real skill names (C++, .NET, C#, Node.js)
  3. Multiple consecutive spaces collapsed to one

The alias patterns are compiled against normalized text.
"""

from __future__ import annotations

import asyncio
import logging
import re
import string
import time
from dataclasses import dataclass, field
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# ── Module-level taxonomy cache ───────────────────────────────────────────────
# Populated by load_taxonomy(db). Read-only after that.

@dataclass
class SkillEntry:
    """One skill from the taxonomy, with pre-compiled regex patterns."""
    canonical: str                          # e.g. "Python"
    category: str                           # Technical | Soft | Tool | Certification
    patterns: list[re.Pattern] = field(default_factory=list)   # one per alias


_cache: list[SkillEntry] = []
_cache_loaded: bool = False
_cache_lock = asyncio.Lock()


# ── Punctuation normalizer ────────────────────────────────────────────────────
# We strip "dumb" punctuation (commas, brackets, semicolons) but PRESERVE
# characters that appear in real skill names: . + # / -
_STRIP_PUNCT = re.compile(r"[,;:()\[\]{}'\"!?@$%^&*~`]")
_MULTI_SPACE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    """
    Prepare a job description for alias matching.

    Steps:
      1. Lowercase
      2. Replace 'dumb' punctuation with spaces (preserves . + # / -)
      3. Collapse multiple whitespace into one space
    """
    text = text.lower()
    text = _STRIP_PUNCT.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


# ── Regex pattern builder ─────────────────────────────────────────────────────
_SPECIAL_CHARS = set(".+#-/")
_CUSTOM_BOUNDARY = r"(?<![a-zA-Z0-9.+#]){}(?![a-zA-Z0-9.+#])"


def _build_pattern(alias: str) -> Optional[re.Pattern]:
    """
    Compile a case-insensitive regex for a single alias string.

    Boundary strategy:
      - Alphanumeric alias  → use \\b word boundaries (safe, fast)
      - Contains special chars → use negative lookaround with custom char class

    Returns None if the alias is too short (< 2 chars) to be meaningful.
    """
    alias = alias.strip()
    if len(alias) < 2:
        # Single-char aliases like "R" are valid skills but dangerously broad.
        # We allow them but require extra-strict boundary: must be surrounded
        # by whitespace or start/end of string (not just any non-word char).
        pattern_str = r"(?i)(?:^|\s)" + re.escape(alias) + r"(?:\s|$)"
        return re.compile(pattern_str, re.IGNORECASE)

    has_special = any(c in _SPECIAL_CHARS for c in alias)

    if has_special:
        # e.g.: ".net" → (?<![a-zA-Z0-9.+#])\.net(?![a-zA-Z0-9.+#])
        pattern_str = _CUSTOM_BOUNDARY.format(re.escape(alias))
    else:
        # e.g.: "python" → \bpython\b
        pattern_str = r"\b" + re.escape(alias) + r"\b"

    try:
        return re.compile(pattern_str, re.IGNORECASE)
    except re.error as e:
        logger.warning("[SkillExtractor] Failed to compile pattern for '%s': %s", alias, e)
        return None


# ── Taxonomy loader ───────────────────────────────────────────────────────────

async def load_taxonomy(db: AsyncIOMotorDatabase) -> int:
    """
    Load the skill taxonomy from MongoDB into the module-level cache.

    Thread-safe (uses asyncio.Lock). Safe to call multiple times —
    only loads once. Returns the number of skills loaded.

    Expected MongoDB document shape:
      {
        "canonical": "Python",
        "aliases":   ["python", "python3", "python 3", "py"],
        "category":  "Technical"
      }

    Call this BEFORE extract_skills(). Typically called once per analysis
    request (or wired into app startup for a persistent warm cache).
    """
    global _cache, _cache_loaded

    async with _cache_lock:
        if _cache_loaded:
            logger.debug("[SkillExtractor] Taxonomy cache already loaded (%d skills).", len(_cache))
            return len(_cache)

        t_start = time.perf_counter()
        entries: list[SkillEntry] = []
        pattern_failures = 0

        cursor = db["skill_taxonomy"].find({}, {"_id": 0})
        async for doc in cursor:
            canonical = doc.get("canonical", "").strip()
            category  = doc.get("category", "Technical")
            aliases   = doc.get("aliases", [])

            if not canonical:
                continue

            # Always include the canonical name itself as an alias
            all_aliases = list({canonical.lower()} | {a.lower() for a in aliases})
            patterns: list[re.Pattern] = []

            for alias in all_aliases:
                p = _build_pattern(alias)
                if p:
                    patterns.append(p)
                else:
                    pattern_failures += 1

            if patterns:
                entries.append(SkillEntry(canonical=canonical, category=category, patterns=patterns))

        _cache = entries
        _cache_loaded = True
        elapsed = round((time.perf_counter() - t_start) * 1000, 2)

        logger.info(
            "[SkillExtractor] Taxonomy loaded: %d skills, %d total patterns, "
            "%d pattern failures, %.2fms",
            len(_cache), sum(len(e.patterns) for e in _cache),
            pattern_failures, elapsed,
        )

        return len(_cache)


def reset_taxonomy_cache() -> None:
    """
    Clear the in-memory cache. Useful in tests or after a taxonomy update.
    Not async — safe to call synchronously since it just resets module state.
    """
    global _cache, _cache_loaded
    _cache = []
    _cache_loaded = False
    logger.info("[SkillExtractor] Taxonomy cache cleared.")


# ── Main extraction function ──────────────────────────────────────────────────

async def extract_skills(job_descriptions: list[str]) -> list[set[str]]:
    """
    Extract canonical skill names from a list of job description strings.

    Args:
        job_descriptions: Raw text of each job posting's description field.

    Returns:
        A list of sets, one per description.
        Each set contains the canonical skill names found in that description.
        Order matches the input list index-for-index.

    Raises:
        RuntimeError: If load_taxonomy() has not been called yet.

    Example:
        descriptions = [
            "We need Python, SQL, and experience with AWS.",
            "Looking for a React developer who knows TypeScript and Node.js.",
        ]
        result = await extract_skills(descriptions)
        # result[0] → {"Python", "SQL", "AWS"}
        # result[1] → {"React", "TypeScript", "Node.js"}
    """
    if not _cache_loaded:
        raise RuntimeError(
            "Skill taxonomy not loaded. "
            "Call `await load_taxonomy(db)` before using extract_skills()."
        )

    if not job_descriptions:
        return []

    if not _cache:
        logger.warning("[SkillExtractor] Taxonomy cache is empty — no skills will be matched.")
        return [set() for _ in job_descriptions]

    t_start = time.perf_counter()
    results: list[set[str]] = []

    for i, raw_description in enumerate(job_descriptions):
        normalized = _normalize_text(raw_description)
        found: set[str] = set()

        for entry in _cache:
            # Stop checking this skill once matched — one mention per job is enough
            for pattern in entry.patterns:
                if pattern.search(normalized):
                    found.add(entry.canonical)
                    break   # ← prevents double-counting via multiple aliases

        results.append(found)

    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 2)
    total_matches = sum(len(s) for s in results)

    logger.info(
        "[SkillExtractor] Extracted skills from %d descriptions: "
        "%d total skill matches in %.2fms (avg %.2f skills/job)",
        len(job_descriptions),
        total_matches,
        elapsed_ms,
        total_matches / len(job_descriptions) if job_descriptions else 0,
    )

    return results


# ── Unknown token logger (opt-in) ─────────────────────────────────────────────

def log_unknown_tokens(
    descriptions: list[str],
    known_skills: set[str],
    top_n: int = 20,
) -> dict[str, int]:
    """
    Optional diagnostic: find high-frequency capitalized tokens in descriptions
    that are NOT in the known skill canonical names.

    Use this to identify skills the taxonomy is missing.

    Args:
        descriptions: Raw job description strings.
        known_skills: Set of canonical skill names already in taxonomy.
        top_n:        How many top unknown tokens to return.

    Returns:
        Dict of {token: frequency} sorted descending by frequency.

    Usage:
        unknown = log_unknown_tokens(raw_descriptions, {e.canonical for e in _cache})
        logger.info("[SkillExtractor] Top unknown tokens: %s", unknown)
    """
    from collections import Counter

    # Tokenize: extract capitalized words and acronyms (likely skill names)
    token_pattern = re.compile(r'\b[A-Z][a-zA-Z0-9.+#]*\b')
    known_lower = {s.lower() for s in known_skills}

    counter: Counter = Counter()
    for desc in descriptions:
        tokens = token_pattern.findall(desc)
        for token in tokens:
            if token.lower() not in known_lower and len(token) > 1:
                counter[token] += 1

    top = dict(counter.most_common(top_n))
    if top:
        logger.info(
            "[SkillExtractor] Top %d unknown tokens (possible missing skills): %s",
            top_n, top,
        )
    return top
