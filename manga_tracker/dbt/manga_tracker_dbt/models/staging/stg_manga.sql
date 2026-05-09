{{
    config(
        unique_key=['source', 'mangadex_id'],
        incremental_strategy='merge',
        on_schema_change='fail'
    )
}}

SELECT
    -- identity
    m.payload ->> 'id'                                                  AS mangadex_id,
    'mangadex'                                                          AS source,

    -- titles
    COALESCE(
        m.payload -> 'attributes' -> 'title' ->> 'en',
        m.payload -> 'attributes' -> 'title' ->> 'ja-ro'
    )                                                                   AS title,
    m.payload -> 'attributes' -> 'title' ->> 'ja-ro'                   AS title_japanese,
    m.payload -> 'attributes' -> 'altTitles'                            AS alt_titles,

    -- description
    COALESCE(
        m.payload -> 'attributes' -> 'description' ->> 'en',
        m.payload -> 'attributes' -> 'description' ->> 'ja'
    )                                                                   AS description,

    -- attributes
    m.payload -> 'attributes' ->> 'originalLanguage'                    AS original_language,
    m.payload -> 'attributes' ->> 'status'                              AS status,
    NULLIF(m.payload -> 'attributes' ->> 'year', '')::INT               AS year,
    m.payload -> 'attributes' ->> 'contentRating'                       AS content_rating,

    -- tags (flattened to array)
    COALESCE(
        ARRAY(
            SELECT DISTINCT t -> 'attributes' -> 'name' ->> 'en'
            FROM jsonb_array_elements(
                COALESCE(m.payload -> 'attributes' -> 'tags', '[]'::jsonb)
            ) t
            WHERE t -> 'attributes' -> 'name' ? 'en'
        ),
        ARRAY[]::TEXT[]
    )                                                                   AS tags,

    -- authors (array)
    COALESCE(
        ARRAY(
            SELECT r -> 'attributes' ->> 'name'
            FROM jsonb_array_elements(
                COALESCE(m.payload -> 'relationships', '[]'::jsonb)
            ) r
            WHERE r ->> 'type' = 'author'
              AND r -> 'attributes' ? 'name'
        ),
        ARRAY[]::TEXT[]
    )                                                                   AS authors,

    -- artists (array)
    COALESCE(
        ARRAY(
            SELECT r -> 'attributes' ->> 'name'
            FROM jsonb_array_elements(
                COALESCE(m.payload -> 'relationships', '[]'::jsonb)
            ) r
            WHERE r ->> 'type' = 'artist'
              AND r -> 'attributes' ? 'name'
        ),
        ARRAY[]::TEXT[]
    )                                                                   AS artists,

    -- cover url
    'https://uploads.mangadex.org/covers/'
    || (m.payload ->> 'id')
    || '/'
    || (
        jsonb_path_query_first(
            m.payload,
            '$.relationships[*] ? (@.type == "cover_art")'
        )::jsonb -> 'attributes' ->> 'fileName'
    )                                                                   AS cover_url,

    -- source timestamps
    (m.payload -> 'attributes' ->> 'createdAt')::timestamptz           AS created_at_source,
    (m.payload -> 'attributes' ->> 'updatedAt')::timestamptz           AS updated_at_source,

    -- pipeline timestamp
    NOW()                                                               AS ingested_at

FROM {{ source('raw', 'manga_responses') }} m

{% if is_incremental() %}
WHERE m.pulled_at > (SELECT MAX(ingested_at) FROM {{ this }})
{% endif %}