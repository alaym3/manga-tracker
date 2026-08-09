"""
manga_tracker/utils/loaders/mangadex/chapters.py

Loads all English chapters from the MangaDex API using date-chunked pagination.
Thin adapter over the shared engine in chunked_pagination.py — see that module
for the pagination/offset-limit/splitting mechanics.

No authentication required — MangaDex public API is unauthenticated.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

import pandas as pd
import requests

from manga_tracker.utils.helpers.api_request import make_api_request
from manga_tracker.utils.loaders.mangadex.chunked_pagination import (
    ChunkedResourceConfig,
    ChunkTooLargeError,
    stream_records_by_chunk,
)

__all__ = [
    "ChunkTooLargeError",
    "stream_raw_chapters_by_chunk",
    "stream_raw_chapters",
    "load_chapters",
]

# ---------------------------------------------------------------------------
# Resource configuration
# ---------------------------------------------------------------------------

_MANGADEX_CHAPTER_URL = "https://api.mangadex.org/chapter"
_PAGE_LIMIT = 100
_REQUEST_TIMEOUT_SECONDS = 30
_CHUNK_DAYS = (
    7  # chunk by week; will split dynamically if a time window still hits the offset limit
)
_MIN_CHUNK_HOURS = 1
_SLEEP_BETWEEN_PAGES = 1.5  # seconds — prevents CDN throttling
DEFAULT_INCLUDES = ["scanlation_group"]
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "manga-tracker/raw-chapter-loader/1.0",
}

_CONFIG = ChunkedResourceConfig(
    resource_name="chapter",
    url=_MANGADEX_CHAPTER_URL,
    default_includes=DEFAULT_INCLUDES,
    headers=DEFAULT_HEADERS,
    extra_query_params=(("translatedLanguage[]", "en"),),
    chunk_days=_CHUNK_DAYS,
    min_chunk_hours=_MIN_CHUNK_HOURS,
    page_limit=_PAGE_LIMIT,
    request_timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
    sleep_between_pages=_SLEEP_BETWEEN_PAGES,
)


def _extract_manga_id(payload: dict) -> Optional[str]:
    """Extract manga UUID from relationships[] without needing includes[]=manga."""
    for rel in payload.get("relationships", []):
        if rel.get("type") == "manga":
            return rel.get("id")
    return None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def stream_raw_chapters_by_chunk(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
    make_request: Callable[..., requests.Response] = make_api_request,
) -> Generator[Tuple[datetime, List[Dict[str, Any]]], None, None]:
    """
    Yield (chunk_end, records) for each date chunk from MangaDex.

    Unlike stream_raw_chapters() which yields individual records, this yields one
    batch per date window so callers can checkpoint at chunk boundaries. Empty
    chunks still yield (chunk_end, []) so callers can advance their resume cursor
    past sparse date ranges without re-scanning them on restarts.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to MANGADEX_EPOCH.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after this many total records.
        make_request (Callable, optional): HTTP call function, injectable for tests.

    Yields:
        Tuple[datetime, List[dict]]: (chunk_end, records) where chunk_end is the
            exclusive upper bound used for checkpointing and records is the list
            of raw chapter payloads (may be empty for sparse date ranges).

    Raises:
        APIRequestError: If any paginated request fails after all retry attempts.
        ValueError: If any page response has an unexpected structure.
    """
    return stream_records_by_chunk(
        config=_CONFIG,
        pipeline_uuid=pipeline_uuid,
        since=since,
        limit=limit,
        includes=includes,
        max_records=max_records,
        make_request=make_request,
    )


def stream_raw_chapters(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
    make_request: Callable[..., requests.Response] = make_api_request,
) -> Generator[Dict[str, Any], None, None]:
    """
    Yield raw chapter payloads from MangaDex using date-chunked pagination.

    Thin wrapper around stream_raw_chapters_by_chunk() that flattens chunk
    batches into individual records. Use stream_raw_chapters_by_chunk() directly
    when you need chunk boundaries for checkpointing.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to MANGADEX_EPOCH.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.
        make_request (Callable, optional): HTTP call function, injectable for tests.

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
        make_request=make_request,
    ):
        yield from chunk_records


def load_chapters(
    pipeline_uuid: str,
    since: Optional[datetime] = None,
    limit: int = _PAGE_LIMIT,
    includes: Optional[List[str]] = None,
    max_records: Optional[int] = None,
    make_request: Callable[..., requests.Response] = make_api_request,
) -> pd.DataFrame:
    """
    Load chapters from MangaDex and return as a DataFrame.

    Thin orchestration wrapper around stream_raw_chapters() that handles
    row construction, pulled_at timestamping, and DataFrame assembly.
    This is the function Mage blocks should call directly.

    Args:
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        since (datetime, optional): Start of date range. Defaults to MANGADEX_EPOCH.
        limit (int): Page size to request from MangaDex. Max 100.
        includes (List[str], optional): Relationship expansions to include.
        max_records (int, optional): Stop early after yielding this many records.
        make_request (Callable, optional): HTTP call function, injectable for tests.

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
            make_request=make_request,
        )
    ]

    df = pd.DataFrame(rows)
    if not df.empty:
        df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)
    return df
