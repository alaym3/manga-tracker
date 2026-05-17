from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import PaginatedChapters

router = APIRouter(prefix="/chapters", tags=["chapters"])


@router.get("/recent", response_model=PaginatedChapters)
async def recent_chapters(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    params = {"limit": limit, "offset": offset}

    total = (
        await db.execute(
            text("SELECT COUNT(*) FROM staging.stg_chapters WHERE is_unavailable = false"),
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
                WHERE is_unavailable = false
                ORDER BY published_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
    ).mappings().all()

    return PaginatedChapters(total=total, limit=limit, offset=offset, data=rows)
