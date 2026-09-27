import logging
import feedparser
import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "AutoNews/1.0"


def fetch_rss(url: str, timeout: int = 10) -> list:
    """Fetch and parse an RSS/Atom feed from a given URL.

    Parameters:
        url (str): The RSS/Atom feed URL to fetch.
        timeout (int): Maximum time in seconds to wait for the HTTP response.
            Defaults to 10 seconds.

    Returns:
        list: A list of raw feed entry objects returned by feedparser, or an
            empty list ([]) if fetching/parsing fails or if no entries exist.

    Failure Handling:
        - Network errors, timeouts, invalid URLs, or HTTP errors are caught,
          logged, and result in an empty list ([]) being returned.
        - Malformed feeds (where feedparser sets the bozo flag):
            - If entries are still successfully extracted, a warning is logged
              and the extracted entries are returned.
            - If no usable entries are available, a warning/error is logged
              and an empty list ([]) is returned.
    """
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Failed to fetch RSS feed from %s: %s", url, exc)
        return []

    try:
        parsed_feed = feedparser.parse(response.content)
    except Exception as exc:
        logger.error("Failed to parse RSS feed content from %s: %s", url, exc)
        return []

    entries = getattr(parsed_feed, "entries", [])
    bozo = getattr(parsed_feed, "bozo", 0)

    if bozo == 1:
        bozo_exception = getattr(parsed_feed, "bozo_exception", "Unknown XML parsing error")
        if entries:
            logger.warning(
                "Malformed feed detected at %s (%s), but %d entries were recovered.",
                url,
                bozo_exception,
                len(entries),
            )
            return entries
        else:
            logger.warning(
                "Malformed feed detected at %s (%s) and no usable entries were found.",
                url,
                bozo_exception,
            )
            return []

    return entries
