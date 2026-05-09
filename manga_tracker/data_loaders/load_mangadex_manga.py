from manga_tracker.utils.loaders.mangadex.manga import load_manga
import pandas as pd

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test

# setting max_records temporarily to a low number for testing — can be removed or set to None for no limit in production
max_records = 1000

@data_loader
def load_data_from_api(*args, **kwargs):
    return load_manga(
        pipeline_uuid=kwargs.get("pipeline_uuid"),
        max_records=max_records,
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