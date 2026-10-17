"""
routers/analyze.py
------------------
POST /api/analyze — entry point for skill gap analysis.

ROUTER RESPONSIBILITIES (strict separation of concerns):
  1. Validate incoming request (Pydantic handles this automatically).
  2. Generate slug + insert PENDING report into MongoDB.
  3. Call run_analysis(payload, db) from analyze_pipeline.
  4. On SUCCESS: update report → status=done, merge result dict.
  5. On TIMEOUT: update report → status=failed, error_msg="timeout" → HTTP 504.
  6. On ANY OTHER ERROR: update report → status=failed, error_msg → HTTP 500.
  7. Return full structured response.

WHAT THE ROUTER MUST NOT DO:
  - No business logic (frequency, gap, scoring).
  - No direct service calls (fetch_jobs, extract_skills, etc).
  - No knowledge of pipeline internals.
"""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_db, get_reports_collection
from models.report import (
    AnalyzeRequest,
    AnalyzeResponse,
    ReportMeta,
    ReportInsights,
    ReportExamples,
    ReportStatus,
)
from config import get_settings
from services.analyze_pipeline import run_analysis
from services.job_fetcher import JobFetchError, NoJobsFoundError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Analysis"])


def _generate_slug(length: int = 8) -> str:
    """Cryptographically random URL-safe slug (e.g. 'a3f9bc12')."""
    return secrets.token_hex(length // 2)


@router.post("/analyze", response_model=AnalyzeResponse, status_code=200)
async def start_analysis(
    payload: AnalyzeRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Run a full skill gap analysis synchronously.

    Flow:
      1. Insert pending report (immediate DB write).
      2. Execute full pipeline (fetch → extract → frequency → gap → score).
      3. Update report with results on success.
      4. Return structured response.

    HTTP status: 200 (synchronous, result is ready in the response).
    Error status: 504 on timeout, 500 on pipeline failure.
    """
    settings = get_settings()
    slug     = _generate_slug()
    now      = datetime.now(timezone.utc)
    collection = get_reports_collection(db)

    # ── Step 1: Insert pending report ─────────────────────────────────────────
    pending_doc = {
        "slug":             slug,
        "target_role":      payload.target_role,
        "current_role":     payload.current_role,
        "location":         payload.location,
        "experience_lvl":   payload.experience_lvl.value,
        "known_skills":     payload.known_skills,
        "status":           ReportStatus.pending.value,
        "postings_analyzed": 0,
        "low_data_warning": False,
        "error_msg":        None,
        "created_at":       now,
        "expires_at":       now + timedelta(days=settings.REPORT_TTL_DAYS),
    }
    await collection.insert_one(pending_doc)
    logger.info("[Analyze] slug=%s — pending report inserted.", slug)

    # ── Step 2: Run pipeline ──────────────────────────────────────────────────
    try:
        result = await run_analysis(payload=payload, db=db)

    except asyncio.TimeoutError:
        # Pipeline exceeded PIPELINE_TIMEOUT_S.
        # Mark failed, return 504. Do NOT swallow — surface clearly to client.
        logger.error("[Analyze] slug=%s — TIMEOUT after pipeline limit.", slug)
        await collection.update_one(
            {"slug": slug},
            {"$set": {
                "status":    ReportStatus.failed.value,
                "error_msg": "Analysis timed out. Try a narrower search or fewer pages.",
            }},
        )
        raise HTTPException(
            status_code=504,
            detail=f"Analysis timed out. Report slug={slug} is available but incomplete.",
        )

    except NoJobsFoundError as e:
        # 0 jobs returned — client used a role/location with no postings.
        # Mark failed so the slug is queryable, return 422 (client error).
        logger.warning("[Analyze] slug=%s — NoJobsFoundError: %s", slug, e)
        await collection.update_one(
            {"slug": slug},
            {"$set": {
                "status":    ReportStatus.failed.value,
                "error_msg": str(e),
            }},
        )
        raise HTTPException(
            status_code=422,
            detail="No job postings found for this role. Try a broader or different title.",
        )

    except JobFetchError as e:
        # Adzuna API failure (credentials, rate-limit, network).
        logger.error("[Analyze] slug=%s — JobFetchError: %s", slug, e)
        await collection.update_one(
            {"slug": slug},
            {"$set": {
                "status":    ReportStatus.failed.value,
                "error_msg": f"Job data unavailable: {e}",
            }},
        )
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch job data: {e}",
        )

    except Exception as e:
        # Any unexpected pipeline error — preserve slug for debugging.
        logger.exception("[Analyze] slug=%s — unexpected pipeline error.", slug)
        await collection.update_one(
            {"slug": slug},
            {"$set": {
                "status":    ReportStatus.failed.value,
                "error_msg": str(e),
            }},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during analysis. Please try again.",
        )

    # ── Step 3: Write results to MongoDB ──────────────────────────────────────
    meta_data     = result["meta"]
    insights_data = result["insights"]
    examples_data = result["examples"]
    n             = meta_data["total_jobs"]

    await collection.update_one(
        {"slug": slug},
        {"$set": {
            "status":            ReportStatus.done.value,
            "postings_analyzed": n,
            "low_data_warning":  meta_data.get("low_data_warning", False),
            "confidence_level":  meta_data["confidence"],
            "meta":              meta_data,
            "insights":          insights_data,
            "examples":          examples_data,
            "error_msg":         None,
        }},
    )
    logger.info(
        "[Analyze] slug=%s — done. jobs=%d total_ms=%d",
        slug, n, meta_data["timings_ms"].get("total", 0),
    )

    # ── Step 4: Return structured response ────────────────────────────────────
    return AnalyzeResponse(
        slug=slug,
        status=ReportStatus.done,
        low_data_warning=meta_data.get("low_data_warning", False),
        meta=ReportMeta(**meta_data),
        insights=ReportInsights(
            frequency_results=insights_data["frequency_results"],
            gap_results=insights_data["gap_results"],
            gap_summary=insights_data["gap_summary"],
        ),
        examples=ReportExamples(
            top_jobs=examples_data["top_jobs"],
        ),
    )
