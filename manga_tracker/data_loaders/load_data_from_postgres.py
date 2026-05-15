import pandas as pd
from manga_tracker.utils.helpers.postgres.loader import (
    load_from_postgres,
)

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader
if "test" not in globals():
    from mage_ai.data_preparation.decorators import test


@data_loader
def load_data_from_postgres(*args, **kwargs) -> pd.DataFrame:
    return load_from_postgres(
        sql_path=kwargs["loader_sql_postgres_analytics"],
        pipeline_uuid=kwargs["pipeline_uuid"],
    )


@test
def test_output(output, *args) -> None:
    """
    Template code for testing the output of the block.
    """
    assert output is not None, "The output is undefined"