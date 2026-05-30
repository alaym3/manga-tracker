-- V6__create_user_follows.sql
-- Tracks which manga the user wants chapter notifications for.

CREATE TABLE IF NOT EXISTS raw.user_follows (
    mangadex_id  TEXT        NOT NULL,
    title        TEXT        NOT NULL,
    followed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_follows_pkey PRIMARY KEY (mangadex_id)
);

COMMENT ON TABLE raw.user_follows IS 'Manga the user wants new-chapter notifications for. Populated manually.';
COMMENT ON COLUMN raw.user_follows.mangadex_id IS 'MangaDex UUID for the manga, matching staging.stg_manga.mangadex_id.';
COMMENT ON COLUMN raw.user_follows.title IS 'Human-readable title — stored here so notifications do not require a join.';
