"""
manga_tracker/utils/helpers/postgres/loader.py

Shared utility for loading data from the Postgres database.

Connection config is loaded from io_config.yaml via the loader_config_profile
variable set in each pipeline's metadata.yaml.

Public functions:

    load_from_postgres()                    — executes a SQL file
    load_from_postgres_with_custom_params() — executes a SQL file with
                                              {param_name} placeholders
                                              substituted from query_params
"""

from os import path

import pandas as pd
from mage_ai.io.config import ConfigFileLoader
from mage_ai.io.postgres import Postgres
from mage_ai.settings.repo import get_repo_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _execute_query(
    query: str,
    config_profile: str,
    pipeline_uuid: str,
) -> pd.DataFrame:
    """
    Execute a SQL query against Postgres using Mage's Postgres loader.

    This is the single place where the Mage connection is opened — all
    public loader functions delegate here.

    Args:
        query (str): The SQL query to execute.
        config_profile (str): The io_config.yaml profile name for the
            database connection. Set in metadata.yaml via loader_config_profile.
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.

    Returns:
        pd.DataFrame: Query results as a DataFrame.

    Raises:
        Exception: Any exception raised by Mage's Postgres loader is logged
            and re-raised.
    """
    config_path = path.join(get_repo_path(), "io_config.yaml")

    try:
        with Postgres.with_config(
            ConfigFileLoader(config_path, config_profile)
        ) as loader:
            df = loader.load(query)
    except Exception as e:
        print(
            f"[{pipeline_uuid}] Query failed "
            f"(profile='{config_profile}'): {e}"
        )
        raise

    print(
        f"[{pipeline_uuid}] Successfully loaded {len(df)} rows from Postgres "
        f"(profile='{config_profile}')."
    )

    return df


def _read_sql_file(sql_path: str, pipeline_uuid: str) -> str:
    """
    Read a SQL file from disk.

    Args:
        sql_path (str): Path to the SQL file.
        pipeline_uuid (str): Used for log prefixing on failure.

    Returns:
        str: The SQL query string.

    Raises:
        FileNotFoundError: If the SQL file does not exist at the given path.
    """
    try:
        with open(sql_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        print(f"[{pipeline_uuid}] SQL file not found at path: '{sql_path}'.")
        raise


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def load_from_postgres(
    sql_path: str,
    pipeline_uuid: str,
    config_profile: str,
) -> pd.DataFrame:
    """
    Load data from Postgres by executing a SQL file.

    Args:
        sql_path (str): Path to the SQL file to execute. Set in metadata.yaml
            via loader_sql_path.
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        config_profile (str): io_config.yaml profile name for the database
            connection. Set in metadata.yaml via loader_config_profile.

    Returns:
        pd.DataFrame: Query results as a DataFrame.

    Raises:
        FileNotFoundError: If the SQL file is not found.
        Exception: If the query fails.
    """
    print(f"[{pipeline_uuid}] Starting Postgres load.")

    query = _read_sql_file(sql_path, pipeline_uuid)

    return _execute_query(
        query=query,
        config_profile=config_profile,
        pipeline_uuid=pipeline_uuid,
    )


def load_from_postgres_with_custom_params(
    sql_path: str,
    pipeline_uuid: str,
    config_profile: str,
    query_params: dict,
) -> pd.DataFrame:
    """
    Load data from Postgres by executing a SQL file with custom parameters
    substituted into the query.

    The SQL file can contain {param_name} placeholders matching keys in
    query_params. e.g. {pipeline_name} in get_checkpoint.sql.

    Args:
        sql_path (str): Path to the SQL file. Set in metadata.yaml via
            loader_sql_path.
        pipeline_uuid (str): UUID of the Mage pipeline — used for log prefixing.
        config_profile (str): io_config.yaml profile name for the database
            connection. Set in metadata.yaml via loader_config_profile.
        query_params (dict): Key-value pairs substituted into SQL placeholders.
            Keys must match {placeholder} names in the SQL file.

    Returns:
        pd.DataFrame: Query results as a DataFrame.

    Raises:
        FileNotFoundError: If the SQL file is not found.
        Exception: If the query fails.
    """
    print(
        f"[{pipeline_uuid}] Starting Postgres load with custom params "
        f"— {query_params}."
    )

    query = _read_sql_file(sql_path, pipeline_uuid)
    query = query.format(**query_params)

    return _execute_query(
        query=query,
        config_profile=config_profile,
        pipeline_uuid=pipeline_uuid,
    )