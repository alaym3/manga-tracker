"""
Block: lookup_statistics
Type: data_loader

Fetches community statistics (ratings, follows) for all manga in raw.manga_responses
from the MangaDex public API and returns a DataFrame ready to upsert into
raw.manga_statistics.

No authentication required — statistics endpoint is public.
"""

import pandas as pd

from manga_tracker.utils.loaders.mangadex.statistics import load_statistics

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def lookup_statistics(**kwargs) -> pd.DataFrame:
    return load_statistics(
        pipeline_uuid=kwargs.get("pipeline_uuid", "load_mangadex_statistics"),
        config_profile=kwargs.get("exporter_config_profile", "manga_tracker_postgres"),
    )


@test
def test_output(output, *args) -> None:
    assert isinstance(output, pd.DataFrame)
    assert {"mangadex_id", "payload", "pulled_at"}.issubset(output.columns)
