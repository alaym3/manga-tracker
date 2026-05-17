from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import MangaDetail, MangaSummary, PaginatedChapters, PaginatedManga

router = APIRouter(prefix="/manga", tags=["manga"])


@router.get("", response_model=PaginatedManga)
async def list_manga(
    status: Optional[str] = Query(None, description="ongoing | completed | hiatus | cancelled"),
    tag: Optional[str] = Query(None, description="Filter by tag name, e.g. action"),
    content_rating: Optional[str] = Query(None, description="safe | suggestive | erotica"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
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
    ).mappings().all()

    return PaginatedManga(total=total, limit=limit, offset=offset, data=rows)


@router.get("/{mangadex_id}", response_model=MangaDetail)
async def get_manga(mangadex_id: str, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            text("SELECT * FROM staging.stg_manga WHERE mangadex_id = :id"),
            {"id": mangadex_id},
        )
    ).mappings().first()

    if not row:
        raise HTTPException(status_code=404, detail="Manga not found")

    return row


@router.get("/{mangadex_id}/chapters", response_model=PaginatedChapters)
async def get_manga_chapters(
    mangadex_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    params = {"id": mangadex_id, "limit": limit, "offset": offset}

    total = (
        await db.execute(
            text("SELECT COUNT(*) FROM staging.stg_chapters WHERE manga_mangadex_id = :id"),
            params,
        )
    ).scalar()

    rows = (
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
    ).mappings().all()

    return PaginatedChapters(total=total, limit=limit, offset=offset, data=rows)
