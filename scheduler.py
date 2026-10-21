import argparse
import logging
import sys
import time
from typing import Any, Dict, List, Optional, Set

from database import DEFAULT_DB_PATH
import pipeline
import publisher
import research
from sources import SOURCES

logger = logging.getLogger(__name__)


def run_once(
    sources: list,
    llm_provider: Any,
    publisher_provider: Any,
    timeout: int = 10,
    db_path: Optional[str] = None,
    target_language: str = "fa",
    limit: Optional[int] = None,
) -> dict:
    """Run one pass of the pipeline: extract -> research -> publish.

    Parameters:
        sources (list): List of source configuration dicts.
        llm_provider: LLMProvider instance for research stage.
        publisher_provider: PublisherProvider instance for publish stage.
        timeout (int): Network timeout in seconds. Defaults to 10.
        db_path (str, optional): SQLite DB path. None disables DB persistence.
        target_language (str): Target output language code ('fa').
        limit (int, optional): Optional limit on number of extracted articles to process.

    Returns:
        dict: Summary result dictionary.
    """
    if llm_provider is None or publisher_provider is None:
        raise ValueError("llm_provider and publisher_provider must not be None.")

    empty_summary = {
        "extracted": 0,
        "researched": 0,
        "published": 0,
        "research_failures": 0,
        "publish_failures": 0,
        "research_results": [],
        "publish_results": [],
    }

    if not sources:
        return empty_summary

    extracted_articles = pipeline.run_sources(sources, timeout=timeout, db_path=db_path)
    if not extracted_articles:
        return empty_summary

    extracted_count = len(extracted_articles)

    if limit is not None and limit > 0:
        articles_to_process = extracted_articles[:limit]
    else:
        articles_to_process = extracted_articles

    researched_count = 0
    published_count = 0
    research_failures = 0
    publish_failures = 0

    research_results: List[Dict[str, Any]] = []
    publish_results: List[Dict[str, Any]] = []

    for article in articles_to_process:
        researched = None
        try:
            researched = research.research_article(
                article,
                llm_provider,
                target_language=target_language,
            )
        except Exception as exc:
            logger.error("Exception during research stage for article %s: %s", article.get("url"), exc)

        if not researched or not isinstance(researched, dict):
            research_failures += 1
            continue

        researched_count += 1
        research_results.append(researched)

        pub_result = None
        try:
            pub_result = publisher.publish_article(researched, publisher_provider)
        except Exception as exc:
            logger.error("Exception during publish stage for article %s: %s", article.get("url"), exc)

        if isinstance(pub_result, dict):
            publish_results.append(pub_result)
            if pub_result.get("ok") is True:
                published_count += 1
            else:
                publish_failures += 1
        else:
            publish_failures += 1

    return {
        "extracted": extracted_count,
        "researched": researched_count,
        "published": published_count,
        "research_failures": research_failures,
        "publish_failures": publish_failures,
        "research_results": research_results,
        "publish_results": publish_results,
    }


def run_forever(
    interval: int,
    sources: list,
    llm_provider: Any,
    publisher_provider: Any,
    timeout: int = 10,
    db_path: Optional[str] = None,
    target_language: str = "fa",
    limit: Optional[int] = None,
    max_cycles: Optional[int] = None,
) -> None:
    """Loop run_once execution every interval seconds.

    Parameters:
        interval (int): Interval in seconds between cycle starts (>0).
        sources (list): Source dicts.
        llm_provider: LLMProvider.
        publisher_provider: PublisherProvider.
        timeout (int): Timeout seconds.
        db_path (str, optional): Database file path.
        target_language (str): Output language code.
        limit (int, optional): Per-cycle article limit.
        max_cycles (int, optional): Maximum cycle iterations (None for infinite).
    """
    if interval <= 0:
        raise ValueError("Interval must be greater than 0 for run_forever.")

    cycle_count = 0
    while max_cycles is None or cycle_count < max_cycles:
        cycle_count += 1
        logger.info("Starting scheduler cycle %d...", cycle_count)
        try:
            run_once(
                sources=sources,
                llm_provider=llm_provider,
                publisher_provider=publisher_provider,
                timeout=timeout,
                db_path=db_path,
                target_language=target_language,
                limit=limit,
            )
        except Exception as exc:
            logger.error("Error encountered in scheduler cycle %d: %s", cycle_count, exc)

        if max_cycles is not None and cycle_count >= max_cycles:
            break

        time.sleep(interval)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for scheduler.py.

    Parameters:
        argv (list, optional): Command line argument list.

    Returns:
        argparse.Namespace: Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description="AutoNews Pipeline Scheduler")
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Filter sources by name (case-insensitive).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Extraction timeout in seconds.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Path to SQLite DB file. Pass 'none' to disable persistence.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of articles processed per pass.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Interval in seconds for daemon mode (0 = run once).",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Maximum cycle iterations for daemon mode.",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="fa",
        help="Target language for research writing.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose INFO logging.",
    )

    args = parser.parse_args(argv)

    if isinstance(args.db_path, str) and args.db_path.lower() == "none":
        args.db_path = None

    return args


def filter_sources(sources: List[Dict[str, Any]], name_filter: Optional[str]) -> List[Dict[str, Any]]:
    """Filter source configurations by name (case-insensitive)."""
    if not name_filter or not isinstance(name_filter, str) or not name_filter.strip():
        return sources

    clean_filter = name_filter.strip().lower()
    matching = [
        s for s in sources
        if isinstance(s, dict) and s.get("name", "").strip().lower() == clean_filter
    ]

    if not matching:
        logger.warning("No sources matched name filter: %r", name_filter)
        return []

    return matching


def main(argv: Optional[List[str]] = None) -> int:
    """CLI main execution function for scheduler.py.

    Parameters:
        argv (list, optional): Argument list.

    Returns:
        int: Exit status code (0 for success, 1 for error/no sources matched).
    """
    args = parse_args(argv)

    log_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    filtered_sources = filter_sources(SOURCES, args.source)
    if not filtered_sources:
        sys.stderr.write("No sources matched.\n")
        return 1

    try:
        llm = research.get_default_provider()
        pub = publisher.get_default_publisher()

        if args.interval > 0:
            run_forever(
                interval=args.interval,
                sources=filtered_sources,
                llm_provider=llm,
                publisher_provider=pub,
                timeout=args.timeout,
                db_path=args.db_path,
                target_language=args.language,
                limit=args.limit,
                max_cycles=args.max_cycles,
            )
            return 0
        else:
            summary = run_once(
                sources=filtered_sources,
                llm_provider=llm,
                publisher_provider=pub,
                timeout=args.timeout,
                db_path=args.db_path,
                target_language=args.language,
                limit=args.limit,
            )
            print(
                f"Extraction summary: extracted={summary['extracted']}, "
                f"researched={summary['researched']}, published={summary['published']}, "
                f"research_failures={summary['research_failures']}, "
                f"publish_failures={summary['publish_failures']}"
            )
            return 0
    except Exception as exc:
        logger.error("Unhandled error in scheduler main: %s", exc)
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
