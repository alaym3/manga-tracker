"""
manga_tracker/utils/exporters/postgres/exporter.py

Shared utility for exporting a DataFrame to a postgres table.

Connection config is loaded from io_config.yaml via the exporter_config_profile
variable set in each pipeline's metadata.yaml.

"""

from os import path
from typing import List

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maps execution_type to Mage's if_exists policy.
# incremental and manual_run both append — duplicates are handled by
# unique_conflict_method="UPDATE" on the unique constraints, so running
# the same date range multiple times will upsert, never duplicate.
# backfill replaces the entire table to ensure a clean reload from scratch.
_EXECUTION_TYPE_TO_POLICY = {
    "incremental": "append",
    "manual_run": "append",
    "backfill": "replace",
}


# ---------------------------------------------------------------------------
# Main exporter
# ---------------------------------------------------------------------------


def export_data_to_postgres(
    df: pd.DataFrame,
    exporter_schema_name: str,
    exporter_table_name: str,
    exporter_unique_constraints: List[str],
    execution_type: str,
    exporter_config_profile: str,
    pipeline_uuid: str,
) -> None:
    """
    Export a DataFrame to a postgres table.

    Determines the export policy (append vs replace) based on execution_type,
    then loads the data using Mage's Postgres exporter. Unique constraint
    conflicts are resolved with UPDATE — running the same data multiple times
    is safe and will never create duplicates.

    Args:
        df (pd.DataFrame): The DataFrame to export.
        exporter_schema_name (str): Target postgres schema. Set in metadata.yaml.
        exporter_table_name (str): Target postgres table. Set in metadata.yaml.
        exporter_unique_constraints (List[str]): Columns that form the unique
            constraint on the target table. Set in metadata.yaml.
        execution_type (str): One of 'incremental', 'backfill', or 'manual_run'.
            Determines whether data is appended or the table is replaced.
        exporter_config_profile (str): Config profile from io_config.yaml that
            specifies the target database connection. Set in metadata.yaml.
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.

    Returns:
        None.

    Raises:
        ValueError: If execution_type is not a recognized value.
    """
    print(
        f"[{pipeline_uuid}] Starting postgres export — "
        f"{len(df)} rows to {exporter_schema_name}.{exporter_table_name} "
        f"(execution_type='{execution_type}')."
    )

    ## We should NEVER hit this code because we skip exports if the previous block returned 0 rows. ##
    # Guard against empty input — skip the export and alert so we know it happened.
    # For backfills this is especially critical (replace would wipe the table)

    if df.empty and execution_type == "backfill":
        print(f"[{pipeline_uuid}] Export backfill failed — input DataFrame is empty.")
        raise ValueError(
            f"Input DataFrame is empty. Backfill blocked to "
            f"{exporter_schema_name}.{exporter_table_name}."
        )

        # return empty dataframe so Mage has something to return
        return pd.DataFrame()

    # Resolve export policy from execution_type
    if_exists_policy = _EXECUTION_TYPE_TO_POLICY.get(execution_type)
    print(
        f"[{pipeline_uuid}] - exists policy = {if_exists_policy}, execution type = {execution_type}"
    )
    if if_exists_policy is None:
        print(
            f"[{pipeline_uuid}] Export failed — unrecognized execution_type "
            f"'{execution_type}'."
        )
        raise ValueError(
            f"Unrecognized execution_type '{execution_type}'. "
            f"Must be one of: {list(_EXECUTION_TYPE_TO_POLICY.keys())}."
        )

    config_path = path.join(get_repo_path(), "io_config.yaml")

    try:
        with Postgres.with_config(
            ConfigFileLoader(config_path, exporter_config_profile)
        ) as loader:
            loader.export(
                df,
                exporter_schema_name,
                exporter_table_name,
                index=False,
                # append: upsert on unique constraints — safe to run multiple times
                # replace: full table reload for backfills
                if_exists=if_exists_policy,
                # On unique constraint conflict, update the existing row rather
                # than raising an error or skipping — ensures re-runs are idempotent
                unique_conflict_method="UPDATE",
                unique_constraints=exporter_unique_constraints,
            )
    except Exception as e:
        print(
            f"[{pipeline_uuid}] Export failed for "
            f"{exporter_schema_name}.{exporter_table_name}: {e}"
        )
        raise

    print(
        f"[{pipeline_uuid}] Successfully exported {len(df)} rows to "
        f"{exporter_schema_name}.{exporter_table_name} "
        f"(policy='{if_exists_policy}'), "
        f"(unique_conflict_method=UPDATE)"
    )