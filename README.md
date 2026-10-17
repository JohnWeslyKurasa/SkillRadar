# Skill Gap Radar 🎯

> **Market-driven career intelligence engine.**  
> Analyzes job postings to identify demanded skills and surface your skill gaps.

> Demo: https://skillradar-v6as.onrender.com/

---

## What It Does

1. Fetches live job postings from the Adzuna API for a given role + location
2. Extracts required skills using a curated taxonomy of 284 canonical skills
3. Calculates per-skill frequency across all postings
4. Compares against your current role's baseline to identify gaps
5. Returns a shareable report with prioritized skill recommendations

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 + FastAPI + Uvicorn |
| Database | MongoDB Atlas (Motor async driver) |
| Job Data | Adzuna API |
| Config | pydantic-settings + python-dotenv |

## Project Structure

```
backend/
├── main.py                    # FastAPI app, lifespan events
├── config.py                  # Settings (pydantic-settings)
├── database.py                # MongoDB connection + dependency
├── models/
│   └── report.py              # Pydantic models for Report entity
├── routers/
│   ├── health.py              # GET /api/health
│   ├── analyze.py             # POST /api/analyze
│   └── test_adzuna.py         # GET /api/test-adzuna (diagnostic)
├── services/
│   ├── job_fetcher.py         # Adzuna API client (async, retry, pagination)
│   ├── skill_extractor.py     # Regex-based skill extraction from JDs
│   ├── frequency_calc.py      # Per-job skill frequency calculator
│   └── gap_engine.py          # Baseline-driven gap detection + prioritization
└── data/
    ├── generate_taxonomy.py   # Taxonomy generator (source of truth)
    ├── skill_keywords.json    # Generated taxonomy: 284 skills, 1061 aliases
    ├── seed_taxonomy.py       # Seeds skill_taxonomy MongoDB collection
    └── role_baselines.json    # Baseline skill sets for 12 common roles
```

## Setup

```bash
# 1. Clone and enter
 git clone https://github.com/JohnWeslyKurasa/SkillRadar.git
 cd SkillRadar/backend

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Fill in MONGODB_URI, ADZUNA_APP_ID, ADZUNA_APP_KEY

# 5. Seed the skill taxonomy
python data/generate_taxonomy.py   # generates skill_keywords.json
python data/seed_taxonomy.py       # pushes 284 skills to MongoDB

# 6. Run the server
uvicorn main:app --reload
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check + DB connection status |
| POST | `/api/analyze` | Start a skill gap analysis (returns slug) |
| GET | `/api/test-adzuna` | Diagnostic: fetch sample Adzuna jobs |

## Skill Taxonomy

The taxonomy lives in `data/generate_taxonomy.py` — **never edit `skill_keywords.json` directly**.

```bash
# After any taxonomy change:
python data/generate_taxonomy.py   # validates + writes JSON (zero collisions enforced)
python data/seed_taxonomy.py       # re-seeds MongoDB
```

**284 canonical skills | 1,061 aliases | 0 collisions**

| Category | Count |
|---|---|
| Technical | 214 |
| Tool | 48 |
| Certification | 12 |
| Soft Skill | 10 |

## MVP Scope

This is a solo 3-week MVP. Out of scope: user auth, email, NLP libraries, queues/workers, microservices.

## License

MIT
