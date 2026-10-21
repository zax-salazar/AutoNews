import logging
from typing import Any, Dict, List, Optional, Set
from fetcher import fetch_rss
from parser import parse_entries
from article_extractor import extract_article
from database import (
    DEFAULT_DB_PATH,
    init_db,
    is_article_completed,
    normalize_url,
    record_article,
    mark_article_status,
    save_article_data,
)

logger = logging.getLogger(__name__)


def run_source(
    source: dict,
    timeout: int = 10,
    db_path: Optional[str] = DEFAULT_DB_PATH,
    seen_normalized_urls: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Execute the news collection pipeline for a single news source.

    Steps:
    1. Validate source configuration and URL.
    2. Check enabled state.
    3. Fetch raw RSS feed entries via fetch_rss().
    4. Normalize RSS entries via parse_entries().
    5. Deduplicate entries using normalized URLs and persistent DB status.
    6. Extract full article contents via extract_article().
    7. Record article processing outcomes persistently.

    Parameters:
        source (dict): Source configuration dictionary.
        timeout (int): Timeout in seconds for network requests. Defaults to 10.
        db_path (str, optional): Database file path for persistent tracking.
            Defaults to 'autonews.db'. If None, persistent database tracking is disabled
            while retaining in-memory deduplication for the run.
        seen_normalized_urls (set, optional): Set of normalized URLs processed in current run.

    Returns:
        list: List of normalized articles with full content, or empty list on failure.
    """
    if not isinstance(source, dict):
        logger.warning("Invalid source type provided to run_source: %r", source)
        return []

    source_name = source.get("name") or source.get("url") or "unknown source"

    enabled = source.get("enabled", True)
    if not enabled:
        logger.info("Source disabled, skipping: %s", source_name)
        return []

    url = source.get("url")
    if not url or not isinstance(url, str) or not url.strip():
        logger.warning("Source '%s' is missing or has an empty URL.", source_name)
        return []

    url = url.strip()
    logger.info("Starting processing for source: %s", source_name)

    if db_path:
        init_db(db_path)

    if seen_normalized_urls is None:
        seen_normalized_urls = set()

    try:
        raw_entries = fetch_rss(url, timeout=timeout)
        if not raw_entries:
            logger.warning("No RSS entries fetched for source: %s", source_name)
            return []
        logger.info("Fetched %d raw RSS entries for source: %s", len(raw_entries), source_name)

        parsed_articles = parse_entries(raw_entries)
        if not parsed_articles:
            logger.warning("No valid RSS entries parsed for source: %s", source_name)
            return []
        logger.info("Normalized %d articles for source: %s", len(parsed_articles), source_name)

        extracted_articles: List[Dict[str, Any]] = []

        for entry in parsed_articles:
            raw_url = entry.get("url")
            if not raw_url or not isinstance(raw_url, str) or not raw_url.strip():
                continue

            norm_url = normalize_url(raw_url)
            if not norm_url:
                continue

            # 1. In-run memory deduplication check
            if norm_url in seen_normalized_urls:
                logger.info("Skipping duplicate article in current run: %s", norm_url)
                continue

            # 2. Persistent database completion check
            if db_path and is_article_completed(norm_url, db_path=db_path):
                logger.info("Skipping previously completed article: %s", norm_url)
                seen_normalized_urls.add(norm_url)
                continue

            seen_normalized_urls.add(norm_url)

            # Record article as processing
            if db_path:
                record_article(
                    url=raw_url,
                    normalized_url=norm_url,
                    source_name=source_name,
                    title=entry.get("title"),
                    status="processing",
                    db_path=db_path,
                )

            # Perform content extraction
            extracted = extract_article(entry, timeout=timeout)

            if extracted is not None and isinstance(extracted, dict):
                if db_path:
                    mark_article_status(
                        norm_url,
                        status="completed",
                        title=extracted.get("title"),
                        db_path=db_path,
                    )
                    save_article_data(norm_url, extracted, db_path=db_path)
                extracted_articles.append(extracted)
            else:
                logger.warning("Extraction failed for article URL: %s", raw_url)
                if db_path:
                    mark_article_status(
                        norm_url,
                        status="failed",
                        error_message="Article content extraction returned None",
                        db_path=db_path,
                    )

        logger.info(
            "Successfully extracted content for %d articles from source: %s",
            len(extracted_articles),
            source_name,
        )

        return extracted_articles

    except Exception as exc:
        logger.error("Error encountered while processing source '%s': %s", source_name, exc)
        return []


def run_sources(
    sources: list,
    timeout: int = 10,
    db_path: Optional[str] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Execute the pipeline for multiple news sources and combine results.

    Parameters:
        sources (list): List of source configuration dictionaries.
        timeout (int): Timeout in seconds for network requests. Defaults to 10.
        db_path (str, optional): Database file path for persistent tracking.
            Defaults to 'autonews.db'. If None, persistent database tracking is disabled
            while retaining in-memory deduplication for the run.

    Returns:
        list: Combined list of successfully extracted articles from all sources.
    """
    if not isinstance(sources, (list, tuple)):
        logger.warning("Invalid sources list provided to run_sources: %r", sources)
        return []

    if db_path:
        init_db(db_path)

    seen_normalized_urls: Set[str] = set()
    all_articles: List[Dict[str, Any]] = []

    for source in sources:
        try:
            articles = run_source(
                source,
                timeout=timeout,
                db_path=db_path,
                seen_normalized_urls=seen_normalized_urls,
            )
            if articles:
                all_articles.extend(articles)
        except Exception as exc:
            logger.error("Unhandled error processing source in run_sources: %s", exc)

    return all_articles
