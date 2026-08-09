"""
manga_tracker/utils/loaders/mangadex/chunked_pagination.py

Shared engine for date-chunked, offset-paginated MangaDex resource fetching.
Used by chapters.py and manga.py, which each build a ChunkedResourceConfig
describing what varies per resource and delegate to stream_records_by_chunk().

Chunks by createdAt to stay under MangaDex's 10k Elasticsearch offset limit.
Client-side filtering is used to cap each chunk since the API does not support
a createdAtBefore parameter. A chunk that itself exceeds the offset limit is
dynamically halved and re-queued rather than failing the whole load.

No authentication required — MangaDex public API is unauthenticated.

Retry logic per page request is handled by the shared utility:
    manga_tracker/utils/helpers/api_request.py
"""

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, Generator, Iterator, List, Optional, Tuple
from urllib.parse import quote, urlencode

import requests

from manga_tracker.utils.helpers.api_request import make_api_request
from manga_tracker.utils.logging import get_logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANGADEX_EPOCH = datetime(2018, 1, 1, tzinfo=timezone.utc)
_OFFSET_LIMIT = 10_000


class ChunkTooLargeError(Exception):
    """Raised when a chunk contains too many records and must be split."""


@dataclass(frozen=True)
class ChunkedResourceConfig:
    """Everything that varies per MangaDex resource (e.g. chapters vs manga)."""

    resource_name: str
    url: str
    default_includes: List[str]
    headers: Dict[str, str]
    extra_query_params: Tuple[Tuple[str, str], ...] = ()
    chunk_days: int = 7
    min_chunk_hours: int = 1
    page_limit: int = 100
    request_timeout_seconds: int = 30
    sleep_between_pages: float = 1.5


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


def _split_chunk_range(
    chunk_start: datetime,
    chunk_end: datetime,
    min_chunk_hours: int = 1,
) -> List[Tuple[datetime, datetime]]:
    """Split a time chunk into two smaller windows."""
    span = chunk_end - chunk_start
    if span <= timedelta(hours=min_chunk_hours):
        raise ChunkTooLargeError(f"Chunk too small to split further: {chunk_start} to {chunk_end}.")
    midpoint = chunk_start + timedelta(seconds=span.total_seconds() / 2)
    return [(chunk_start, midpoint), (midpoint, chunk_end)]


def _build_params(
    offset: int,
    limit: int,
    includes: List[str],
    since: datetime,
    extra_query_params: Tuple[Tuple[str, str], ...] = (),
) -> str:
    """Build query string with unencoded brackets for MangaDex API compatibility."""
    parts = [
        ("limit", limit),
        ("offset", offset),
        ("order[createdAt]", "asc"),
        ("createdAtSince", since.strftime("%Y-%m-%dT%H:%M:%S")),
        *extra_query_params,
    ]
    for include in includes:
        parts.append(("includes[]", include))
    return urlencode(parts, quote_via=lambda s, safe, encoding, errors: quote(s, safe="[]/:"))


def _parse_page(response_json: dict, offset: int) -> list:
    """
    Validate and extract records from a single paginated response.

    Args:
        response_json (dict): Parsed JSON body from the MangaDex API.
        offset (int): Current pagination offset — used for error context.

    Returns:
        List[dict]: Records from this page.

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
    """Extract and parse createdAt from a record's attributes."""
    raw = record.get("attributes", {}).get("createdAt")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def _collect_chunk_records(
    config: ChunkedResourceConfig,
    pipeline_uuid: str,
    chunk_start: datetime,
    chunk_end: datetime,
    limit: int,
    includes: List[str],
    max_records_remaining: Optional[int],
    make_request: Callable[..., requests.Response],
) -> List[Dict[str, Any]]:
    """Fetch all records for a single chunk without yielding them until complete."""
    chunk_records: List[Dict[str, Any]] = []
    offset = 0

    while True:
        if offset >= _OFFSET_LIMIT:
            raise ChunkTooLargeError(
                f"Chunk {chunk_start.date()} to {chunk_end.date()} exceeds Mangadex offset limit."
            )

        params = _build_params(
            offset=offset,
            limit=limit,
            includes=includes,
            since=chunk_start,
            extra_query_params=config.extra_query_params,
        )

        response = make_request(
            method="GET",
            url=f"{config.url}?{params}",
            timeout=config.request_timeout_seconds,
            headers=config.headers,
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
        time.sleep(config.sleep_between_pages)

    return chunk_records


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def stream_records_by_chunk(
    config: ChunkedResourceConfig,
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: Optional[int] = None,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
    make_request: Callable[..., requests.Response] = make_api_request,
) -> Generator[Tuple[datetime, List[Dict[str, Any]]], None, None]:
    """
    Yield (chunk_end, records) for each date chunk from MangaDex.

    Yields one batch per date window so callers can checkpoint at chunk
    boundaries. Empty chunks still yield (chunk_end, []) so callers can
    advance their resume cursor past sparse date ranges without re-scanning
    them on restarts. Chunks that exceed MangaDex's offset limit are
    dynamically split and re-queued rather than failing the load.

    Args:
        config (ChunkedResourceConfig): Resource-specific fetch configuration.
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to MANGADEX_EPOCH.
        limit (int, optional): Page size to request from MangaDex. Defaults to config.page_limit.
        includes (List[str], optional): Relationship expansions to include.
            Defaults to config.default_includes.
        max_records (int, optional): Stop early after this many total records.
        make_request (Callable, optional): HTTP call function. Defaults to
            make_api_request; tests can inject a fake here instead of
            monkeypatching the module-level import.

    Yields:
        Tuple[datetime, List[dict]]: (chunk_end, records) where chunk_end is the
            exclusive upper bound used for checkpointing and records is the list
            of raw payloads (may be empty for sparse date ranges).

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    log = get_logger(__name__).bind(pipeline_uuid=pipeline_uuid, resource=config.resource_name)
    limit = limit or config.page_limit
    includes = list(includes if includes is not None else config.default_includes)

    print(f"[{pipeline_uuid}] Starting MangaDex {config.resource_name} load.")
    log.info(f"{config.resource_name}_load_started")

    since = since or MANGADEX_EPOCH
    before = datetime.now(timezone.utc)
    total_records = 0
    chunks: Deque[Tuple[datetime, datetime]] = deque(
        _generate_date_chunks(since, before, config.chunk_days)
    )

    print(
        f"[{pipeline_uuid}] Date range: {since.date()} to {before.date()} "
        f"— {len(chunks)} initial chunks of {config.chunk_days} days each."
    )
    log.info(
        "date_range", since=str(since.date()), before=str(before.date()), initial_chunks=len(chunks)
    )

    chunk_index = 0
    while chunks:
        chunk_start, chunk_end = chunks.popleft()
        chunk_index += 1
        print(f"[{pipeline_uuid}] Chunk {chunk_index}: {chunk_start.date()} to {chunk_end.date()}.")
        log.info(
            "chunk_started",
            chunk=chunk_index,
            chunk_start=str(chunk_start.date()),
            chunk_end=str(chunk_end.date()),
        )

        max_records_remaining = None if max_records is None else max_records - total_records

        try:
            chunk_records = _collect_chunk_records(
                config=config,
                pipeline_uuid=pipeline_uuid,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                limit=limit,
                includes=includes,
                max_records_remaining=max_records_remaining,
                make_request=make_request,
            )
        except ChunkTooLargeError:
            smaller_chunks = _split_chunk_range(chunk_start, chunk_end, config.min_chunk_hours)
            print(
                f"[{pipeline_uuid}] Chunk {chunk_index}: "
                f"too large for offset pagination, splitting into "
                f"{len(smaller_chunks)} smaller chunks."
            )
            log.warning(
                "chunk_too_large_splitting", chunk=chunk_index, split_count=len(smaller_chunks)
            )
            for smaller_chunk in reversed(smaller_chunks):
                chunks.appendleft(smaller_chunk)
            continue

        if not chunk_records:
            print(f"[{pipeline_uuid}] Chunk {chunk_index}: no records in range.")
            log.info("chunk_empty", chunk=chunk_index)
            # Yield the empty chunk so callers can advance their checkpoint past
            # this date range and avoid re-scanning it on restarts.
            yield chunk_end, []
            continue

        print(
            f"[{pipeline_uuid}] Chunk {chunk_index}: fetched {len(chunk_records)} records "
            f"from {chunk_start.date()} to {chunk_end.date()}."
        )
        log.info(
            "chunk_fetched",
            chunk=chunk_index,
            records=len(chunk_records),
            chunk_start=str(chunk_start.date()),
            chunk_end=str(chunk_end.date()),
        )

        total_records += len(chunk_records)
        yield chunk_end, chunk_records

        if max_records is not None and total_records >= max_records:
            print(f"[{pipeline_uuid}] Reached max_records={max_records}; stopping early.")
            log.info("max_records_reached", max_records=max_records, total_records=total_records)
            return

    print(
        f"[{pipeline_uuid}] Done. Total {config.resource_name} records retrieved: {total_records}."
    )
    log.info(f"{config.resource_name}_load_complete", total_records=total_records)
