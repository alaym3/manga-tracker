{{
    config(
        unique_key=['mangadex_id'],
        incremental_strategy='merge',
        on_schema_change='fail'
    )
}}

SELECT
    mangadex_id,

    -- community rating
    NULLIF(s.payload -> 'rating' ->> 'average',  '')::NUMERIC(5, 2)   AS rating_average,
    NULLIF(s.payload -> 'rating' ->> 'bayesian', '')::NUMERIC(5, 2)   AS rating_bayesian,
    s.payload -> 'rating' -> 'distribution'                            AS rating_distribution,

    -- engagement
    NULLIF(s.payload ->> 'follows', '')::INTEGER                       AS follows,
    NULLIF(s.payload -> 'comments' ->> 'repliesCount', '')::INTEGER    AS comments_count,

    -- pipeline timestamp
    s.pulled_at

FROM {{ source('raw', 'manga_statistics') }} s

{% if is_incremental() %}
WHERE s.pulled_at > (SELECT MAX(pulled_at) FROM {{ this }})
{% endif %}
