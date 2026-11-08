import html
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
from bs4 import BeautifulSoup, Tag, Comment
import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "AutoNews/1.0"
MIN_CONTENT_LENGTH = 100
MAX_IMAGES_PER_ARTICLE = 20

# Patterns for elements/classes/ids to decompose (e.g., ads, comments, social shares, widgets)
UNWANTED_CLASSES_IDS = re.compile(
    r"(?:^|[\-_])(?:ad|ads|advertisement|banner|sidebar|comments|related|social|share|nav|menu|footer|cookie|consent|newsletter|recommendation|widget|recirculation|outbrain|taboola|sponsored|polopoly)(?:[\-_]|$)",
    re.IGNORECASE,
)

# Specific article container patterns (conservative matching)
ARTICLE_CONTAINER_PATTERNS = re.compile(
    r"(?:^|[\-_])(?:article\-body|article\-content|post\-content|entry\-content|story\-body|main\-content|article\-text)(?:[\-_]|$)",
    re.IGNORECASE,
)

# Subtitle / dek / standfirst container patterns
DEK_PATTERNS = re.compile(
    r"(?:^|[\-_])(?:dek|subtitle|standfirst|lead|summary|excerpt)(?:[\-_]|$)",
    re.IGNORECASE,
)

# Patterns for filtering unwanted images (tracking pixels, avatars, icons, logos, ads)
UNWANTED_IMAGE_PATTERNS = re.compile(
    r"(?:pixel|spacer|blank|tracking|avatar|logo|icon|social|button|banner|analytics|1x1|(?:^|[\-_/\.])ads?(?:[\-_/\.]|$))",
    re.IGNORECASE,
)

# Video provider patterns
VIDEO_URL_PATTERNS = re.compile(
    r"(?:youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|twitch\.tv|player\.|video)",
    re.IGNORECASE,
)

# Block-level tags for DOM traversal
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "figure", "img", "video", "iframe", "blockquote", "li"}


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


def _clean_text(text: Optional[str]) -> Optional[str]:
    """Strip whitespace, unescape HTML entities, and collapse internal spaces."""
    if not text:
        return None
    cleaned = html.unescape(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else None


def _extract_title(soup: BeautifulSoup, container: Optional[Tag]) -> Tuple[Optional[str], bool]:
    """Extract page/article title.

    Returns:
        tuple: (title_str | None, is_high_confidence_h1: bool)
    """
    # 1. High-confidence H1 inside article container
    if container:
        h1 = container.find("h1")
        if h1 and isinstance(h1, Tag):
            h1_text = _clean_text(h1.get_text())
            if h1_text and len(h1_text) >= 3:
                return h1_text, True

    # 1b. High-confidence H1 globally in soup
    global_h1 = soup.find("h1")
    if global_h1 and isinstance(global_h1, Tag):
        global_h1_text = _clean_text(global_h1.get_text())
        if global_h1_text and len(global_h1_text) >= 3:
            return global_h1_text, True

    # 2. Open Graph or Twitter title meta tags
    og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og_title and isinstance(og_title, Tag):
        meta_content = _clean_text(og_title.get("content"))
        if meta_content:
            return meta_content, False

    # 3. HTML <title> tag
    title_tag = soup.find("title")
    if title_tag and isinstance(title_tag, Tag):
        page_title = _clean_text(title_tag.get_text())
        if page_title:
            return page_title, False

    return None, False


def _extract_description(
    soup: BeautifulSoup, container: Optional[Tag], fallback_summary: Optional[str] = None
) -> Optional[str]:
    """Extract article description/subtitle/introduction."""
    # 1. Dek / Subtitle / Standfirst inside container
    if container:
        dek_tag = container.find(
            lambda tag: isinstance(tag, Tag)
            and tag.attrs is not None
            and tag.name in ("p", "div", "header", "h2", "span")
            and (
                DEK_PATTERNS.search(" ".join(tag.get("class", [])) if isinstance(tag.get("class"), list) else tag.get("class", ""))
                or DEK_PATTERNS.search(tag.get("id") or "")
            )
        )
        if dek_tag and isinstance(dek_tag, Tag):
            dek_text = _clean_text(dek_tag.get_text())
            if dek_text:
                return dek_text

    # 2. Meta tags (og:description, description, twitter:description)
    meta_desc = (
        soup.find("meta", property="og:description")
        or soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", attrs={"name": "twitter:description"})
    )
    if meta_desc and isinstance(meta_desc, Tag):
        content = _clean_text(meta_desc.get("content"))
        if content:
            return content

    # 3. Fallback to RSS summary if available
    if fallback_summary:
        cleaned_summary = _clean_text(fallback_summary)
        if cleaned_summary:
            return cleaned_summary

    return None


def _parse_srcset(srcset_val: str) -> List[Tuple[float, str]]:
    """Parse srcset string into a list of (score, url) tuples sorted by score ascending."""
    if not srcset_val or not isinstance(srcset_val, str):
        return []

    entries: List[Tuple[float, str]] = []
    # Split on commas that separate candidate entries
    raw_candidates = [c.strip() for c in srcset_val.split(",") if c.strip()]
    for candidate in raw_candidates:
        tokens = candidate.split()
        if not tokens:
            continue
        c_url = tokens[0].strip()
        if c_url.startswith("data:"):
            continue

        score = 0.0
        if len(tokens) > 1:
            desc = tokens[1].strip().lower()
            if desc.endswith("w"):
                try:
                    score = float(desc[:-1])
                except ValueError:
                    score = 0.0
            elif desc.endswith("x"):
                try:
                    score = float(desc[:-1]) * 1000.0
                except ValueError:
                    score = 0.0

        entries.append((score, c_url))

    return entries


def _resolve_image_url(img_tag: Tag) -> Optional[str]:
    """Extract best image URL for an <img> element picking a single final URL:
    Priority:
      1. largest srcset entry (from img srcset/data-srcset or parent <picture> <source>)
      2. parent <picture> <source> src/data-src
      3. img src/data-src/data-lazy-src/data-original
    """
    if img_tag.attrs is None:
        return None

    parent = img_tag.parent
    picture_sources = parent.find_all("source") if (parent and isinstance(parent, Tag) and parent.name == "picture") else []

    # 1. Collect srcset candidates from parent <picture> <source> tags
    picture_srcset_candidates: List[Tuple[float, str]] = []
    for source in picture_sources:
        if isinstance(source, Tag) and source.attrs:
            for attr in ("srcset", "data-srcset"):
                val = source.get(attr)
                if val and isinstance(val, str):
                    picture_srcset_candidates.extend(_parse_srcset(val))

    # 2. Collect direct img srcset candidates
    img_srcset_candidates: List[Tuple[float, str]] = []
    for srcset_attr in ("srcset", "data-srcset"):
        srcset = img_tag.get(srcset_attr)
        if srcset and isinstance(srcset, str):
            img_srcset_candidates.extend(_parse_srcset(srcset))

    # Check srcset candidates: largest by descriptor
    if picture_srcset_candidates:
        picture_srcset_candidates.sort(key=lambda x: x[0])
        return picture_srcset_candidates[-1][1]

    if img_srcset_candidates:
        img_srcset_candidates.sort(key=lambda x: x[0])
        return img_srcset_candidates[-1][1]

    # 3. Check parent <picture> <source> src / data-src
    for source in picture_sources:
        if isinstance(source, Tag) and source.attrs:
            for attr in ("src", "data-src"):
                val = source.get(attr)
                if val and isinstance(val, str) and not val.strip().startswith("data:"):
                    return val.strip()

    # 4. Check direct img attributes
    for attr in ("data-src", "data-lazy-src", "data-original", "src"):
        val = img_tag.get(attr)
        if val and isinstance(val, str) and not val.strip().startswith("data:"):
            return val.strip()

    return None


SIZE_SUFFIX_PATTERN = re.compile(
    r"-\d{2,5}-\d{1,3}\.(jpg|jpeg|png|webp|gif)$",
    re.IGNORECASE,
)


def _normalize_image_url(url: str) -> str:
    """Strip size/quality variants for dedup purposes only.
    - Remove trailing "-NNN-NN" segments before the file extension
      (e.g. "-1200-80", "-1920-80", "-2342-80").
    - Remove query strings of the form ?w=NNN, ?width=NNN, ?q=NN.
    - Return the normalized URL. The ORIGINAL url is still used
      for the block; this normalized form is only the dedup key.
    """
    if not url or not isinstance(url, str):
        return ""

    url_str = url.strip()
    try:
        parsed = urllib.parse.urlsplit(url_str)
    except Exception:
        return url_str.lower()

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path

    # Remove trailing suffix matching regex -\d{2,5}-\d{1,3}\.(jpg|jpeg|png|webp|gif)$ from path
    match = SIZE_SUFFIX_PATTERN.search(path)
    if match:
        ext = match.group(1)
        path = path[:match.start()] + "." + ext

    # Strip query params w, width, q, quality
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_query = [
        (k, v) for k, v in query_params
        if k.lower() not in ("w", "width", "q", "quality")
    ]
    new_query = urllib.parse.urlencode(filtered_query)

    return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))


IMAGE_NOISE_SUBSTRINGS = (
    "sprite", "icon", "logo", "avatar", "gravatar",
    "1x1", "pixel.gif", "spacer", "tracking"
)

IMAGE_NOISE_ALTS = {"", "image", "photo", "picture", "thumbnail", "icon", "logo"}


def _is_valid_image(img_tag: Tag, url: Optional[str]) -> bool:
    """Validate whether an image is a genuine article image rather than logo/icon/ad."""
    if not url or not isinstance(url, str):
        return False

    url_str = url.strip()
    if url_str.startswith("data:"):
        return False

    if len(url_str) < 20:
        return False

    clean_path = url_str.split("?")[0].split("#")[0].lower()
    if clean_path.endswith(".svg"):
        return False

    url_lower = url_str.lower()
    if any(sub in url_lower for sub in IMAGE_NOISE_SUBSTRINGS):
        return False

    if img_tag.attrs is not None:
        classes = img_tag.get("class")
        class_str = " ".join(classes) if isinstance(classes, list) else (classes or "")
        tag_id = img_tag.get("id") or ""
        if UNWANTED_IMAGE_PATTERNS.search(class_str) or UNWANTED_IMAGE_PATTERNS.search(tag_id):
            return False

        raw_alt = img_tag.get("alt")
        alt_text = _clean_text(raw_alt) or ""
        alt_lower = alt_text.lower()

        # Check dimensions
        width_val = None
        height_val = None
        if "width" in img_tag.attrs:
            try:
                width_val = float(re.sub(r"[^\d.]", "", str(img_tag.get("width"))))
            except (ValueError, TypeError):
                pass
        if "height" in img_tag.attrs:
            try:
                height_val = float(re.sub(r"[^\d.]", "", str(img_tag.get("height"))))
            except (ValueError, TypeError):
                pass

        if width_val is not None and width_val <= 1:
            return False
        if height_val is not None and height_val <= 1:
            return False

        # Skip images where alt matches known noise values AND width/height attributes (if present) are <= 64 pixels.
        if alt_lower in IMAGE_NOISE_ALTS:
            is_small = False
            if width_val is not None and width_val <= 64:
                is_small = True
            if height_val is not None and height_val <= 64:
                is_small = True
            if is_small:
                return False

    return True


def _extract_image_block(img_tag: Tag, parent_figure: Optional[Tag] = None) -> Optional[Dict[str, Any]]:
    """Extract structured image block dictionary."""
    url = _resolve_image_url(img_tag)
    if not _is_valid_image(img_tag, url):
        return None

    alt = _clean_text(img_tag.get("alt")) if img_tag.attrs else None

    caption = None
    if parent_figure and parent_figure.attrs is not None:
        figcaption = parent_figure.find("figcaption")
        if figcaption and isinstance(figcaption, Tag):
            caption = _clean_text(figcaption.get_text())

    if not caption and img_tag.attrs is not None:
        caption = _clean_text(img_tag.get("title"))

    return {
        "type": "image",
        "url": url,
        "alt": alt,
        "caption": caption,
    }


def _extract_video_block(tag: Tag) -> Optional[Dict[str, Any]]:
    """Extract structured video block dictionary from <video> or <iframe> tag."""
    if tag.attrs is None:
        return None

    video_url = None
    title = None

    if tag.name == "video":
        src = tag.get("src")
        if not src:
            source = tag.find("source")
            if source and isinstance(source, Tag) and source.attrs:
                src = source.get("src")
        if src and isinstance(src, str):
            video_url = src.strip()
        title = _clean_text(tag.get("title") or tag.get("aria-label"))

    elif tag.name == "iframe":
        src = tag.get("src") or tag.get("data-src")
        if src and isinstance(src, str):
            src = src.strip()
            if VIDEO_URL_PATTERNS.search(src):
                video_url = src
                title = _clean_text(tag.get("title") or tag.get("aria-label"))

    if not video_url:
        return None

    return {
        "type": "video",
        "url": video_url,
        "title": title,
    }


def _find_article_container(soup: BeautifulSoup) -> Optional[Tag]:
    """Find the best article container using prioritized heuristics.

    Priority:
    1. #article-body element
    2. .text-copy.bodyCopy container
    3. <article> tag
    4. <main> tag
    5. ARTICLE_CONTAINER_PATTERNS
    6. <body> tag
    """
    # 1. #article-body
    article_body = soup.find(id="article-body")
    if article_body and isinstance(article_body, Tag):
        return article_body

    # 2. .text-copy.bodyCopy
    body_copy = soup.find(
        lambda tag: isinstance(tag, Tag)
        and tag.attrs is not None
        and tag.get("class")
        and "text-copy" in tag.get("class")
        and any("bodyCopy" in c for c in tag.get("class"))
    )
    if body_copy and isinstance(body_copy, Tag):
        return body_copy

    # 3. <article>
    article_tag = soup.find("article")
    if article_tag and isinstance(article_tag, Tag):
        return article_tag

    # 4. <main>
    main_tag = soup.find("main")
    if main_tag and isinstance(main_tag, Tag):
        return main_tag

    # 5. ARTICLE_CONTAINER_PATTERNS
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag) or tag.attrs is None:
            continue
        classes = tag.get("class")
        class_str = " ".join(classes) if isinstance(classes, list) else (classes or "")
        tag_id = tag.get("id") or ""

        if ARTICLE_CONTAINER_PATTERNS.search(class_str) or ARTICLE_CONTAINER_PATTERNS.search(tag_id):
            return tag

    # 6. <body>
    body_tag = soup.body
    if body_tag and isinstance(body_tag, Tag):
        return body_tag

    return None


def _clean_container(container: Tag) -> None:
    """Decompose non-content elements inside container while preserving article text structures."""
    # Remove HTML comments
    for comment in container.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Decompose unwanted tag types
    for tag in container.find_all(["script", "style", "noscript", "nav", "footer", "aside", "form", "svg"]):
        tag.decompose()

    # Decompose header tags only if not containing article title/heading
    for header_tag in container.find_all("header"):
        if not header_tag.find(["h1", "h2"]):
            header_tag.decompose()

    # Decompose unwanted containers by class/id
    for tag in list(container.find_all(True)):
        if not isinstance(tag, Tag) or tag.attrs is None:
            continue
        classes = tag.get("class")
        class_str = " ".join(classes) if isinstance(classes, list) else (classes or "")
        tag_id = tag.get("id") or ""

        if UNWANTED_CLASSES_IDS.search(class_str) or UNWANTED_CLASSES_IDS.search(tag_id):
            if tag is not container and tag.name not in ("body", "main", "article") and tag_id != "article-body":
                tag.decompose()


def _extract_blocks(container: Tag) -> List[Dict[str, Any]]:
    """Extract structured, DOM-ordered blocks (paragraphs, headings, images, videos) from container."""
    blocks: List[Dict[str, Any]] = []
    processed_elements = set()
    seen_normalized_media_urls = set()
    image_count = 0

    elements = container.find_all(BLOCK_TAGS)

    for element in elements:
        if not isinstance(element, Tag) or element.attrs is None:
            continue

        if element in processed_elements:
            continue

        ancestors = list(element.parents)
        if any(anc in processed_elements for anc in ancestors):
            continue

        # Confine check: Ensure element is container or descendant of container
        if element != container and container not in ancestors:
            continue

        tag_name = element.name

        # 1. Headings
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            heading_text = _clean_text(element.get_text())
            if heading_text:
                blocks.append({"type": "heading", "level": level, "content": heading_text})
            processed_elements.add(element)

        # 2. Figure containers
        elif tag_name == "figure":
            img = element.find("img")
            if img and isinstance(img, Tag) and img.attrs is not None:
                if image_count < MAX_IMAGES_PER_ARTICLE:
                    img_block = _extract_image_block(img, parent_figure=element)
                    if img_block:
                        norm_key = _normalize_image_url(img_block["url"])
                        if norm_key not in seen_normalized_media_urls:
                            seen_normalized_media_urls.add(norm_key)
                            blocks.append(img_block)
                            image_count += 1
                processed_elements.add(img)
            else:
                video = element.find(["video", "iframe"])
                if video and isinstance(video, Tag) and video.attrs is not None:
                    video_block = _extract_video_block(video)
                    if video_block and video_block["url"] not in seen_normalized_media_urls:
                        seen_normalized_media_urls.add(video_block["url"])
                        blocks.append(video_block)
                    processed_elements.add(video)

            processed_elements.add(element)
            for child in element.find_all(True):
                processed_elements.add(child)

        # 3. Standalone Image
        elif tag_name == "img":
            if image_count < MAX_IMAGES_PER_ARTICLE:
                parent_figure = element.find_parent("figure")
                img_block = _extract_image_block(element, parent_figure=parent_figure)
                if img_block:
                    norm_key = _normalize_image_url(img_block["url"])
                    if norm_key not in seen_normalized_media_urls:
                        seen_normalized_media_urls.add(norm_key)
                        blocks.append(img_block)
                        image_count += 1
            processed_elements.add(element)
            parent_figure = element.find_parent("figure")
            if parent_figure:
                processed_elements.add(parent_figure)
                for child in parent_figure.find_all(True):
                    processed_elements.add(child)

        # 4. Standalone Video or Iframe
        elif tag_name in ("video", "iframe"):
            video_block = _extract_video_block(element)
            if video_block and video_block["url"] not in seen_normalized_media_urls:
                seen_normalized_media_urls.add(video_block["url"])
                blocks.append(video_block)
            processed_elements.add(element)

        # 5. Paragraphs, Blockquotes, List items (represented as paragraph blocks)
        elif tag_name in ("p", "blockquote", "li"):
            nested_imgs = element.find_all("img")
            nested_videos = element.find_all(["video", "iframe"])

            p_text = _clean_text(element.get_text())
            if p_text:
                if not blocks or blocks[-1].get("content") != p_text:
                    blocks.append({"type": "paragraph", "content": p_text})

            processed_elements.add(element)

            for img in nested_imgs:
                if isinstance(img, Tag) and img.attrs is not None and img not in processed_elements:
                    if image_count < MAX_IMAGES_PER_ARTICLE:
                        parent_fig = img.find_parent("figure")
                        img_block = _extract_image_block(img, parent_figure=parent_fig)
                        if img_block:
                            norm_key = _normalize_image_url(img_block["url"])
                            if norm_key not in seen_normalized_media_urls:
                                seen_normalized_media_urls.add(norm_key)
                                blocks.append(img_block)
                                image_count += 1
                    processed_elements.add(img)

            for vid in nested_videos:
                if isinstance(vid, Tag) and vid.attrs is not None and vid not in processed_elements:
                    video_block = _extract_video_block(vid)
                    if video_block and video_block["url"] not in seen_normalized_media_urls:
                        seen_normalized_media_urls.add(video_block["url"])
                        blocks.append(video_block)
                    processed_elements.add(vid)

    if not blocks:
        raw_text = container.get_text("\n")
        for line in raw_text.splitlines():
            cleaned_line = _clean_text(line)
            if cleaned_line:
                blocks.append({"type": "paragraph", "content": cleaned_line})

    return blocks


def extract_article_data(html_content: str, fallback_summary: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Extract structured article data (title, description, content, blocks) from HTML string.

    Parameters:
        html_content (str): The raw HTML string.
        fallback_summary (str, optional): RSS summary to use as description fallback.

    Returns:
        dict | None: Dictionary with 'title', 'description', 'content', and 'blocks',
            or None if extraction fails or content length is below threshold.
    """
    if not html_content or not isinstance(html_content, str) or not html_content.strip():
        logger.warning("Empty or invalid HTML content passed to extract_article_data.")
        return None

    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception as exc:
        logger.error("Failed to parse HTML with BeautifulSoup: %s", exc)
        return None

    container = _find_article_container(soup)
    if not container:
        logger.warning("No suitable article container found in HTML.")
        return None

    title, is_high_confidence_h1 = _extract_title(soup, container)
    description = _extract_description(soup, container, fallback_summary=fallback_summary)

    _clean_container(container)

    blocks = _extract_blocks(container)

    # Feature-image fallback if no image blocks were extracted
    has_image = any(b.get("type") == "image" for b in blocks)
    if not has_image:
        og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og_img and isinstance(og_img, Tag):
            content = og_img.get("content")
            if content and isinstance(content, str) and content.strip():
                url_str = content.strip()
                if not url_str.startswith("data:") and not url_str.lower().endswith(".svg") and len(url_str) >= 20:
                    blocks.append({
                        "type": "image",
                        "url": url_str,
                        "alt": "",
                        "caption": "",
                    })

    text_parts = [
        block["content"]
        for block in blocks
        if block["type"] in ("paragraph", "heading") and "content" in block
    ]
    content_text = "\n\n".join(text_parts)

    non_ws_count = len(re.sub(r"\s+", "", content_text))
    if non_ws_count < MIN_CONTENT_LENGTH:
        logger.warning(
            "Extracted content length (%d non-ws chars) is below minimum threshold (%d).",
            non_ws_count,
            MIN_CONTENT_LENGTH,
        )
        return None

    return {
        "title": title,
        "is_high_confidence_h1": is_high_confidence_h1,
        "description": description,
        "content": content_text,
        "blocks": blocks,
    }


def extract_article_content(html_content: str) -> Optional[str]:
    """Extract main article text content from HTML string (backward compatible function).

    Parameters:
        html_content (str): The raw HTML string.

    Returns:
        str | None: Cleaned article text with paragraph separation,
            or None if extraction fails or content length is below threshold.
    """
    data = extract_article_data(html_content)
    return data["content"] if data else None


def extract_article(article: dict, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """Fetch and extract structured article data for a single article dictionary.

    Parameters:
        article (dict): Article metadata dictionary (must contain 'url').
        timeout (int): HTTP timeout in seconds.

    Returns:
        dict | None: A copy of the input dictionary updated with 'content', 'blocks',
            'description', and high-confidence 'title', or None if extraction fails.
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

    data = extract_article_data(html_content, fallback_summary=article.get("summary"))
    if not data:
        logger.warning("Failed to extract content for article URL: %s", url)
        return None

    result = dict(article)
    result["content"] = data["content"]
    result["blocks"] = data["blocks"]
    result["description"] = data["description"]

    if data["is_high_confidence_h1"] and data["title"]:
        result["title"] = data["title"]

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
