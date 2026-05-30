"""
Block: notify_new_chapters
Type: custom

Runs after the stg_chapters dbt model. Sends Discord notifications for any
newly ingested chapters belonging to manga in raw.user_follows.

Requires DISCORD_WEBHOOK_URL in .env — see utils/notifiers/chapter_notifier.py.
"""

import os

from manga_tracker.utils.notifiers.chapter_notifier import send_chapter_notifications

if "custom" not in globals():
    from mage_ai.data_preparation.decorators import custom


@custom
def notify_new_chapters(*args, **kwargs):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("[notify_new_chapters] DISCORD_WEBHOOK_URL not set — skipping.")
        return
    send_chapter_notifications(
        webhook_url=webhook_url,
        config_profile=kwargs.get("exporter_config_profile", "manga_tracker_postgres"),
        pipeline_uuid=kwargs.get("pipeline_uuid", "notify_new_chapters"),
    )
