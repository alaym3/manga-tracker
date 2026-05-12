from datetime import datetime, timezone
from manga_tracker.utils.loaders.mangadex.manga import load_manga
import pandas as pd

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test


def _parse_since_date(value: str) -> datetime:
    """Parse ISO date string from pipeline variable into UTC datetime."""
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)

# deleted variables manga_since_date and max_records can be used

@data_loader
def load_data_from_api(*args, **kwargs):
    since_raw = kwargs.get("manga_since_date")
    since = _parse_since_date(since_raw) if since_raw else None

    return load_manga(
        pipeline_uuid=kwargs.get("pipeline_uuid"),
        since=since,
        # max_records=kwargs.get("max_records"),
    )


@test
def test_output(output, *args) -> None:
    assert isinstance(output, pd.DataFrame), (
        f"Expected a DataFrame but got {type(output)}"
    )
    assert len(output) > 0, "No manga returned — expected at least one record"
    assert "mangadex_id" in output.columns, "DataFrame must contain mangadex_id"
    assert "payload" in output.columns, "DataFrame must contain payload"
    assert "pulled_at" in output.columns, "DataFrame must contain pulled_at"