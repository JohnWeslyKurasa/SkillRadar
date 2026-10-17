"""
config.py
---------
Single source of truth for all environment-dependent settings.

Uses pydantic-settings (v2) which reads from `.env` automatically.
Any value can be overridden by a real environment variable at deploy time
(e.g., on Render), making this config zero-change between local and prod.

Access settings anywhere via the cached `get_settings()` dependency.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Application ────────────────────────────────────────────────────────
    APP_NAME: str = "Skill Gap Radar API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ── MongoDB ────────────────────────────────────────────────────────────
    # Set in .env as:  MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/
    MONGODB_URI: str
    MONGODB_DB_NAME: str = "skillradar"

    # ── Adzuna API ─────────────────────────────────────────────────────────
    # Register free at: https://developer.adzuna.com/
    ADZUNA_APP_ID: str
    ADZUNA_APP_KEY: str
    ADZUNA_BASE_URL: str = "https://api.adzuna.com/v1/api/jobs"
    ADZUNA_COUNTRY: str = "us"           # us | gb | au | ca — affects job pool
    ADZUNA_RESULTS_PER_PAGE: int = 50    # max per request; 50 is Adzuna's limit

    # ── Report settings ────────────────────────────────────────────────────
    REPORT_TTL_DAYS: int = 30            # reports expire after this many days
    MIN_POSTINGS_THRESHOLD: int = 10     # warn user if fewer postings found

    # ── CORS ───────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.  "*" is fine for MVP.
    CORS_ORIGINS: str = "*"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    lru_cache ensures we parse .env exactly once per process —
    use this as a FastAPI dependency wherever settings are needed:

        from config import get_settings, Settings
        from fastapi import Depends

        def my_route(settings: Settings = Depends(get_settings)):
            ...
    """
    return Settings()
