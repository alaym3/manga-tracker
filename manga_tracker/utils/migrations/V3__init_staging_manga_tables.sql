-- V3__init_staging_schema.sql
-- Cleaned, normalized tables transformed from raw schema
-- Source: MangaDex API via raw.manga_responses and raw.chapter_responses

CREATE TABLE IF NOT EXISTS staging.manga (
    id                  SERIAL PRIMARY KEY,
    mangadex_id         TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'mangadex',
    title               TEXT NOT NULL,
    title_japanese      TEXT,
    alt_titles          JSONB,
    description         TEXT,
    original_language   TEXT,
    status              TEXT,
    year                INT,
    content_rating      TEXT,
    tags                TEXT[],
    authors             TEXT[],
    -- cover_url           TEXT,
    created_at_source   TIMESTAMPTZ,
    updated_at_source   TIMESTAMPTZ,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source, mangadex_id)
);

COMMENT ON TABLE staging.manga IS 'Cleaned and normalized manga records transformed from raw.manga_responses. One row per manga title.';
COMMENT ON COLUMN staging.manga.id                  IS 'Internal surrogate key.';
COMMENT ON COLUMN staging.manga.mangadex_id         IS 'MangaDex UUID, sourced from data[].id. Used to join back to raw.manga_responses.';
COMMENT ON COLUMN staging.manga.source              IS 'API source for this record. Defaults to mangadex, allows future multi-source ingestion.';
COMMENT ON COLUMN staging.manga.title               IS 'Primary English title, extracted from data[].attributes.title.en.';
COMMENT ON COLUMN staging.manga.title_japanese      IS 'Japanese title, extracted from data[].attributes.title.ja or altTitles[].ja.';
COMMENT ON COLUMN staging.manga.alt_titles          IS 'Full localized title dict from data[].attributes.altTitles, kept as JSONB for all languages.';
COMMENT ON COLUMN staging.manga.description         IS 'English description, extracted from data[].attributes.description.en.';
COMMENT ON COLUMN staging.manga.original_language   IS 'Original publication language from data[].attributes.originalLanguage. e.g. ja, ko, zh.';
COMMENT ON COLUMN staging.manga.status              IS 'Publication status from data[].attributes.status. One of: ongoing, completed, hiatus, cancelled.';
COMMENT ON COLUMN staging.manga.year                IS 'Publication start year from data[].attributes.year.';
COMMENT ON COLUMN staging.manga.content_rating      IS 'Content rating from data[].attributes.contentRating. One of: safe, suggestive, erotica, pornographic.';
COMMENT ON COLUMN staging.manga.tags                IS 'Flattened array of tag names in English, extracted from data[].attributes.tags[].attributes.name.en.';
COMMENT ON COLUMN staging.manga.authors             IS 'Array of author names, extracted from relationships[] where type=author with includes[]=author expansion.';
-- COMMENT ON COLUMN staging.manga.cover_url           IS 'Constructed cover image URL. Pattern: https://uploads.mangadex.org/covers/{mangadex_id}/{fileName} where fileName comes from relationships[] where type=cover_art.';
COMMENT ON COLUMN staging.manga.created_at_source   IS 'Record creation timestamp on MangaDex, from data[].attributes.createdAt.';
COMMENT ON COLUMN staging.manga.updated_at_source   IS 'Last update timestamp on MangaDex, from data[].attributes.updatedAt. Useful for detecting upstream changes.';
COMMENT ON COLUMN staging.manga.ingested_at         IS 'Timestamp when this record was first written to staging.';
COMMENT ON COLUMN staging.manga.updated_at          IS 'Timestamp when this staging record was last updated by a pipeline run.';


CREATE TABLE IF NOT EXISTS staging.chapters (
    id                  SERIAL PRIMARY KEY,
    mangadex_id         TEXT NOT NULL,
    manga_id            INTEGER NOT NULL REFERENCES staging.manga(id) ON DELETE CASCADE,
    manga_mangadex_id   TEXT NOT NULL,
    volume              TEXT,
    chapter_number      TEXT,
    title               TEXT,
    language            TEXT NOT NULL DEFAULT 'en',
    scanlation_group    TEXT,
    pages               INT,
    published_at        TIMESTAMPTZ,
    readable_at         TIMESTAMPTZ,
    external_url        TEXT,
    ingested_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(mangadex_id, language, scanlation_group)
);

COMMENT ON TABLE staging.chapters IS 'Cleaned and normalized chapter records transformed from raw.chapter_responses. One row per unique chapter release.';
COMMENT ON COLUMN staging.chapters.id                IS 'Internal surrogate key.';
COMMENT ON COLUMN staging.chapters.mangadex_id       IS 'MangaDex UUID for the chapter, sourced from data[].id. Used to join back to raw.chapter_responses.';
COMMENT ON COLUMN staging.chapters.manga_id          IS 'FK to staging.manga.id.';
COMMENT ON COLUMN staging.chapters.manga_mangadex_id IS 'MangaDex UUID of the parent manga, denormalized for pipeline convenience without needing a staging.manga join.';
COMMENT ON COLUMN staging.chapters.volume            IS 'Volume number as string from data[].attributes.volume. Kept as TEXT since values like "Omnibus 1" are valid.';
COMMENT ON COLUMN staging.chapters.chapter_number    IS 'Chapter number as string from data[].attributes.chapter. Kept as TEXT since values like "97.5" and "extra" are valid.';
COMMENT ON COLUMN staging.chapters.title             IS 'Chapter title from data[].attributes.title. Frequently null.';
COMMENT ON COLUMN staging.chapters.language          IS 'Translated language from data[].attributes.translatedLanguage. ISO 639-1 code e.g. en, fr, es.';
COMMENT ON COLUMN staging.chapters.scanlation_group  IS 'Scanlation group name from relationships[] where type=scanlation_group. Null for official releases.';
COMMENT ON COLUMN staging.chapters.pages             IS 'Page count from data[].attributes.pages.';
COMMENT ON COLUMN staging.chapters.published_at      IS 'Scheduled publish timestamp from data[].attributes.publishAt. Used for new chapter notifications.';
COMMENT ON COLUMN staging.chapters.readable_at       IS 'Timestamp when chapter becomes readable from data[].attributes.readableAt. May differ from published_at for delayed releases.';
COMMENT ON COLUMN staging.chapters.external_url      IS 'External hosting URL from data[].attributes.externalUrl. Non-null for officially hosted chapters e.g. Viz, Manga Plus.';
COMMENT ON COLUMN staging.chapters.ingested_at       IS 'Timestamp when this record was first written to staging.';


-- indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_staging_manga_mangadex_id       ON staging.manga(mangadex_id);
CREATE INDEX IF NOT EXISTS idx_staging_manga_status            ON staging.manga(status);
CREATE INDEX IF NOT EXISTS idx_staging_manga_content_rating    ON staging.manga(content_rating);
CREATE INDEX IF NOT EXISTS idx_staging_chapters_manga_id       ON staging.chapters(manga_id);
CREATE INDEX IF NOT EXISTS idx_staging_chapters_published_at   ON staging.chapters(published_at);
CREATE INDEX IF NOT EXISTS idx_staging_chapters_language       ON staging.chapters(language);