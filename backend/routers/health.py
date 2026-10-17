"""
routers/health.py
-----------------
Single health check endpoint.

Why this exists:
  - Render.com and other PaaS providers ping a health endpoint to decide
    whether to route traffic to your instance. Without it, a cold-start
    or crash goes undetected until a real user hits an error.
  - Also used during local dev to confirm the server + DB are wired up
    correctly before touching any business logic.

GET /api/health
  → 200 { status: "ok", db: "connected" }
  → 503 { status: "error", db: "unreachable" } on DB failure
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(request: Request):
    """
    Verifies the API is alive and the MongoDB connection is healthy.
    Returns HTTP 200 on success, HTTP 503 if the DB ping fails.
    """
    try:
        # Ping MongoDB to confirm the connection pool is still alive.
        # This is a lightweight admin command — not a full query.
        await request.app.state.mongo_client.admin.command("ping")
        db_status = "connected"
        http_status = 200
    except Exception as e:
        db_status = f"unreachable: {str(e)}"
        http_status = 503

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ok" if http_status == 200 else "error",
            "db": db_status,
            "version": request.app.version,
        },
    )
