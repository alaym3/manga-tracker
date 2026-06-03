import json

from tests.conftest import make_rows_result, make_scalar_result

MANGA_ROW = {
    "mangadex_id": "abc-123",
    "source": "mangadex",
    "title": "Berserk",
    "status": "ongoing",
    "year": 1989,
    "content_rating": "suggestive",
    "original_language": "ja",
    "tags": ["Action", "Fantasy"],
    "authors": ["Miura Kentarou"],
    "cover_url": "https://example.com/cover.jpg",
}

MANGA_DETAIL_ROW = {
    **MANGA_ROW,
    "title_japanese": "ベルセルク",
    "alt_titles": [],
    "description": "A dark fantasy manga.",
    "artists": ["Miura Kentarou"],
    "created_at_source": None,
    "updated_at_source": None,
    "ingested_at": None,
}


# ---------------------------------------------------------------------------
# GET /manga
# ---------------------------------------------------------------------------


async def test_list_manga_empty(client, mock_db):
    mock_db.execute.side_effect = [make_scalar_result(0), make_rows_result([])]

    response = await client.get("/manga")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["data"] == []
    assert body["limit"] == 20
    assert body["offset"] == 0


async def test_list_manga_returns_results(client, mock_db):
    mock_db.execute.side_effect = [make_scalar_result(1), make_rows_result([MANGA_ROW])]

    response = await client.get("/manga")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["data"]) == 1
    assert body["data"][0]["title"] == "Berserk"
    assert body["data"][0]["mangadex_id"] == "abc-123"


async def test_list_manga_pagination_params_passed_through(client, mock_db):
    mock_db.execute.side_effect = [make_scalar_result(50), make_rows_result([])]

    response = await client.get("/manga?limit=5&offset=10")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert body["offset"] == 10


async def test_list_manga_cache_hit_skips_db(client, mock_db, mock_redis):
    cached = {"total": 1, "limit": 20, "offset": 0, "data": [MANGA_ROW]}
    mock_redis.get.return_value = json.dumps(cached)

    response = await client.get("/manga")

    assert response.status_code == 200
    mock_db.execute.assert_not_called()


async def test_list_manga_cache_miss_stores_result(client, mock_db, mock_redis):
    mock_redis.get.return_value = None
    mock_db.execute.side_effect = [make_scalar_result(1), make_rows_result([MANGA_ROW])]

    await client.get("/manga")

    mock_redis.setex.assert_called_once()


# ---------------------------------------------------------------------------
# GET /manga/{id}
# ---------------------------------------------------------------------------


async def test_get_manga_found(client, mock_db):
    mock_result = make_rows_result(None)
    mock_result.mappings.return_value.first.return_value = MANGA_DETAIL_ROW
    mock_db.execute.return_value = mock_result

    response = await client.get("/manga/abc-123")

    assert response.status_code == 200
    body = response.json()
    assert body["mangadex_id"] == "abc-123"
    assert body["title"] == "Berserk"
    assert body["description"] == "A dark fantasy manga."


async def test_get_manga_not_found(client, mock_db):
    mock_result = make_rows_result(None)
    mock_result.mappings.return_value.first.return_value = None
    mock_db.execute.return_value = mock_result

    response = await client.get("/manga/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Manga not found"


async def test_get_manga_cache_hit_skips_db(client, mock_db, mock_redis):
    mock_redis.get.return_value = json.dumps(MANGA_DETAIL_ROW)

    response = await client.get("/manga/abc-123")

    assert response.status_code == 200
    mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# GET /manga/{id}/chapters
# ---------------------------------------------------------------------------

CHAPTER_ROW = {
    "mangadex_id": "ch-001",
    "manga_mangadex_id": "abc-123",
    "volume": "1",
    "chapter_number": "1",
    "title": "The Black Swordsman",
    "language": "en",
    "is_unavailable": False,
    "pages": 45,
    "scanlation_group": "Dark Horse",
    "published_at": "2024-01-01T00:00:00",
    "readable_at": "2024-01-01T00:00:00",
    "external_url": None,
}


async def test_get_manga_chapters_returns_results(client, mock_db):
    mock_db.execute.side_effect = [make_scalar_result(1), make_rows_result([CHAPTER_ROW])]

    response = await client.get("/manga/abc-123/chapters")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["mangadex_id"] == "ch-001"


async def test_get_manga_chapters_cache_hit_skips_db(client, mock_db, mock_redis):
    cached = {"total": 1, "limit": 20, "offset": 0, "data": [CHAPTER_ROW]}
    mock_redis.get.return_value = json.dumps(cached)

    response = await client.get("/manga/abc-123/chapters")

    assert response.status_code == 200
    mock_db.execute.assert_not_called()
