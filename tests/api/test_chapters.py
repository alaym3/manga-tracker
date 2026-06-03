import json

from tests.conftest import make_rows_result, make_scalar_result

CHAPTER_ROW = {
    "mangadex_id": "ch-001",
    "manga_mangadex_id": "abc-123",
    "volume": "1",
    "chapter_number": "42",
    "title": "The Eclipse",
    "language": "en",
    "is_unavailable": False,
    "pages": 52,
    "scanlation_group": "Dark Horse",
    "published_at": "2024-06-01T00:00:00",
    "readable_at": "2024-06-01T00:00:00",
    "external_url": None,
}


async def test_recent_chapters_empty(client, mock_db):
    mock_db.execute.side_effect = [make_scalar_result(0), make_rows_result([])]

    response = await client.get("/chapters/recent")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["data"] == []


async def test_recent_chapters_returns_results(client, mock_db):
    mock_db.execute.side_effect = [make_scalar_result(1), make_rows_result([CHAPTER_ROW])]

    response = await client.get("/chapters/recent")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["mangadex_id"] == "ch-001"
    assert body["data"][0]["is_unavailable"] is False


async def test_recent_chapters_cache_hit_skips_db(client, mock_db, mock_redis):
    cached = {"total": 1, "limit": 20, "offset": 0, "data": [CHAPTER_ROW]}
    mock_redis.get.return_value = json.dumps(cached)

    response = await client.get("/chapters/recent")

    assert response.status_code == 200
    mock_db.execute.assert_not_called()


async def test_recent_chapters_cache_miss_stores_result(client, mock_db, mock_redis):
    mock_redis.get.return_value = None
    mock_db.execute.side_effect = [make_scalar_result(1), make_rows_result([CHAPTER_ROW])]

    await client.get("/chapters/recent")

    mock_redis.setex.assert_called_once()


async def test_recent_chapters_pagination(client, mock_db):
    mock_db.execute.side_effect = [make_scalar_result(100), make_rows_result([])]

    response = await client.get("/chapters/recent?limit=5&offset=20")

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert body["offset"] == 20
