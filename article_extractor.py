import html
import logging
import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup, Tag, Comment
import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "AutoNews/1.0"
MIN_CONTENT_LENGTH = 100

# Non-content tags to strip before extraction
UNWANTED_TAGS = [
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "iframe",
    "svg",
]

# Patterns for elements to decompose (e.g., ads, comments, navigation)
UNWANTED_CLASSES_IDS = re.compile(
    r"(?:^|[\-_])(?:ad|ads|advertisement|banner|sidebar|comments|related|social|share|nav|menu|footer|header)(?:[\-_]|$)",
    re.IGNORECASE,
)

# Specific article container patterns (conservative matching)
ARTICLE_CONTAINER_PATTERNS = re.compile(
    r"(?:^|[\-_])(?:article\-body|article\-content|post\-content|entry\-content|story\-body|main\-content|article\-text)(?:[\-_]|$)",
    re.IGNORECASE,
)

# Semantic block-level HTML tags for text extraction
LEAF_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "dt", "dd"}


def fetch_article_html(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch HTML content of an article from a URL.

    Parameters:
        url (str): The URL of the article.
        timeout (int): HTTP request timeout in seconds. Defaults to 10.

    Returns:
        str | None: The raw HTML content string, or None if fetching fails.
    """
    if not url or not isinstance(url, str) or not url.strip():
        logger.warning("Invalid or empty URL provided to fetch_article_html: %r", url)
        return None

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.error("Failed to fetch article from %s: %s", url, exc)
        return None


def _clean_soup(soup: BeautifulSoup) -> None:
    """Decompose non-content tags, comments, and obvious ad/nav containers in place."""
    # Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove unwanted tags
    for tag in soup.find_all(UNWANTED_TAGS):
        tag.decompose()

    # Remove elements with unwanted classes or IDs
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        classes = tag.get("class")
        class_str = " ".join(classes) if isinstance(classes, list) else (classes or "")
        tag_id = tag.get("id") or ""

        if UNWANTED_CLASSES_IDS.search(class_str) or UNWANTED_CLASSES_IDS.search(tag_id):
            # Avoid decomposing main article containers or body
            if tag.name not in ("body", "main", "article"):
                tag.decompose()


def _find_article_container(soup: BeautifulSoup) -> Optional[Tag]:
    """Find the best article container using prioritized heuristics.

    Priority:
    1. Explicit <article> tag or tags with specific article class/ID patterns.
    2. <main> tag.
    3. <body> tag.
    """
    # 1. Look for <article> tag
    article_tag = soup.find("article")
    if article_tag and isinstance(article_tag, Tag):
        return article_tag

    # 1b. Search for explicit article classes/IDs
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        classes = tag.get("class")
        class_str = " ".join(classes) if isinstance(classes, list) else (classes or "")
        tag_id = tag.get("id") or ""

        if ARTICLE_CONTAINER_PATTERNS.search(class_str) or ARTICLE_CONTAINER_PATTERNS.search(tag_id):
            return tag

    # 2. Fall back to <main>
    main_tag = soup.find("main")
    if main_tag and isinstance(main_tag, Tag):
        return main_tag

    # 3. Fall back to <body>
    body_tag = soup.body
    if body_tag and isinstance(body_tag, Tag):
        return body_tag

    return None


def _format_container_text(container: Tag) -> str:
    """Extract clean text from a container, preserving paragraph breaks."""
    paragraphs: List[str] = []

    # Find block elements in container
    candidate_blocks = container.find_all(LEAF_BLOCK_TAGS)

    # Filter to leaf block tags (block tags that do not contain child block tags)
    leaf_blocks: List[Tag] = []
    for block in candidate_blocks:
        if isinstance(block, Tag):
            has_child_block = any(
                isinstance(child, Tag) and child.name in LEAF_BLOCK_TAGS
                for child in block.find_all(True)
            )
            if not has_child_block:
                leaf_blocks.append(block)

    if leaf_blocks:
        for block in leaf_blocks:
            text = block.get_text(" ", strip=True)
            cleaned_text = html.unescape(re.sub(r"\s+", " ", text).strip())
            if cleaned_text:
                if not paragraphs or paragraphs[-1] != cleaned_text:
                    paragraphs.append(cleaned_text)

    # Fall back if no leaf blocks were found or if they produced no text
    if not paragraphs:
        raw_text = container.get_text("\n")
        for line in raw_text.splitlines():
            cleaned_line = html.unescape(re.sub(r"\s+", " ", line).strip())
            if cleaned_line:
                if not paragraphs or paragraphs[-1] != cleaned_line:
                    paragraphs.append(cleaned_line)

    return "\n\n".join(paragraphs)


def extract_article_content(html_content: str) -> Optional[str]:
    """Extract main article text content from HTML string.

    Parameters:
        html_content (str): The raw HTML string.

    Returns:
        str | None: Cleaned article text with paragraph separation,
            or None if extraction fails or content length is below threshold.
    """
    if not html_content or not isinstance(html_content, str) or not html_content.strip():
        logger.warning("Empty or invalid HTML content passed to extract_article_content.")
        return None

    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception as exc:
        logger.error("Failed to parse HTML with BeautifulSoup: %s", exc)
        return None

    _clean_soup(soup)

    container = _find_article_container(soup)
    if not container:
        logger.warning("No suitable article container found in HTML.")
        return None

    extracted_text = _format_container_text(container)

    # Calculate non-whitespace character count
    non_ws_count = len(re.sub(r"\s+", "", extracted_text))
    if non_ws_count < MIN_CONTENT_LENGTH:
        logger.warning(
            "Extracted content length (%d non-ws chars) is below minimum threshold (%d).",
            non_ws_count,
            MIN_CONTENT_LENGTH,
        )
        return None

    return extracted_text


def extract_article(article: dict, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Fetch and extract article text for a single article dictionary.

    Parameters:
        article (dict): Article metadata dictionary (must contain 'url').
        timeout (int): HTTP timeout in seconds.

    Returns:
        dict | None: A copy of the input dictionary with an added 'content' field,
            or None if fetching/extraction fails.
    """
    if not isinstance(article, dict):
        logger.warning("Invalid article type passed to extract_article: %r", article)
        return None

    url = article.get("url")
    if not url or not isinstance(url, str) or not url.strip():
        logger.warning("Article dictionary missing or has empty 'url': %r", article)
        return None

    html_content = fetch_article_html(url, timeout=timeout)
    if not html_content:
        logger.warning("Failed to fetch HTML for article URL: %s", url)
        return None

    content = extract_article_content(html_content)
    if not content:
        logger.warning("Failed to extract content for article URL: %s", url)
        return None

    # Return a copy with new 'content' field
    result = dict(article)
    result["content"] = content
    return result


def extract_articles(articles: list, timeout: int = 10) -> List[Dict[str, Any]]:
    """Batch-extract articles from a list of article dictionaries.

    Parameters:
        articles (list): List of article dictionaries.
        timeout (int): HTTP timeout in seconds per request.

    Returns:
        list: List of successfully extracted article dictionaries.
    """
    if not isinstance(articles, (list, tuple)):
        logger.warning("Invalid articles list passed to extract_articles: %r", articles)
        return []

    results: List[Dict[str, Any]] = []
    for item in articles:
        extracted = extract_article(item, timeout=timeout)
        if extracted is not None:
            results.append(extracted)

    return results
