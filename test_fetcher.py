import unittest
from unittest.mock import patch, MagicMock
import requests
from fetcher import fetch_rss, DEFAULT_USER_AGENT


class TestFetcher(unittest.TestCase):

    @patch("fetcher.requests.get")
    @patch("fetcher.feedparser.parse")
    def test_fetch_rss_success(self, mock_parse, mock_get):
        mock_response = MagicMock()
        mock_response.content = b"<xml>rss content</xml>"
        mock_get.return_value = mock_response

        mock_entry1 = MagicMock(title="Article 1", link="https://example.com/1")
        mock_entry2 = MagicMock(title="Article 2", link="https://example.com/2")

        mock_parsed = MagicMock()
        mock_parsed.entries = [mock_entry1, mock_entry2]
        mock_parsed.bozo = 0
        mock_parse.return_value = mock_parsed

        url = "https://example.com/rss"
        entries = fetch_rss(url)

        mock_get.assert_called_once_with(url, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=10)
        mock_parse.assert_called_once_with(b"<xml>rss content</xml>")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].title, "Article 1")

    @patch("fetcher.requests.get")
    def test_fetch_rss_http_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        entries = fetch_rss("https://example.com/404")
        self.assertEqual(entries, [])

    @patch("fetcher.requests.get")
    def test_fetch_rss_connection_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout("Connection timed out")

        entries = fetch_rss("https://example.com/timeout", timeout=5)
        self.assertEqual(entries, [])

    @patch("fetcher.requests.get")
    @patch("fetcher.feedparser.parse")
    def test_fetch_rss_bozo_with_entries(self, mock_parse, mock_get):
        mock_response = MagicMock()
        mock_response.content = b"<xml>imperfect rss</xml>"
        mock_get.return_value = mock_response

        mock_entry = MagicMock(title="Article Bozo", link="https://example.com/bozo")
        mock_parsed = MagicMock()
        mock_parsed.entries = [mock_entry]
        mock_parsed.bozo = 1
        mock_parsed.bozo_exception = Exception("SAXParseException")
        mock_parse.return_value = mock_parsed

        entries = fetch_rss("https://example.com/bozo_rss")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "Article Bozo")

    @patch("fetcher.requests.get")
    @patch("fetcher.feedparser.parse")
    def test_fetch_rss_bozo_no_entries(self, mock_parse, mock_get):
        mock_response = MagicMock()
        mock_response.content = b"not xml at all"
        mock_get.return_value = mock_response

        mock_parsed = MagicMock()
        mock_parsed.entries = []
        mock_parsed.bozo = 1
        mock_parsed.bozo_exception = Exception("SAXParseException")
        mock_parse.return_value = mock_parsed

        entries = fetch_rss("https://example.com/invalid_rss")
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
