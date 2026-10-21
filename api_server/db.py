from contextlib import contextmanager
import json
import logging
import os
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _db_path() -> str:
    """Resolve the SQLite DB path for the API server.

    Returns:
        str: Absolute or relative path to the SQLite database file.
    """
    env_path = os.environ.get("AUTONEWS_API_DB")
    if env_path and env_path.strip():
        return env_path.strip()

    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "articles.db")


@contextmanager
def _conn(path: Optional[str] = None):
    """Context manager yielding a sqlite3 connection with Row factory.

    Commits on success, rolls back on exception, and always closes connection.
    """
    db_file = path if path else _db_path()
    conn = sqlite3.connect(db_file, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Optional[str] = None) -> None:
    """Initialize the SQLite schema and indexes safely for the API server."""
    with _conn(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                language TEXT NOT NULL DEFAULT 'fa',
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                body TEXT NOT NULL,
                seo_description TEXT DEFAULT '',
                keywords TEXT DEFAULT '[]',
                research_notes TEXT DEFAULT '',
                images TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at DESC);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_articles_language ON articles(language);
        """)


def insert_article(article: dict, path: Optional[str] = None) -> str:
    """Insert one article and return generated UUID string.

    Parameters:
        article (dict): ArticleIn model dictionary payload.
        path (str, optional): Database file path.

    Returns:
        str: Generated article UUID hex string.
    """
    article_id = uuid.uuid4().hex

    language = article.get("language", "fa") or "fa"
    title = article.get("title", "")
    summary = article.get("summary", "") or ""
    body = article.get("body", "")
    seo_description = article.get("seo_description", "") or ""

    keywords_list = article.get("keywords") if isinstance(article.get("keywords"), list) else []
    keywords_json = json.dumps(keywords_list, ensure_ascii=False)

    research_notes = article.get("research_notes", "") or ""

    images_raw = article.get("images") if isinstance(article.get("images"), list) else []
    images_list = [img if isinstance(img, dict) else img.model_dump() for img in images_raw]
    images_json = json.dumps(images_list, ensure_ascii=False)

    with _conn(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO articles (
                id, language, title, summary, body, seo_description,
                keywords, research_notes, images, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
            """,
            (
                article_id,
                language,
                title,
                summary,
                body,
                seo_description,
                keywords_json,
                research_notes,
                images_json,
            ),
        )

    return article_id


def get_article(article_id: str, path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve an article by ID, excluding internal research_notes.

    Parameters:
        article_id (str): Article UUID string.
        path (str, optional): Database file path.

    Returns:
        dict | None: Formatted article dict or None if not found.
    """
    if not article_id:
        return None

    with _conn(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, language, title, summary, body, seo_description,
                   keywords, images, created_at
            FROM articles
            WHERE id = ?;
            """,
            (article_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        keywords = []
        if row["keywords"]:
            try:
                keywords = json.loads(row["keywords"])
            except Exception:
                keywords = []

        images = []
        if row["images"]:
            try:
                images = json.loads(row["images"])
            except Exception:
                images = []

        return {
            "id": row["id"],
            "language": row["language"],
            "title": row["title"],
            "summary": row["summary"],
            "body": row["body"],
            "seo_description": row["seo_description"],
            "keywords": keywords,
            "images": images,
            "created_at": str(row["created_at"]),
        }


def list_articles(
    limit: int = 20,
    offset: int = 0,
    language: Optional[str] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve paginated list of articles sorted by created_at DESC, id DESC.

    Parameters:
        limit (int): Pagination size limit (clamped to 1-100).
        offset (int): Pagination offset (clamped to >= 0).
        language (str, optional): Optional language filter code.
        path (str, optional): Database file path.

    Returns:
        dict: Paginated results {"total": int, "limit": int, "offset": int, "items": list}.
    """
    clamped_limit = max(1, min(100, limit))
    clamped_offset = max(0, offset)

    with _conn(path) as conn:
        cursor = conn.cursor()

        if language:
            cursor.execute(
                "SELECT COUNT(*) as total FROM articles WHERE language = ?;",
                (language,),
            )
            total = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT id, language, title, summary, body, seo_description,
                       keywords, images, created_at
                FROM articles
                WHERE language = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?;
                """,
                (language, clamped_limit, clamped_offset),
            )
        else:
            cursor.execute("SELECT COUNT(*) as total FROM articles;")
            total = cursor.fetchone()["total"]

            cursor.execute(
                """
                SELECT id, language, title, summary, body, seo_description,
                       keywords, images, created_at
                FROM articles
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?;
                """,
                (clamped_limit, clamped_offset),
            )

        rows = cursor.fetchall()
        items = []
        for row in rows:
            keywords = []
            if row["keywords"]:
                try:
                    keywords = json.loads(row["keywords"])
                except Exception:
                    keywords = []

            images = []
            if row["images"]:
                try:
                    images = json.loads(row["images"])
                except Exception:
                    images = []

            items.append({
                "id": row["id"],
                "language": row["language"],
                "title": row["title"],
                "summary": row["summary"],
                "body": row["body"],
                "seo_description": row["seo_description"],
                "keywords": keywords,
                "images": images,
                "created_at": str(row["created_at"]),
            })

        return {
            "total": total,
            "limit": clamped_limit,
            "offset": clamped_offset,
            "items": items,
        }
