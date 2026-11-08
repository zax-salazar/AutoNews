from abc import ABC, abstractmethod
import json
import logging
import os
import re
import time as _time
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

BASE_RETRY_SECONDS = 5.0


def _backoff(attempt: int, retry_after_header) -> float:
    """Sleep and return the number of seconds slept.
    - If retry_after_header is a valid non-negative number of seconds,
      sleep min(float(value), 60.0).
    - Otherwise sleep BASE_RETRY_SECONDS * (2 ** attempt), capped at 40.
    Never raises.
    """
    if retry_after_header is not None:
        try:
            secs = float(retry_after_header)
            if secs >= 0:
                secs = min(secs, 60.0)
                _time.sleep(secs)
                return secs
        except (TypeError, ValueError):
            pass
    secs = min(BASE_RETRY_SECONDS * (2 ** attempt), 40.0)
    _time.sleep(secs)
    return secs


class LLMProvider(ABC):
    """Abstract base class for LLM text generation providers."""

    @abstractmethod
    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate text from prompt.

        Parameters:
            prompt (str): User prompt text.
            system (str, optional): System instruction prompt text.

        Returns:
            str: Model response text.
        """
        pass


class GeminiProvider(LLMProvider):
    """Google Gemini API LLM provider implementation."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout: int = 60,
        max_retries: int = 3,
    ):
        if not api_key:
            raise ValueError("GeminiProvider requires a non-empty api_key")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def _build_url(self) -> str:
        return (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:generateContent?key={self.api_key}"
        )

    def _build_body(self, prompt: str, system: Optional[str] = None) -> Dict[str, Any]:
        parts: List[Dict[str, str]] = []
        if system:
            parts.append({"text": system})
        parts.append({"text": prompt})

        return {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.4,
            },
        }

    def _parse_success(self, response: requests.Response) -> str:
        res_json = response.json()
        candidates = res_json.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini API response contained no candidates.")
        content = candidates[0].get("content", {})
        res_parts = content.get("parts", [])
        if not res_parts:
            raise RuntimeError("Gemini API candidate contained no content parts.")
        return res_parts[0].get("text", "")

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self._build_url(),
                    json=self._build_body(prompt, system),
                    headers={
                        "x-goog-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    slept = _backoff(attempt, None)
                    logger.warning(
                        "Gemini API network error: %s; retry %d/%d after %.1fs",
                        exc, attempt + 1, self.max_retries, slept,
                    )
                    continue
                raise RuntimeError(f"Gemini API request failed: {exc}") from exc

            status = response.status_code

            if status in (429, 500, 502, 503, 504):
                if attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After")
                    slept = _backoff(attempt, retry_after)
                    logger.warning(
                        "Gemini API returned %d; retry %d/%d after %.1fs",
                        status, attempt + 1, self.max_retries, slept,
                    )
                    continue
                raise RuntimeError(
                    f"Gemini API request failed: {status} {response.reason}"
                )

            if status >= 400:
                raise RuntimeError(
                    f"Gemini API request failed: {status} {response.reason}"
                )

            return self._parse_success(response)

        raise RuntimeError(
            f"Gemini API request failed: {last_exc or 'retries exhausted'}"
        )


class NullProvider(LLMProvider):
    """Deterministic provider for unit testing. Never touches the network."""

    def __init__(self, response: Optional[str] = None):
        self.response = response
        self.calls: List[Tuple[str, Optional[str]]] = []

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        self.calls.append((prompt, system))
        if self.response is not None:
            return self.response
        return json.dumps(
            {
                "title": "عنوان تست",
                "summary": "خلاصه تست",
                "body": "متن کامل نوشته‌شده تست",
                "seo_description": "توضیح سئو تست",
                "keywords": ["تست", "خبر"],
                "research_notes": "نکات تحقیق تست",
                "image_alts": [],
            },
            ensure_ascii=False,
        )


def get_default_provider() -> LLMProvider:
    """Instantiate the default LLMProvider based on environment variables."""
    provider_type = os.environ.get("AUTONEWS_LLM_PROVIDER", "").strip().lower()

    if not provider_type or provider_type == "null":
        return NullProvider()

    if provider_type == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required for gemini provider.")
        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        max_retries = int(os.environ.get("AUTONEWS_LLM_MAX_RETRIES", "3"))
        return GeminiProvider(api_key=api_key, model=model, max_retries=max_retries)

    raise ValueError(f"Unknown LLM provider type: {provider_type}")


def extract_json(raw: str) -> Optional[Dict[str, Any]]:
    """Parse raw model output string into a JSON dictionary safely.

    Parameters:
        raw (str): Raw string returned by model.

    Returns:
        dict | None: Parsed JSON dictionary or None on failure.
    """
    if not raw or not isinstance(raw, str):
        return None

    cleaned = raw.strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Handle markdown code fence wrapping
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned, re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def build_research_prompt(
    article: Dict[str, Any],
    target_language: str = "fa",
    policy: str = "B",
) -> str:
    """Build prompt string sent to LLM for researching and writing an original article.

    Parameters:
        article (dict): Extracted source article metadata and blocks.
        target_language (str): Target output language code ('fa' for Persian).
        policy (str): Policy identifier ("B").

    Returns:
        str: Structured directive prompt string with anti-hallucination rules forbidding invented proper nouns.
    """
    if target_language == "fa":
        target_language_label = "Persian (Farsi)"
    elif target_language == "en":
        target_language_label = "English"
    else:
        target_language_label = target_language

    original_title = article.get("title") or ""
    original_url = article.get("url") or ""
    original_description = article.get("description") or article.get("summary") or ""
    original_content = article.get("content") or ""
    blocks = article.get("blocks") or []

    # Format structured blocks
    if blocks:
        block_lines: List[str] = []
        for idx, b in enumerate(blocks):
            if isinstance(b, dict):
                b_type = b.get("type", "unknown")
                raw_val = b.get("content") or b.get("url") or ""
                val_str = str(raw_val)[:200]
                block_lines.append(f"[{idx}] {b_type}: {val_str}")
            else:
                block_lines.append(f"[{idx}] unknown: {str(b)[:200]}")
        blocks_with_indices = "\n".join(block_lines)
    else:
        blocks_with_indices = "(no structured blocks)"

    # Format images list
    image_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "image"]
    if image_blocks:
        img_lines: List[str] = []
        for img_idx, b in enumerate(image_blocks):
            img_url = b.get("url") or ""
            img_alt = b.get("alt") or "(no alt)"
            img_cap = b.get("caption") or "(none)"
            img_lines.append(f"[{img_idx}] url={img_url} alt={img_alt} caption={img_cap}")
        images_list_with_index = "\n".join(img_lines)
    else:
        images_list_with_index = "(no images)"

    # Prompt-length safety check
    combined_len = (
        len(original_title)
        + len(original_description)
        + len(original_content)
        + len(blocks_with_indices)
        + len(images_list_with_index)
    )
    if combined_len > 8000:
        max_content = min(6000, max(2000, 11000 - 6800 - len(blocks_with_indices) - len(images_list_with_index)))
        original_content = original_content[:max_content] + "\n[... content truncated for length ...]"

    prompt = f"""You are a senior Iranian gaming journalist writing for a Persian-language
gaming news site. Your job is to produce ONE ORIGINAL Persian article
based on the source material below.

You are NOT a translator. You are NOT summarizing. You are WRITING a
new article — with your own structure, your own angle, your own
analysis — grounded in the facts from the source.

====================================================================
HARD RULES (do not break — these are legal/editorial constraints)
====================================================================

1. Do NOT translate the source article word-for-word. Write in your
   own voice.

2. Do NOT mention the source publisher anywhere in the output. No
   "according to [source]", no links to the original, no attribution.

3. Output MUST be valid JSON matching the schema at the bottom. No
   markdown code fences, no explanation, just the JSON object.

4. Output language: {target_language_label}. All prose fields (title,
   summary, body, seo_description, keywords, research_notes,
   image_alts) must be in {target_language_label}. Proper nouns (see
   NAMING below) stay in English.

====================================================================
LENGTH — vary by news type
====================================================================

Choose the body length based on the news type you judge this to be.
Do NOT pad shorter stories to hit a longer target.

  • Breaking / major announcement    → 2200-3000 chars
  • Review / hands-on preview        → 2000-2800 chars
  • Guide / how-to                   → 1500-2200 chars
  • Mid-size news / patch notes      → 1500-2200 chars
  • Small update / minor patch       → 800-1300 chars
  • Rumor / speculation              → 900-1400 chars

Persian "character" counts every letter, space, and punctuation.
Aim for the middle of the range. Do not exceed the max.

Other fields:
  • title:            55-75 chars
  • summary:          120-180 chars, ONE sentence
  • seo_description:  120-155 chars, DIFFERENT wording from summary,
                      include game name + main fact

====================================================================
STRUCTURE — vary by news type
====================================================================

Use markdown `##` for subheadings inside body. Number/name them
naturally in {target_language_label} (e.g. `## چه اتفاقی افتاد`,
`## چرا مهم است`). Do NOT use markdown for anything else (no `#`,
no `**bold**`, no `-` bullet lists, no links).

  • Breaking / major announcement → 2 subheadings:
      open with the fact, then "why it matters" section
  • Review → 3-4 subheadings:
      gameplay, graphics/performance, story/design, verdict
  • Guide / how-to → 2-4 numbered sections
  • Mid-size news → 1-2 subheadings
  • Small update → NO subheadings. 2-3 paragraphs separated by blank lines
  • Rumor → 1-2 subheadings (claim + credibility assessment)

Every subheading is followed by a paragraph. Do NOT put two
subheadings back to back. Do NOT put a subheading at the very start
of body — the first 2-4 sentences are a hook without a subheading.

Opening rules:
  • Open with the most interesting fact or quote
  • 2-4 sentences before the first subheading
  • Vary sentence length: mix short (5-8 words) with longer (15-25)

Closing rules:
  • End with implication, context, or a brief opinion
  • Do NOT end with "what do you think? comment below" or similar

====================================================================
NAMING — all proper nouns stay in English
====================================================================

- Game titles:     "Cyberpunk 2077", "Half-Life 3", "GTA 6"
- Companies:       "CD Projekt Red", "Valve", "BioWare", "EA"
- Engines:         "RE Engine", "Unreal Engine 5", "Decima"
- Platforms:       "Steam", "PlayStation 5", "Xbox Series X"
- People:          "Casey Hudson", "David Gaider"
- Technologies:    "DLSS 4", "FSR 4.1", "ray tracing"
- Numbers/dates:   Persian digits, English units ("۷۰ دلار")

Persian prose between English nouns flows naturally:
  CORRECT:   "استودیو Valve به‌تازگی تأیید کرد که Half-Life 3 در دست
              توسعه است."
  INCORRECT: "استودیو ولو تأیید کرد که هاف-لایف ۳ در دست توسعه است."
  INCORRECT: "Valve recently confirmed that Half-Life 3 is in development."

Technical terms use the common Persian gaming-community word when
one exists ("به‌روزرسانی", "بازخورد", "ذخیره‌سازی ابری"). Do NOT
invent transliterations of English words.

====================================================================
ANTI-HALLUCINATION
====================================================================

- Every specific number, date, price, or direct quote in body MUST
  come from the source material. Do NOT invent statistics.
- You MAY add well-established context (studio history, prior games,
  known industry facts).
- Anything you're uncertain about goes in `research_notes`, NOT in
  `body`. If the source is thin, write a shorter article and say so
  in research_notes.
- No "منابع می‌گویند" or "گفته می‌شود" hedging unless the source is
  explicitly speculative (rumor type). For rumor-type news, do hedge
  — but clearly.
- Do NOT invent or guess the NAME of a specific work (documentary,
  film, book, song, album, TV series, comic, podcast, event) if the
  name does not appear in the SOURCE ARTICLE above. If the source
  describes an event but doesn't name it, describe it descriptively
  in Persian (e.g. 'یک مستند درباره استودیو' — 'a documentary about
  the studio') instead of inventing a title.
- The only proper nouns you may include are:
    (a) proper nouns that appear verbatim in the SOURCE ARTICLE,
    (b) game / company / engine / platform / person names that are
        genuinely established industry facts about the entities
        named in the source (e.g. Valve, Half-Life, Unreal Engine).
  Anything else is a hallucination and will be rejected.
- If you are unsure whether a specific name is real, put your
  uncertainty in `research_notes`, NOT in `title`, `summary`,
  `body`, or `seo_description`.

====================================================================
IMAGE PLACEMENT
====================================================================

Each image listed below gets exactly ONE `[[IMG:i]]` marker in the
body, where `i` matches the index shown. Place markers at natural
breaks:
  • End of a paragraph (after the final period, before blank line)
  • Between two subheadings, on its own line

Do NOT put a marker inside a sentence. Do NOT put a marker in the
first paragraph. If there are no images, do not emit any [[IMG:...]].

====================================================================
SOURCE ARTICLE
====================================================================

Title: {original_title}
URL (context only, do NOT output): {original_url}
Description: {original_description}

Body:
{original_content}

Ordered blocks (paragraphs, headings, and images with indices):
{blocks_with_indices}

Images available (each MUST appear once as [[IMG:i]]):
{images_list_with_index}

====================================================================
OUTPUT SCHEMA (strict)
====================================================================

{{
  "title": "<Persian title, 55-75 chars>",
  "summary": "<Persian one-sentence, 120-180 chars>",
  "body": "<Persian article; may contain ## subheadings and [[IMG:i]]>",
  "seo_description": "<Persian meta, 120-155 chars, different from summary>",
  "keywords": ["<Persian keyword>", ... 5-8 items],
  "research_notes": "<1-2 sentences in Persian, what you added or were unsure about>",
  "image_alts": ["<Persian alt for image 0, max 80 chars>", "..."]
}}

Return ONLY the JSON object. No code fences, no commentary."""
    return prompt.strip()


def research_article(
    article: Dict[str, Any],
    provider: LLMProvider,
    target_language: str = "fa",
) -> Optional[Dict[str, Any]]:
    """Produce an enriched Persian-version dict from one extracted article.

    Parameters:
        article (dict): Input extracted article dictionary.
        provider (LLMProvider): Active LLM provider instance.
        target_language (str): Output language code.

    Returns:
        dict | None: Enriched original Persian article dictionary or None if invalid.
    """
    if not isinstance(article, dict) or not article:
        return None

    title = article.get("title")
    url = article.get("url")
    if not title and not url:
        return None

    # Internal logging only - source metadata MUST NOT leak into returned dict
    logger.info(
        "Researching article: url=%r title=%r source=%r",
        url,
        title,
        article.get("source_name"),
    )

    prompt = build_research_prompt(article, target_language=target_language)

    try:
        raw_output = provider.generate(prompt)
    except Exception as exc:
        logger.error("LLM provider generation failed: %s", exc)
        return None

    parsed = extract_json(raw_output)
    if not parsed:
        logger.warning("Failed to parse JSON response from LLM provider.")
        return None

    out_title = str(parsed.get("title") or "")
    out_summary = str(parsed.get("summary") or "")
    out_body = str(parsed.get("body") or "")
    out_seo_desc = str(parsed.get("seo_description") or "")
    out_keywords = parsed.get("keywords") if isinstance(parsed.get("keywords"), list) else []
    out_notes = str(parsed.get("research_notes") or "")

    blocks = article.get("blocks", [])
    n_imgs = sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "image")

    alts = parsed.get("image_alts", [])
    if not isinstance(alts, list):
        alts = []
    alts = [str(a) if a is not None else "" for a in alts]
    if len(alts) < n_imgs:
        alts = alts + [""] * (n_imgs - len(alts))
    else:
        alts = alts[:n_imgs]

    # Map image blocks from source article blocks list preserving technical URLs
    images: List[Dict[str, Any]] = []
    img_counter = 0

    if isinstance(blocks, list):
        for idx, block in enumerate(blocks):
            if isinstance(block, dict) and block.get("type") == "image":
                img_url = block.get("url", "")
                alt_fa = alts[img_counter] if img_counter < len(alts) else ""
                img_counter += 1
                images.append({
                    "index": idx,
                    "url": img_url,
                    "alt_fa": alt_fa,
                })

    return {
        "language": target_language,
        "title": out_title,
        "summary": out_summary,
        "body": out_body,
        "seo_description": out_seo_desc,
        "keywords": [str(k) for k in out_keywords],
        "research_notes": out_notes,
        "images": images,
    }
