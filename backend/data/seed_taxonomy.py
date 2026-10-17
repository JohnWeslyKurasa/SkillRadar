"""
data/seed_taxonomy.py
---------------------
One-time script to seed the `skill_taxonomy` MongoDB collection from
data/skill_keywords.json.

Run manually whenever the taxonomy JSON changes:
    cd backend/
    python data/seed_taxonomy.py

What it does:
  1. Validates the JSON for duplicates / empty aliases / collisions
  2. Normalizes all aliases to lowercase + stripped
  3. Drops and recreates the skill_taxonomy collection (clean slate)
  4. Inserts all skill documents
  5. Creates a unique index on `canonical`
  6. Prints a full summary report

Why drop-and-recreate?
  Skills are seeded infrequently (once per update).
  An upsert strategy would leave stale aliases from deleted entries.
  A clean drop is safer and simpler for a seed script.
"""

import asyncio
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DATA_FILE    = SCRIPT_DIR / "skill_keywords.json"
BACKEND_DIR  = SCRIPT_DIR.parent

# Add backend root to path so we can import config
sys.path.insert(0, str(BACKEND_DIR))
from config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_taxonomy")


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_taxonomy(raw_skills: list[dict]) -> dict:
    """
    Validate the loaded taxonomy JSON before inserting into MongoDB.

    Checks:
      1. Canonical names must be unique (case-insensitive)
      2. Alias arrays must not be empty
      3. Same alias must not appear under two different canonicals (collision)
      4. All required fields present: canonical, aliases, category

    Returns:
        dict with keys:
            valid        (bool)
            errors       (list[str])
            warnings     (list[str])
            stats        (dict)
    """
    errors: list[str]   = []
    warnings: list[str] = []

    seen_canonicals: dict[str, str] = {}       # lower(canonical) → canonical
    alias_to_canonical: dict[str, str] = {}    # lower(alias)     → canonical

    duplicate_aliases: dict[str, list[str]] = defaultdict(list)   # alias → [canonicals]
    empty_alias_entries: list[str]          = []
    missing_fields: list[str]               = []

    valid_categories = {"Technical", "Tool", "Soft Skill", "Certification"}
    bad_categories: list[str] = []

    for entry in raw_skills:
        canonical = entry.get("canonical", "").strip()
        aliases   = entry.get("aliases", [])
        category  = entry.get("category", "")

        # ── Required fields check ──────────────────────────────────────────
        if not canonical:
            missing_fields.append(f"[MISSING canonical]: {entry}")
            continue
        if not aliases:
            empty_alias_entries.append(canonical)
        if not category:
            missing_fields.append(f"[MISSING category]: {canonical}")
        if category not in valid_categories:
            bad_categories.append(f"{canonical!r} → {category!r}")

        # ── Duplicate canonical check ──────────────────────────────────────
        canonical_lower = canonical.lower()
        if canonical_lower in seen_canonicals:
            errors.append(
                f"DUPLICATE CANONICAL: {canonical!r} already exists as "
                f"{seen_canonicals[canonical_lower]!r}"
            )
        else:
            seen_canonicals[canonical_lower] = canonical

        # ── Alias collision check ──────────────────────────────────────────
        normalized_aliases = [a.strip().lower() for a in aliases if a.strip()]
        for alias in normalized_aliases:
            if alias in alias_to_canonical and alias_to_canonical[alias] != canonical:
                duplicate_aliases[alias].append(canonical)
                duplicate_aliases[alias].append(alias_to_canonical[alias])
            else:
                alias_to_canonical[alias] = canonical

    # Consolidate duplicate alias errors
    for alias, canonicals in duplicate_aliases.items():
        unique = list(set(canonicals))
        errors.append(
            f"ALIAS COLLISION: alias {alias!r} appears in: {unique}"
        )

    if empty_alias_entries:
        warnings.append(
            f"EMPTY ALIASES ({len(empty_alias_entries)} entries): "
            f"{empty_alias_entries[:10]}"
        )

    if missing_fields:
        for msg in missing_fields:
            errors.append(msg)

    if bad_categories:
        warnings.append(
            f"UNKNOWN CATEGORIES: {bad_categories[:10]}  "
            f"(allowed: {valid_categories})"
        )

    total_aliases = sum(
        len([a for a in e.get("aliases", []) if a.strip()])
        for e in raw_skills
    )

    return {
        "valid":    len(errors) == 0,
        "errors":   errors,
        "warnings": warnings,
        "stats": {
            "total_skills":  len(raw_skills),
            "total_aliases": total_aliases,
            "avg_aliases_per_skill": round(total_aliases / max(len(raw_skills), 1), 1),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def prepare_documents(raw_skills: list[dict]) -> list[dict]:
    """
    Normalize each taxonomy entry before DB insertion:
      - Aliases: lowercased, stripped, deduplicated
      - Canonical: stripped (preserve original casing for display)
      - Ensures canonical itself is included in aliases
    """
    docs = []
    for entry in raw_skills:
        canonical = entry["canonical"].strip()
        raw_aliases = entry.get("aliases", [])

        # Normalize: lowercase + strip + deduplicate + include canonical itself
        aliases_normalized = list({
            a.strip().lower()
            for a in raw_aliases
            if a.strip()
        } | {canonical.lower()})

        docs.append({
            "canonical": canonical,
            "aliases":   aliases_normalized,
            "category":  entry.get("category", "Technical"),
        })
    return docs


# ─────────────────────────────────────────────────────────────────────────────
# SEEDER
# ─────────────────────────────────────────────────────────────────────────────

async def seed_taxonomy() -> None:
    """
    Main seeding routine:
      1. Load and validate JSON
      2. Connect to MongoDB
      3. Drop + recreate the collection
      4. Insert all documents
      5. Create unique index on canonical
      6. Print summary
    """
    logger.info("=" * 60)
    logger.info("Skill Taxonomy Seeder — Starting")
    logger.info("=" * 60)

    # ── Load JSON ─────────────────────────────────────────────────────────────
    if not DATA_FILE.exists():
        logger.error("Data file not found: %s", DATA_FILE)
        sys.exit(1)

    raw_skills: list[dict] = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    logger.info("Loaded %d entries from %s", len(raw_skills), DATA_FILE.name)

    # ── Validate ──────────────────────────────────────────────────────────────
    logger.info("\n--- Validation ---")
    result = validate_taxonomy(raw_skills)

    for warning in result["warnings"]:
        logger.warning(warning)

    if result["errors"]:
        logger.error("Validation FAILED. Fix these errors before seeding:")
        for err in result["errors"]:
            logger.error("  %s", err)
        sys.exit(1)

    stats = result["stats"]
    logger.info(
        "Validation PASSED — %d skills, %d total aliases (avg %.1f/skill)",
        stats["total_skills"], stats["total_aliases"], stats["avg_aliases_per_skill"],
    )

    # ── Connect to MongoDB ────────────────────────────────────────────────────
    settings = get_settings()
    logger.info("\n--- Connecting to MongoDB ---")
    client = AsyncIOMotorClient(settings.MONGODB_URI)

    try:
        await client.admin.command("ping")
        logger.info("Connected to: %s", settings.MONGODB_DB_NAME)
    except Exception as e:
        logger.error("MongoDB connection failed: %s", e)
        sys.exit(1)

    db = client[settings.MONGODB_DB_NAME]
    collection = db["skill_taxonomy"]

    # ── Drop existing collection ──────────────────────────────────────────────
    logger.info("\n--- Resetting Collection ---")
    existing_count = await collection.count_documents({})
    if existing_count > 0:
        await collection.drop()
        logger.info("Dropped existing collection (had %d documents).", existing_count)
    else:
        logger.info("Collection was empty — no drop needed.")

    # ── Prepare + Insert ──────────────────────────────────────────────────────
    logger.info("\n--- Inserting Documents ---")
    docs = prepare_documents(raw_skills)

    insert_result = await collection.insert_many(docs)
    inserted_count = len(insert_result.inserted_ids)
    logger.info("Inserted %d skill documents.", inserted_count)

    # ── Create indexes ────────────────────────────────────────────────────────
    logger.info("\n--- Creating Indexes ---")
    await collection.create_index("canonical", unique=True)
    logger.info("Unique index created on: canonical")

    # Non-unique index on category for stats queries
    await collection.create_index("category")
    logger.info("Index created on: category")

    # ── Final report ──────────────────────────────────────────────────────────
    final_count = await collection.count_documents({})

    # Count by category
    pipeline = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}]
    category_counts = {
        doc["_id"]: doc["count"]
        async for doc in collection.aggregate(pipeline)
    }

    logger.info("\n" + "=" * 60)
    logger.info("SEED COMPLETE")
    logger.info("=" * 60)
    logger.info("  Total skills inserted : %d", final_count)
    logger.info("  Total aliases         : %d", stats["total_aliases"])
    logger.info("  Breakdown by category :")
    for cat, count in sorted(category_counts.items()):
        logger.info("    %-20s %d", cat, count)
    logger.info("=" * 60)

    client.close()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(seed_taxonomy())
