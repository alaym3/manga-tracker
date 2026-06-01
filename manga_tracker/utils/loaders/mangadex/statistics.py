"""
manga_tracker/utils/loaders/mangadex/statistics.py

Fetches community statistics (ratings, follows) for all manga in raw.manga
from the MangaDex public GET /statistics/manga endpoint.

No authentication required — statistics are public.

API response shape per manga ID:
    {
        "rating": {"average": 8.5, "bayesian": 8.2, "distribution": {"1": 0, ..., "10": 150}},
        "follows": 5000,
        "comments": {"repliesCount": 42}
    }

Each row stored as (mangadex_id, payload JSONB, pulled_at) to match the raw
table pattern used by manga_responses and chapter_responses.

Use stream_statistics_batches() rather than load_statistics() so callers can
write each batch to Postgres immediately and keep memory usage flat.
"""

import time
from datetime import datetime
from os import path
from typing import Generator, List, Tuple
from urllib.parse import quote, urlencode

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path

from manga_tracker.utils.helpers.api_request import make_api_request
from manga_tracker.utils.logging import get_logger

_STATISTICS_URL = "https://api.mangadex.org/statistics/manga"
_BATCH_SIZE = 100
_SLEEP_BETWEEN_BATCHES = 0.5
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "manga-tracker/statistics-loader/1.0",
}


def _config_path() -> str:
    return path.join(get_repo_path(), "io_config.yaml")


def _load_manga_ids(config_profile: str) -> List[str]:
    """Read all mangadex_ids from raw.manga_responses."""
    with Postgres.with_config(ConfigFileLoader(_config_path(), config_profile)) as pg:
        df = pg.load("SELECT DISTINCT mangadex_id FROM raw.manga_responses ORDER BY mangadex_id")
    return df["mangadex_id"].tolist()


def _fetch_statistics_batch(manga_ids: List[str]) -> dict:
    """
    Call GET /statistics/manga for up to _BATCH_SIZE IDs.

    Returns the 'statistics' dict from the response, keyed by manga ID.
    """
    params = urlencode([("manga[]", mid) for mid in manga_ids], quote_via=quote)
    response = make_api_request(
        method="GET",
        url=f"{_STATISTICS_URL}?{params}",
        headers=_HEADERS,
        timeout=30,
    )
    return response.json().get("statistics", {})


def stream_statistics_batches(
    pipeline_uuid: str,
    config_profile: str,
    pulled_at: datetime,
) -> Generator[Tuple[int, int, pd.DataFrame], None, None]:
    """
    Yield (batch_num, total_batches, df) for each batch of manga statistics.

    Each yielded DataFrame has columns: mangadex_id, payload, pulled_at.
    Callers should write each batch to Postgres immediately to keep memory flat.
    """
    log = get_logger(__name__).bind(pipeline_uuid=pipeline_uuid)
    manga_ids = _load_manga_ids(config_profile)
    total_batches = max(1, (len(manga_ids) + _BATCH_SIZE - 1) // _BATCH_SIZE)
    print(
        f"[{pipeline_uuid}] Fetching statistics for {len(manga_ids)} manga in {total_batches} batches..."
    )
    log.info("fetching_statistics", manga_count=len(manga_ids), total_batches=total_batches)

    for i in range(0, len(manga_ids), _BATCH_SIZE):
        batch = manga_ids[i : i + _BATCH_SIZE]
        batch_num = i // _BATCH_SIZE + 1
        stats = _fetch_statistics_batch(batch)

        rows = [
            {"mangadex_id": manga_id, "payload": stat_payload, "pulled_at": pulled_at}
            for manga_id, stat_payload in stats.items()
        ]
        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(columns=["mangadex_id", "payload", "pulled_at"])
        )
        if not df.empty:
            df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)

        yield batch_num, total_batches, df

        if i + _BATCH_SIZE < len(manga_ids):
            time.sleep(_SLEEP_BETWEEN_BATCHES)
