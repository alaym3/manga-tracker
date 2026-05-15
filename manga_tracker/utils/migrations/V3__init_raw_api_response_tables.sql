-- V2__init_raw_schema.sql
-- Raw landing tables for MangaDex API responses
-- One row per item from data[] array, append-only, never modified after insert

CREATE TABLE IF NOT EXISTS raw.manga_responses (
    id              SERIAL PRIMARY KEY,
    mangadex_id     TEXT NOT NULL UNIQUE,
    pulled_at       TIMESTAMPTZ DEFAULT NOW(),
    payload         JSONB NOT NULL
);

COMMENT ON TABLE raw.manga_responses IS 'Raw manga payloads from MangaDex API.';
COMMENT ON COLUMN raw.manga_responses.id          IS 'Internal surrogate key.';
COMMENT ON COLUMN raw.manga_responses.mangadex_id IS 'MangaDex UUID for the manga, sourced from data[].id in the API response.';
COMMENT ON COLUMN raw.manga_responses.pulled_at   IS 'Timestamp when this record was fetched from the API.';
COMMENT ON COLUMN raw.manga_responses.payload     IS 'Full data[] item from the API response, stored untouched as JSONB.';


CREATE TABLE IF NOT EXISTS raw.chapter_responses (
    id              SERIAL PRIMARY KEY,
    mangadex_id     TEXT NOT NULL UNIQUE,
    manga_id        TEXT NOT NULL,
    pulled_at       TIMESTAMPTZ DEFAULT NOW(),
    payload         JSONB NOT NULL
);

COMMENT ON TABLE raw.chapter_responses IS 'Raw chapter payloads from MangaDex API.';
COMMENT ON COLUMN raw.chapter_responses.id          IS 'Internal surrogate key.';
COMMENT ON COLUMN raw.chapter_responses.mangadex_id IS 'MangaDex UUID for the chapter, sourced from data[].id in the API response.';
COMMENT ON COLUMN raw.chapter_responses.manga_id    IS 'MangaDex UUID of the parent manga, denormalized from relationships[] for efficient filtering without JSONB traversal.';
COMMENT ON COLUMN raw.chapter_responses.pulled_at   IS 'Timestamp when this record was fetched from the API.';
COMMENT ON COLUMN raw.chapter_responses.payload     IS 'Full data[] item from the API response, stored untouched as JSONB.';


-- indexes to make the transform step fast when reading from raw
CREATE INDEX IF NOT EXISTS idx_raw_manga_mangadex_id     ON raw.manga_responses(mangadex_id);
CREATE INDEX IF NOT EXISTS idx_raw_manga_pulled_at       ON raw.manga_responses(pulled_at);
CREATE INDEX IF NOT EXISTS idx_raw_chapters_mangadex_id  ON raw.chapter_responses(mangadex_id);
CREATE INDEX IF NOT EXISTS idx_raw_chapters_manga_id     ON raw.chapter_responses(manga_id);
CREATE INDEX IF NOT EXISTS idx_raw_chapters_pulled_at    ON raw.chapter_responses(pulled_at);