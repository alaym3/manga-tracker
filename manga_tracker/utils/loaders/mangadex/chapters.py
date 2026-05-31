"""
manga_tracker/utils/loaders/mangadex/chapters.py

Loads all English chapters from the MangaDex API using date-chunked pagination.
Chunks by createdAt to stay under MangaDex's 10k Elasticsearch offset limit.
Client-side filtering is used to cap each chunk since the API does not support
a createdAtBefore parameter.

No authentication required — MangaDex public API is unauthenticated.

Retry logic per page request is handled by the shared utility:
    manga_tracker/utils/helpers/api_request.py
"""

import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Generator, Iterator, List, Optional, Tuple
from urllib.parse import quote, urlencode

import pandas as pd

from manga_tracker.utils.helpers.api_request import make_api_request

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANGADEX_CHAPTER_URL = "https://api.mangadex.org/chapter"
_PAGE_LIMIT = 100
_REQUEST_TIMEOUT_SECONDS = 30
_CHUNK_DAYS = (
    7  # chunk by week; will split dynamically if a time window still hits the offset limit
)
_MIN_CHUNK_HOURS = 1
_MANGADEX_EPOCH = datetime(2018, 1, 1, tzinfo=timezone.utc)
_SLEEP_BETWEEN_PAGES = 1.5  # seconds — prevents CDN throttling
DEFAULT_INCLUDES = ["scanlation_group"]
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "manga-tracker/raw-chapter-loader/1.0",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_date_chunks(
    start: datetime,
    end: datetime,
    chunk_days: int,
) -> Iterator[Tuple[datetime, datetime]]:
    """
    Yield (chunk_start, chunk_end) tuples covering start to end in
    increments of chunk_days days.

    chunk_end is used for client-side filtering only — it is not sent
    to the API since createdAtBefore is not a supported parameter.
    """
    chunk_start = start
    while chunk_start < end:
        chunk_end = chunk_start + timedelta(days=chunk_days)
        if chunk_end > end:
            chunk_end = end
        yield chunk_start, chunk_end
        chunk_start = chunk_end


class ChunkTooLargeError(Exception):
    """Raised when a chunk contains too many records and must be split."""


def _split_chunk_range(
    chunk_start: datetime,
    chunk_end: datetime,
) -> List[Tuple[datetime, datetime]]:
    """Split a time chunk into two smaller windows."""
    span = chunk_end - chunk_start
    if span <= timedelta(hours=_MIN_CHUNK_HOURS):
        raise ChunkTooLargeError(f"Chunk too small to split further: {chunk_start} to {chunk_end}.")
    midpoint = chunk_start + timedelta(seconds=span.total_seconds() / 2)
    return [(chunk_start, midpoint), (midpoint, chunk_end)]


def _collect_chunk_records(
    pipeline_uuid: str,
    chunk_start: datetime,
    chunk_end: datetime,
    limit: int,
    includes: List[str],
    max_records_remaining: Optional[int],
) -> List[Dict[str, Any]]:
    """Fetch all records for a single chunk without yielding them until complete."""
    chunk_records: List[Dict[str, Any]] = []
    offset = 0

    while True:
        if offset >= 10000:
            raise ChunkTooLargeError(
                f"Chunk {chunk_start.date()} to {chunk_end.date()} exceeds Mangadex offset limit."
            )

        params = _build_params(
            offset=offset,
            limit=limit,
            includes=includes,
            since=chunk_start,
        )
        (offset // limit) + 1

        response = make_api_request(
            method="GET",
            url=f"{_MANGADEX_CHAPTER_URL}?{params}",
            timeout=_REQUEST_TIMEOUT_SECONDS,
            headers=DEFAULT_HEADERS,
        )
        response_json = response.json()
        page_records = _parse_page(response_json, offset=offset)

        if not page_records:
            break

        chunk_exhausted = False
        for record in page_records:
            created_at = _parse_created_at(record)
            if created_at and created_at >= chunk_end:
                chunk_exhausted = True
                break

            chunk_records.append(record)
            if max_records_remaining is not None and len(chunk_records) >= max_records_remaining:
                return chunk_records

        if chunk_exhausted or len(page_records) < limit:
            break

        offset += len(page_records)
        time.sleep(_SLEEP_BETWEEN_PAGES)

    return chunk_records


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
        ("translatedLanguage[]", "en"),
    ]
    for include in includes:
        parts.append(("includes[]", include))
    return urlencode(parts, quote_via=lambda s, safe, encoding, errors: quote(s, safe="[]/:"))


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


def _parse_created_at(record: dict) -> Optional[datetime]:
    """Extract and parse createdAt from a chapter record's attributes."""
    raw = record.get("attributes", {}).get("createdAt")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def stream_raw_chapters_by_chunk(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
) -> Generator[Tuple[datetime, List[Dict[str, Any]]], None, None]:
    """
    Yield (chunk_end, records) for each date chunk from MangaDex.

    Unlike stream_raw_chapters() which yields individual records, this yields one
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
            of raw chapter payloads (may be empty for sparse date ranges).

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    print(f"[{pipeline_uuid}] Starting MangaDex chapter load.")

    since = since or _MANGADEX_EPOCH
    before = datetime.now(timezone.utc)
    includes = list(includes or DEFAULT_INCLUDES)
    total_records = 0
    chunks: Deque[Tuple[datetime, datetime]] = deque(
        _generate_date_chunks(since, before, _CHUNK_DAYS)
    )

    print(
        f"[{pipeline_uuid}] Date range: {since.date()} to {before.date()} "
        f"— {len(chunks)} initial chunks of {_CHUNK_DAYS} days each."
    )

    chunk_index = 0
    while chunks:
        chunk_start, chunk_end = chunks.popleft()
        chunk_index += 1
        print(f"[{pipeline_uuid}] Chunk {chunk_index}: {chunk_start.date()} to {chunk_end.date()}.")

        max_records_remaining = None if max_records is None else max_records - total_records

        try:
            chunk_records = _collect_chunk_records(
                pipeline_uuid=pipeline_uuid,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                limit=limit,
                includes=includes,
                max_records_remaining=max_records_remaining,
            )
        except ChunkTooLargeError:
            smaller_chunks = _split_chunk_range(chunk_start, chunk_end)
            print(
                f"[{pipeline_uuid}] Chunk {chunk_index}: "
                f"too large for offset pagination, splitting into "
                f"{len(smaller_chunks)} smaller chunks."
            )
            for smaller_chunk in reversed(smaller_chunks):
                chunks.appendleft(smaller_chunk)
            continue

        if not chunk_records:
            print(f"[{pipeline_uuid}] Chunk {chunk_index}: no records in range.")
            # Yield the empty chunk so callers can advance their checkpoint past
            # this date range and avoid re-scanning it on restarts.
            yield chunk_end, []
            continue

        print(
            f"[{pipeline_uuid}] Chunk {chunk_index}: fetched {len(chunk_records)} records "
            f"from {chunk_start.date()} to {chunk_end.date()}."
        )

        total_records += len(chunk_records)
        yield chunk_end, chunk_records

        if max_records is not None and total_records >= max_records:
            print(f"[{pipeline_uuid}] Reached max_records={max_records}; stopping early.")
            return

    print(f"[{pipeline_uuid}] Done. Total chapters retrieved: {total_records}.")


def stream_raw_chapters(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield raw chapter payloads from MangaDex using date-chunked pagination.

    Thin wrapper around stream_raw_chapters_by_chunk() that flattens chunk
    batches into individual records. Use stream_raw_chapters_by_chunk() directly
    when you need chunk boundaries for checkpointing.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to _MANGADEX_EPOCH.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.

    Yields:
        dict: Raw chapter payload from data[] in the MangaDex API response.

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    for _, chunk_records in stream_raw_chapters_by_chunk(
        pipeline_uuid=pipeline_uuid,
        since=since,
        limit=limit,
        includes=includes,
        max_records=max_records,
    ):
        yield from chunk_records


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
        since (datetime, optional): Start of date range. Defaults to _MANGADEX_EPOCH.
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
