import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pipeline import run_source, run_sources
from database import init_db, is_article_completed, get_article_status, get_article_data, normalize_url


class TestPipeline(unittest.TestCase):

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        init_db(self.temp_db_path)

    def tearDown(self):
        os.close(self.temp_db_fd)
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    # --- Test 1: Successful single source & registration ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_success_and_registration(self, mock_fetch, mock_parse, mock_extract):
        mock_raw_entries = [{"title": "Raw Entry 1"}]
        mock_parsed_articles = [
            {"title": "Parsed Article 1", "url": "https://example.com/1?utm_source=rss"}
        ]
        mock_extracted_article = {
            "title": "Parsed Article 1",
            "url": "https://example.com/1?utm_source=rss",
            "content": "Full extracted article text...",
        }

        mock_fetch.return_value = mock_raw_entries
        mock_parse.return_value = mock_parsed_articles
        mock_extract.return_value = mock_extracted_article

        source = {
            "name": "Test Source",
            "url": "https://example.com/rss",
            "enabled": True,
        }

        results = run_source(source, timeout=10, db_path=self.temp_db_path)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], mock_extracted_article)

        norm_url = normalize_url("https://example.com/1?utm_source=rss")
        self.assertTrue(is_article_completed(norm_url, db_path=self.temp_db_path))

    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_saves_article_data(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [{"title": "Saved Art", "url": "https://example.com/save-data"}]
        mock_extracted = {"title": "Saved Art", "url": "https://example.com/save-data", "content": "Text", "blocks": []}
        mock_extract.return_value = mock_extracted

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        run_source(source, db_path=self.temp_db_path)

        norm_url = normalize_url("https://example.com/save-data")
        saved_data = get_article_data(norm_url, db_path=self.temp_db_path)
        self.assertEqual(saved_data, mock_extracted)

    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_extraction_failure_does_not_save_article_data(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [{"title": "Fail Art", "url": "https://example.com/fail-data"}]
        mock_extract.return_value = None

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        run_source(source, db_path=self.temp_db_path)

        norm_url = normalize_url("https://example.com/fail-data")
        self.assertIsNone(get_article_data(norm_url, db_path=self.temp_db_path))

    # --- Test 2: Completed article skipped on subsequent runs ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_completed_article_skipped_on_subsequent_runs(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [{"title": "Article 1", "url": "https://example.com/subsequent-1"}]
        mock_extract.return_value = {"title": "Article 1", "url": "https://example.com/subsequent-1", "content": "Text"}

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        # Run 1: Article is processed and completed
        run1 = run_source(source, db_path=self.temp_db_path)
        self.assertEqual(len(run1), 1)
        self.assertEqual(mock_extract.call_count, 1)

        # Run 2: Article should be skipped
        mock_extract.reset_mock()
        run2 = run_source(source, db_path=self.temp_db_path)
        self.assertEqual(len(run2), 0)
        mock_extract.assert_not_called()

    # --- Test 3: In-feed duplicate deduplication ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_in_feed_duplicate_deduplication(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [
            {"title": "Article 1", "url": "https://example.com/same-article"},
            {"title": "Article 1 Duplicate", "url": "https://example.com/same-article?utm_medium=email"},
        ]
        mock_extract.return_value = {"title": "Article 1", "url": "https://example.com/same-article", "content": "Text"}

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        results = run_source(source, db_path=self.temp_db_path)

        self.assertEqual(len(results), 1)
        self.assertEqual(mock_extract.call_count, 1)

    # --- Test 4: Cross-source duplicate deduplication ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_cross_source_duplicate_deduplication(self, mock_fetch, mock_parse, mock_extract):
        def parse_side_effect(raw):
            if raw == [{"feed": "A"}]:
                return [{"title": "Story", "url": "https://example.com/shared-story"}]
            elif raw == [{"feed": "B"}]:
                return [{"title": "Story B", "url": "https://example.com/shared-story?fbclid=999"}]
            return []

        def fetch_side_effect(url, timeout=10):
            if url == "https://a.com/rss":
                return [{"feed": "A"}]
            elif url == "https://b.com/rss":
                return [{"feed": "B"}]
            return []

        mock_fetch.side_effect = fetch_side_effect
        mock_parse.side_effect = parse_side_effect
        mock_extract.return_value = {"title": "Story", "url": "https://example.com/shared-story", "content": "Text"}

        sources = [
            {"name": "Source A", "url": "https://a.com/rss"},
            {"name": "Source B", "url": "https://b.com/rss"},
        ]

        results = run_sources(sources, db_path=self.temp_db_path)

        self.assertEqual(len(results), 1)
        self.assertEqual(mock_extract.call_count, 1)

    # --- Test 5 & 6 & 7: Tracking params, fragments, meaningful params, identical titles ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_url_normalization_identity_and_identical_titles(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [
            {"title": "Same Title News", "url": "https://example.com/article?id=10&utm_source=rss#top"},
            {"title": "Same Title News", "url": "https://example.com/article?id=10&utm_medium=feed"},
            {"title": "Same Title News", "url": "https://example.com/article?id=20"},
        ]

        def extract_side_effect(article, timeout=10):
            return dict(article, content="Extracted text content here")

        mock_extract.side_effect = extract_side_effect

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        results = run_source(source, db_path=self.temp_db_path)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["url"], "https://example.com/article?id=10&utm_source=rss#top")
        self.assertEqual(results[1]["url"], "https://example.com/article?id=20")

    # --- Test 8 & 9: Extraction failure does not permanently block retry ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_extraction_failure_allows_retry(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [{"title": "Flaky Article", "url": "https://example.com/flaky"}]

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        # Run 1: Extraction fails (returns None)
        mock_extract.return_value = None
        run1 = run_source(source, db_path=self.temp_db_path)
        self.assertEqual(len(run1), 0)

        norm_url = normalize_url("https://example.com/flaky")
        self.assertEqual(get_article_status(norm_url, self.temp_db_path), "failed")

        # Run 2: Retry succeeds
        mock_extract.return_value = {"title": "Flaky Article", "url": "https://example.com/flaky", "content": "Text"}
        run2 = run_source(source, db_path=self.temp_db_path)
        self.assertEqual(len(run2), 1)
        self.assertEqual(get_article_status(norm_url, self.temp_db_path), "completed")

    def test_orphan_processing_article_is_retried(self):
        """A prior crashed run leaves status='processing'; next run must retry."""
        norm_url = normalize_url("https://example.com/crashed-article")

        from database import record_article
        record_article(
            url="https://example.com/crashed-article",
            normalized_url=norm_url,
            status="processing",
            db_path=self.temp_db_path,
        )

        self.assertEqual(
            get_article_status(norm_url, self.temp_db_path),
            "processing",
        )
        self.assertFalse(
            is_article_completed(norm_url, self.temp_db_path),
            "processing must not count as completed",
        )

        with patch("pipeline.fetch_rss") as mock_fetch, \
             patch("pipeline.parse_entries") as mock_parse, \
             patch("pipeline.extract_article") as mock_extract:

            mock_fetch.return_value = [{"raw": "data"}]
            mock_parse.return_value = [
                {"title": "Crashed Article",
                 "url": "https://example.com/crashed-article"}
            ]
            mock_extract.return_value = {
                "title": "Crashed Article",
                "url": "https://example.com/crashed-article",
                "content": "Recovered text",
            }

            source = {"name": "Test Source", "url": "https://example.com/rss"}
            results = run_source(source, db_path=self.temp_db_path)

        self.assertEqual(len(results), 1)
        self.assertEqual(mock_extract.call_count, 1)

        self.assertEqual(
            get_article_status(norm_url, self.temp_db_path),
            "completed",
        )

    # --- Test 10: Persistent deduplication across DB connections ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_persistence_across_db_connections(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [{"title": "Persisted Article", "url": "https://example.com/persisted"}]
        mock_extract.return_value = {"title": "Persisted Article", "url": "https://example.com/persisted", "content": "Text"}

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        # Process in connection 1
        run_source(source, db_path=self.temp_db_path)

        # Connection 2 / process 2 checks status
        norm_url = normalize_url("https://example.com/persisted")
        self.assertTrue(is_article_completed(norm_url, self.temp_db_path))

    # --- Test 11: Disabled sources remain ignored ---
    @patch("pipeline.fetch_rss")
    def test_disabled_sources_ignored(self, mock_fetch):
        source = {"name": "Disabled", "url": "https://example.com/rss", "enabled": False}
        results = run_source(source, db_path=self.temp_db_path)
        self.assertEqual(results, [])
        mock_fetch.assert_not_called()

    # --- Test 12: db_path=None disables persistent DB tracking ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_db_path_none_behavior(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = [
            {"title": "No DB Art", "url": "https://example.com/nodb"},
            {"title": "No DB Art Dup", "url": "https://example.com/nodb?utm_source=x"},
        ]
        mock_extract.return_value = {"title": "No DB Art", "url": "https://example.com/nodb", "content": "Text"}

        source = {"name": "Test Source", "url": "https://example.com/rss"}

        # With db_path=None, in-run memory deduplication still prevents dup in same run
        results = run_source(source, db_path=None)
        self.assertEqual(len(results), 1)

        # But DB status is not written
        norm_url = normalize_url("https://example.com/nodb")
        self.assertIsNone(get_article_status(norm_url, self.temp_db_path))

    # --- Test 13: RSS fetch failure ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_fetch_failure(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = []
        source = {"name": "Failed Fetch Source", "url": "https://example.com/rss-fail"}
        result = run_source(source, db_path=self.temp_db_path)
        mock_fetch.assert_called_once_with("https://example.com/rss-fail", timeout=10)
        mock_parse.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(result, [])

    # --- Test 14: Empty parsed entries ---
    @patch("pipeline.extract_article")
    @patch("pipeline.parse_entries")
    @patch("pipeline.fetch_rss")
    def test_run_source_empty_parsed_entries(self, mock_fetch, mock_parse, mock_extract):
        mock_fetch.return_value = [{"raw": "data"}]
        mock_parse.return_value = []
        source = {"name": "Parse Fail Source", "url": "https://example.com/rss-parse-fail"}
        result = run_source(source, db_path=self.temp_db_path)
        mock_fetch.assert_called_once_with("https://example.com/rss-parse-fail", timeout=10)
        mock_parse.assert_called_once_with([{"raw": "data"}])
        mock_extract.assert_not_called()
        self.assertEqual(result, [])

    # --- Test 15: Invalid source input ---
    @patch("pipeline.fetch_rss")
    def test_run_source_invalid_source_input(self, mock_fetch):
        self.assertEqual(run_source(None, db_path=self.temp_db_path), [])
        self.assertEqual(run_source("not a dict", db_path=self.temp_db_path), [])
        self.assertEqual(run_source({"name": "No URL"}, db_path=self.temp_db_path), [])
        self.assertEqual(run_source({"name": "Empty URL", "url": "   "}, db_path=self.temp_db_path), [])
        mock_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
