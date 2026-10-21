from typing import List, Optional
from pydantic import BaseModel, Field


class ImageIn(BaseModel):
    index: int = Field(..., ge=0)
    url: str = Field(..., min_length=1)
    alt_fa: str = ""


class ArticleIn(BaseModel):
    language: str = "fa"
    title: str = Field(..., min_length=1)
    summary: str = ""
    body: str = Field(..., min_length=1)
    seo_description: str = ""
    keywords: List[str] = []
    research_notes: str = ""
    images: List[ImageIn] = []


class ArticleOut(BaseModel):
    id: str
    language: str
    title: str
    summary: str
    body: str
    seo_description: str
    keywords: List[str]
    images: List[ImageIn]
    created_at: str
    # research_notes is intentionally NOT returned by GET endpoints
    # (it is internal metadata; the frontend does not need it).


class ArticleList(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ArticleOut]
