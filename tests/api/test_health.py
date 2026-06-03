async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_sets_request_id_header(client):
    response = await client.get("/health")
    assert "x-request-id" in response.headers
