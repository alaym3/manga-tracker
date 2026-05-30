"""
manga_tracker/utils/helpers/checkpoint.py

Shared helpers for reading and writing pipeline watermarks in
mage.pipeline_checkpoints. Used by any Mage block that needs to track
the last-processed timestamp across runs.
"""

from datetime import datetime, timezone
from os import path
from typing import Optional

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path


def _config_path() -> str:
    return path.join(get_repo_path(), "io_config.yaml")


def read_checkpoint(
    pipeline_name: str,
    config_profile: str,
    pipeline_uuid: str,
) -> Optional[datetime]:
    """
    Return the last checkpoint timestamp for pipeline_name, or None if no
    row exists yet. Errors are caught and logged so callers can fall back to
    their epoch default rather than crashing.
    """
    try:
        with Postgres.with_config(
            ConfigFileLoader(_config_path(), config_profile)
        ) as pg:
            df = pg.load(
                f"SELECT last_pulled_at FROM mage.pipeline_checkpoints "
                f"WHERE pipeline_name = '{pipeline_name}'"
            )
        if df.empty or df["last_pulled_at"].iloc[0] is None:
            return None
        val = df["last_pulled_at"].iloc[0]
        if hasattr(val, "to_pydatetime"):
            val = val.to_pydatetime()
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val
    except Exception as e:
        print(f"[{pipeline_uuid}] Could not read checkpoint: {e}. Starting from epoch.")
        return None


def save_checkpoint(
    pipeline_name: str,
    ts: datetime,
    config_profile: str,
    pipeline_uuid: str,
) -> None:
    """Upsert ts as the current checkpoint for pipeline_name."""
    df = pd.DataFrame([{
        "pipeline_name": pipeline_name,
        "last_pulled_at": ts,
        "updated_at": datetime.now(timezone.utc),
    }])
    df["last_pulled_at"] = pd.to_datetime(df["last_pulled_at"], utc=True)
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True)
    with Postgres.with_config(
        ConfigFileLoader(_config_path(), config_profile)
    ) as pg:
        pg.export(
            df,
            "mage",
            "pipeline_checkpoints",
            index=False,
            if_exists="append",
            unique_conflict_method="UPDATE",
            unique_constraints=["pipeline_name"],
        )
    print(f"[{pipeline_uuid}] Checkpoint saved: {pipeline_name} → {ts.date()}")
