"""
Block: notify_new_manga
Type: custom

Runs after the stg_manga dbt model. Sends Discord notifications for newly
ingested manga whose tags match the notification_tags pipeline variable.

Requires DISCORD_MANGA_WEBHOOK_URL in .env — see utils/notifiers/manga_notifier.py.
"""

import os

from manga_tracker.utils.notifiers.manga_notifier import send_manga_notifications

if "custom" not in globals():
    from mage_ai.data_preparation.decorators import custom


@custom
def notify_new_manga(*args, **kwargs):
    webhook_url = os.environ.get("DISCORD_MANGA_WEBHOOK_URL")
    if not webhook_url:
        print("[notify_new_manga] DISCORD_MANGA_WEBHOOK_URL not set — skipping.")
        return
    notification_tags = kwargs.get("notification_tags", [])
    if not notification_tags:
        print("[notify_new_manga] No notification_tags configured — skipping.")
        return
    send_manga_notifications(
        webhook_url=webhook_url,
        notification_tags=notification_tags,
        config_profile=kwargs.get("exporter_config_profile", "manga_tracker_postgres"),
        pipeline_uuid=kwargs.get("pipeline_uuid", "notify_new_manga"),
    )
