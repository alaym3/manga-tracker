"""
manga_tracker/utils/loaders/mangadex/manga.py

Loads all manga from the MangaDex API using paginated requests.

No authentication required — MangaDex public API is unauthenticated.

Retry logic per page request is handled by the shared utility:
    manga_tracker/utils/helpers/api_request.py
"""

from datetime import datetime, timezone
from typing import Any, Dict, Generator, Iterable, List, Optional

import pandas as pd

from manga_tracker.utils.helpers.api_request import APIRequestError, make_api_request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANGADEX_MANGA_URL = "https://api.mangadex.org/manga"
_PAGE_LIMIT = 100  # records per page — MangaDex max
_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_INCLUDES = ["author", "artist","cover_art", "tags"]
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "manga-tracker/raw-manga-loader/1.0",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_params(
    offset: int,
    limit: int,
    includes: Iterable[str],
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    for include in includes:
        params.setdefault("includes[]", []).append(include)
    return params


def _parse_page(response_json: dict, offset: int) -> list:
    """
    Validate and extract manga records from a single paginated response.

    Args:
        response_json (dict): Parsed JSON body from the MangaDex API.
        offset (int): Current pagination offset — used for error context.

    Returns:
        List[dict]: Manga records from this page.

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

def stream_raw_manga(
    pipeline_uuid: str,
    limit: int = _PAGE_LIMIT,
    includes: Optional[Iterable[str]] = None,
    max_records: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield raw manga payloads from MangaDex with pagination.

    Fetches manga in paginated batches of {_PAGE_LIMIT} records per request.
    Continues until all pages are exhausted. If any page request fails after all
    retry attempts, raises immediately with a log of how many manga were
    successfully fetched before the failure — partial data is never returned.

    Retry logic (3 attempts, exponential backoff with jitter) is handled
    transparently by make_api_request() for each individual page request.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (Iterable[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.
            Useful for development runs.

    Yields:
        dict: Raw manga payload from data[] in the MangaDex API response.

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    print(f"[{pipeline_uuid}] Starting MangaDex manga load.")

    includes = list(includes or DEFAULT_INCLUDES)
    offset = 0
    total_records = 0
    total: Optional[int] = None  # populated from first response

    while True:
        params = _build_params(offset=offset, limit=limit, includes=includes)
        page_number = (offset // limit) + 1

        try:
            response = make_api_request(
                method="GET",
                url=_MANGADEX_MANGA_URL,
                params=params,
                timeout=_REQUEST_TIMEOUT_SECONDS,
                headers=DEFAULT_HEADERS,
            )
        except APIRequestError as e:
            print(
                f"[{pipeline_uuid}] API request failed on page {page_number} "
                f"(offset={offset}). "
                f"Successfully fetched {total_records}"
                + (f"/{total}" if total is not None else "")
                + f" manga before failure. Error: {e}"
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
                + f" manga before failure. Error: {e}"
            )
            raise

        # Capture total from first response for progress logging
        if total is None and "total" in response_json:
            total = response_json["total"]

        # Empty batch means we've passed the last page
        if not records:
            print(f"[{pipeline_uuid}] No more records returned by MangaDex.")
            break

        for record in records:
            yield record
            total_records += 1

            if max_records is not None and total_records >= max_records:
                print(
                    f"[{pipeline_uuid}] Reached max_records={max_records}; stopping early."
                )
                return

        print(
            f"[{pipeline_uuid}] Page {page_number}: fetched {len(records)} manga "
            f"(total so far: {total_records}"
            + (f"/{total}" if total is not None else "")
            + ")."
        )

        # Stop if this was the last page
        if len(records) < limit:
            break
        if total is not None and total_records >= total:
            break

        offset += len(records)

    print(f"[{pipeline_uuid}] Done. Total manga retrieved: {total_records}.")


def load_manga(
    pipeline_uuid: str,
    limit: int = _PAGE_LIMIT,
    includes=None,
    max_records=None,
):
    """
    Load all manga from the MangaDex API and return as a DataFrame.

    Thin orchestration wrapper around stream_raw_manga() that handles
    row construction, pulled_at timestamping, and DataFrame assembly.
    This is the function Mage blocks should call directly.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (Iterable[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.
            Useful for development runs.

    Returns:
        pd.DataFrame: All manga as a DataFrame with columns:
            mangadex_id, pulled_at, payload.

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    pulled_at = datetime.now(timezone.utc)

    rows = [
        {
            "mangadex_id": record.get("id"),
            "pulled_at": pulled_at,
            "payload": record,
        }
        for record in stream_raw_manga(
            pipeline_uuid=pipeline_uuid,
            limit=limit,
            includes=includes,
            max_records=max_records,
        )
    ]

    df = pd.DataFrame(rows)
    if not df.empty:
        df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)
    return df