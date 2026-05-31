import pandas as pd

from manga_tracker.utils.exporters.postgres.exporter import (
    export_data_to_postgres,
)

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


@data_exporter
def data_exporter(df: pd.DataFrame, **kwargs) -> None:
    export_data_to_postgres(
        df=df,
        exporter_schema_name=kwargs.get("exporter_schema_name"),
        exporter_table_name=kwargs.get("exporter_table_name"),
        exporter_unique_constraints=kwargs.get("exporter_unique_constraints", []),
        execution_type=kwargs.get("execution_type"),
        exporter_config_profile=kwargs.get("exporter_config_profile"),
        pipeline_uuid=kwargs.get("pipeline_uuid"),
    )
