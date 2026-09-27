import html
from html.parser import HTMLParser
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class _HTMLTagStripper(HTMLParser):
    """Simple HTML parser to strip tags and accumulate text content."""

    def __init__(self):
        super().__init__()
        self.reset()
        self.fed: List[str] = []

    def handle_data(self, d: str) -> None:
        self.fed.append(d)

    def get_data(self) -> str:
        return "".join(self.fed)


def _clean_html_text(text: Optional[str]) -> Optional[str]:
    """Strip HTML tags, unescape HTML entities, and normalize whitespace."""
    if not text:
        return None

    # Strip HTML tags using HTMLParser
    stripper = _HTMLTagStripper()
    try:
        stripper.feed(text)
        cleaned = stripper.get_data()
    except Exception:
        # Fallback regex tag removal if parsing fails
        cleaned = re.sub(r"<[^>]+>", "", text)

    # Unescape HTML entities (e.g. &amp; -> &)
    cleaned = html.unescape(cleaned)

    # Normalize whitespace (replace multi-spaces/newlines with a single space)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned if cleaned else None


def _format_time_struct(time_struct: time.struct_time) -> str:
    """Format a struct_time object into UTC ISO 8601 format string (YYYY-MM-DDTHH:MM:SSZ)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time_struct)


def _get_entry_field(entry: Any, *field_names: str) -> Optional[Any]:
    """Retrieve the first non-None value matching any of the given field names."""
    if isinstance(entry, dict):
        for name in field_names:
            val = entry.get(name)
            if val is not None:
                return val
    else:
        for name in field_names:
            val = getattr(entry, name, None)
            if val is not None:
                return val
    return None


def parse_entry(entry: Any) -> Optional[Dict[str, Any]]:
    """Normalize a raw RSS/Atom feed entry into a standard article dictionary.

    Parameters:
        entry: A raw feedparser entry object or dictionary.

    Returns:
        dict | None: A dictionary containing normalized article data:
            {
                "title": str,
                "url": str,
                "published": str | None,
                "summary": str | None
            }
        Returns None if title or url is missing/empty, or if an error occurs.
    """
    if not entry:
        logger.warning("Empty or None entry passed to parse_entry.")
        return None

    try:
        # 1. Extract and validate title
        raw_title = _get_entry_field(entry, "title")
        title = str(raw_title).strip() if raw_title is not None else ""

        # 2. Extract and validate URL/link
        raw_url = _get_entry_field(entry, "link", "id", "guid")
        url = str(raw_url).strip() if raw_url is not None else ""

        if not url:
            # Fallback: check if entry has a links list
            links = _get_entry_field(entry, "links")
            if isinstance(links, (list, tuple)) and len(links) > 0:
                first_link = links[0]
                if isinstance(first_link, dict):
                    url = str(first_link.get("href", "")).strip()
                elif hasattr(first_link, "href"):
                    url = str(getattr(first_link, "href", "")).strip()

        if not title:
            logger.warning("Entry missing required title: %r", entry)
            return None

        if not url:
            logger.warning("Entry missing required url: %r", entry)
            return None

        # 3. Extract publication date
        published_parsed = _get_entry_field(entry, "published_parsed", "updated_parsed")
        published: Optional[str] = None

        if published_parsed and isinstance(published_parsed, time.struct_time):
            try:
                published = _format_time_struct(published_parsed)
            except Exception as exc:
                logger.warning("Failed to format time_struct date: %s", exc)
                published = None

        if not published:
            raw_date = _get_entry_field(entry, "published", "updated", "pubDate")
            if raw_date is not None:
                raw_date_str = str(raw_date).strip()
                if raw_date_str:
                    published = raw_date_str

        # 4. Extract and clean summary
        raw_summary = _get_entry_field(entry, "summary", "description")
        if not raw_summary:
            content_list = _get_entry_field(entry, "content")
            if isinstance(content_list, (list, tuple)) and len(content_list) > 0:
                first_content = content_list[0]
                if isinstance(first_content, dict):
                    raw_summary = first_content.get("value")
                elif hasattr(first_content, "value"):
                    raw_summary = getattr(first_content, "value", None)

        summary = _clean_html_text(str(raw_summary)) if raw_summary is not None else None

        return {
            "title": title,
            "url": url,
            "published": published,
            "summary": summary,
        }

    except Exception as exc:
        logger.warning("Unexpected error while parsing RSS entry: %s", exc)
        return None


def parse_entries(entries: Any) -> List[Dict[str, Any]]:
    """Iterate through raw RSS entries and return a list of normalized articles.

    Parameters:
        entries: An iterable of raw feedparser entry objects or dictionaries.

    Returns:
        list: A list of normalized article dictionaries for all valid entries.
    """
    if not entries:
        return []

    normalized_articles: List[Dict[str, Any]] = []

    for entry in entries:
        parsed = parse_entry(entry)
        if parsed is not None:
            normalized_articles.append(parsed)

    return normalized_articles
