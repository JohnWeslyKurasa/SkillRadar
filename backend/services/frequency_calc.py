"""
services/frequency_calc.py
--------------------------
Phase 4 — Frequency Calculator

Converts raw per-job skill sets into a ranked, percentage-based frequency table.

Design
======
This module is intentionally STATELESS and PURE:
  - No I/O, no DB calls, no async.
  - Input is entirely in-memory (already fetched + extracted).
  - Category data is passed in as a pre-built map (built by the analyze pipeline
    from the skill_extractor in-memory cache). This keeps the function testable
    and free of hidden dependencies.

Called by the analyze pipeline AFTER:
  1. fetch_jobs()         — job descriptions retrieved from Adzuna
  2. load_taxonomy(db)    — taxonomy loaded into skill_extractor cache
  3. extract_skills()     — descriptions → List[Set[str]] of canonical names

Why job-level frequency (not raw word count)?
See module docstring bottom section.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TypedDict

logger = logging.getLogger(__name__)

# ── Output schema ─────────────────────────────────────────────────────────────

class SkillFrequency(TypedDict):
    """
    Frequency record for one canonical skill across all analyzed jobs.

    Fields:
        skill          Canonical skill name (e.g. "Python")
        job_count      Number of job descriptions containing this skill
        frequency_pct  job_count / total_jobs * 100, rounded to 1 decimal
        category       From taxonomy: "Technical" | "Tool" | "Soft Skill" | "Certification"
    """
    skill:         str
    job_count:     int
    frequency_pct: float
    category:      str


# ── Minimum job threshold ─────────────────────────────────────────────────────
# Below this count, frequency percentages are statistically unreliable.
# Used as a soft warning — caller decides whether to honour it.
MIN_RELIABLE_JOB_COUNT = 30


# ── Main function ─────────────────────────────────────────────────────────────

def calculate_frequencies(
    skill_sets: list[set[str]],
    total_jobs: int,
    category_map: dict[str, str],
    *,
    exclude_soft_skills: bool = False,
    min_frequency_pct: float = 0.0,
) -> list[SkillFrequency]:
    """
    Calculate per-skill job frequency across a list of job postings.

    Args:
        skill_sets:
            One set of canonical skill names per job description.
            Produced by skill_extractor.extract_skills().
            Each skill appears AT MOST ONCE per job (set guarantees this).

        total_jobs:
            Denominator for frequency calculation.
            Must equal len(skill_sets). Passed explicitly so the caller
            can cap it (e.g. if fetcher returned fewer than requested).

        category_map:
            Dict mapping canonical skill name → category string.
            Build from skill_extractor._cache:
                {entry.canonical: entry.category for entry in _cache}
            Skills not found in the map get category "Unknown".

        exclude_soft_skills:
            If True, omit all skills with category "Soft Skill".
            Default: False (include everything).

        min_frequency_pct:
            Omit skills with frequency below this threshold.
            Default: 0.0 (include all skills that appear at least once).

    Returns:
        List of SkillFrequency dicts, sorted descending by frequency_pct.
        Ties broken alphabetically by skill name.

    Raises:
        ValueError: if total_jobs < 1 (division by zero guard).
    """
    if total_jobs < 1:
        raise ValueError(
            f"total_jobs must be >= 1, got {total_jobs}. "
            "Cannot calculate frequency without job data."
        )

    if total_jobs < MIN_RELIABLE_JOB_COUNT:
        logger.warning(
            "[FrequencyCalc] Low sample size: %d jobs (recommended minimum: %d). "
            "Frequency percentages may not be statistically reliable.",
            total_jobs, MIN_RELIABLE_JOB_COUNT,
        )

    # ── Count: each skill contributes +1 per JOB it appears in ───────────────
    # Sets already guarantee one-count-per-job.
    # We use Counter rather than defaultdict to get a clean sorted interface.
    job_counter: Counter[str] = Counter()
    for skill_set in skill_sets:
        for skill in skill_set:
            job_counter[skill] += 1

    if not job_counter:
        logger.warning("[FrequencyCalc] No skills found across %d jobs.", total_jobs)
        return []

    # ── Build frequency records ───────────────────────────────────────────────
    results: list[SkillFrequency] = []

    for skill, count in job_counter.items():
        category = category_map.get(skill, "Unknown")

        # Apply filters
        if exclude_soft_skills and category == "Soft Skill":
            continue

        freq_pct = round(count / total_jobs * 100, 1)
        if freq_pct < min_frequency_pct:
            continue

        results.append(
            SkillFrequency(
                skill=skill,
                job_count=count,
                frequency_pct=freq_pct,
                category=category,
            )
        )

    # ── Sort: descending frequency, alphabetical tiebreak ────────────────────
    results.sort(key=lambda r: (-r["frequency_pct"], r["skill"]))

    logger.info(
        "[FrequencyCalc] total_jobs=%d | unique_skills_found=%d | "
        "skills_after_filter=%d | top_skill=%s (%.1f%%)",
        total_jobs,
        len(job_counter),
        len(results),
        results[0]["skill"] if results else "none",
        results[0]["frequency_pct"] if results else 0.0,
    )

    return results


# ── Convenience: build category_map from skill_extractor cache ────────────────

def build_category_map() -> dict[str, str]:
    """
    Build a canonical → category lookup dict from the skill_extractor cache.

    Call this AFTER skill_extractor.load_taxonomy(db) has been awaited.
    Safe to call multiple times (cache is read-only here).

    Returns:
        Dict mapping e.g. {"Python": "Technical", "Scrum": "Soft Skill", ...}
    """
    from services.skill_extractor import _cache   # import here to avoid circular deps

    if not _cache:
        logger.warning(
            "[FrequencyCalc] skill_extractor cache is empty. "
            "Call load_taxonomy(db) before build_category_map()."
        )
        return {}

    category_map = {entry.canonical: entry.category for entry in _cache}
    logger.debug(
        "[FrequencyCalc] Built category map from %d cached skills.", len(category_map)
    )
    return category_map


# ── Reliability helper ───────────────────────────────────────────────────────

def reliability_note(total_jobs: int) -> str:
    """
    Return a human-readable note about the statistical reliability of the results.
    Intended for inclusion in the API response / report UI.

    Examples:
        reliability_note(10)  → "Based on 10 job postings. Low sample — treat as indicative only."
        reliability_note(50)  → "Based on 50 job postings."
        reliability_note(100) → "Based on 100 job postings. High confidence."
    """
    if total_jobs < 20:
        return (
            f"Based on {total_jobs} job postings. "
            "Very low sample — treat as directional only, not statistically significant."
        )
    if total_jobs < MIN_RELIABLE_JOB_COUNT:
        return (
            f"Based on {total_jobs} job postings. "
            "Moderate sample — results may shift as more postings are analyzed."
        )
    if total_jobs >= 100:
        return (
            f"Based on {total_jobs} job postings. High confidence."
        )
    return f"Based on {total_jobs} job postings."
