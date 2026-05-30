"""
manga_tracker/utils/loaders/mangadex/follows.py

Fetches the authenticated user's followed manga from the MangaDex API.
Requires a Personal API Client — see mangadex.org > Account > API Clients.

Auth uses the OAuth password grant since the follows list is user-scoped.
The token endpoint (auth.mangadex.org) uses form-encoded POST, not JSON, so
it goes through requests directly rather than make_api_request. Pagination
of the follows list uses make_api_request for standard retry behaviour.

Required env vars:
    MANGADEX_CLIENT_ID
    MANGADEX_CLIENT_SECRET
    MANGADEX_USERNAME
    MANGADEX_PASSWORD
"""

import os
import time
from typing import List
from urllib.parse import urlencode, quote

import pandas as pd
import requests

from manga_tracker.utils.helpers.api_request import make_api_request

_AUTH_URL = "https://auth.mangadex.org/realms/mangadex/protocol/openid-connect/token"
_FOLLOWS_URL = "https://api.mangadex.org/user/follows/manga"
_PAGE_LIMIT = 100
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
        title_obj.get("en")
        or title_obj.get("ja-ro")
        or next(iter(title_obj.values()), "Unknown")
    )


def _stream_follows(access_token: str, pipeline_uuid: str) -> List[dict]:
    """Paginate through /user/follows/manga and return all manga records."""
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

        if len(all_records) >= total:
            break

        offset += len(records)
        time.sleep(_SLEEP_BETWEEN_PAGES)

    return all_records


def load_follows(pipeline_uuid: str) -> pd.DataFrame:
    """
    Authenticate and return all followed manga as a DataFrame.

    This is the function Mage blocks should call directly.

    Returns:
        pd.DataFrame: Columns: mangadex_id, title.
    """
    print(f"[{pipeline_uuid}] Authenticating with MangaDex...")
    access_token = get_access_token()
    print(f"[{pipeline_uuid}] Authenticated. Fetching follows...")

    records = _stream_follows(access_token, pipeline_uuid)

    rows = [
        {
            "mangadex_id": record["id"],
            "title": _extract_title(record),
        }
        for record in records
    ]

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["mangadex_id", "title"])
    preview = [r["title"] for r in rows[:5]]
    suffix = "..." if len(rows) > 5 else ""
    print(f"[{pipeline_uuid}] Done. {len(df)} manga followed: {preview}{suffix}")
    return df
