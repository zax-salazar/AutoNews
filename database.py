from contextlib import contextmanager
import json
import logging
import os
import sqlite3
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "autonews.db",
)

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "msclkid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "ref",
    "referrer",
}

VALID_STATUSES = ("pending", "completed", "failed")


def normalize_url(url: str) -> str:
    """Normalize an article URL for stable duplicate detection.

    Steps:
    1. Scheme and hostname to lowercase.
    2. Strip default ports (:80 for http, :443 for https).
    3. Strip URL fragment (#...).
    4. Remove common tracking query parameters (utm_*, fbclid, gclid, etc.).
    5. Sort remaining query parameters for canonical ordering.
    6. Normalize trailing slashes on non-root paths.

    Parameters:
        url (str): The raw URL string.

    Returns:
        str: Cleaned and normalized canonical URL string.
    """
    if not url or not isinstance(url, str):
        return ""

    url = url.strip()
    if not url:
        return ""

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        logger.warning("Failed to parse URL %r: %s", url, exc)
        return url

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Remove default ports
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    # Path trailing slash normalization
    path = parsed.path
    if path and path != "/":
        path = path.rstrip("/")

    # Query parameters filtering and sorting
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_params = [
        (k, v)
        for k, v in query_params
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    filtered_params.sort(key=lambda x: (x[0], x[1]))
    new_query = urllib.parse.urlencode(filtered_params)

    # Reconstruct normalized URL without fragment
    normalized = urllib.parse.urlunparse((
        scheme,
        netloc,
        path,
        "",  # params
        new_query,
        "",  # fragment
    ))

    return normalized


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Get a SQLite database connection.

    Parameters:
        db_path (str): Database file path.

    Returns:
        sqlite3.Connection: Active database connection.
    """
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection(db_path: str = DEFAULT_DB_PATH):
    """Context manager yielding a SQLite connection.

    Commits on success, rolls back on exception, and always closes.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize the SQLite database schema and indexes safely.

    Parameters:
        db_path (str): Database file path.
    """
    if not db_path:
        return

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL UNIQUE,
                    source_name TEXT,
                    title TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    article_data TEXT,
                    research_data TEXT,
                    research_status TEXT NOT NULL DEFAULT 'pending',
                    publish_status TEXT NOT NULL DEFAULT 'pending',
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Run idempotent schema migrations for existing databases
            existing_cols = {row["name"] for row in cursor.execute("PRAGMA table_info(articles)").fetchall()}

            if "article_data" not in existing_cols:
                cursor.execute("ALTER TABLE articles ADD COLUMN article_data TEXT;")
            if "research_data" not in existing_cols:
                cursor.execute("ALTER TABLE articles ADD COLUMN research_data TEXT;")
            if "research_status" not in existing_cols:
                cursor.execute("ALTER TABLE articles ADD COLUMN research_status TEXT NOT NULL DEFAULT 'pending';")
            if "publish_status" not in existing_cols:
                cursor.execute("ALTER TABLE articles ADD COLUMN publish_status TEXT NOT NULL DEFAULT 'pending';")

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_normalized_url ON articles(normalized_url);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_research_status ON articles(research_status);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_publish_status ON articles(publish_status);
            """)
    except Exception as exc:
        logger.error("Failed to initialize database at %s: %s", db_path, exc)
        raise


def get_article_status(normalized_url: str, db_path: str = DEFAULT_DB_PATH) -> Optional[str]:
    """Retrieve the processing status of an article by its normalized URL.

    Parameters:
        normalized_url (str): The normalized URL.
        db_path (str): Database file path.

    Returns:
        str | None: The status string ('pending', 'processing', 'completed', 'failed'),
            or None if no record exists.
    """
    if not db_path or not normalized_url:
        return None

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM articles WHERE normalized_url = ?",
                (normalized_url,),
            )
            row = cursor.fetchone()
            return row["status"] if row else None
    except Exception as exc:
        logger.error("Database query error for %s: %s", normalized_url, exc)
        return None


def is_article_completed(normalized_url: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Check if an article has been successfully completed.

    Parameters:
        normalized_url (str): The normalized URL.
        db_path (str): Database file path.

    Returns:
        bool: True if article status is 'completed', False otherwise.
    """
    return get_article_status(normalized_url, db_path=db_path) == "completed"


def record_article(
    url: str,
    normalized_url: str,
    source_name: Optional[str] = None,
    title: Optional[str] = None,
    status: str = "pending",
    error_message: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Insert or update an article record in persistent storage.

    Parameters:
        url (str): Raw original article URL.
        normalized_url (str): Normalized article URL (unique key).
        source_name (str, optional): Source identifier.
        title (str, optional): Article title.
        status (str): Processing status ('pending', 'processing', 'completed', 'failed').
        error_message (str, optional): Error message if status is 'failed'.
        db_path (str): Database file path.
    """
    if not db_path or not normalized_url:
        return

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO articles (url, normalized_url, source_name, title, status, error_message, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(normalized_url) DO UPDATE SET
                    url = excluded.url,
                    source_name = COALESCE(excluded.source_name, articles.source_name),
                    title = COALESCE(excluded.title, articles.title),
                    status = excluded.status,
                    error_message = excluded.error_message,
                    last_seen = CURRENT_TIMESTAMP;
                """,
                (url, normalized_url, source_name, title, status, error_message),
            )
    except Exception as exc:
        logger.error("Failed to record article %s in DB: %s", normalized_url, exc)


def mark_article_status(
    normalized_url: str,
    status: str,
    error_message: Optional[str] = None,
    title: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Update processing status and timestamp for an existing article record.

    Parameters:
        normalized_url (str): Normalized article URL.
        status (str): New status ('completed', 'failed', 'processing', etc.).
        error_message (str, optional): Error message if failed.
        title (str, optional): Updated title if extracted.
        db_path (str): Database file path.
    """
    if not db_path or not normalized_url:
        return

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            if title:
                cursor.execute(
                    """
                    UPDATE articles
                    SET status = ?, error_message = ?, title = ?, last_seen = CURRENT_TIMESTAMP
                    WHERE normalized_url = ?;
                    """,
                    (status, error_message, title, normalized_url),
                )
            else:
                cursor.execute(
                    """
                    UPDATE articles
                    SET status = ?, error_message = ?, last_seen = CURRENT_TIMESTAMP
                    WHERE normalized_url = ?;
                    """,
                    (status, error_message, normalized_url),
                )
    except Exception as exc:
        logger.error("Failed to update status for article %s: %s", normalized_url, exc)


def save_article_data(normalized_url: str, data: dict, db_path: str = DEFAULT_DB_PATH) -> None:
    """Persist JSON serialized extracted article data."""
    if not db_path or not normalized_url or data is None:
        return

    try:
        json_str = json.dumps(data, ensure_ascii=False)
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE articles
                SET article_data = ?, last_seen = CURRENT_TIMESTAMP
                WHERE normalized_url = ?;
                """,
                (json_str, normalized_url),
            )
    except Exception as exc:
        logger.error("Failed to save article_data for %s: %s", normalized_url, exc)


def save_research_data(normalized_url: str, data: dict, db_path: str = DEFAULT_DB_PATH) -> None:
    """Persist JSON serialized research article data."""
    if not db_path or not normalized_url or data is None:
        return

    try:
        json_str = json.dumps(data, ensure_ascii=False)
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE articles
                SET research_data = ?, last_seen = CURRENT_TIMESTAMP
                WHERE normalized_url = ?;
                """,
                (json_str, normalized_url),
            )
    except Exception as exc:
        logger.error("Failed to save research_data for %s: %s", normalized_url, exc)


def get_article_data(normalized_url: str, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    """Retrieve parsed JSON article_data dict."""
    if not db_path or not normalized_url:
        return None

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT article_data FROM articles WHERE normalized_url = ?",
                (normalized_url,),
            )
            row = cursor.fetchone()
            if row and row["article_data"]:
                return json.loads(row["article_data"])
            return None
    except Exception as exc:
        logger.error("Failed to get article_data for %s: %s", normalized_url, exc)
        return None


def get_research_data(normalized_url: str, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    """Retrieve parsed JSON research_data dict."""
    if not db_path or not normalized_url:
        return None

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT research_data FROM articles WHERE normalized_url = ?",
                (normalized_url,),
            )
            row = cursor.fetchone()
            if row and row["research_data"]:
                return json.loads(row["research_data"])
            return None
    except Exception as exc:
        logger.error("Failed to get research_data for %s: %s", normalized_url, exc)
        return None


def mark_research_status(
    normalized_url: str,
    status: str,
    error_message: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Update research status for an article."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid research status: {status}")

    if not db_path or not normalized_url:
        return

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE articles
                SET research_status = ?, error_message = ?, last_seen = CURRENT_TIMESTAMP
                WHERE normalized_url = ?;
                """,
                (status, error_message, normalized_url),
            )
    except Exception as exc:
        logger.error("Failed to mark research_status for %s: %s", normalized_url, exc)


def mark_publish_status(
    normalized_url: str,
    status: str,
    error_message: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Update publish status for an article."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid publish status: {status}")

    if not db_path or not normalized_url:
        return

    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE articles
                SET publish_status = ?, error_message = ?, last_seen = CURRENT_TIMESTAMP
                WHERE normalized_url = ?;
                """,
                (status, error_message, normalized_url),
            )
    except Exception as exc:
        logger.error("Failed to mark publish_status for %s: %s", normalized_url, exc)


def get_pending_research(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Return articles that need research (research_status IN ('pending', 'failed')), where extraction is completed."""
    if not db_path:
        return []

    results: List[Dict[str, Any]] = []
    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT url, normalized_url, title, article_data
                FROM articles
                WHERE status = 'completed' AND research_status IN ('pending', 'failed');
                """
            )
            rows = cursor.fetchall()
            for row in rows:
                parsed_data = None
                if row["article_data"]:
                    try:
                        parsed_data = json.loads(row["article_data"])
                    except Exception:
                        pass
                results.append({
                    "url": row["url"],
                    "normalized_url": row["normalized_url"],
                    "title": row["title"],
                    "article_data": parsed_data,
                })
    except Exception as exc:
        logger.error("Failed to query get_pending_research: %s", exc)

    return results


def get_pending_publish(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Return articles that need publish (publish_status IN ('pending', 'failed')), where research_status = 'completed'."""
    if not db_path:
        return []

    results: List[Dict[str, Any]] = []
    try:
        with db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT url, normalized_url, title, research_data
                FROM articles
                WHERE research_status = 'completed' AND publish_status IN ('pending', 'failed');
                """
            )
            rows = cursor.fetchall()
            for row in rows:
                parsed_data = None
                if row["research_data"]:
                    try:
                        parsed_data = json.loads(row["research_data"])
                    except Exception:
                        pass
                results.append({
                    "url": row["url"],
                    "normalized_url": row["normalized_url"],
                    "title": row["title"],
                    "research_data": parsed_data,
                })
    except Exception as exc:
        logger.error("Failed to query get_pending_publish: %s", exc)

    return results
