from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import (
    CHAPTERS_TTL,
    MANGA_DETAIL_TTL,
    MANGA_LIST_TTL,
    get_cached,
    get_redis,
    set_cached,
)
from ..database import get_db
from ..models import MangaDetail, PaginatedChapters, PaginatedManga

router = APIRouter(prefix="/manga", tags=["manga"])


@router.get("", response_model=PaginatedManga)
async def list_manga(
    status: Optional[str] = Query(None, description="ongoing | completed | hiatus | cancelled"),
    tag: Optional[str] = Query(None, description="Filter by tag name, e.g. action"),
    content_rating: Optional[str] = Query(None, description="safe | suggestive | erotica"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    cache_key = f"manga:list:{status}:{tag}:{content_rating}:{limit}:{offset}"
    if cached := await get_cached(redis, cache_key):
        return cached

    conditions = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if tag:
        conditions.append(":tag = ANY(tags)")
        params["tag"] = tag
    if content_rating:
        conditions.append("content_rating = :content_rating")
        params["content_rating"] = content_rating

    where = " AND ".join(conditions)

    total = (
        await db.execute(
            text(f"SELECT COUNT(*) FROM staging.stg_manga WHERE {where}"),
            params,
        )
    ).scalar()

    rows = (
        (
            await db.execute(
                text(f"""
                SELECT mangadex_id, source, title, status, year, content_rating,
                       original_language, tags, authors, cover_url
                FROM staging.stg_manga
                WHERE {where}
                ORDER BY title ASC
                LIMIT :limit OFFSET :offset
            """),
                params,
            )
        )
        .mappings()
        .all()
    )

    result = PaginatedManga(total=total, limit=limit, offset=offset, data=rows)
    await set_cached(redis, cache_key, result.model_dump(), MANGA_LIST_TTL)
    return result


@router.get("/{mangadex_id}", response_model=MangaDetail)
async def get_manga(
    mangadex_id: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    cache_key = f"manga:{mangadex_id}"
    if cached := await get_cached(redis, cache_key):
        return cached

    row = (
        (
            await db.execute(
                text("SELECT * FROM staging.stg_manga WHERE mangadex_id = :id"),
                {"id": mangadex_id},
            )
        )
        .mappings()
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Manga not found")

    result = MangaDetail.model_validate(dict(row))
    await set_cached(redis, cache_key, result.model_dump(), MANGA_DETAIL_TTL)
    return result


@router.get("/{mangadex_id}/chapters", response_model=PaginatedChapters)
async def get_manga_chapters(
    mangadex_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    cache_key = f"manga:{mangadex_id}:chapters:{limit}:{offset}"
    if cached := await get_cached(redis, cache_key):
        return cached

    params = {"id": mangadex_id, "limit": limit, "offset": offset}

    total = (
        await db.execute(
            text("SELECT COUNT(*) FROM staging.stg_chapters WHERE manga_mangadex_id = :id"),
            params,
        )
    ).scalar()

    rows = (
        (
            await db.execute(
                text("""
                SELECT mangadex_id, manga_mangadex_id, volume, chapter_number, title,
                       language, is_unavailable, pages, scanlation_group,
                       published_at, readable_at, external_url
                FROM staging.stg_chapters
                WHERE manga_mangadex_id = :id
                ORDER BY published_at ASC NULLS LAST
                LIMIT :limit OFFSET :offset
            """),
                params,
            )
        )
        .mappings()
        .all()
    )

    result = PaginatedChapters(total=total, limit=limit, offset=offset, data=rows)
    await set_cached(redis, cache_key, result.model_dump(), CHAPTERS_TTL)
    return result
