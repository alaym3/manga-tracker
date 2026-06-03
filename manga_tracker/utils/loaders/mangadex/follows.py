"""
manga_tracker/utils/loaders/mangadex/follows.py

Fetches the authenticated user's followed manga and personal ratings from the
MangaDex API. Requires a Personal API Client — see mangadex.org > Account >
API Clients.

Auth uses the OAuth password grant since follows and ratings are user-scoped.
The token endpoint (auth.mangadex.org) uses form-encoded POST, not JSON, so
it goes through requests directly rather than make_api_request. Pagination
of the follows list and ratings batching use make_api_request for standard
retry behaviour.

Required env vars:
    MANGADEX_CLIENT_ID
    MANGADEX_CLIENT_SECRET
    MANGADEX_USERNAME
    MANGADEX_PASSWORD
"""

import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

import pandas as pd
import requests

from manga_tracker.utils.helpers.api_request import make_api_request
from manga_tracker.utils.logging import get_logger

_AUTH_URL = "https://auth.mangadex.org/realms/mangadex/protocol/openid-connect/token"
_FOLLOWS_URL = "https://api.mangadex.org/user/follows/manga"
_RATINGS_URL = "https://api.mangadex.org/rating"
_PAGE_LIMIT = 100
_RATINGS_BATCH = 100
_SLEEP_BETWEEN_PAGES = 0.5
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "manga-tracker/follows-loader/1.0",
}


def get_access_token() -> str:
    """Exchange Personal API Client credentials for a short-lived Bearer token."""
    response = requests.post(
        _AUTH_URL,
        data={
            "grant_type": "password",
            "username": os.environ["MANGADEX_USERNAME"],
            "password": os.environ["MANGADEX_PASSWORD"],
            "client_id": os.environ["MANGADEX_CLIENT_ID"],
            "client_secret": os.environ["MANGADEX_CLIENT_SECRET"],
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _extract_title(record: dict) -> str:
    title_obj = record.get("attributes", {}).get("title", {})
    return (
        title_obj.get("en") or title_obj.get("ja-ro") or next(iter(title_obj.values()), "Unknown")
    )


def _stream_follows(access_token: str, pipeline_uuid: str) -> List[dict]:
    """Paginate through /user/follows/manga and return all manga records."""
    log = get_logger(__name__).bind(pipeline_uuid=pipeline_uuid)
    auth_headers = {**_HEADERS, "Authorization": f"Bearer {access_token}"}
    all_records = []
    offset = 0

    while True:
        params = urlencode(
            [("limit", _PAGE_LIMIT), ("offset", offset)],
            quote_via=quote,
        )
        body = make_api_request(
            method="GET",
            url=f"{_FOLLOWS_URL}?{params}",
            headers=auth_headers,
            timeout=30,
        ).json()

        records = body.get("data", [])
        if not records:
            break

        all_records.extend(records)
        total = body.get("total", 0)
        print(f"[{pipeline_uuid}] Fetched {len(all_records)}/{total} follows.")
        log.info("follows_page_fetched", fetched=len(all_records), total=total)

        if len(all_records) >= total:
            break

        offset += len(records)
        time.sleep(_SLEEP_BETWEEN_PAGES)

    return all_records


def _fetch_ratings(
    access_token: str,
    manga_ids: List[str],
    pipeline_uuid: str,
) -> Dict[str, Tuple[int, Optional[datetime]]]:
    """
    Fetch the user's personal ratings for the given manga IDs.

    Batches requests to stay under the API's per-request limit.

    Returns:
        Dict mapping mangadex_id → (rating, rated_at). Only rated manga appear.
    """
    log = get_logger(__name__).bind(pipeline_uuid=pipeline_uuid)
    auth_headers = {**_HEADERS, "Authorization": f"Bearer {access_token}"}
    ratings: Dict[str, Tuple[int, Optional[datetime]]] = {}

    for i in range(0, len(manga_ids), _RATINGS_BATCH):
        batch = manga_ids[i : i + _RATINGS_BATCH]
        params = urlencode([("manga[]", mid) for mid in batch], quote_via=quote)
        body = make_api_request(
            method="GET",
            url=f"{_RATINGS_URL}?{params}",
            headers=auth_headers,
            timeout=30,
        ).json()

        raw_ratings = body.get("ratings", {})
        if not isinstance(raw_ratings, dict):
            raw_ratings = {}
        for manga_id, data in raw_ratings.items():
            raw_ts = data.get("createdAt")
            rated_at = datetime.fromisoformat(raw_ts) if raw_ts else None
            ratings[manga_id] = (data["rating"], rated_at)

        batch_num = i // _RATINGS_BATCH + 1
        rated_count = len(body.get("ratings", {}))
        print(f"[{pipeline_uuid}] Ratings batch {batch_num}: {rated_count} rated.")
        log.info("ratings_batch_fetched", batch=batch_num, rated=rated_count)
        time.sleep(_SLEEP_BETWEEN_PAGES)

    return ratings


def load_follows(pipeline_uuid: str) -> pd.DataFrame:
    """
    Authenticate and return all followed manga as a DataFrame, including the
    user's personal rating for each title where one exists.

    This is the function Mage blocks should call directly.

    Returns:
        pd.DataFrame: Columns: mangadex_id, title, rating (nullable INT), rated_at (nullable TIMESTAMPTZ).
    """
    log = get_logger(__name__).bind(pipeline_uuid=pipeline_uuid)
    print(f"[{pipeline_uuid}] Authenticating with MangaDex...")
    log.info("authenticating")
    access_token = get_access_token()
    print(f"[{pipeline_uuid}] Authenticated. Fetching follows...")
    log.info("authenticated_fetching_follows")

    records = _stream_follows(access_token, pipeline_uuid)
    manga_ids = [r["id"] for r in records]

    print(f"[{pipeline_uuid}] Fetching personal ratings for {len(manga_ids)} followed manga...")
    log.info("fetching_ratings", manga_count=len(manga_ids))
    ratings = _fetch_ratings(access_token, manga_ids, pipeline_uuid)

    rows = []
    for record in records:
        mid = record["id"]
        rating_val, rated_at = ratings.get(mid, (None, None))
        rows.append(
            {
                "mangadex_id": mid,
                "title": _extract_title(record),
                "rating": rating_val,
                "rated_at": rated_at,
            }
        )

    if not rows:
        return pd.DataFrame(columns=["mangadex_id", "title", "rating", "rated_at"])

    df = pd.DataFrame(rows)
    df["rated_at"] = pd.to_datetime(df["rated_at"], utc=True)
    rated_count = df["rating"].notna().sum()
    preview = [r["title"] for r in rows[:5]]
    suffix = "..." if len(rows) > 5 else ""
    print(
        f"[{pipeline_uuid}] Done. {len(df)} manga followed, {rated_count} rated: {preview}{suffix}"
    )
    log.info(
        "load_complete",
        manga_count=len(df),
        rated_count=int(rated_count),
        preview=f"{preview}{suffix}",
    )
    return df
