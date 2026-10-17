"""
services/analyze_pipeline.py
------------------------------
Phase 6 — Full Pipeline Orchestrator

CONTRACT:
  run_analysis(payload, db) -> dict
    - Pure computation. NO DB writes. NO slug awareness. NO status mutation.
    - Returns a structured report dict (3-key shape: meta, insights, examples).
    - Raises asyncio.TimeoutError if total runtime exceeds PIPELINE_TIMEOUT_S.
    - All other exceptions propagate to the ROUTER, which owns error handling.

ROUTER IS RESPONSIBLE FOR:
  - Inserting the pending report into MongoDB.
  - Calling run_analysis().
  - Writing the result to MongoDB (status=done).
  - Catching exceptions and writing status=failed + error_msg.
  - Returning the HTTP response.

TAXONOMY CACHE:
  load_taxonomy(db) is called every request but is internally lock-protected
  and idempotent (asyncio.Lock inside skill_extractor ensures exactly-once
  load even under concurrent requests from multiple Uvicorn workers).
  This module does NOT touch _cache_loaded directly.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import perf_counter

from models.report import AnalyzeRequest
from services.job_fetcher import fetch_jobs, JobFetchError, NoJobsFoundError
from services.skill_extractor import load_taxonomy, extract_skills
from services.frequency_calc import (
    calculate_frequencies,
    build_category_map,
    reliability_note,
    MIN_RELIABLE_JOB_COUNT,
)
from services.gap_engine import (
    compute_gaps,
    gap_summary,
    load_role_baselines,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

PIPELINE_TIMEOUT_S = 25.0    # Hard wall-clock limit. TimeoutError bubbles to router.
JOBS_TO_FETCH      = 100     # Adzuna pages fetched per analysis run
TOP_JOBS_LIMIT     = 20      # Max representative jobs in report
SKILL_POOL_SIZE    = 10      # Top-N skills used to score each job


# ── Public entry point ────────────────────────────────────────────────────────

async def run_analysis(
    payload: AnalyzeRequest,
    db,
) -> dict:
    """
    Orchestrate the full skill-gap analysis pipeline.

    Args:
        payload:  Validated AnalyzeRequest from the router.
        db:       AsyncIOMotorDatabase — passed through only for taxonomy loading.

    Returns:
        Structured report dict:
        {
            "meta":     { target_role, location, total_jobs, confidence,
                          generated_at, timings_ms, low_data_warning },
            "insights": { frequency_results, gap_results, gap_summary },
            "examples": { top_jobs },
        }

    Raises:
        asyncio.TimeoutError  — pipeline exceeded PIPELINE_TIMEOUT_S seconds.
        JobFetchError         — Adzuna API failure (401, 429, network error).
        Exception             — any other unexpected failure.

    NOTE: All callers must handle these exceptions and write the appropriate
    failure state to the database. This function never touches MongoDB.
    """
    return await asyncio.wait_for(
        _run_pipeline(payload, db),
        timeout=PIPELINE_TIMEOUT_S,
    )


# ── Inner pipeline (unwrapped — do not call directly outside tests) ────────────

async def _run_pipeline(payload: AnalyzeRequest, db) -> dict:
    timings: dict[str, int] = {}
    t_total = perf_counter()

    logger.info(
        "[Pipeline] START — role=%r location=%r",
        payload.target_role, payload.location,
    )

    # ── Stage 0: Taxonomy (cached after first load) ───────────────────────────
    # load_taxonomy() is idempotent and asyncio.Lock-protected internally.
    # Calling it here ensures the cache is warm before extract_skills().
    await load_taxonomy(db)

    # ── Stage 1: Fetch jobs ───────────────────────────────────────────────────
    t0 = perf_counter()
    jobs: list[dict] = await fetch_jobs(
        role=payload.target_role,
        location=payload.location,
        limit=JOBS_TO_FETCH,
    )
    timings["fetch"] = round((perf_counter() - t0) * 1000)
    logger.info("[Pipeline] fetch done — %d jobs in %dms", len(jobs), timings["fetch"])

    n = len(jobs)
    if n == 0:
        raise NoJobsFoundError(
            f"No job postings found for '{payload.target_role}' in '{payload.location}'. "
            "Try a broader or different job title."
        )
    low_data_warning = n < MIN_RELIABLE_JOB_COUNT

    # ── Stage 2: Extract skills ───────────────────────────────────────────────
    t0 = perf_counter()
    descriptions: list[str] = [j["description"] for j in jobs]
    skill_sets: list[set[str]] = await extract_skills(descriptions)
    timings["extract"] = round((perf_counter() - t0) * 1000)
    logger.info("[Pipeline] extract done in %dms", timings["extract"])

    # ── Stage 3: Frequency ────────────────────────────────────────────────────
    t0 = perf_counter()
    category_map  = build_category_map()
    freq_results  = calculate_frequencies(skill_sets, max(n, 1), category_map)
    timings["frequency"] = round((perf_counter() - t0) * 1000)
    logger.info(
        "[Pipeline] frequency done — %d unique skills in %dms",
        len(freq_results), timings["frequency"],
    )

    # ── Stage 4: Gap detection ────────────────────────────────────────────────
    t0 = perf_counter()
    role_baselines = load_role_baselines()
    gap_results    = compute_gaps(
        frequency_results=freq_results,
        total_jobs=max(n, 1),
        current_role=payload.current_role,
        role_baselines=role_baselines,
    )
    summary = gap_summary(gap_results)
    timings["gap"] = round((perf_counter() - t0) * 1000)
    logger.info("[Pipeline] gap done in %dms", timings["gap"])

    # ── Stage 5: Score & select top jobs ──────────────────────────────────────
    t0 = perf_counter()
    top_jobs = _score_top_jobs(jobs, skill_sets, freq_results)
    timings["scoring"] = round((perf_counter() - t0) * 1000)
    logger.info(
        "[Pipeline] scoring done — %d top jobs selected in %dms",
        len(top_jobs), timings["scoring"],
    )

    timings["total"] = round((perf_counter() - t_total) * 1000)
    logger.info(
        "[Pipeline] COMPLETE — total=%dms  (fetch=%d extract=%d freq=%d gap=%d score=%d)",
        timings["total"], timings["fetch"], timings["extract"],
        timings["frequency"], timings["gap"], timings["scoring"],
    )

    # Extract gap mode signals for meta (no silent fallback)
    gap_mode          = summary.get("gap_mode", "market-only")
    baseline_supported = summary.get("baseline_supported", False)

    return {
        "meta": {
            "target_role":      payload.target_role,
            "location":         payload.location,
            "total_jobs":       n,
            "confidence":       reliability_note(n),
            "generated_at":     datetime.now(timezone.utc).isoformat(),
            "timings_ms":       timings,
            "low_data_warning": low_data_warning,
            "gap_mode":         gap_mode,
            "baseline_supported": baseline_supported,
        },
        "insights": {
            "frequency_results": freq_results,
            "gap_results":       gap_results,
            "gap_summary":       summary,
        },
        "examples": {
            "top_jobs": top_jobs,
        },
    }


# ── Scoring helper (module-private) ───────────────────────────────────────────

def _score_top_jobs(
    jobs: list[dict],
    skill_sets: list[set[str]],
    freq_results: list[dict],
    *,
    top_n:      int = TOP_JOBS_LIMIT,
    skill_pool: int = SKILL_POOL_SIZE,
) -> list[dict]:
    """
    Score each job by the fraction of top-N demanded skills it covers.

    score = |job_skills ∩ top_skills| / skill_pool * 100  (rounded to 1dp)

    Args:
        jobs:         Raw job dicts from fetch_jobs (include description).
        skill_sets:   Parallel list of canonical skill sets from extract_skills.
        freq_results: Sorted frequency list from calculate_frequencies.
        top_n:        Max number of jobs to return.
        skill_pool:   How many top skills form the scoring pool.

    Returns:
        Up to top_n jobs, sorted descending by skill_match_score.
        Description field is EXPLICITLY DROPPED — only metadata is returned.
    """
    # Build pool of top `skill_pool` demanded canonical skill names
    top_skills: set[str] = {r["skill"] for r in freq_results[:skill_pool]}
    denominator = max(len(top_skills), 1)  # guard against empty taxonomy

    scored: list[dict] = []
    for i, job in enumerate(jobs):
        job_skills = skill_sets[i] if i < len(skill_sets) else set()
        score = round(len(job_skills & top_skills) / denominator * 100, 1)
        scored.append({
            "external_id":       job.get("external_id", ""),
            "title":             job.get("title", ""),
            "company":           job.get("company"),          # Optional[str], may be None
            "redirect_url":      job.get("redirect_url", ""),
            "skill_match_score": score,
            # "description" intentionally omitted — never persisted
        })

    scored.sort(key=lambda x: -x["skill_match_score"])
    return scored[:top_n]
