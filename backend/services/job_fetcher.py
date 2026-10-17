"""
services/job_fetcher.py
-----------------------
Fetches raw job postings from Adzuna and returns a normalized list.

Responsibilities (Phase 2 only):
  ✓ Call Adzuna API with correct auth + pagination
  ✓ Handle remote-location searches correctly
  ✓ Retry transient failures (up to 2 retries per page)
  ✓ Return a flat, normalized list of dicts
  ✗ Does NOT extract skills   → skill_extractor.py (Phase 3)
  ✗ Does NOT write to MongoDB → analyze pipeline (Phase 4)

Adzuna API behaviour:
  - URL:              /v1/api/jobs/{country}/search/{page}
  - Page numbering:   1-indexed
  - Max per page:     50 (hard limit from Adzuna)
  - `where` param:    MUST be a real city/state/country.
                      'remote' is NOT a valid location — returns 0 results.
                      Handled below via REMOTE_TERMS normalization.
  - Free tier quota:  250 requests / day
"""

import asyncio
import logging
import math
import time

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_PER_PAGE  = 50      # Adzuna hard limit per request
MAX_LIMIT     = 200     # We never fetch more than this per analysis
REQUEST_TIMEOUT = 10.0  # Seconds before a single request is considered failed
MAX_RETRIES   = 2       # Retry a failed page up to this many times
RETRY_BACKOFF = 1.5     # Seconds to wait between retries (avoids hammering API)

# Synonyms for "remote work" — none of these are valid Adzuna `where` values.
REMOTE_TERMS = {"remote", "anywhere", "wfh", "work from home", "distributed", "worldwide"}

# Country-name → Adzuna country code.
# When location matches a key here, we use that code in the URL path
# and omit the `where` param entirely (country-wide search).
# This prevents e.g. "india" being routed to Indiana (US) via the default /us/ path.
COUNTRY_MAP: dict[str, str] = {
    # South Asia
    "india":          "in",
    "in":             "in",
    # United States
    "us":             "us",
    "usa":            "us",
    "united states":  "us",
    "america":        "us",
    # United Kingdom
    "uk":             "gb",
    "gb":             "gb",
    "united kingdom": "gb",
    "britain":        "gb",
    "great britain":  "gb",
    # Canada
    "canada":         "ca",
    "ca":             "ca",
    # Australia
    "australia":      "au",
    "au":             "au",
    # Germany
    "germany":        "de",
    "de":             "de",
    # France
    "france":         "fr",
    "fr":             "fr",
    # Netherlands
    "netherlands":    "nl",
    "nl":             "nl",
    # Singapore
    "singapore":      "sg",
    "sg":             "sg",
    # New Zealand
    "new zealand":    "nz",
    "nz":             "nz",
    # Brazil
    "brazil":         "br",
    "br":             "br",
}


class JobFetchError(Exception):
    """Raised when Adzuna returns a non-retriable error (401, 429, network)."""


class NoJobsFoundError(Exception):
    """
    Raised when Adzuna returns 0 results for the given role + location.

    This is a client-visible error (422): the search parameters returned
    nothing and proceeding to extraction would produce meaningless output.
    The caller should return a helpful message suggesting a broader title.
    """
    pass


async def fetch_jobs(
    role: str,
    location: str,
    limit: int = 50,
) -> list[dict]:
    """
    Fetch up to `limit` job postings from Adzuna for the given role + location.
    Args:
        role:     Job title to search, e.g. "Data Engineer"
        location: Location string — "remote" triggers country-wide search
                  with 'remote' injected into the title query.
                  Real locations (e.g. "New York", "London") use Adzuna's
                  geographic `where` filter directly.
        limit:    Max number of postings to retrieve. Hard-capped at 200.
    Returns:
        List of normalized job dicts, each containing:
            external_id  (str)  — Adzuna's unique job identifier
            title        (str)  — Job posting title
            description  (str)  — Full raw description text (used for skill extraction)

    Raises:
        JobFetchError: On auth failure (401), rate limit (429), or
                       persistent failures after all retries exhausted.
    """
    settings  = get_settings()
    limit     = min(limit, MAX_LIMIT)
    pages_needed = math.ceil(limit / MAX_PER_PAGE)

    # ── Location normalization ────────────────────────────────────────────────
    # Priority order:
    #   1. Remote terms  → country-wide search with 'remote' in title query.
    #   2. Country names → correct Adzuna /jobs/{code}/ path, no `where` param.
    #      This prevents "india" being routed to Indiana (US state) via /us/.
    #   3. Everything else (city, state, region) → env-var country + `where` param.

    loc_key = location.lower().strip()

    if loc_key in REMOTE_TERMS:
        country_code = settings.ADZUNA_COUNTRY   # use configured default
        search_what  = f"{role} remote"
        search_where = None
        location_mode = "remote"

    elif loc_key in COUNTRY_MAP:
        country_code  = COUNTRY_MAP[loc_key]
        search_what   = role
        search_where  = None      # omit — country-code in path is enough
        location_mode = f"country ({country_code.upper()})"

    else:
        country_code  = settings.ADZUNA_COUNTRY  # fallback: config default
        search_what   = role
        search_where  = location
        location_mode = f"region (country={country_code.upper()}, where={location!r})"

    logger.info(
        "[JobFetcher] location=%r -> mode=%s",
        location, location_mode,
    )

    collected: list[dict] = []
    api_calls_made = 0
    wall_start = time.perf_counter()

    logger.info(
        "[JobFetcher] START role=%r location=%r "
        "(what=%r where=%r) limit=%d pages_needed=%d",
        role, location, search_what, search_where or "ALL", limit, pages_needed,
    )

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for page in range(1, pages_needed + 1):
            # Never ask for more than we still need
            remaining = limit - len(collected)
            per_page  = min(remaining, MAX_PER_PAGE)

            url = (
                f"{settings.ADZUNA_BASE_URL}"
                f"/{country_code}/search/{page}"
            )
            params: dict = {
                "app_id":           settings.ADZUNA_APP_ID,
                "app_key":          settings.ADZUNA_APP_KEY,
                "what":             search_what,
                "results_per_page": per_page,
            }
            if search_where:
                params["where"] = search_where

            # ── Retry loop ────────────────────────────────────────────────────
            data = await _get_with_retry(client, url, params, page)
            api_calls_made += 1

            # On page 1, check if Adzuna has any results at all
            if page == 1:
                total_available = data.get("count", 0)
                logger.info(
                    "[JobFetcher] Page 1 response: total_available=%d",
                    total_available,
                )
                if total_available == 0:
                    logger.warning(
                        "[JobFetcher] Adzuna returned 0 results for "
                        "what=%r where=%r — stopping early.",
                        search_what, search_where or "ALL",
                    )
                    break

            page_jobs = data.get("results", [])
            if not page_jobs:
                logger.info(
                    "[JobFetcher] Page %d returned no results — stopping early.", page
                )
                break

            for job in page_jobs:
                company_raw = job.get("company") or {}
                collected.append({
                    "external_id":  str(job.get("id", "")),
                    "title":        job.get("title", "").strip(),
                    "description":  job.get("description", "").strip(),
                    "redirect_url": job.get("redirect_url", ""),
                    "company":      company_raw.get("display_name") if isinstance(company_raw, dict) else None,
                })

            logger.info(
                "[JobFetcher] Page %d/%d → fetched %d jobs (total so far: %d)",
                page, pages_needed, len(page_jobs), len(collected),
            )

            if len(collected) >= limit:
                break

    # ── Summary log ──────────────────────────────────────────────────────────
    elapsed_ms = round((time.perf_counter() - wall_start) * 1000, 2)
    logger.info(
        "[JobFetcher] DONE — jobs_collected=%d api_calls=%d latency=%.2fms",
        len(collected), api_calls_made, elapsed_ms,
    )

    return collected[:limit]


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    page: int,
) -> dict:
    """
    Perform a GET request with up to MAX_RETRIES retries on transient failures.

    Transient failures retried:
      - Network errors (DNS, TCP reset)
      - Timeouts
      - HTTP 5xx (server-side errors)

    Non-retriable — raised immediately:
      - HTTP 401 (bad credentials)
      - HTTP 429 (rate limit — retrying would burn more quota)
    """
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 2):   # attempts: 1, 2, 3
        try:
            response = await client.get(url, params=params)
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(
                "[JobFetcher] Page %d attempt %d timed out after %.0fs",
                page, attempt, REQUEST_TIMEOUT,
            )
            if attempt <= MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
            continue
        except httpx.RequestError as e:
            last_error = e
            logger.warning(
                "[JobFetcher] Page %d attempt %d network error: %s",
                page, attempt, e,
            )
            if attempt <= MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
            continue

        # ── Non-retriable HTTP errors ─────────────────────────────────────
        if response.status_code == 401:
            raise JobFetchError(
                "Adzuna returned 401 Unauthorized. "
                "Check ADZUNA_APP_ID and ADZUNA_APP_KEY in .env."
            )
        if response.status_code == 429:
            raise JobFetchError(
                "Adzuna rate limit hit (429 Too Many Requests). "
                "Free tier allows 250 requests/day. Wait until tomorrow or upgrade."
            )

        # ── Retriable server errors ───────────────────────────────────────
        if response.status_code >= 500:
            last_error = httpx.HTTPStatusError(
                f"HTTP {response.status_code}", request=response.request, response=response
            )
            logger.warning(
                "[JobFetcher] Page %d attempt %d → HTTP %d, retrying...",
                page, attempt, response.status_code,
            )
            if attempt <= MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
            continue

        # ── Success ───────────────────────────────────────────────────────
        if response.status_code != 200:
            raise JobFetchError(
                f"Adzuna returned unexpected HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        return response.json()

    # All retries exhausted
    raise JobFetchError(
        f"Adzuna API failed on page {page} after {MAX_RETRIES + 1} attempts. "
        f"Last error: {last_error}"
    )
