{{
    config(
        unique_key=['mangadex_id'],
        materialized='table'
    )
}}

SELECT
    m.mangadex_id,
    m.source,
    m.title,
    m.title_japanese,
    m.description,
    m.original_language,
    m.status,
    m.year,
    m.content_rating,
    m.tags,
    m.authors,
    m.artists,
    m.cover_url,
    m.created_at_source,
    m.updated_at_source,
    m.ingested_at,

    -- community statistics (null when statistics haven't been loaded yet)
    s.rating_average,
    s.rating_bayesian,
    s.rating_distribution,
    s.follows,
    s.comments_count,
    s.pulled_at                                                         AS statistics_pulled_at,

    -- personal data
    f.rating                                                            AS user_rating,
    f.rated_at                                                          AS user_rated_at,
    f.followed_at                                                       AS user_followed_at,
    CASE WHEN f.mangadex_id IS NOT NULL THEN TRUE ELSE FALSE END        AS is_followed

FROM {{ ref('stg_manga') }} m
LEFT JOIN {{ ref('stg_manga_statistics') }} s USING (mangadex_id)
LEFT JOIN {{ source('raw', 'user_follows') }} f USING (mangadex_id)
