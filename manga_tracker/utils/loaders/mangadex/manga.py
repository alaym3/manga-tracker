"""
manga_tracker/utils/loaders/mangadex/manga.py

Loads all manga from the MangaDex API using date-chunked pagination.
Chunks by createdAt to stay under MangaDex's 10k Elasticsearch offset limit.
Client-side filtering is used to cap each chunk since the API does not support
a createdAtBefore parameter.

No authentication required — MangaDex public API is unauthenticated.

Retry logic per page request is handled by the shared utility:
    manga_tracker/utils/helpers/api_request.py
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, Iterator, List, Optional, Tuple
from urllib.parse import quote, urlencode

import pandas as pd

from manga_tracker.utils.helpers.api_request import APIRequestError, make_api_request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANGADEX_MANGA_URL = "https://api.mangadex.org/manga"
_PAGE_LIMIT = 100
_REQUEST_TIMEOUT_SECONDS = 30
_CHUNK_MONTHS = 2  # safe under 10k Elasticsearch limit
_MANGADEX_EPOCH = datetime(2018, 1, 1, tzinfo=timezone.utc)
_SLEEP_BETWEEN_PAGES = 1.5  # seconds — prevents CDN throttling
DEFAULT_INCLUDES = ["author", "artist", "cover_art", "tags"]
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "manga-tracker/raw-manga-loader/1.0",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_date_chunks(
    start: datetime,
    end: datetime,
    chunk_months: int,
) -> Iterator[Tuple[datetime, datetime]]:
    """
    Yield (chunk_start, chunk_end) tuples covering start to end in
    increments of chunk_months months.

    chunk_end is used for client-side filtering only — it is not sent
    to the API since createdAtBefore is not a supported parameter.
    """
    chunk_start = start
    while chunk_start < end:
        chunk_end = chunk_start + timedelta(days=chunk_months * 30)
        if chunk_end > end:
            chunk_end = end
        yield chunk_start, chunk_end
        chunk_start = chunk_end


def _build_params(
    offset: int,
    limit: int,
    includes: List[str],
    since: datetime,
) -> str:
    """Build query string with unencoded brackets for MangaDex API compatibility."""
    parts = [
        ("limit", limit),
        ("offset", offset),
        ("order[createdAt]", "asc"),
        ("createdAtSince", since.strftime("%Y-%m-%dT%H:%M:%S")),
    ]
    for include in includes:
        parts.append(("includes[]", include))
    return urlencode(parts, quote_via=quote)


# unsure about if we need this here - it was required for chapters.
# def _build_params(
#     offset: int,
#     limit: int,
#     includes: List[str],
#     since: datetime,
# ) -> str:
#     """Build query string with unencoded brackets for MangaDex API compatibility."""
#     parts = [
#         ("limit", limit),
#         ("offset", offset),
#         ("order[createdAt]", "asc"),
#         ("createdAtSince", since.strftime("%Y-%m-%dT%H:%M:%S")),
#     ]
#     for include in includes:
#         parts.append(("includes[]", include))
#     return urlencode(parts, quote_via=lambda s, safe, encoding, errors: quote(s, safe="[]/:"))


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


def _parse_created_at(record: dict) -> Optional[datetime]:
    """Extract and parse createdAt from a manga record's attributes."""
    raw = record.get("attributes", {}).get("createdAt")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def stream_raw_manga_by_chunk(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
) -> Generator[Tuple[datetime, List[Dict[str, Any]]], None, None]:
    """
    Yield (chunk_end, records) for each date chunk from MangaDex.

    Unlike stream_raw_manga() which yields individual records, this yields one
    batch per date window so callers can checkpoint at chunk boundaries. Empty
    chunks still yield (chunk_end, []) so callers can advance their resume cursor
    past sparse date ranges without re-scanning them on restarts.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to _MANGADEX_EPOCH.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after this many total records.

    Yields:
        Tuple[datetime, List[dict]]: (chunk_end, records) where chunk_end is the
            exclusive upper bound used for checkpointing and records is the list
            of raw manga payloads (may be empty for sparse date ranges).

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    print(f"[{pipeline_uuid}] Starting MangaDex manga load.")

    since = since or _MANGADEX_EPOCH
    before = datetime.now(timezone.utc)
    includes = list(includes or DEFAULT_INCLUDES)
    total_records = 0
    chunks = list(_generate_date_chunks(since, before, _CHUNK_MONTHS))

    print(
        f"[{pipeline_uuid}] Date range: {since.date()} to {before.date()} "
        f"— {len(chunks)} chunks of {_CHUNK_MONTHS} months each."
    )

    for chunk_index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        print(
            f"[{pipeline_uuid}] Chunk {chunk_index}/{len(chunks)}: "
            f"{chunk_start.date()} to {chunk_end.date()}."
        )

        offset = 0
        chunk_records: List[Dict[str, Any]] = []
        total: Optional[int] = None

        while True:
            params = _build_params(
                offset=offset,
                limit=limit,
                includes=includes,
                since=chunk_start,
            )
            page_number = (offset // limit) + 1

            try:
                response = make_api_request(
                    method="GET",
                    url=f"{_MANGADEX_MANGA_URL}?{params}",
                    timeout=_REQUEST_TIMEOUT_SECONDS,
                    headers=DEFAULT_HEADERS,
                )
            except APIRequestError as e:
                print(
                    f"[{pipeline_uuid}] API request failed on chunk "
                    f"{chunk_index}/{len(chunks)} page {page_number} "
                    f"(offset={offset}). "
                    f"Successfully fetched {total_records} manga before failure. "
                    f"Error: {e}"
                )
                raise

            try:
                response_json = response.json()
                records = _parse_page(response_json, offset=offset)
            except ValueError as e:
                print(
                    f"[{pipeline_uuid}] Failed to parse response on chunk "
                    f"{chunk_index}/{len(chunks)} page {page_number} "
                    f"(offset={offset}). "
                    f"Successfully fetched {total_records} manga before failure. "
                    f"Error: {e}"
                )
                raise

            if total is None and "total" in response_json:
                total = response_json["total"]

            if not records:
                print(f"[{pipeline_uuid}] Chunk {chunk_index}/{len(chunks)}: no more records.")
                break

            chunk_exhausted = False
            for record in records:
                created_at = _parse_created_at(record)
                if created_at and created_at >= chunk_end:
                    chunk_exhausted = True
                    break
                chunk_records.append(record)
                if max_records is not None and (total_records + len(chunk_records)) >= max_records:
                    chunk_exhausted = True
                    break

            print(
                f"[{pipeline_uuid}] Chunk {chunk_index}/{len(chunks)} "
                f"page {page_number}: fetched {len(records)} manga "
                f"(chunk total: {len(chunk_records)}, overall: {total_records + len(chunk_records)})."
            )

            if chunk_exhausted:
                print(
                    f"[{pipeline_uuid}] Chunk {chunk_index}/{len(chunks)}: "
                    f"reached chunk boundary at {chunk_end.date()}, advancing."
                )
                break

            if len(records) < limit:
                break

            offset += len(records)
            time.sleep(_SLEEP_BETWEEN_PAGES)

        if not chunk_records:
            print(f"[{pipeline_uuid}] Chunk {chunk_index}/{len(chunks)}: no records in range.")
            yield chunk_end, []
            continue

        total_records += len(chunk_records)
        yield chunk_end, chunk_records

        if max_records is not None and total_records >= max_records:
            print(f"[{pipeline_uuid}] Reached max_records={max_records}; stopping early.")
            return

    print(f"[{pipeline_uuid}] Done. Total manga retrieved: {total_records}.")


def stream_raw_manga(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield raw manga payloads from MangaDex using date-chunked pagination.

    Thin wrapper around stream_raw_manga_by_chunk() that flattens chunk
    batches into individual records. Use stream_raw_manga_by_chunk() directly
    when you need chunk boundaries for checkpointing.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to _MANGADEX_EPOCH.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.

    Yields:
        dict: Raw manga payload from data[] in the MangaDex API response.

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    for _, chunk_records in stream_raw_manga_by_chunk(
        pipeline_uuid=pipeline_uuid,
        since=since,
        limit=limit,
        includes=includes,
        max_records=max_records,
    ):
        yield from chunk_records


def load_manga(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
) -> pd.DataFrame:
    """
    Load all manga from the MangaDex API and return as a DataFrame.

    Thin orchestration wrapper around stream_raw_manga() that handles
    row construction, pulled_at timestamping, and DataFrame assembly.
    This is the function Mage blocks should call directly.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to _MANGADEX_EPOCH.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
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
