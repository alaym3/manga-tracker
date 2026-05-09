SELECT
	-- identity
	m.payload ->> 'id' AS mangadex_id,
	'mangadex' AS source,
	-- titles (safe fallbacks) 
	COALESCE(m.payload -> 'attributes' -> 'title' ->> 'en', m.payload -> 'attributes' -> 'title' ->> 'ja-ro') AS title,
	m.payload -> 'attributes' -> 'title' ->> 'ja-ro' AS title_japanese,
	m.payload -> 'attributes' -> 'altTitles' AS alt_titles,
	COALESCE(m.payload -> 'attributes' -> 'description' ->> 'en', m.payload -> 'attributes' -> 'description' ->> 'ja') AS description,
	m.payload -> 'attributes' ->> 'originalLanguage' AS original_language,
	m.payload -> 'attributes' ->> 'status' AS status,
	NULLIF(m.payload -> 'attributes' ->> 'year', '')::INT AS YEAR,
	m.payload -> 'attributes' ->> 'contentRating' AS content_rating,
	-- tags (flattened)
	COALESCE(
		ARRAY(
			SELECT DISTINCT
				t -> 'attributes' -> 'name' ->> 'en'
			FROM
				jsonb_array_elements(COALESCE(m.payload -> 'attributes' -> 'tags', '[]'::jsonb)) t
			WHERE
				t -> 'attributes' -> 'name' ? 'en'
		),
		ARRAY[]::TEXT[]
	) AS tags,
	-- authors (array)
	COALESCE(
		ARRAY(
			SELECT
				r -> 'attributes' ->> 'name'
			FROM
				jsonb_array_elements(COALESCE(m.payload -> 'relationships', '[]'::jsonb)) r
			WHERE
				r ->> 'type' = 'author'
				AND r -> 'attributes' ? 'name'
		),
		ARRAY[]::TEXT[]
	) AS authors,
	-- timestamps
	(m.payload -> 'attributes' ->> 'createdAt')::timestamptz AS created_at_source,
	(m.payload -> 'attributes' ->> 'updatedAt')::timestamptz AS updated_at_source
FROM
	raw.manga_responses m;