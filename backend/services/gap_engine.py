"""
services/gap_engine.py
-----------------------
Phase 5 — Gap Engine

Enriches frequency data with gap detection, priority scoring,
and confidence levels relative to the user's current role.

Architecture
============
Like frequency_calc.py, this module is STATELESS and PURE:
  - No I/O, no DB calls, no async.
  - Accepts pre-loaded frequency results and role baselines.
  - Returns an enriched copy of the frequency list (originals untouched).

Two operating modes
===================
1. BASELINE MODE  (current_role found in role_baselines)
   - is_gap = True  if skill is NOT in baseline AND frequency_pct >= GAP_THRESHOLD_PCT
   - is_gap = False if skill IS in baseline (practitioner already has it)

2. MARKET-ONLY MODE (current_role not found, or not provided)
   - is_gap = None  (gap concept does not apply)
   - Still returns priority + confidence — useful for pure market intelligence.

Design reasoning
================
We intentionally keep gap detection as a heuristic (threshold-based):
  - No user profile required for MVP.
  - Baselines are curated, not user-submitted (avoids cold-start UX problem).
  - Threshold (30%) as the floor prevents noise skills from being gaps.
  See bottom of module for a full critique of the heuristic approach.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────

GAP_THRESHOLD_PCT   = 30.0   # A skill must appear in >= 30% of jobs to be a gap
HIGH_PRIORITY_PCT   = 60.0   # >= 60% → High priority
MEDIUM_PRIORITY_PCT = 30.0   # 30–59% → Medium priority
# < 30% → Low priority (not a gap — below gap threshold by definition)

CONFIDENCE_LOW_MAX      = 20  # < 20 jobs → Low confidence
CONFIDENCE_MODERATE_MAX = 50  # 20–49 jobs → Moderate confidence
# >= 50 jobs → High confidence

# ── Type aliases ─────────────────────────────────────────────────────────────

Priority   = Literal["High", "Medium", "Low"]
Confidence = Literal["Low", "Moderate", "High"]

# ── Default baselines path ────────────────────────────────────────────────────

_DEFAULT_BASELINES_PATH = Path(__file__).parent.parent / "data" / "role_baselines.json"


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_role_baselines(
    path: Path | str | None = None,
) -> dict[str, list[str]]:
    """
    Load role_baselines.json from disk.

    Args:
        path: Override path. Uses data/role_baselines.json by default.

    Returns:
        Dict mapping role name → list of canonical skill names.
        The _meta key is stripped before returning.

    Raises:
        FileNotFoundError: if the file does not exist.
        json.JSONDecodeError: if the file is not valid JSON.
    """
    target = Path(path) if path else _DEFAULT_BASELINES_PATH
    raw = json.loads(target.read_text(encoding="utf-8"))
    raw.pop("_meta", None)

    # Normalise: role names to lowercase keys for case-insensitive lookup
    baselines: dict[str, list[str]] = {
        role.strip(): skills
        for role, skills in raw.items()
    }
    logger.debug("[GapEngine] Loaded baselines for %d roles.", len(baselines))
    return baselines


# Word-level synonyms applied before baseline lookup.
# Maps free-form words users commonly type -> canonical word in baseline key.
_ROLE_WORD_SYNONYMS: dict[str, str] = {
    "developer":  "engineer",
    "dev":        "engineer",
    "programmer": "engineer",
    "swe":        "software engineer",
    "sde":        "software engineer",
    "eng":        "engineer",
    "ml":         "machine learning",
    "ai":         "machine learning",
    "fullstack":  "full stack",
    "full-stack": "full stack",
}


def _normalize_role(role: str) -> str:
    """Lowercase, collapse whitespace, apply word-level synonyms."""
    tokens = role.strip().lower().split()
    normalized = []
    i = 0
    while i < len(tokens):
        word = _ROLE_WORD_SYNONYMS.get(tokens[i], tokens[i])
        normalized.append(word)
        i += 1
    return " ".join(normalized)


def _lookup_baseline(
    current_role: str,
    baselines: dict[str, list[str]],
) -> set[str] | None:
    """
    Look up a role in baselines with 4 fallback levels:
      1. Exact match
      2. Case-insensitive exact match
      3. Synonym-normalized match  (e.g. 'frontend developer' -> 'Frontend Engineer')
      4. Token-overlap best match  (>= 50% tokens shared)

    Returns set of skills, or None if no match found.
    """
    # 1. Exact match
    if current_role in baselines:
        return set(baselines[current_role])

    # 2. Case-insensitive exact
    lower_input = current_role.strip().lower()
    for role, skills in baselines.items():
        if role.lower() == lower_input:
            return set(skills)

    # 3. Synonym-normalized match
    norm_input = _normalize_role(current_role)
    for role, skills in baselines.items():
        if _normalize_role(role) == norm_input:
            logger.info("[GapEngine] Synonym match: '%s' -> '%s'", current_role, role)
            return set(skills)

    # 4. Token-overlap: find the baseline role with most shared normalized words
    input_tokens = set(norm_input.split())
    best_role, best_overlap = None, 0
    for role, skills in baselines.items():
        role_tokens = set(_normalize_role(role).split())
        overlap = len(input_tokens & role_tokens)
        # Require >= 1 overlap AND at least half of input tokens matched
        if overlap > best_overlap and overlap >= max(1, len(input_tokens) // 2):
            best_role, best_overlap = role, overlap

    if best_role:
        logger.info(
            "[GapEngine] Token-overlap match: '%s' -> '%s' (overlap=%d)",
            current_role, best_role, best_overlap,
        )
        return set(baselines[best_role])

    return None


# ── Priority + Confidence helpers ─────────────────────────────────────────────

def _priority(freq_pct: float) -> Priority:
    if freq_pct >= HIGH_PRIORITY_PCT:
        return "High"
    if freq_pct >= MEDIUM_PRIORITY_PCT:
        return "Medium"
    return "Low"


def _confidence(total_jobs: int) -> Confidence:
    if total_jobs < CONFIDENCE_LOW_MAX:
        return "Low"
    if total_jobs < CONFIDENCE_MODERATE_MAX:
        return "Moderate"
    return "High"


# ── Main function ─────────────────────────────────────────────────────────────

def compute_gaps(
    frequency_results: list[dict],
    total_jobs: int,
    current_role: str | None = None,
    role_baselines: dict[str, list[str]] | None = None,
) -> list[dict]:
    """
    Enrich frequency results with gap detection, priority, and confidence.

    Args:
        frequency_results:
            Output of frequency_calc.calculate_frequencies().
            Each dict has: skill, job_count, frequency_pct, category.
            This list is NOT modified — a fresh enriched copy is returned.

        total_jobs:
            Used to compute confidence level. Should match the value
            passed to calculate_frequencies().

        current_role:
            The user's current job role (e.g. "Data Engineer").
            Case-insensitive lookup is performed. If None or not found
            in baselines, MARKET-ONLY MODE is used (is_gap = None).

        role_baselines:
            Dict loaded by load_role_baselines(). If not provided and
            current_role is given, load_role_baselines() is called
            automatically from the default path.

    Returns:
        List of enriched dicts, one per skill. Schema:
        {
            "skill":         str,
            "frequency_pct": float,
            "category":      str,
            "job_count":     int,
            "is_gap":        bool | None,
            "priority":      "High" | "Medium" | "Low",
            "confidence":    "Low" | "Moderate" | "High",
        }
        Preserves the descending frequency_pct sort order from frequency_calc.

    Raises:
        ValueError: if frequency_results is None or total_jobs < 1.
    """
    if frequency_results is None:
        raise ValueError("frequency_results must not be None.")
    if total_jobs < 1:
        raise ValueError(f"total_jobs must be >= 1, got {total_jobs}.")

    # ── Resolve baseline ──────────────────────────────────────────────────────
    baseline_skills: set[str] | None = None
    mode = "market-only"

    if current_role:
        if role_baselines is None:
            try:
                role_baselines = load_role_baselines()
            except FileNotFoundError:
                logger.warning(
                    "[GapEngine] role_baselines.json not found. "
                    "Falling back to market-only mode."
                )

        if role_baselines:
            baseline_skills = _lookup_baseline(current_role, role_baselines)

        if baseline_skills is not None:
            mode = "baseline"
            logger.info(
                "[GapEngine] Baseline mode: role='%s', baseline_size=%d skills.",
                current_role, len(baseline_skills),
            )
        else:
            logger.warning(
                "[GapEngine] Role '%s' not found in baselines. "
                "Market-only mode activated.",
                current_role,
            )

    else:
        logger.info("[GapEngine] No current_role provided. Market-only mode.")

    # ── Compute confidence once (same for all skills in this run) ─────────────
    confidence_label = _confidence(total_jobs)

    # ── Enrich each frequency record ──────────────────────────────────────────
    enriched: list[dict] = []
    n_gaps = 0

    for record in frequency_results:
        skill     = record["skill"]
        freq_pct  = record["frequency_pct"]
        priority  = _priority(freq_pct)

        if mode == "baseline":
            # A gap = market demands it at >= threshold AND practitioner lacks it.
            if skill in baseline_skills:
                is_gap = False          # already known skill, not a gap
            elif freq_pct >= GAP_THRESHOLD_PCT:
                is_gap = True           # demanded & missing → true gap
                n_gaps += 1
            else:
                is_gap = False          # missing but low-demand → not actionable
        else:
            is_gap = None               # market-only: concept of gap doesn't apply

        enriched.append({
            "skill":         skill,
            "frequency_pct": freq_pct,
            "category":      record.get("category", "Unknown"),
            "job_count":     record.get("job_count", 0),
            "is_gap":        is_gap,
            "priority":      priority,
            "confidence":    confidence_label,
        })

    logger.info(
        "[GapEngine] mode=%s | total_skills=%d | gaps_found=%s | confidence=%s",
        mode,
        len(enriched),
        n_gaps if mode == "baseline" else "n/a",
        confidence_label,
    )

    return enriched


# ── Summary helper ────────────────────────────────────────────────────────────

def gap_summary(gap_results: list[dict]) -> dict:
    """
    Produce a compact summary dict from the output of compute_gaps().

    Suitable for embedding at the top of an API response or report.

    Returns:
        {
            "gap_mode":             "baseline-driven" | "market-only",
            "baseline_supported":   bool,
            "mode":                 (same as gap_mode — kept for backwards compat),
            "total_skills":         int,
            "high_priority_gaps":   int,
            "medium_priority_gaps": int,
            "top_gaps": [{"skill": str, "frequency_pct": float}, ...]  (up to 5)
        }
    """
    baseline_supported = not any(r["is_gap"] is None for r in gap_results)
    gap_mode = "baseline-driven" if baseline_supported else "market-only"

    high_gaps   = [r for r in gap_results if r["is_gap"] and r["priority"] == "High"]
    medium_gaps = [r for r in gap_results if r["is_gap"] and r["priority"] == "Medium"]
    top_gaps    = (high_gaps + medium_gaps)[:5]

    return {
        "gap_mode":              gap_mode,
        "baseline_supported":    baseline_supported,
        "mode":                  gap_mode,   # backwards-compat alias
        "total_skills":          len(gap_results),
        "high_priority_gaps":    len(high_gaps),
        "medium_priority_gaps":  len(medium_gaps),
        "top_gaps": [
            {"skill": r["skill"], "frequency_pct": r["frequency_pct"]}
            for r in top_gaps
        ],
    }
