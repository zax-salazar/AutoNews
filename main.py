import argparse
import logging
import sys
from typing import Any, Dict, List, Optional
from database import DEFAULT_DB_PATH
from pipeline import run_sources
from sources import SOURCES

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for AutoNews main entry point.

    Parameters:
        argv (list, optional): Argument string list. Defaults to sys.argv[1:].

    Returns:
        argparse.Namespace: Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description="AutoNews Automation CLI")
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Path to SQLite database file. Pass 'none' to disable persistence.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout in seconds for network requests.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Filter sources by name (case-insensitive).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force disabling persistent database writes.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose INFO logging output.",
    )

    args = parser.parse_args(argv)

    if isinstance(args.db_path, str) and args.db_path.lower() == "none":
        args.db_path = None

    return args


def filter_sources(sources: List[Dict[str, Any]], name_filter: Optional[str]) -> List[Dict[str, Any]]:
    """Filter source configurations by name (case-insensitive).

    Parameters:
        sources (list): List of source configuration dicts.
        name_filter (str, optional): Name string filter.

    Returns:
        list: Filtered source configurations.
    """
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


def summarize(articles: Optional[List[Dict[str, Any]]]) -> str:
    """Format a human-readable CLI summary of processed articles.

    Parameters:
        articles (list, optional): List of processed article dictionaries.

    Returns:
        str: Summary text output.
    """
    if not articles:
        return "No articles processed."

    lines = [f"Processed {len(articles)} article(s):"]
    for art in articles:
        title = art.get("title") or "(no title)"
        url = art.get("url") or "(no url)"
        lines.append(f"  - {title}  ({url})")

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI main execution function for AutoNews.

    Parameters:
        argv (list, optional): Argument list. Defaults to sys.argv[1:].

    Returns:
        int: Exit status code (0 for success, 1 for error/no sources matched).
    """
    args = parse_args(argv)

    log_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.dry_run:
        effective_db_path = None
        sys.stderr.write("WARNING: --dry-run set; persistent database disabled.\n")
    else:
        effective_db_path = args.db_path

    filtered_sources = filter_sources(SOURCES, args.source)
    if not filtered_sources:
        sys.stderr.write("No sources matched.\n")
        return 1

    try:
        articles = run_sources(
            filtered_sources,
            timeout=args.timeout,
            db_path=effective_db_path,
        )
        print(summarize(articles))
        return 0
    except Exception as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
