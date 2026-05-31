import json
import os
from typing import Any, Optional

from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

# TTLs in seconds — chosen based on how often each data type changes.
# Pipeline runs at most hourly, so caching beyond that window is safe.
MANGA_DETAIL_TTL = 86_400  # 24h — manga metadata almost never changes
MANGA_LIST_TTL = 3_600  # 1h  — list results shift only when pipeline runs
CHAPTERS_TTL = 3_600  # 1h
RECENT_CHAPTERS_TTL = 600  # 10m — most likely to have fresh uploads


async def get_redis() -> Redis:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def get_cached(redis: Redis, key: str) -> Optional[Any]:
    try:
        value = await redis.get(key)
        return json.loads(value) if value else None
    except Exception:
        # Redis unavailable — fail open and let the caller hit Postgres
        return None


async def set_cached(redis: Redis, key: str, data: Any, ttl: int) -> None:
    try:
        # default=str handles datetimes and other non-JSON-serializable types
        await redis.setex(key, ttl, json.dumps(data, default=str))
    except Exception:
        pass
