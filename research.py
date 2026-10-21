from abc import ABC, abstractmethod
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)


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
    ):
        if not api_key:
            raise ValueError("API key must be provided for GeminiProvider.")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:generateContent?key={self.api_key}"
        )
        parts: List[Dict[str, str]] = []
        if system:
            parts.append({"text": system})
        parts.append({"text": prompt})

        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.4,
            },
        }

        try:
            response = requests.post(url, json=body, timeout=self.timeout)
            response.raise_for_status()
            res_json = response.json()
            candidates = res_json.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini API response contained no candidates.")
            content = candidates[0].get("content", {})
            res_parts = content.get("parts", [])
            if not res_parts:
                raise RuntimeError("Gemini API candidate contained no content parts.")
            return res_parts[0].get("text", "")
        except Exception as exc:
            logger.error("Gemini API request failed: %s", exc)
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc


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
        return GeminiProvider(api_key=api_key, model=model)

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

    prompt = f"""
You are an expert news analyst and journalist.

SOURCE ARTICLE CONTEXT:
Title: {title}
Description: {description}
URL: {url}
Content: {content}
Structured Blocks: {json.dumps(blocks, ensure_ascii=False)}

CRITICAL WRITING REQUIREMENTS:
1. Target Language: {target_language}
2. Do NOT translate the source article. You must write an ORIGINAL article in {target_language} based on facts extracted from the source, using your own structure and words.
3. You do not mention the source publisher or credit any specific news outlet in the output.
4. You may add relevant contextual information that you know (such as game history, similar game updates, developer track record, or industry background).
5. Mark any uncertain or added speculative claims clearly in `research_notes`.
6. For images, the `body` Persian text may insert image markers in the format [[IMG:i]] where i is the 0-based index into the source article's `blocks` list (only for blocks of type 'image').

OUTPUT FORMAT:
Output STRICT JSON with exactly these keys:
{{
  "title": "original Persian headline",
  "summary": "original Persian summary paragraph",
  "body": "original Persian body text with optional [[IMG:i]] markers",
  "seo_description": "original Persian SEO meta description",
  "keywords": ["keyword1", "keyword2"],
  "research_notes": "notes on added context or uncertainties",
  "image_alts": ["Persian alt text for image at block 0", "Persian alt text for image at block 1"]
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
    out_alts = parsed.get("image_alts") if isinstance(parsed.get("image_alts"), list) else []

    # Map image blocks from source article blocks list preserving technical URLs
    blocks = article.get("blocks", [])
    images: List[Dict[str, Any]] = []

    if isinstance(blocks, list):
        for idx, block in enumerate(blocks):
            if isinstance(block, dict) and block.get("type") == "image":
                img_url = block.get("url", "")
                alt_fa = out_alts[idx] if idx < len(out_alts) and isinstance(out_alts[idx], str) else ""
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
