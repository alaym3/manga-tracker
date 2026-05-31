"""
manga_tracker/utils/notifiers/chapter_notifier.py

Queries for newly ingested chapters belonging to followed manga and sends
one Discord notification per manga, grouping multiple chapters into a single
message to avoid spam.
"""

from datetime import datetime
from os import path

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path

from manga_tracker.utils.notifiers.base import run_with_watermark
from manga_tracker.utils.notifiers.discord import send_embed, send_notification

_CHECKPOINT_KEY = "notify_new_chapters"


def _config_path() -> str:
    return path.join(get_repo_path(), "io_config.yaml")


def send_chapter_notifications(
    webhook_url: str,
    config_profile: str,
    pipeline_uuid: str,
) -> None:
    def _notify(watermark: datetime) -> None:
        with Postgres.with_config(ConfigFileLoader(_config_path(), config_profile)) as pg:
            new_chapters = pg.load(f"""
                SELECT
                    c.manga_mangadex_id,
                    f.title          AS manga_title,
                    c.mangadex_id    AS chapter_id,
                    c.chapter_number,
                    c.title          AS chapter_title,
                    c.published_at,
                    m.cover_url
                FROM staging.stg_chapters c
                JOIN raw.user_follows f ON f.mangadex_id = c.manga_mangadex_id
                LEFT JOIN staging.stg_manga m ON m.mangadex_id = c.manga_mangadex_id
                WHERE c.ingested_at > '{watermark.isoformat()}'
                  AND (c.is_unavailable IS FALSE OR c.is_unavailable IS NULL)
                ORDER BY c.manga_mangadex_id, c.published_at
            """)

        if new_chapters.empty:
            print(f"[{pipeline_uuid}] No new chapters for followed manga.")
            return

        for manga_id, group in new_chapters.groupby("manga_mangadex_id"):
            manga_title = group["manga_title"].iloc[0]
            cover_url = group["cover_url"].iloc[0] if pd.notna(group["cover_url"].iloc[0]) else None
            manga_url = f"https://mangadex.org/title/{manga_id}"

            lines = []
            for _, row in group.iterrows():
                chapter_url = f"https://mangadex.org/chapter/{row['chapter_id']}"
                ch = f"Ch. {row['chapter_number']}"
                if row["chapter_title"] and pd.notna(row["chapter_title"]):
                    ch += f" — {row['chapter_title']}"
                lines.append(f"[{ch}]({chapter_url})")

            # For a single chapter, link the title directly to the reader
            title_url = f"https://mangadex.org/chapter/{group['chapter_id'].iloc[0]}" \
                if len(lines) == 1 else manga_url

            label = "chapter" if len(lines) == 1 else "chapters"
            send_embed(
                webhook_url=webhook_url,
                title=f"New {label}: {manga_title}",
                title_url=title_url,
                description="\n".join(lines),
                thumbnail_url=cover_url,
            )
            print(f"[{pipeline_uuid}] Notified: {manga_title} ({len(lines)} chapter(s))")

    run_with_watermark(_CHECKPOINT_KEY, config_profile, pipeline_uuid, _notify)
