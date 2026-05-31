from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class Chapter(BaseModel):
    mangadex_id: str
    manga_mangadex_id: Optional[str] = None
    volume: Optional[str] = None
    chapter_number: Optional[str] = None
    title: Optional[str] = None
    language: str
    is_unavailable: bool
    pages: Optional[int] = None
    scanlation_group: Optional[str] = None
    published_at: Optional[datetime] = None
    readable_at: Optional[datetime] = None
    external_url: Optional[str] = None

    model_config = {"from_attributes": True}


class MangaSummary(BaseModel):
    mangadex_id: str
    source: str
    title: Optional[str] = None
    status: Optional[str] = None
    year: Optional[int] = None
    content_rating: Optional[str] = None
    original_language: Optional[str] = None
    tags: List[str] = []
    authors: List[str] = []
    cover_url: Optional[str] = None

    model_config = {"from_attributes": True}


class MangaDetail(MangaSummary):
    title_japanese: Optional[str] = None
    alt_titles: Optional[Any] = None
    description: Optional[str] = None
    artists: List[str] = []
    created_at_source: Optional[datetime] = None
    updated_at_source: Optional[datetime] = None
    ingested_at: Optional[datetime] = None


class PaginatedManga(BaseModel):
    total: int
    limit: int
    offset: int
    data: List[MangaSummary]


class PaginatedChapters(BaseModel):
    total: int
    limit: int
    offset: int
    data: List[Chapter]
