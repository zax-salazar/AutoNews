import os
import unittest
from unittest.mock import patch, MagicMock
import requests

from publisher import (
    PublisherProvider,
    NullPublisher,
    HttpPublisher,
    get_default_publisher,
    validate_article,
    publish_article,
)


class TestPublisher(unittest.TestCase):

    # --- validate_article tests ---
    def test_validate_article_valid(self):
        article = {
            "title": "Valid Article Title",
            "body": "Valid article body text.",
            "keywords": ["news", "gaming"],
            "images": [{"url": "https://example.com/image.jpg"}],
        }
        self.assertIsNone(validate_article(article))

    def test_validate_article_not_a_dict(self):
        self.assertEqual(validate_article("not a dict"), "article is not a dict")
        self.assertEqual(validate_article(None), "article is not a dict")

    def test_validate_article_missing_title(self):
        article = {"body": "Body without title"}
        self.assertEqual(validate_article(article), "missing required field: title")

    def test_validate_article_missing_body(self):
        article = {"title": "Title without body"}
        self.assertEqual(validate_article(article), "missing required field: body")

    def test_validate_article_blank_title(self):
        article = {"title": "   ", "body": "Valid body"}
        self.assertEqual(validate_article(article), "missing required field: title")

    def test_validate_article_bad_keywords_type(self):
        article = {"title": "Title", "body": "Body", "keywords": "not a list"}
        self.assertEqual(validate_article(article), "keywords must be a list")

    def test_validate_article_bad_images_type(self):
        article = {"title": "Title", "body": "Body", "images": "not a list"}
        self.assertEqual(validate_article(article), "images must be a list")

    # --- NullPublisher tests ---
    def test_null_publisher_success(self):
        publisher = NullPublisher(ok=True)
        res = publisher.publish({"title": "T", "body": "B"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["id"], "null-1")
        self.assertIsNone(res["error"])

    def test_null_publisher_failure(self):
        publisher = NullPublisher(ok=False)
        res = publisher.publish({"title": "T", "body": "B"})
        self.assertFalse(res["ok"])
        self.assertIsNone(res["id"])
        self.assertEqual(res["error"], "NullPublisher: forced failure")

    def test_null_publisher_records_calls(self):
        publisher = NullPublisher()
        art1 = {"title": "T1", "body": "B1"}
        art2 = {"title": "T2", "body": "B2"}
        publisher.publish(art1)
        publisher.publish(art2)
        self.assertEqual(len(publisher.calls), 2)
        self.assertEqual(publisher.calls[0], art1)
        self.assertEqual(publisher.calls[1], art2)

    # --- HttpPublisher tests ---
    def test_http_publisher_requires_endpoint(self):
        with self.assertRaises(ValueError):
            HttpPublisher(endpoint="")
        with self.assertRaises(ValueError):
            HttpPublisher(endpoint="   ")

    @patch("publisher.requests.post")
    def test_http_publisher_builds_request(self, mock_post):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.text = '{"id": "http-123"}'
        mock_res.json.return_value = {"id": "http-123"}
        mock_post.return_value = mock_res

        article = {"title": "HTTP Title", "body": "HTTP Body"}

        # Case 1: With token
        pub_token = HttpPublisher(
            endpoint="https://api.example.com/publish",
            token="secret-token-123",
            auth_header="Authorization",
            auth_scheme="Bearer",
        )
        res1 = pub_token.publish(article)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.example.com/publish")
        self.assertEqual(kwargs["json"], article)
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["headers"]["User-Agent"], "AutoNews/1.0")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token-123")
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["id"], "http-123")

        # Case 2: Without token
        mock_post.reset_mock()
        pub_no_token = HttpPublisher(endpoint="https://api.example.com/publish")
        pub_no_token.publish(article)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertNotIn("Authorization", kwargs["headers"])

    @patch("publisher.requests.post")
    def test_http_publisher_handles_2xx(self, mock_post):
        mock_res = MagicMock()
        mock_res.status_code = 201
        mock_res.text = '{"id": "abc123"}'
        mock_res.json.return_value = {"id": "abc123"}
        mock_post.return_value = mock_res

        pub = HttpPublisher(endpoint="https://example.com/post")
        res = pub.publish({"title": "T", "body": "B"})

        self.assertEqual(res, {"ok": True, "id": "abc123", "error": None})

    @patch("publisher.requests.post")
    def test_http_publisher_handles_2xx_no_json(self, mock_post):
        mock_res = MagicMock()
        mock_res.status_code = 204
        mock_res.text = ""
        mock_res.json.side_effect = ValueError("No JSON")
        mock_post.return_value = mock_res

        pub = HttpPublisher(endpoint="https://example.com/post")
        res = pub.publish({"title": "T", "body": "B"})

        self.assertEqual(res, {"ok": True, "id": None, "error": None})

    @patch("publisher.requests.post")
    def test_http_publisher_handles_non_2xx(self, mock_post):
        mock_res = MagicMock()
        mock_res.status_code = 400
        mock_res.text = "bad request error payload"
        mock_post.return_value = mock_res

        pub = HttpPublisher(endpoint="https://example.com/post")
        res = pub.publish({"title": "T", "body": "B"})

        self.assertFalse(res["ok"])
        self.assertIsNone(res["id"])
        self.assertIn("HTTP 400", res["error"])

    @patch("publisher.requests.post")
    def test_http_publisher_handles_connection_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("Failed to connect")

        pub = HttpPublisher(endpoint="https://example.com/post")
        res = pub.publish({"title": "T", "body": "B"})

        self.assertFalse(res["ok"])
        self.assertIsNone(res["id"])
        self.assertIn("Failed to connect", res["error"])

    # --- publish_article tests ---
    def test_publish_article_valid(self):
        publisher = NullPublisher(ok=True)
        article = {"title": "Title", "body": "Body"}
        res = publish_article(article, publisher)

        self.assertTrue(res["ok"])
        self.assertEqual(len(publisher.calls), 1)
        self.assertEqual(publisher.calls[0], article)

    def test_publish_article_validation_failure(self):
        publisher = NullPublisher(ok=True)
        article = {"title": "Title"}  # Missing body
        res = publish_article(article, publisher)

        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "missing required field: body")
        self.assertEqual(len(publisher.calls), 0)

    def test_publish_article_does_not_add_extra_fields(self):
        publisher = NullPublisher(ok=True)
        article = {"title": "title", "body": "body"}
        publish_article(article, publisher)

        self.assertEqual(set(publisher.calls[0].keys()), {"title", "body"})

    # --- factory tests ---
    @patch.dict(os.environ, {"AUTONEWS_PUBLISHER": ""}, clear=True)
    def test_get_default_publisher_null_when_env_unset(self):
        pub = get_default_publisher()
        self.assertIsInstance(pub, NullPublisher)

    @patch.dict(
        os.environ,
        {
            "AUTONEWS_PUBLISHER": "http",
            "AUTONEWS_PUBLISH_URL": "https://example.com/api/publish",
            "AUTONEWS_PUBLISH_TOKEN": "token-xyz",
        },
        clear=True,
    )
    def test_get_default_publisher_http_when_env_set(self):
        pub = get_default_publisher()
        self.assertIsInstance(pub, HttpPublisher)
        self.assertEqual(pub.endpoint, "https://example.com/api/publish")
        self.assertEqual(pub.token, "token-xyz")

    @patch.dict(os.environ, {"AUTONEWS_PUBLISHER": "http"}, clear=True)
    def test_get_default_publisher_http_without_url_raises(self):
        with self.assertRaises(ValueError):
            get_default_publisher()


if __name__ == "__main__":
    unittest.main()
