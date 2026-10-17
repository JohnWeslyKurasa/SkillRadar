"""
routers/test_adzuna.py
----------------------
TEMPORARY diagnostic route — DELETE before production launch.

GET /api/test-adzuna

Calls fetch_jobs() in isolation and returns diagnostic metadata.
  ✗ No MongoDB     ✗ No skill extraction     ✗ No pipeline integration
"""

import time
from fastapi import APIRouter, HTTPException
from services.job_fetcher import fetch_jobs, JobFetchError

router = APIRouter(tags=["Testing — Remove in Production"])

TEST_ROLE     = "Data Engineer"
TEST_LOCATION = "remote"
TEST_LIMIT    = 20


@router.get("/test-adzuna")
async def test_adzuna():
    """
    Smoke-test for the Adzuna integration.
    Fetches 20 Data Engineer (remote) postings and returns diagnostic info.
    """
    wall_start = time.perf_counter()

    try:
        jobs = await fetch_jobs(
            role=TEST_ROLE,
            location=TEST_LOCATION,
            limit=TEST_LIMIT,
        )
    except JobFetchError as e:
        raise HTTPException(status_code=502, detail=str(e))

    elapsed_ms = round((time.perf_counter() - wall_start) * 1000, 2)

    return {
        "query": {
            "role":     TEST_ROLE,
            "location": TEST_LOCATION,
            "limit":    TEST_LIMIT,
        },
        "location_note": (
            "'remote' is not a valid Adzuna location. "
            f"Sent as: what='{TEST_ROLE} remote', where=(omitted — country-wide search)"
        ),
        "jobs_returned":    len(jobs),
        "sample_titles":    [j["title"]       for j in jobs[:5]],
        "sample_ids":       [j["external_id"] for j in jobs[:5]],
        "desc_preview":     jobs[0]["description"][:200] if jobs else None,
        "latency_ms":       elapsed_ms,
    }
