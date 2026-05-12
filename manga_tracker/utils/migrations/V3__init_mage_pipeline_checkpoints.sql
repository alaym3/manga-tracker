-- V3__init_mage_schema.sql

CREATE TABLE IF NOT EXISTS mage.pipeline_checkpoints (
    pipeline_name   TEXT PRIMARY KEY,
    last_pulled_at  TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE mage.pipeline_checkpoints IS 'Watermark table for incremental pipeline loads. One row per pipeline. Stores MAX(pulled_at) from the last successful export to use as createdAtSince on the next run.';
COMMENT ON COLUMN mage.pipeline_checkpoints.pipeline_name IS 'Unique pipeline identifier matching the Mage pipeline name. e.g. load_manga, load_chapters.';
COMMENT ON COLUMN mage.pipeline_checkpoints.last_pulled_at IS 'MAX(pulled_at) from the raw table after the last successful export. Used as createdAtSince for the next incremental load.';
COMMENT ON COLUMN mage.pipeline_checkpoints.updated_at IS 'Timestamp when this checkpoint was last updated.';