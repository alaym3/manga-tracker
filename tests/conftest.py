from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from manga_tracker.api.cache import get_redis
from manga_tracker.api.database import get_db
from manga_tracker.api.main import app


def make_scalar_result(value):
    """Mimics the result of db.execute() for COUNT queries (.scalar())."""
    m = MagicMock()
    m.scalar.return_value = value
    return m


def make_rows_result(rows):
    """Mimics the result of db.execute() for data queries (.mappings().all())."""
    m = MagicMock()
    m.mappings.return_value.all.return_value = rows
    return m


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get.return_value = None  # cache miss by default
    return redis


@pytest.fixture
async def client(mock_db, mock_redis):
    async def _get_db():
        yield mock_db

    async def _get_redis():
        yield mock_redis

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_redis] = _get_redis

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
