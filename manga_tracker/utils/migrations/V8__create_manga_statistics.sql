-- V8__create_manga_statistics.sql
-- Raw landing table for MangaDex community statistics per manga.
-- Populated by the load_mangadex_statistics pipeline via GET /statistics/manga.
-- One row per manga; upserted on each run so values stay current.

CREATE TABLE IF NOT EXISTS raw.manga_statistics (
    mangadex_id  TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    pulled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT manga_statistics_pkey PRIMARY KEY (mangadex_id)
);

COMMENT ON TABLE raw.manga_statistics IS 'Community statistics for manga from MangaDex GET /statistics/manga. One row per manga, upserted on each pipeline run.';
COMMENT ON COLUMN raw.manga_statistics.mangadex_id IS 'MangaDex UUID for the manga, matching raw.manga_responses.mangadex_id.';
COMMENT ON COLUMN raw.manga_statistics.payload     IS 'Raw statistics object from the API: rating (average, bayesian, distribution), follows, comments.';
COMMENT ON COLUMN raw.manga_statistics.pulled_at   IS 'Timestamp when this record was last fetched from the API.';

CREATE INDEX IF NOT EXISTS idx_raw_manga_statistics_pulled_at ON raw.manga_statistics(pulled_at);
