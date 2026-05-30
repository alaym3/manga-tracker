-- V7__add_rating_to_user_follows.sql
-- Adds personal rating columns to raw.user_follows.
-- Populated by the load_mangadex_follows pipeline via GET /rating.

ALTER TABLE raw.user_follows
    ADD COLUMN IF NOT EXISTS rating    INTEGER     CHECK (rating BETWEEN 1 AND 10),
    ADD COLUMN IF NOT EXISTS rated_at  TIMESTAMPTZ;

COMMENT ON COLUMN raw.user_follows.rating   IS 'User''s personal rating for this manga (1–10), from GET /rating. NULL if unrated.';
COMMENT ON COLUMN raw.user_follows.rated_at IS 'Timestamp when the rating was first created on MangaDex, from createdAt in GET /rating response.';
