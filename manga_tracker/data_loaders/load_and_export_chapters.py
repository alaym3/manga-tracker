"""
Block: load_and_export_raw_chapters
Type: data_loader

Streams chapters from MangaDex in date chunks and exports each chunk to Postgres
immediately, keeping memory usage flat regardless of total record count. Saves a
progress checkpoint to mage.pipeline_checkpoints after every chunk so the pipeline
can resume from where it left off if interrupted — run it again and it picks up
where it stopped.

Pipeline variables (metadata.yaml):
    exporter_config_profile:    io_config.yaml profile for Postgres
    chapters_since_date:        optional ISO date override — skips checkpoint lookup
    max_records:                optional int to cap records (dev/testing)
"""

import pandas as pd
from datetime import datetime, timezone
from os import path
from typing import List

from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path

from manga_tracker.utils.helpers.checkpoint import read_checkpoint, save_checkpoint
from manga_tracker.utils.loaders.mangadex.chapters import (
    stream_raw_chapters_by_chunk,
    _extract_manga_id,
)

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test

_PIPELINE_NAME = "load_mangadex_chapters"


def _get_config_path() -> str:
    return path.join(get_repo_path(), "io_config.yaml")


def _parse_since_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _export_chunk(rows: List[dict], config_profile: str, pipeline_uuid: str) -> None:
    """Upsert a batch of chapter row dicts into raw.chapter_responses."""
    df = pd.DataFrame(rows)
    df["pulled_at"] = pd.to_datetime(df["pulled_at"], utc=True)
    df = df.drop_duplicates(subset=["mangadex_id"], keep="last")
    with Postgres.with_config(
        ConfigFileLoader(_get_config_path(), config_profile)
    ) as pg:
        pg.export(
            df,
            "raw",
            "chapter_responses",
            index=False,
            if_exists="append",
            unique_conflict_method="UPDATE",
            unique_constraints=["mangadex_id"],
        )
    print(f"[{pipeline_uuid}] Exported {len(df)} rows to raw.chapter_responses.")


@data_loader
def load_and_export(**kwargs) -> pd.DataFrame:
    pipeline_uuid = kwargs.get("pipeline_uuid")
    config_profile = kwargs.get("exporter_config_profile")

    # Priority: explicit pipeline var > checkpoint in DB > epoch (first ever run)
    since_raw = kwargs.get("chapters_since_date")
    if since_raw:
        since = _parse_since_date(since_raw)
        print(f"[{pipeline_uuid}] Using explicit since date: {since.date()}.")
    else:
        since = read_checkpoint(_PIPELINE_NAME, config_profile, pipeline_uuid)
        if since:
            print(f"[{pipeline_uuid}] Resuming from checkpoint: {since.date()}.")
        else:
            print(f"[{pipeline_uuid}] No checkpoint found — starting from epoch.")

    pulled_at = datetime.now(timezone.utc)
    total_exported = 0

    for chunk_end, chunk_records in stream_raw_chapters_by_chunk(
        pipeline_uuid=pipeline_uuid,
        since=since,
        max_records=kwargs.get("max_records"),
    ):
        if chunk_records:
            rows = [
                {
                    "mangadex_id": record.get("id"),
                    "manga_id": _extract_manga_id(record),
                    "pulled_at": pulled_at,
                    "payload": record,
                }
                for record in chunk_records
            ]
            _export_chunk(rows, config_profile, pipeline_uuid)
            total_exported += len(rows)

        # Checkpoint advances only after the chunk is fully exported so a crash
        # mid-export re-fetches the partial chunk rather than skipping it.
        save_checkpoint(_PIPELINE_NAME, chunk_end, config_profile, pipeline_uuid)

    print(f"[{pipeline_uuid}] Done. Total chapters exported: {total_exported}.")
    return pd.DataFrame([{"total_exported": total_exported, "pulled_at": pulled_at}])


@test
def test_output(output, *args) -> None:
    assert isinstance(output, pd.DataFrame), "Output must be a DataFrame"
    assert len(output) > 0, "Output must contain at least one row"
    assert output["total_exported"].iloc[0] >= 0, "total_exported must be non-negative"
