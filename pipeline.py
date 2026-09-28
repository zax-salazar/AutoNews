import logging
from typing import Any, Dict, List
from fetcher import fetch_rss
from parser import parse_entries
from article_extractor import extract_articles

logger = logging.getLogger(__name__)


def run_source(source: dict, timeout: int = 10) -> List[Dict[str, Any]]:
    """Execute the news collection pipeline for a single news source.

    Steps:
    1. Validate source configuration and URL.
    2. Check enabled state.
    3. Fetch raw RSS feed entries via fetch_rss().
    4. Normalize RSS entries via parse_entries().
    5. Extract full article contents via extract_articles().

    Parameters:
        source (dict): Source configuration dictionary.
        timeout (int): Timeout in seconds for network requests. Defaults to 10.

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

        extracted_articles = extract_articles(parsed_articles, timeout=timeout)
        logger.info(
            "Successfully extracted content for %d articles from source: %s",
            len(extracted_articles),
            source_name,
        )

        return extracted_articles

    except Exception as exc:
        logger.error("Error encountered while processing source '%s': %s", source_name, exc)
        return []


def run_sources(sources: list, timeout: int = 10) -> List[Dict[str, Any]]:
    """Execute the pipeline for multiple news sources and combine results.

    Parameters:
        sources (list): List of source configuration dictionaries.
        timeout (int): Timeout in seconds for network requests. Defaults to 10.

    Returns:
        list: Combined list of successfully extracted articles from all sources.
    """
    if not isinstance(sources, (list, tuple)):
        logger.warning("Invalid sources list provided to run_sources: %r", sources)
        return []

    all_articles: List[Dict[str, Any]] = []

    for source in sources:
        try:
            articles = run_source(source, timeout=timeout)
            if articles:
                all_articles.extend(articles)
        except Exception as exc:
            logger.error("Unhandled error processing source in run_sources: %s", exc)

    return all_articles
