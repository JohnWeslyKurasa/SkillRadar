"""
database.py
-----------
Manages the Motor (async MongoDB) client lifecycle.

Design decisions:
  - Motor client is created ONCE at startup and closed at shutdown.
    This is the correct pattern — Motor clients are thread-safe and
    connection-pooled; you never create one per request.

  - The client is stored on `app.state` (FastAPI's built-in state bag)
    so it survives the full application lifetime.

  - `get_db()` is a FastAPI dependency that yields the database handle.
    Routers import only this function — they never touch the raw client.

  - Collection helpers (get_reports_collection, etc.) are thin wrappers
    that make router code self-documenting.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from fastapi import Request
from config import get_settings


# ── Lifecycle helpers (called from main.py lifespan) ──────────────────────────

async def connect_to_mongo(app) -> None:
    """
    Open the Motor client and store it on app.state.
    Called once during application startup.
    """
    settings = get_settings()
    app.state.mongo_client = AsyncIOMotorClient(settings.MONGODB_URI)
    app.state.db = app.state.mongo_client[settings.MONGODB_DB_NAME]

    # Verify connectivity early so startup fails loudly rather than
    # silently serving broken requests.
    await app.state.mongo_client.admin.command("ping")
    print(f"[DB] Connected to MongoDB: {settings.MONGODB_DB_NAME}")


async def close_mongo_connection(app) -> None:
    """
    Close the Motor client gracefully.
    Called once during application shutdown.
    """
    app.state.mongo_client.close()
    print("[DB] MongoDB connection closed.")


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db(request: Request) -> AsyncIOMotorDatabase:
    """
    Dependency that yields the database from app.state.

    Usage in a router:
        from database import get_db
        from motor.motor_asyncio import AsyncIOMotorDatabase
        from fastapi import Depends

        @router.get("/example")
        async def example(db: AsyncIOMotorDatabase = Depends(get_db)):
            doc = await db["reports"].find_one({"slug": "abc"})
    """
    return request.app.state.db


# ── Collection accessors ──────────────────────────────────────────────────────
# Named helpers prevent typos in collection names scattered across routers.

def get_reports_collection(db: AsyncIOMotorDatabase):
    return db["reports"]

def get_job_postings_collection(db: AsyncIOMotorDatabase):
    return db["job_postings"]

def get_skill_taxonomy_collection(db: AsyncIOMotorDatabase):
    return db["skill_taxonomy"]
