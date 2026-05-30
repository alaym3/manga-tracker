"""
manga_tracker/utils/notifiers/chapter_notifier.py

Queries for newly ingested chapters belonging to followed manga and sends
one Discord notification per manga, grouping multiple chapters into a single
message to avoid spam.

Uses mage.pipeline_checkpoints (pipeline_name='notify_new_chapters') as a
watermark. On the first ever run the watermark is set without sending anything
so backfilled history doesn't flood the notification feed.
"""

from datetime import datetime, timezone
from os import path

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path

from manga_tracker.utils.helpers.checkpoint import read_checkpoint, save_checkpoint
from manga_tracker.utils.notifiers.discord import send_notification

_CHECKPOINT_KEY = "notify_new_chapters"


def _config_path() -> str:
    return path.join(get_repo_path(), "io_config.yaml")


def send_chapter_notifications(
    webhook_url: str,
    config_profile: str,
    pipeline_uuid: str,
) -> None:
    """
    Send Discord notifications for any chapters ingested since the last run.
    Updates the watermark checkpoint after dispatching so each chapter fires once.
    """
    now = datetime.now(timezone.utc)
    watermark = read_checkpoint(_CHECKPOINT_KEY, config_profile, pipeline_uuid)

    if watermark is None:
        print(f"[{pipeline_uuid}] First run — watermark set, no notifications sent.")
        save_checkpoint(_CHECKPOINT_KEY, now, config_profile, pipeline_uuid)
        return

    with Postgres.with_config(ConfigFileLoader(_config_path(), config_profile)) as pg:
        new_chapters = pg.load(f"""
            SELECT
                c.manga_mangadex_id,
                f.title          AS manga_title,
                c.chapter_number,
                c.title          AS chapter_title,
                c.published_at
            FROM staging.stg_chapters c
            JOIN raw.user_follows f ON f.mangadex_id = c.manga_mangadex_id
            WHERE c.ingested_at > '{watermark.isoformat()}'
              AND (c.is_unavailable IS FALSE OR c.is_unavailable IS NULL)
            ORDER BY c.manga_mangadex_id, c.published_at
        """)

    if new_chapters.empty:
        print(f"[{pipeline_uuid}] No new chapters for followed manga.")
    else:
        for manga_id, group in new_chapters.groupby("manga_mangadex_id"):
            manga_title = group["manga_title"].iloc[0]
            lines = []
            for _, row in group.iterrows():
                ch = f"Ch. {row['chapter_number']}"
                if row["chapter_title"] and pd.notna(row["chapter_title"]):
                    ch += f" — {row['chapter_title']}"
                lines.append(ch)

            send_notification(
                webhook_url=webhook_url,
                title=f"New chapter: {manga_title}",
                message="\n".join(lines),
            )
            print(f"[{pipeline_uuid}] Notified: {manga_title} ({len(lines)} chapter(s))")

    save_checkpoint(_CHECKPOINT_KEY, now, config_profile, pipeline_uuid)
