import json
import os
import unittest
from unittest.mock import patch, MagicMock
import requests

from research import (
    LLMProvider,
    GeminiProvider,
    NullProvider,
    get_default_provider,
    extract_json,
    build_research_prompt,
    research_article,
)


class TestResearch(unittest.TestCase):

    # --- JSON Extraction Tests ---
    def test_extract_json_plain(self):
        raw = '{"title": "Test Title", "body": "Test Body"}'
        result = extract_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("title"), "Test Title")

    def test_extract_json_code_fence_json(self):
        raw = '```json\n{\n  "title": "Fenced Title"\n}\n```'
        result = extract_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("title"), "Fenced Title")

    def test_extract_json_code_fence_plain(self):
        raw = '```\n{\n  "summary": "Fenced Summary"\n}\n```'
        result = extract_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result.get("summary"), "Fenced Summary")

    def test_extract_json_invalid_returns_none(self):
        self.assertIsNone(extract_json("not json at all"))
        self.assertIsNone(extract_json(""))
        self.assertIsNone(extract_json(None))

    # --- Prompt Construction (Legal Contract) Tests ---
    def test_build_research_prompt_contains_title_and_url(self):
        article = {
            "title": "Unique Title 123",
            "url": "https://example.com/unique-url-456",
            "content": "Content string",
        }
        prompt = build_research_prompt(article)
        self.assertIn("Unique Title 123", prompt)
        self.assertIn("https://example.com/unique-url-456", prompt)

    def test_build_research_prompt_forbids_translation(self):
        article = {"title": "Title", "url": "https://example.com/1"}
        prompt = build_research_prompt(article)
        self.assertIn("Do NOT translate", prompt)

    def test_build_research_prompt_asks_for_original(self):
        article = {"title": "Title", "url": "https://example.com/1"}
        prompt = build_research_prompt(article)
        self.assertIn("original", prompt.lower())

    def test_build_research_prompt_forbids_source_mention(self):
        article = {"title": "Title", "url": "https://example.com/1"}
        prompt = build_research_prompt(article)
        self.assertIn("do not mention the source publisher", prompt.lower())

    def test_build_research_prompt_contains_target_language(self):
        article = {"title": "Title", "url": "https://example.com/1"}
        prompt_fa = build_research_prompt(article, target_language="fa")
        self.assertIn("fa", prompt_fa)

        prompt_en = build_research_prompt(article, target_language="en")
        self.assertIn("en", prompt_en)

    def test_build_research_prompt_mentions_image_markers(self):
        article = {"title": "Title", "url": "https://example.com/1"}
        prompt = build_research_prompt(article)
        self.assertIn("[[IMG:", prompt)

    # --- NullProvider Tests ---
    def test_null_provider_returns_deterministic_json(self):
        provider = NullProvider()
        output = provider.generate("Test prompt")
        parsed = extract_json(output)
        self.assertIsNotNone(parsed)
        self.assertIn("title", parsed)
        self.assertIn("body", parsed)

    def test_null_provider_records_calls(self):
        provider = NullProvider(response='{"title": "Custom"}')
        output = provider.generate("Prompt 1", system="System 1")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0], ("Prompt 1", "System 1"))
        self.assertEqual(output, '{"title": "Custom"}')

    # --- GeminiProvider Tests ---
    def test_gemini_provider_requires_api_key(self):
        with self.assertRaises(ValueError):
            GeminiProvider(api_key="")
        with self.assertRaises(ValueError):
            GeminiProvider(api_key=None)

    @patch("research.requests.post")
    def test_gemini_provider_builds_request(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": '{"title": "Gemini Title"}'}]}}
            ]
        }
        mock_post.return_value = mock_response

        provider = GeminiProvider(api_key="test-api-key-123", model="gemini-2.0-flash")
        res = provider.generate("Prompt text", system="System text")

        mock_post.assert_called_once()
        url_arg = mock_post.call_args[0][0]
        self.assertIn("gemini-2.0-flash", url_arg)
        self.assertIn("key=test-api-key-123", url_arg)

        json_arg = mock_post.call_args[1]["json"]
        parts = json_arg["contents"][0]["parts"]
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0]["text"], "System text")
        self.assertEqual(parts[1]["text"], "Prompt text")
        self.assertEqual(res, '{"title": "Gemini Title"}')

    @patch("research.requests.post")
    def test_gemini_provider_handles_http_error(self, mock_post):
        mock_post.side_effect = requests.RequestException("HTTP Connection Error")
        provider = GeminiProvider(api_key="test-key")

        with self.assertRaises(RuntimeError):
            provider.generate("Prompt text")

    # --- research_article End-to-End Tests ---
    def test_research_article_returns_full_schema(self):
        article = {
            "title": "Original English Title",
            "url": "https://example.com/original-article",
            "content": "English article body...",
            "blocks": [
                {"type": "paragraph", "content": "Text paragraph"},
                {"type": "image", "url": "https://example.com/img1.jpg", "alt": "Old alt"},
            ],
        }

        mock_json_res = json.dumps({
            "title": "عنوان جدید فارسی",
            "summary": "خلاصه خبر فارسی",
            "body": "متن کامل مقاله جدید فارسی...",
            "seo_description": "توضیحات سئو",
            "keywords": ["گیم", "خبر"],
            "research_notes": "نکات تحقیق",
            "image_alts": ["", "توضیح عکس اول"],
        }, ensure_ascii=False)

        provider = NullProvider(response=mock_json_res)
        result = research_article(article, provider)

        self.assertIsNotNone(result)
        expected_keys = {
            "language", "title", "summary", "body",
            "seo_description", "keywords", "research_notes", "images",
        }
        self.assertEqual(set(result.keys()), expected_keys)
        self.assertEqual(result["language"], "fa")
        self.assertEqual(result["title"], "عنوان جدید فارسی")
        self.assertEqual(len(result["images"]), 1)
        self.assertEqual(result["images"][0]["url"], "https://example.com/img1.jpg")
        self.assertEqual(result["images"][0]["index"], 1)

        # Assert no key contains forbidden terms
        forbidden_substrings = ["source", "credit", "attribution", "copyright", "original_"]
        for k in result.keys():
            for forbidden in forbidden_substrings:
                self.assertNotIn(forbidden, k.lower())

    def test_research_article_no_source_leak(self):
        article = {
            "title": "Title Leak Check",
            "url": "https://example.com/leak",
            "published": "2026-10-21T00:00:00Z",
            "source_name": "PC Gamer",
        }
        provider = NullProvider()
        result = research_article(article, provider)

        self.assertIsNotNone(result)
        forbidden_keys = {"source_name", "source_url", "attribution", "copyright_notice", "credit", "original_title", "original_published"}
        for fk in forbidden_keys:
            self.assertNotIn(fk, result)

    def test_research_article_handles_missing_blocks(self):
        article = {"title": "Title Only", "url": "https://example.com/no-blocks"}
        provider = NullProvider()
        result = research_article(article, provider)

        self.assertIsNotNone(result)
        self.assertEqual(result["images"], [])

    def test_research_article_invalid_article_returns_none(self):
        provider = NullProvider()
        self.assertIsNone(research_article({}, provider))
        self.assertIsNone(research_article(None, provider))
        self.assertIsNone(research_article({"content": "no title or url"}, provider))

    def test_research_article_unparseable_model_output_returns_none(self):
        article = {"title": "Title", "url": "https://example.com/1"}
        provider = NullProvider(response="This is completely unparseable plain text")
        self.assertIsNone(research_article(article, provider))

    # --- Factory Tests ---
    @patch.dict(os.environ, {"AUTONEWS_LLM_PROVIDER": ""}, clear=True)
    def test_get_default_provider_null_when_env_unset(self):
        provider = get_default_provider()
        self.assertIsInstance(provider, NullProvider)

    @patch.dict(os.environ, {"AUTONEWS_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "test-key-999"}, clear=True)
    def test_get_default_provider_gemini_when_env_set(self):
        provider = get_default_provider()
        self.assertIsInstance(provider, GeminiProvider)
        self.assertEqual(provider.api_key, "test-key-999")


if __name__ == "__main__":
    unittest.main()
