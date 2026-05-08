from datetime import datetime, timezone
from typing import Any, Dict, List
from manga_tracker.utils.loaders.mangadex.manga import (
    DEFAULT_INCLUDES,
    DEFAULT_LIMIT,
    stream_raw_manga,
)
import pandas as pd

if 'data_loader' not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if 'test' not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_data_from_api(*args, **kwargs) -> pd.DataFrame:
    """Load raw MangaDex manga responses for the Mage pipeline."""
    limit = int(kwargs.get("limit", DEFAULT_LIMIT))
    includes = kwargs.get("includes", DEFAULT_INCLUDES)
    pulled_at = datetime.now(timezone.utc)

    rows: List[Dict[str, Any]] = [
        {
            "mangadex_id": raw_item.get("id"),
            "pulled_at": pulled_at,
            "payload": raw_item,
        }
        for raw_item in stream_raw_manga(limit=limit, includes=includes, max_records=1000)
    ]

    df = pd.DataFrame(rows)
    if not df.empty:
        df["pulled_at"] = pd.to_datetime(df["pulled_at"])
    return df


@test
def test_output(output, *args) -> None:
    assert output is not None, "The output is undefined"
    assert isinstance(output, pd.DataFrame), "Output must be a DataFrame"
    assert "mangadex_id" in output.columns, "DataFrame must contain mangadex_id"
    assert "payload" in output.columns, "DataFrame must contain payload"
