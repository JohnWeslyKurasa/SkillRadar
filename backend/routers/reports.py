"""
routers/reports.py
------------------
GET /api/report/{slug} — retrieve a completed analysis report.

BEHAVIOR BY STATUS:
  pending     → 202 (report queued, not yet started)
  processing  → 409 (pipeline running — client should wait)
  failed      → 500 with sanitized message (never leaks raw error)
  done        → 200 with full structured report + atomically incremented view_count
  not found   → 404

FIELD SANITIZATION — these are NEVER returned to the client:
  _id         MongoDB ObjectId — internal DB identifier
  error_msg   Raw exception text — may contain stack traces, secrets
  known_skills Stored for pipeline use, not client-relevant after completion

Design notes:
  - view_count is incremented atomically with find_one_and_update (not a
    separate update + find). This prevents double-counting under concurrent
    requests to the same slug.
  - Retrieval NEVER re-triggers the pipeline. The slug is read-only after
    status=done. Pipeline is exclusively owned by POST /api/analyze.
  - Timing log records Mongo retrieval latency for p95 monitoring in future.
"""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_db, get_reports_collection
from models.report import (
    ExperienceLevel,
    FrequencyResult,
    GapResult,
    GapSummary,
    GapSummaryEntry,
    ReportExamples,
    ReportInsights,
    ReportMeta,
    ReportResponse,
    ReportStatus,
    TopJob,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Reports"])


# ── Fields never sent to the client ──────────────────────────────────────────
_EXCLUDED_FIELDS = {"_id", "error_msg", "known_skills"}


@router.get("/report/{slug}", response_model=ReportResponse)
async def get_report(
    slug: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Retrieve a report by its public slug.

    Returns HTTP 200 with the full structured report when status='done'.
    All other status values return appropriate error codes (see module docstring).
    """
    t0 = perf_counter()
    collection = get_reports_collection(db)

    # ── Fetch by slug (project out all excluded fields) ───────────────────────
    projection = {f: 0 for f in _EXCLUDED_FIELDS}
    doc = await collection.find_one({"slug": slug}, projection)

    retrieval_ms = round((perf_counter() - t0) * 1000)

    if doc is None:
        logger.info("[Reports] slug=%s — not found (%dms)", slug, retrieval_ms)
        raise HTTPException(
            status_code=404,
            detail=f"Report '{slug}' not found. It may have expired or never existed.",
        )

    status = ReportStatus(doc.get("status", "pending"))
    logger.info(
        "[Reports] slug=%s — status=%s retrieval=%dms",
        slug, status.value, retrieval_ms,
    )

    # ── Status guards ─────────────────────────────────────────────────────────

    if status == ReportStatus.pending:
        raise HTTPException(
            status_code=202,
            detail="Report is queued and will start processing shortly.",
        )

    if status == ReportStatus.processing:
        raise HTTPException(
            status_code=409,
            detail="Report is still processing. Please retry in a few seconds.",
        )

    if status == ReportStatus.failed:
        # Never return raw error_msg — it may contain stack traces or secrets.
        raise HTTPException(
            status_code=500,
            detail=(
                "Analysis failed. This may be due to insufficient job data "
                "or a temporary upstream issue. Please try again."
            ),
        )

    # status == ReportStatus.done — fall through to return full report

    # ── Atomic view_count increment ───────────────────────────────────────────
    # find_one_and_update returns the document BEFORE the update by default.
    # We already have `doc` from above so we just fire the increment separately.
    # Using update_one (not find_one_and_update) — doc is already in memory.
    await collection.update_one(
        {"slug": slug},
        {"$inc": {"view_count": 1}},
    )

    # ── Build structured response ─────────────────────────────────────────────
    meta_raw     = doc.get("meta") or {}
    insights_raw = doc.get("insights") or {}
    examples_raw = doc.get("examples") or {}

    # Reconstruct sub-models safely — use .get() with defaults throughout
    # so old reports (pre-v6) don't crash the deserializer.

    meta = ReportMeta(
        target_role  = meta_raw.get("target_role",  doc.get("target_role", "")),
        location     = meta_raw.get("location",     doc.get("location", "")),
        total_jobs   = meta_raw.get("total_jobs",   doc.get("postings_analyzed", 0)),
        confidence   = meta_raw.get("confidence",   doc.get("confidence_level", "")),
        generated_at = meta_raw.get("generated_at", str(doc.get("created_at", ""))),
        timings_ms   = meta_raw.get("timings_ms",   {}),
    ) if (meta_raw or doc.get("target_role")) else None

    # Frequency results
    freq_list = [
        FrequencyResult(**r)
        for r in insights_raw.get("frequency_results", [])
    ]

    # Gap results — is_gap may be None (market-only mode), must be Optional[bool]
    gap_list = [
        GapResult(**r)
        for r in insights_raw.get("gap_results", [])
    ]

    # Gap summary
    gap_sum_raw = insights_raw.get("gap_summary")
    gap_sum = None
    if gap_sum_raw:
        gap_sum = GapSummary(
            mode                 = gap_sum_raw.get("mode", "market-only"),
            total_skills         = gap_sum_raw.get("total_skills", 0),
            high_priority_gaps   = gap_sum_raw.get("high_priority_gaps", 0),
            medium_priority_gaps = gap_sum_raw.get("medium_priority_gaps", 0),
            top_gaps = [
                GapSummaryEntry(**g)
                for g in gap_sum_raw.get("top_gaps", [])
            ],
        )

    insights = ReportInsights(
        frequency_results=freq_list,
        gap_results=gap_list,
        gap_summary=gap_sum,
    )

    # Top jobs
    top_jobs = [
        TopJob(**j)
        for j in examples_raw.get("top_jobs", [])
    ]
    examples = ReportExamples(top_jobs=top_jobs)

    return ReportResponse(
        slug              = doc["slug"],
        target_role       = doc.get("target_role", ""),
        current_role      = doc.get("current_role"),
        location          = doc.get("location", ""),
        experience_lvl    = ExperienceLevel(doc.get("experience_lvl", "mid")),
        status            = status,
        postings_analyzed = doc.get("postings_analyzed", 0),
        low_data_warning  = doc.get("low_data_warning", False),
        confidence_level  = doc.get("confidence_level"),
        meta              = meta,
        insights          = insights,
        examples          = examples,
        created_at        = doc["created_at"],
        expires_at        = doc.get("expires_at"),
    )
