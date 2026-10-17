"""
main.py
-------
Application entry point.

Responsibilities:
  - Create the FastAPI app instance
  - Register the lifespan context (startup / shutdown)
  - Mount all routers with their URL prefixes
  - Configure CORS (open for MVP; tighten before any paid tier)
  - Expose /api/health for uptime monitoring and Render health checks

Why a lifespan context manager instead of @app.on_event?
  on_event is deprecated since FastAPI 0.93. The lifespan approach is the
  current idiomatic pattern and works correctly with pytest's anyio fixtures.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import connect_to_mongo, close_mongo_connection
from routers import health, analyze, reports, test_adzuna, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before yield) and once at shutdown (after yield)."""
    # ── Startup ──────────────────────────────────────────────────────────
    settings = get_settings()
    print(f"[START] {settings.APP_NAME} v{settings.APP_VERSION}")
    await connect_to_mongo(app)

    yield  # application is live and serving requests here

    # ── Shutdown ─────────────────────────────────────────────────────────
    await close_mongo_connection(app)
    print("[STOP] Application shutdown complete.")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        # In production: hide all API docs (Swagger, ReDoc, raw schema)
        docs_url    = "/docs"     if settings.DEBUG else None,
        redoc_url   = "/redoc"    if settings.DEBUG else None,
        openapi_url = "/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    # For MVP: allow all origins so the Vercel frontend can reach this API.
    # Before any paid offering: restrict to your Vercel domain.
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,  # No cookies / auth for MVP
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(health.router,        prefix="/api")
    app.include_router(analyze.router,       prefix="/api")
    app.include_router(reports.router,       prefix="/api")
    app.include_router(test_adzuna.router,   prefix="/api")  # TEMP: remove before prod
    app.include_router(dashboard.router)                     # No /api prefix — HTML routes

    return app


app = create_app()
