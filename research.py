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


def build_research_prompt(article: Dict[str, Any], target_language: str = "fa") -> str:
    """Build prompt string sent to LLM for researching and writing an original article.

    Parameters:
        article (dict): Extracted source article metadata and blocks.
        target_language (str): Target output language code ('fa' for Persian).

    Returns:
        str: Structured prompt string.
    """
    title = article.get("title") or ""
    description = article.get("description") or ""
    url = article.get("url") or ""
    content = article.get("content") or ""
    blocks = article.get("blocks") or []

    images_section = ""
    image_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "image"]
    if image_blocks:
        lines = ["IMAGES IN THE SOURCE (index is the 0-based position in the article's `blocks` list):"]
        for img_idx, b in enumerate(image_blocks):
            img_url = b.get("url") or ""
            img_alt = b.get("alt") or ""
            img_cap = b.get("caption") or ""
            lines.append(f"  [{img_idx}] url={img_url} alt={img_alt} caption={img_cap}")
        images_section = "\n".join(lines) + "\n\n"

    prompt = f"""
You are an expert news analyst and journalist.

SOURCE ARTICLE CONTEXT:
Title: {title}
Description: {description}
URL: {url}
Content: {content}
Structured Blocks: {json.dumps(blocks, ensure_ascii=False)}

{images_section}CRITICAL WRITING REQUIREMENTS:
1. Target Language: {target_language}
2. Do NOT translate the source article. You must write an ORIGINAL article in {target_language} based on facts extracted from the source, using your own structure and words.
3. You do not mention the source publisher or credit any specific news outlet in the output.
4. You may add relevant contextual information that you know (such as game history, similar game updates, developer track record, or industry background).
5. Mark any uncertain or added speculative claims clearly in `research_notes`.
6. For images, the `body` Persian text may insert image markers in the format [[IMG:i]] where i is the 0-based index into the source article's `blocks` list (only for blocks of type 'image').

OUTPUT FORMAT:
image_alts MUST be a list of strings whose length exactly equals the number of images listed above. image_alts[i] is a short Persian alt text (max 80 chars) for image i. If you cannot write a meaningful alt text for some image, use an empty string at that position — do NOT omit the entry.

Output STRICT JSON with exactly these keys:
{{
  "title": "original Persian headline",
  "summary": "original Persian summary paragraph",
  "body": "original Persian body text with optional [[IMG:i]] markers",
  "seo_description": "original Persian SEO meta description",
  "keywords": ["keyword1", "keyword2"],
  "research_notes": "notes on added context or uncertainties",
  "image_alts": ["Persian alt text for image 0", "Persian alt text for image 1"]
}}
"""
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
