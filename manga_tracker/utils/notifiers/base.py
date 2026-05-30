"""
manga_tracker/utils/notifiers/base.py

Shared watermark wrapper for notification blocks. Handles the checkpoint
read → first-run guard → notify → checkpoint save pattern so individual
notifiers only need to supply the query and dispatch logic.
"""

from datetime import datetime, timezone
from typing import Callable

from manga_tracker.utils.helpers.checkpoint import read_checkpoint, save_checkpoint


def run_with_watermark(
    checkpoint_key: str,
    config_profile: str,
    pipeline_uuid: str,
    notify_fn: Callable[[datetime], None],
) -> None:
    """
    Read the watermark for checkpoint_key, call notify_fn(watermark) if one exists,
    then advance the watermark to now.

    On the first ever run no watermark exists — it is established at now() and
    notify_fn is NOT called, so backfilled history never floods the feed.
    """
    now = datetime.now(timezone.utc)
    watermark = read_checkpoint(checkpoint_key, config_profile, pipeline_uuid)

    if watermark is None:
        print(f"[{pipeline_uuid}] First run — watermark set, no notifications sent.")
        save_checkpoint(checkpoint_key, now, config_profile, pipeline_uuid)
        return

    notify_fn(watermark)
    save_checkpoint(checkpoint_key, now, config_profile, pipeline_uuid)
