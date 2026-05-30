"""
manga_tracker/utils/notifiers/manga_notifier.py

Queries for newly ingested manga whose tags overlap with a configured list
and sends one Discord notification per match.
"""

from datetime import datetime
from os import path
from typing import List

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path

from manga_tracker.utils.notifiers.base import run_with_watermark
from manga_tracker.utils.notifiers.discord import send_notification

_CHECKPOINT_KEY = "notify_new_manga"


def _config_path() -> str:
    return path.join(get_repo_path(), "io_config.yaml")


def send_manga_notifications(
    webhook_url: str,
    notification_tags: List[str],
    config_profile: str,
    pipeline_uuid: str,
) -> None:
    # Build the Postgres array literal once outside the closure
    tags_array = "ARRAY[" + ", ".join(f"'{t}'" for t in notification_tags) + "]::text[]"
    tag_set = set(notification_tags)

    def _notify(watermark: datetime) -> None:
        with Postgres.with_config(ConfigFileLoader(_config_path(), config_profile)) as pg:
            new_manga = pg.load(f"""
                SELECT
                    mangadex_id,
                    title,
                    tags,
                    status,
                    year
                FROM staging.stg_manga
                WHERE ingested_at > '{watermark.isoformat()}'
                  AND tags && {tags_array}
                ORDER BY ingested_at
            """)

        if new_manga.empty:
            print(f"[{pipeline_uuid}] No new manga matching tags: {notification_tags}")
            return

        for _, row in new_manga.iterrows():
            matching = [t for t in (row["tags"] or []) if t in tag_set]
            parts = [
                " · ".join(matching),
                row.get("status") or "",
                str(int(row["year"])) if pd.notna(row.get("year")) else "",
            ]
            message = " | ".join(p for p in parts if p)
            send_notification(
                webhook_url=webhook_url,
                title=f"New manga: {row['title']}",
                message=message,
            )
            print(f"[{pipeline_uuid}] Notified: {row['title']} ({', '.join(matching)})")

    run_with_watermark(_CHECKPOINT_KEY, config_profile, pipeline_uuid, _notify)
