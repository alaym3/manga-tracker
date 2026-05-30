"""
Block: lookup_follows
Type: data_loader

Fetches all manga the authenticated MangaDex user follows and returns a
DataFrame ready to upsert into raw.user_follows.

Requires MANGADEX_CLIENT_ID, MANGADEX_CLIENT_SECRET, MANGADEX_USERNAME, and
MANGADEX_PASSWORD to be set in .env — see utils/loaders/mangadex/follows.py.
"""

import pandas as pd

from manga_tracker.utils.loaders.mangadex.follows import load_follows

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def lookup_follows(**kwargs) -> pd.DataFrame:
    return load_follows(pipeline_uuid=kwargs.get("pipeline_uuid", "load_mangadex_follows"))


@test
def test_output(output, *args) -> None:
    assert isinstance(output, pd.DataFrame)
    assert {"mangadex_id", "title", "rating", "rated_at"}.issubset(output.columns)
