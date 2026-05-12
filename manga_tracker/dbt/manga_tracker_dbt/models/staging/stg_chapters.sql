{{
    config(
        unique_key=['mangadex_id'],
        incremental_strategy='merge',
        on_schema_change='fail'
    )
}}

SELECT
    -- identity
    c.payload ->> 'id'                                                  AS mangadex_id,

    -- manga foreign key
    (
        SELECT r ->> 'id'
        FROM jsonb_array_elements(
            COALESCE(c.payload -> 'relationships', '[]'::jsonb)
        ) r
        WHERE r ->> 'type' = 'manga'
        LIMIT 1
    )                                                                   AS manga_mangadex_id,

    -- attributes
    c.payload -> 'attributes' ->> 'volume'                              AS volume,
    NULLIF(c.payload -> 'attributes' ->> 'chapter', '')                 AS chapter_number,
    NULLIF(c.payload -> 'attributes' ->> 'title', '')                   AS title,
    c.payload -> 'attributes' ->> 'translatedLanguage'                  AS language,
    (c.payload -> 'attributes' ->> 'isUnavailable')::boolean            AS is_unavailable,
    (c.payload -> 'attributes' ->> 'pages')::int                        AS pages,

    -- scanlation group
    (
        SELECT r -> 'attributes' ->> 'name'
        FROM jsonb_array_elements(
            COALESCE(c.payload -> 'relationships', '[]'::jsonb)
        ) r
        WHERE r ->> 'type' = 'scanlation_group'
          AND r -> 'attributes' ? 'name'
        LIMIT 1
    )                                                                   AS scanlation_group,

    -- timestamps
    (c.payload -> 'attributes' ->> 'publishAt')::timestamptz           AS published_at,
    (c.payload -> 'attributes' ->> 'readableAt')::timestamptz          AS readable_at,
    (c.payload -> 'attributes' ->> 'createdAt')::timestamptz           AS created_at_source,
    (c.payload -> 'attributes' ->> 'updatedAt')::timestamptz           AS updated_at_source,
    NULLIF(c.payload -> 'attributes' ->> 'externalUrl', '')             AS external_url,

    -- pipeline timestamp
    NOW()                                                               AS ingested_at

FROM {{ source('raw', 'chapter_responses') }} c

{% if is_incremental() %}
WHERE c.pulled_at > (SELECT MAX(ingested_at) FROM {{ this }})
{% endif %}