from contextlib import asynccontextmanager
import logging
import os
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api_server.db import init_db, insert_article, get_article, list_articles
from api_server.schemas import ArticleIn, ArticleOut, ArticleList

logger = logging.getLogger(__name__)

# Verify API token is configured at import time
API_TOKEN = os.environ.get("AUTONEWS_API_TOKEN")
if not API_TOKEN or not API_TOKEN.strip():
    raise RuntimeError("AUTONEWS_API_TOKEN environment variable is required to start the API server.")

API_TOKEN = API_TOKEN.strip()

security = HTTPBearer(auto_error=False)


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> str:
    """Validate Bearer HTTP authorization token.

    Parameters:
        credentials (HTTPAuthorizationCredentials, optional): Bearer header credentials.

    Returns:
        str: Validated token.

    Raises:
        HTTPException: 403 Forbidden if missing or invalid token.
    """
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid token",
        )

    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid token",
        )

    return credentials.credentials


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for database initialization on startup."""
    init_db()
    yield


app = FastAPI(
    title="AutoNews Content API",
    description="AutoNews content API server.",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"ok": True, "service": "autonews-api"}


@app.post(
    "/api/articles",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
)
def create_article(
    article_in: ArticleIn,
    token: str = Depends(verify_token),
):
    """Publish a new article (requires Bearer token authentication)."""
    article_id = insert_article(article_in.model_dump())
    return {
        "id": article_id,
        "url": f"/api/articles/{article_id}",
    }


@app.get(
    "/api/articles",
    response_model=ArticleList,
)
def get_articles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    language: Optional[str] = Query(None),
):
    """List published articles with pagination and optional language filter."""
    result = list_articles(limit=limit, offset=offset, language=language)
    return result


@app.get(
    "/api/articles/{article_id}",
    response_model=ArticleOut,
)
def get_article_by_id(article_id: str):
    """Retrieve an article by ID."""
    article = get_article(article_id)
    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="article not found",
        )
    return article
