"""
routers/dashboard.py
---------------------
GET /report/{slug}  — server-rendered HTML intelligence dashboard.

This is a human-facing route, not an API route.
It fetches the report from MongoDB and renders report.html via Jinja2.

No SPA. No React. No build step. Data-first, screenshot-ready.

Status routing:
  not found   → simple 404 inline response
  pending     → status page ("queued")
  processing  → status page ("running")
  failed      → status page ("failed") with generic message
  done        → full report.html render
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from motor.motor_asyncio import AsyncIOMotorDatabase

from database import get_db, get_reports_collection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Dashboard"])

# Templates directory is relative to this file's parent (backend/)
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_EXCLUDED = {"_id", "error_msg", "known_skills"}


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Public landing page — clean form that submits to POST /api/analyze."""
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/report/{slug}", response_class=HTMLResponse)
async def dashboard_report(
    slug: str,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Render report as HTML intelligence dashboard.
    Reuses the same MongoDB projection as the JSON retrieval endpoint.
    """
    t0 = perf_counter()
    collection = get_reports_collection(db)
    projection = {f: 0 for f in _EXCLUDED}
    doc = await collection.find_one({"slug": slug}, projection)
    retrieval_ms = round((perf_counter() - t0) * 1000)

    if doc is None:
        return templates.TemplateResponse(
            "status.html",
            {
                "request":  request,
                "title":    "Report Not Found",
                "heading":  "Report not found",
                "message":  f"No report with slug '{slug}'. It may have expired or never existed.",
                "slug":     slug,
                "status":   "not_found",
            },
            status_code=404,
        )

    status = doc.get("status", "pending")

    if status != "done":
        status_messages = {
            "pending":    ("Queued",     "Your report is queued and will start processing shortly."),
            "processing": ("Processing", "Analysis in progress. This usually takes 5–15 seconds."),
            "failed":     ("Failed",     "Analysis failed. Please submit a new request."),
        }
        heading, message = status_messages.get(status, ("Unknown", "Unknown state."))
        return templates.TemplateResponse(
            "status.html",
            {
                "request": request,
                "title":   f"Report {heading}",
                "heading": heading,
                "message": message,
                "slug":    slug,
                "status":  status,
            },
            status_code=202 if status in ("pending", "processing") else 500,
        )

    # Atomically increment view_count
    await collection.update_one({"slug": slug}, {"$inc": {"view_count": 1}})

    # Pull structured data for template context
    meta          = doc.get("meta") or {}
    insights      = doc.get("insights") or {}
    examples      = doc.get("examples") or {}
    freq_results  = insights.get("frequency_results", [])
    gap_results   = insights.get("gap_results", [])
    gap_summary   = insights.get("gap_summary", {})
    top_jobs      = examples.get("top_jobs", [])

    # Prepare chart data (top 10 skills, descending)
    top10 = freq_results[:10]
    chart_labels = [r["skill"] for r in top10]
    chart_values = [r["frequency_pct"] for r in top10]

    # Split gaps by priority
    high_gaps   = [r for r in gap_results if r.get("is_gap") and r.get("priority") == "High"]
    medium_gaps = [r for r in gap_results if r.get("is_gap") and r.get("priority") == "Medium"]

    gap_mode          = meta.get("gap_mode", "market-only")
    baseline_supported = meta.get("baseline_supported", False)

    logger.info(
        "[Dashboard] slug=%s rendered in %dms (view incremented)",
        slug, retrieval_ms,
    )

    return templates.TemplateResponse(
        "report.html",
        {
            "request":            request,
            "slug":               slug,
            "meta":               meta,
            "gap_mode":           gap_mode,
            "baseline_supported": baseline_supported,
            "chart_labels":       chart_labels,
            "chart_values":       chart_values,
            "freq_results":       freq_results,
            "high_gaps":          high_gaps,
            "medium_gaps":        medium_gaps,
            "gap_summary":        gap_summary,
            "top_jobs":           top_jobs,
        },
    )
