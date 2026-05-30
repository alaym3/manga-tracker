"""
Block: load_and_export_statistics
Type: data_loader

Streams community statistics from MangaDex in batches of 100 and exports each
batch to raw.manga_statistics immediately, keeping memory flat regardless of
how many manga are in the database. Returns a summary row for downstream blocks.

Pipeline variables (metadata.yaml):
    exporter_config_profile:    io_config.yaml profile for Postgres
"""

from datetime import datetime, timezone
from os import path

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path

from manga_tracker.utils.loaders.mangadex.statistics import stream_statistics_batches

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test


def _get_config_path() -> str:
    return path.join(get_repo_path(), "io_config.yaml")


def _export_batch(df: pd.DataFrame, config_profile: str, pipeline_uuid: str) -> None:
    with Postgres.with_config(ConfigFileLoader(_get_config_path(), config_profile)) as pg:
        pg.export(
            df,
            "raw",
            "manga_statistics",
            index=False,
            if_exists="append",
            unique_conflict_method="UPDATE",
            unique_constraints=["mangadex_id"],
        )
    print(f"[{pipeline_uuid}] Exported {len(df)} rows to raw.manga_statistics.")


@data_loader
def load_and_export_statistics(**kwargs) -> pd.DataFrame:
    pipeline_uuid = kwargs.get("pipeline_uuid", "load_mangadex_statistics")
    config_profile = kwargs.get("exporter_config_profile", "manga_tracker_postgres")
    pulled_at = datetime.now(timezone.utc)
    total_exported = 0

    for batch_num, total_batches, df in stream_statistics_batches(
        pipeline_uuid=pipeline_uuid,
        config_profile=config_profile,
        pulled_at=pulled_at,
    ):
        if not df.empty:
            _export_batch(df, config_profile, pipeline_uuid)
            total_exported += len(df)
        print(f"[{pipeline_uuid}] Batch {batch_num}/{total_batches} done.")

    print(f"[{pipeline_uuid}] Done. Total statistics exported: {total_exported}.")
    return pd.DataFrame([{"total_exported": total_exported, "pulled_at": pulled_at}])


@test
def test_output(output, *args) -> None:
    assert isinstance(output, pd.DataFrame)
    assert output["total_exported"].iloc[0] >= 0
