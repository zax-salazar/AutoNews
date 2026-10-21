from abc import ABC, abstractmethod
import json
import logging
import os
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "AutoNews/1.0"
REQUIRED_FIELDS = ("title", "body")


class PublisherProvider(ABC):
    """Abstract base class for article publishing providers."""

    @abstractmethod
    def publish(self, article: dict) -> dict:
        """Publish one article.

        Parameters:
            article (dict): Article dictionary to publish.

        Returns:
            dict: Dictionary with format {"ok": bool, "id": str|None, "error": str|None}.
        """
        pass


class NullPublisher(PublisherProvider):
    """Deterministic publisher for testing. Never touches the network."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.calls: list = []

    def publish(self, article: dict) -> dict:
        self.calls.append(article)
        if self.ok:
            return {
                "ok": True,
                "id": f"null-{len(self.calls)}",
                "error": None,
            }
        return {
            "ok": False,
            "id": None,
            "error": "NullPublisher: forced failure",
        }


class HttpPublisher(PublisherProvider):
    """Generic HTTP POST article publisher implementation."""

    def __init__(
        self,
        endpoint: str,
        token: Optional[str] = None,
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
        timeout: int = 30,
    ):
        if not endpoint or not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("Endpoint URL must be a non-empty string.")

        self.endpoint = endpoint.strip()
        self.token = token
        self.auth_header = auth_header
        self.auth_scheme = auth_scheme
        self.timeout = timeout

    def publish(self, article: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        if self.token:
            headers[self.auth_header] = f"{self.auth_scheme} {self.token}"

        try:
            response = requests.post(
                self.endpoint,
                json=article,
                headers=headers,
                timeout=self.timeout,
            )

            if 200 <= response.status_code < 300:
                article_id = None
                if response.text and response.text.strip():
                    try:
                        res_data = response.json()
                        if isinstance(res_data, dict):
                            raw_id = res_data.get("id")
                            if raw_id is not None:
                                article_id = str(raw_id)
                    except Exception:
                        pass
                return {"ok": True, "id": article_id, "error": None}
            else:
                resp_text = response.text or ""
                logger.error(
                    "HTTP publisher received error response (status %d): %s",
                    response.status_code,
                    resp_text[:500],
                )
                return {
                    "ok": False,
                    "id": None,
                    "error": f"HTTP {response.status_code}: {resp_text[:200]}",
                }

        except requests.RequestException as exc:
            logger.error("HTTP publisher request failed for endpoint %s: %s", self.endpoint, exc)
            return {
                "ok": False,
                "id": None,
                "error": str(exc),
            }


def get_default_publisher() -> PublisherProvider:
    """Instantiate publisher provider according to environment configuration."""
    pub_type = os.environ.get("AUTONEWS_PUBLISHER", "null").strip().lower()
    if not pub_type:
        pub_type = "null"

    if pub_type == "null":
        return NullPublisher()

    if pub_type == "http":
        endpoint = os.environ.get("AUTONEWS_PUBLISH_URL")
        if not endpoint:
            raise ValueError("AUTONEWS_PUBLISH_URL environment variable is required for http publisher.")

        token = os.environ.get("AUTONEWS_PUBLISH_TOKEN")
        auth_header = os.environ.get("AUTONEWS_PUBLISH_AUTH_HEADER", "Authorization")
        auth_scheme = os.environ.get("AUTONEWS_PUBLISH_AUTH_SCHEME", "Bearer")
        timeout_str = os.environ.get("AUTONEWS_PUBLISH_TIMEOUT", "30")

        try:
            timeout = int(timeout_str)
        except ValueError:
            timeout = 30

        return HttpPublisher(
            endpoint=endpoint,
            token=token,
            auth_header=auth_header,
            auth_scheme=auth_scheme,
            timeout=timeout,
        )

    raise ValueError(f"Unknown publisher type: {pub_type}")


def validate_article(article: dict) -> Optional[str]:
    """Validate article payload fields before publishing.

    Parameters:
        article (dict): Article dictionary to validate.

    Returns:
        str | None: Error message string if invalid, or None if valid.
    """
    if not isinstance(article, dict):
        return "article is not a dict"

    for field in REQUIRED_FIELDS:
        val = article.get(field)
        if not val or not isinstance(val, str) or not val.strip():
            return f"missing required field: {field}"

    if "keywords" in article and article["keywords"] is not None:
        if not isinstance(article["keywords"], list):
            return "keywords must be a list"

    if "images" in article and article["images"] is not None:
        if not isinstance(article["images"], list):
            return "images must be a list"

    return None


def publish_article(article: dict, provider: PublisherProvider) -> dict:
    """Validate and publish an article using the provided PublisherProvider.

    Parameters:
        article (dict): Article payload dictionary.
        provider (PublisherProvider): Configured publisher provider instance.

    Returns:
        dict: Result status dictionary {"ok": bool, "id": str|None, "error": str|None}.
    """
    error = validate_article(article)
    if error:
        return {
            "ok": False,
            "id": None,
            "error": error,
        }

    return provider.publish(article)
