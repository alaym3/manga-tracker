"""
Block: get_checkpoint
Type: data_loader
Position: first block in pipeline, before the loader block.

Required pipeline variables (metadata.yaml):
    loader_sql_path:            path to get_checkpoint.sql
    loader_config_profile:      io_config.yaml profile for Postgres
    checkpoint_pipeline_name:   e.g. 'load_manga'
"""

import pandas as pd
from manga_tracker.utils.helpers.postgres.loader import (
    load_from_postgres_with_custom_params,
)

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_checkpoint(*args, **kwargs) -> dict:
    pipeline_uuid = kwargs["pipeline_uuid"]
    pipeline_name = kwargs["checkpoint_pipeline_name"]

    df = load_from_postgres_with_custom_params(
        sql_path=kwargs["loader_sql_path"],
        pipeline_uuid=pipeline_uuid,
        config_profile=kwargs["loader_config_profile"],
        query_params={"pipeline_name": pipeline_name},
    )

    since = df["last_pulled_at"].iloc[0] if not df.empty else None

    if since:
        print(
            f"[{pipeline_uuid}] Checkpoint found for '{pipeline_name}': "
            f"loading since {since.isoformat()}."
        )
    else:
        print(
            f"[{pipeline_uuid}] No checkpoint found for '{pipeline_name}' "
            f"— first run, loading from epoch."
        )

    return {"since": since.isoformat() if since else None}


@test
def test_output(output, *args) -> None:
    assert isinstance(output, dict), "Output must be a dict"
    assert "since" in output, "Output must contain 'since' key"