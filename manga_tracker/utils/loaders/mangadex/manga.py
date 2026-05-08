"""
manga_tracker/utils/loaders/mangadex/manga.py

Shared helper for fetching raw MangaDex manga responses.

This module exposes a thin streaming loader that paginates through the
/public/manga endpoint, handles 429 throttling, and supports an optional
maximum-record cutoff for quick development runs.
"""

import time
from typing import Any, Dict, Generator, Iterable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_ROOT = "https://api.mangadex.org"
DEFAULT_LIMIT = 100
DEFAULT_INCLUDES = ["author", "cover_art", "tags"]
MAX_RETRIES = 5
BACKOFF_FACTOR = 0.5
DEFAULT_SLEEP_SECONDS = 1.0


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def build_mangadex_session() -> requests.Session:
    """Create an HTTP session configured for MangaDex requests."""
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "manga-tracker/raw-manga-loader/1.0",
        }
    )

    retry_strategy = Retry(
        total=MAX_RETRIES,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        backoff_factor=BACKOFF_FACTOR,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


def fetch_manga_page(
    session: requests.Session,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    includes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Fetch a single page of MangaDex manga records."""
    if limit < 1 or limit > DEFAULT_LIMIT:
        raise ValueError(f"limit must be between 1 and {DEFAULT_LIMIT}")

    params: Dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }
    for include in includes or DEFAULT_INCLUDES:
        params.setdefault("includes[]", []).append(include)

    url = f"{API_ROOT}/manga"
    response = session.get(url, params=params, timeout=30)

    if response.status_code == 200:
        return response.json()

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after is not None else DEFAULT_SLEEP_SECONDS
        print(f"MangaDex rate limit hit; sleeping {delay} seconds")
        time.sleep(delay)
        return fetch_manga_page(session, offset=offset, limit=limit, includes=includes)

    response.raise_for_status()
    return {}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def stream_raw_manga(
    limit: int = DEFAULT_LIMIT,
    includes: Optional[Iterable[str]] = None,
    max_records: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """Yield raw manga payloads from MangaDex with pagination.

    Args:
        limit: Page size to request from MangaDex.
        includes: Relationship includes to attach to each manga payload.
        max_records: Optional upper bound on total records to yield.

    Returns:
        Generator of raw MangaDex manga payload dictionaries.
    """
    session = build_mangadex_session()
    offset = 0
    includes = includes or DEFAULT_INCLUDES
    total_records = 0

    print(
        f"Starting MangaDex raw manga fetch: limit={limit}, includes={includes}, "
        f"max_records={max_records}"
    )

    while True:
        page = fetch_manga_page(session, offset=offset, limit=limit, includes=includes)
        records = page.get("data", [])
        total = page.get("total", 0)
        print(f"Fetched page offset={offset} count={len(records)} total={total}")

        if not records:
            print("No more records returned by MangaDex.")
            break

        for record in records:
            if max_records is not None and total_records >= max_records:
                print(f"Reached max_records={max_records}; stopping early.")
                return

            yield record
            total_records += 1

            if max_records is not None and total_records >= max_records:
                print(f"Reached max_records={max_records}; stopping early.")
                return

        offset += len(records)

        if offset >= total:
            print(f"Finished MangaDex fetch: loaded {total_records} records.")
            break