import unittest
from unittest.mock import patch, MagicMock
from pipeline import run_source, run_sources


class TestPipeline(unittest.TestCase):

    # --- Test 1: Successful single source ---
    @patch("pipeline.extract_articles")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_success(self, mock_fetch, mock_parse, mock_extract):
        mock_raw_entries = [{"title": "Raw Entry 1"}]
        mock_parsed_articles = [
            {"title": "Parsed Article 1", "url": "https://example.com/1"}
        ]
        mock_extracted_articles = [
            {
                "title": "Parsed Article 1",
                "url": "https://example.com/1",
                "content": "Full extracted article text...",
            }
        ]

        mock_fetch.return_value = mock_raw_entries
        mock_parse.return_value = mock_parsed_articles
        mock_extract.return_value = mock_extracted_articles

        source = {
            "name": "Test Source",
            "url": "https://example.com/rss",
            "type": "rss",
            "category": "gaming",
            "enabled": True,
        }

        result = run_source(source, timeout=10)

        mock_fetch.assert_called_once_with("https://example.com/rss", timeout=10)
        mock_parse.assert_called_once_with(mock_raw_entries)
        mock_extract.assert_called_once_with(mock_parsed_articles, timeout=10)
        self.assertEqual(result, mock_extracted_articles)

    # --- Test 2: Disabled source ---
    @patch("pipeline.fetch_rss")
    def test_run_source_disabled(self, mock_fetch):
        source = {
            "name": "Disabled Source",
            "url": "https://example.com/rss",
            "enabled": False,
        }

        result = run_source(source)

        mock_fetch.assert_not_called()
        self.assertEqual(result, [])

    # --- Test 3: Invalid source ---
    @patch("pipeline.fetch_rss")
    def test_run_source_invalid(self, mock_fetch):
        self.assertEqual(run_source(None), [])
        self.assertEqual(run_source("not a dict"), [])
        self.assertEqual(run_source({"name": "No URL"}), [])
        self.assertEqual(run_source({"name": "Empty URL", "url": "   "}), [])
        mock_fetch.assert_not_called()

    # --- Test 4: RSS fetch failure ---
    @patch("pipeline.extract_articles")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_fetch_failure(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = []

        source = {
            "name": "Failed Fetch Source",
            "url": "https://example.com/rss-fail",
        }

        result = run_source(source)

        mock_fetch.assert_called_once_with("https://example.com/rss-fail", timeout=10)
        mock_parse.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(result, [])

    # --- Test 5: Multiple sources ---
    @patch("pipeline.run_source")
    def test_run_sources_multiple(self, mock_run_source):
        source_a = {"name": "Source A", "url": "https://a.com/rss"}
        source_b = {"name": "Source B", "url": "https://b.com/rss"}

        article_a1 = {"title": "A1", "url": "https://a.com/1", "content": "Text A1"}
        article_a2 = {"title": "A2", "url": "https://a.com/2", "content": "Text A2"}
        article_b1 = {"title": "B1", "url": "https://b.com/1", "content": "Text B1"}

        def side_effect(source, timeout=10):
            if source == source_a:
                return [article_a1, article_a2]
            elif source == source_b:
                return [article_b1]
            return []

        mock_run_source.side_effect = side_effect

        results = run_sources([source_a, source_b])

        self.assertEqual(len(results), 3)
        self.assertEqual(results, [article_a1, article_a2, article_b1])

    # --- Test 6: One source fails ---
    @patch("pipeline.run_source")
    def test_run_sources_one_fails(self, mock_run_source):
        source_a = {"name": "Source A", "url": "https://a.com/rss"}
        source_b = {"name": "Source B", "url": "https://b.com/rss"}
        source_c = {"name": "Source C", "url": "https://c.com/rss"}

        article_a = {"title": "A1", "url": "https://a.com/1", "content": "Text A1"}
        article_c = {"title": "C1", "url": "https://c.com/1", "content": "Text C1"}

        def side_effect(source, timeout=10):
            if source == source_a:
                return [article_a]
            elif source == source_b:
                return []  # Source B fails
            elif source == source_c:
                return [article_c]
            return []

        mock_run_source.side_effect = side_effect

        results = run_sources([source_a, source_b, source_c])

        self.assertEqual(len(results), 2)
        self.assertEqual(results, [article_a, article_c])

    # --- Test 7: Empty parsed entries ---
    @patch("pipeline.extract_articles")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_empty_parsed_entries(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = []  # No entries successfully parsed

        source = {
            "name": "Parse Fail Source",
            "url": "https://example.com/rss-parse-fail",
        }

        result = run_source(source)

        mock_fetch.assert_called_once_with("https://example.com/rss-parse-fail", timeout=10)
        mock_parse.assert_called_once_with([{"raw": "data"}])
        mock_extract.assert_not_called()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
