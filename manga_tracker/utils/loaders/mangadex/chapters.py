"""
manga_tracker/utils/loaders/mangadex/chapters.py

Loads all English chapters from the MangaDex API using paginated requests
with an optional createdAtSince filter.

No authentication required — MangaDex public API is unauthenticated.

Retry logic per page request is handled by the shared utility:
    manga_tracker/utils/helpers/api_request.py
"""

from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional
from urllib.parse import urlencode, quote

import pandas as pd

from manga_tracker.utils.helpers.api_request import APIRequestError, make_api_request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANGADEX_CHAPTER_URL = "https://api.mangadex.org/chapter"
_PAGE_LIMIT = 100
_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_INCLUDES = ["scanlation_group"]
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "manga-tracker/raw-chapter-loader/1.0",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_params(
    offset: int,
    limit: int,
    includes: List[str],
    since: Optional[datetime],
) -> str:
    parts = [
        ("limit", limit),
        ("offset", offset),
        ("order[createdAt]", "asc"),
        ("translatedLanguage[]", "en"),
    ]
    if since is not None:
        parts.append(("createdAtSince", since.strftime("%Y-%m-%dT%H:%M:%S")))
    for include in includes:
        parts.append(("includes[]", include))
    return urlencode(parts, quote_via=quote)


def _extract_manga_id(payload: dict) -> Optional[str]:
    """Extract manga UUID from relationships[] without needing includes[]=manga."""
    for rel in payload.get("relationships", []):
        if rel.get("type") == "manga":
            return rel.get("id")
    return None


def _parse_page(response_json: dict, offset: int) -> list:
    """
    Validate and extract chapter records from a single paginated response.

    Args:
        response_json (dict): Parsed JSON body from the MangaDex API.
        offset (int): Current pagination offset — used for error context.

    Returns:
        List[dict]: Chapter records from this page.

    Raises:
        ValueError: If the response is missing the expected 'data' key.
    """
    if "data" not in response_json:
        raise ValueError(
            f"Unexpected MangaDex API response structure at offset={offset} — "
            f"'data' key missing. Keys found: {list(response_json.keys())}"
        )
    return response_json["data"]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def stream_raw_chapters(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield raw chapter payloads from MangaDex with pagination.

    Fetches English chapters in paginated batches of {_PAGE_LIMIT} records
    per request, optionally filtered by createdAtSince. Continues until all
    pages are exhausted. If any page request fails after all retry attempts,
    raises immediately with a log of how many chapters were successfully
    fetched before the failure — partial data is never returned.

    Retry logic (3 attempts, exponential backoff with jitter) is handled
    transparently by make_api_request() for each individual page request.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): If set, only fetch chapters created after
            this timestamp via createdAtSince. Defaults to None (all chapters).
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.
            Useful for development runs.

    Yields:
        dict: Raw chapter payload from data[] in the MangaDex API response.

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    print(f"[{pipeline_uuid}] Starting MangaDex chapter load.")
    if since:
        print(f"[{pipeline_uuid}] Filtering chapters created since {since.isoformat()}.")

    includes = includes or DEFAULT_INCLUDES
    offset = 0
    total_records = 0
    total: Optional[int] = None

    while True:
        params = _build_params(
            offset=offset,
            limit=limit,
            includes=includes,
            since=since,
        )
        page_number = (offset // limit) + 1

        try:
            response = make_api_request(
                method="GET",
                url=f"{_MANGADEX_CHAPTER_URL}?{params}",
                timeout=_REQUEST_TIMEOUT_SECONDS,
                headers=DEFAULT_HEADERS,
            )
        except APIRequestError as e:
            print(
                f"[{pipeline_uuid}] API request failed on page {page_number} "
                f"(offset={offset}). "
                f"Successfully fetched {total_records}"
                + (f"/{total}" if total is not None else "")
                + f" chapters before failure. Error: {e}"
            )
            raise

        try:
            response_json = response.json()
            records = _parse_page(response_json, offset=offset)
        except ValueError as e:
            print(
                f"[{pipeline_uuid}] Failed to parse response on page {page_number} "
                f"(offset={offset}). "
                f"Successfully fetched {total_records}"
                + (f"/{total}" if total is not None else "")
                + f" chapters before failure. Error: {e}"
            )
            raise

        if total is None and "total" in response_json:
            total = response_json["total"]

        if not records:
            print(f"[{pipeline_uuid}] No more records returned by MangaDex.")
            break

        for record in records:
            yield record
            total_records += 1

            if max_records is not None and total_records >= max_records:
                print(
                    f"[{pipeline_uuid}] Reached max_records={max_records}; "
                    f"stopping early."
                )
                return

        print(
            f"[{pipeline_uuid}] Page {page_number}: fetched {len(records)} chapters "
            f"(total so far: {total_records}"
            + (f"/{total}" if total is not None else "")
            + ")."
        )

        if len(records) < limit:
            break
        if total is not None and total_records >= total:
            break

        offset += len(records)

    print(f"[{pipeline_uuid}] Done. Total chapters retrieved: {total_records}.")


def load_chapters(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
) -> pd.DataFrame:
    """
    Load chapters from MangaDex and return as a DataFrame.

    Thin orchestration wrapper around stream_raw_chapters() that handles
    row construction, pulled_at timestamping, and DataFrame assembly.
    This is the function Mage blocks should call directly.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): If set, only fetch chapters created after
            this timestamp. Passed through to stream_raw_chapters().
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.

    Returns:
        pd.DataFrame: All chapters as a DataFrame with columns:
            mangadex_id, manga_id, pulled_at, payload.

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    pulled_at = datetime.now(timezone.utc)

    rows = [
        {
            "mangadex_id": record.get("id"),
            "manga_id": _extract_manga_id(record),
            "pulled_at": pulled_at,
            "payload": record,
        }
        for record in stream_raw_chapters(
            pipeline_uuid=pipeline_uuid,
            since=since,
            limit=limit,
            includes=includes,
            max_records=max_records,
        )
    ]

    df = pd.DataFrame(rows)
    if not df.empty:
        df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)
    return df