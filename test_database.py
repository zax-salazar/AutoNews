import os
import tempfile
import unittest
from database import (
    normalize_url,
    init_db,
    get_article_status,
    is_article_completed,
    record_article,
    mark_article_status,
    get_connection,
)


class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")

    def tearDown(self):
        os.close(self.temp_db_fd)
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    # --- URL Normalization Tests ---
    def test_normalize_url_tracking_parameters_and_fragments(self):
        raw = "HTTPS://WWW.Example.COM:443/article/news/?utm_source=newsletter&utm_medium=email&fbclid=12345&id=99#comments"
        expected = "https://www.example.com/article/news?id=99"
        self.assertEqual(normalize_url(raw), expected)

    def test_normalize_url_default_ports_and_trailing_slashes(self):
        raw_http = "http://example.com:80/path/to/page/"
        self.assertEqual(normalize_url(raw_http), "http://example.com/path/to/page")

        raw_https = "https://example.com:443/path/to/page/"
        self.assertEqual(normalize_url(raw_https), "https://example.com/path/to/page")

        root_url = "https://example.com/"
        self.assertEqual(normalize_url(root_url), "https://example.com/")

    def test_normalize_url_canonical_query_param_sorting(self):
        url1 = "https://example.com/item?z=2&a=1&m=3"
        url2 = "https://example.com/item?a=1&m=3&z=2"
        self.assertEqual(normalize_url(url1), "https://example.com/item?a=1&m=3&z=2")
        self.assertEqual(normalize_url(url1), normalize_url(url2))

    def test_normalize_url_preserve_meaningful_query_params(self):
        url_a = "https://example.com/article?id=101"
        url_b = "https://example.com/article?id=102"
        self.assertNotEqual(normalize_url(url_a), normalize_url(url_b))

    def test_normalize_url_empty_or_invalid(self):
        self.assertEqual(normalize_url(""), "")
        self.assertEqual(normalize_url(None), "")
        self.assertEqual(normalize_url("   "), "")

    # --- Database Operations Tests ---
    def test_init_db_and_record_article(self):
        init_db(self.temp_db_path)

        raw_url = "https://example.com/art-1?utm_source=rss"
        norm_url = normalize_url(raw_url)

        self.assertIsNone(get_article_status(norm_url, self.temp_db_path))
        self.assertFalse(is_article_completed(norm_url, self.temp_db_path))

        record_article(
            url=raw_url,
            normalized_url=norm_url,
            source_name="PC Gamer",
            title="Test Title",
            status="pending",
            db_path=self.temp_db_path,
        )

        self.assertEqual(get_article_status(norm_url, self.temp_db_path), "pending")

    def test_mark_article_status_and_completion(self):
        init_db(self.temp_db_path)
        norm_url = "https://example.com/art-2"

        record_article(
            url=norm_url,
            normalized_url=norm_url,
            source_name="PC Gamer",
            title="Title",
            status="processing",
            db_path=self.temp_db_path,
        )

        self.assertEqual(get_article_status(norm_url, self.temp_db_path), "processing")
        self.assertFalse(is_article_completed(norm_url, self.temp_db_path))

        mark_article_status(norm_url, status="completed", title="Extracted Title", db_path=self.temp_db_path)

        self.assertEqual(get_article_status(norm_url, self.temp_db_path), "completed")
        self.assertTrue(is_article_completed(norm_url, self.temp_db_path))

    def test_upsert_on_conflict(self):
        init_db(self.temp_db_path)
        norm_url = "https://example.com/art-3"

        record_article(url=norm_url, normalized_url=norm_url, status="failed", error_message="Network error", db_path=self.temp_db_path)
        self.assertEqual(get_article_status(norm_url, self.temp_db_path), "failed")

        # Retry record
        record_article(url=norm_url, normalized_url=norm_url, status="processing", db_path=self.temp_db_path)
        self.assertEqual(get_article_status(norm_url, self.temp_db_path), "processing")

    def test_persistence_across_separate_connections(self):
        init_db(self.temp_db_path)
        norm_url = "https://example.com/persistent-art"

        record_article(url=norm_url, normalized_url=norm_url, status="completed", db_path=self.temp_db_path)

        # Simulate separate process / connection opening the DB file anew
        conn2 = get_connection(self.temp_db_path)
        cursor = conn2.cursor()
        cursor.execute("SELECT status FROM articles WHERE normalized_url = ?", (norm_url,))
        row = cursor.fetchone()
        conn2.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "completed")


if __name__ == "__main__":
    unittest.main()
