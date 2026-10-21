import os
import sqlite3
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
    save_article_data,
    save_research_data,
    get_article_data,
    get_research_data,
    mark_research_status,
    mark_publish_status,
    get_pending_research,
    get_pending_publish,
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

    def test_orphan_processing_is_not_considered_completed(self):
        """A crashed run leaves status='processing'; next run must be able to retry."""
        init_db(self.temp_db_path)
        norm_url = "https://example.com/orphan-processing"

        record_article(
            url=norm_url,
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
            "processing must not be treated as completed; "
            "otherwise crashed runs never retry.",
        )

    def test_none_db_path_is_a_noop(self):
        """db_path=None must not persist anything and must not open any DB."""
        init_db(self.temp_db_path)

        url = "https://example.com/none-db"
        norm = normalize_url(url)

        # These must silently no-op (early return on falsy db_path).
        init_db(None)
        record_article(
            url=url,
            normalized_url=norm,
            status="completed",
            db_path=None,
        )
        mark_article_status(norm, status="completed", db_path=None)

        # Even though we passed status="completed" above with db_path=None,
        # the temp DB must remain untouched.
        self.assertIsNone(get_article_status(norm, self.temp_db_path))
        self.assertFalse(is_article_completed(norm, self.temp_db_path))

    # --- Schema Migration & Research/Publish Persistence Tests ---
    def test_migration_on_existing_db(self):
        conn = sqlite3.connect(self.temp_db_path)
        conn.execute("""
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                normalized_url TEXT NOT NULL UNIQUE,
                source_name TEXT,
                title TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "INSERT INTO articles (url, normalized_url, title) VALUES (?, ?, ?)",
            ("https://x", "https://x", "Old Title"),
        )
        conn.commit()
        conn.close()

        init_db(self.temp_db_path)

        conn2 = get_connection(self.temp_db_path)
        cols = {r["name"] for r in conn2.execute("PRAGMA table_info(articles)")}
        for required in ("article_data", "research_data", "research_status", "publish_status"):
            self.assertIn(required, cols)

        row = conn2.execute(
            "SELECT title, research_status, publish_status FROM articles WHERE normalized_url = ?",
            ("https://x",),
        ).fetchone()
        conn2.close()

        self.assertEqual(row["title"], "Old Title")
        self.assertEqual(row["research_status"], "pending")
        self.assertEqual(row["publish_status"], "pending")

    def test_save_and_get_article_data(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/art-data"
        record_article("https://example.com/art-data", norm, db_path=self.temp_db_path)

        self.assertIsNone(get_article_data(norm, self.temp_db_path))

        data = {"title": "Title", "content": "Body content"}
        save_article_data(norm, data, self.temp_db_path)

        retrieved = get_article_data(norm, self.temp_db_path)
        self.assertEqual(retrieved, data)

    def test_save_and_get_research_data(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/res-data"
        record_article("https://example.com/res-data", norm, db_path=self.temp_db_path)

        self.assertIsNone(get_research_data(norm, self.temp_db_path))

        res_data = {"title": "عنوان", "body": "متن"}
        save_research_data(norm, res_data, self.temp_db_path)

        retrieved = get_research_data(norm, self.temp_db_path)
        self.assertEqual(retrieved, res_data)

    def test_save_research_data_overwrites(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/res-overwrite"
        record_article("https://example.com/res-overwrite", norm, db_path=self.temp_db_path)

        save_research_data(norm, {"body": "v1"}, self.temp_db_path)
        save_research_data(norm, {"body": "v2"}, self.temp_db_path)

        retrieved = get_research_data(norm, self.temp_db_path)
        self.assertEqual(retrieved["body"], "v2")

    def test_mark_research_status_valid_values(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/res-status"
        record_article(norm, norm, db_path=self.temp_db_path)

        mark_research_status(norm, "completed", db_path=self.temp_db_path)
        mark_research_status(norm, "failed", error_message="LLM Error", db_path=self.temp_db_path)

    def test_mark_research_status_invalid_value_raises(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/res-invalid"
        with self.assertRaises(ValueError):
            mark_research_status(norm, "unknown_status", db_path=self.temp_db_path)

    def test_mark_publish_status_valid_values(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/pub-status"
        record_article(norm, norm, db_path=self.temp_db_path)

        mark_publish_status(norm, "completed", db_path=self.temp_db_path)
        mark_publish_status(norm, "failed", error_message="HTTP Error", db_path=self.temp_db_path)

    def test_mark_publish_status_invalid_value_raises(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/pub-invalid"
        with self.assertRaises(ValueError):
            mark_publish_status(norm, "invalid_status", db_path=self.temp_db_path)

    def test_get_pending_research_empty(self):
        init_db(self.temp_db_path)
        self.assertEqual(get_pending_research(self.temp_db_path), [])

    def test_get_pending_research_returns_pending(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/pend-res"
        record_article(norm, norm, status="completed", db_path=self.temp_db_path)
        save_article_data(norm, {"title": "Art"}, self.temp_db_path)

        pending = get_pending_research(self.temp_db_path)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["normalized_url"], norm)
        self.assertEqual(pending[0]["article_data"], {"title": "Art"})

    def test_get_pending_research_returns_failed(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/failed-res"
        record_article(norm, norm, status="completed", db_path=self.temp_db_path)
        mark_research_status(norm, "failed", db_path=self.temp_db_path)

        pending = get_pending_research(self.temp_db_path)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["normalized_url"], norm)

    def test_get_pending_research_excludes_completed(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/done-res"
        record_article(norm, norm, status="completed", db_path=self.temp_db_path)
        mark_research_status(norm, "completed", db_path=self.temp_db_path)

        self.assertEqual(get_pending_research(self.temp_db_path), [])

    def test_get_pending_research_excludes_non_completed_extraction(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/failed-ext"
        record_article(norm, norm, status="failed", db_path=self.temp_db_path)

        self.assertEqual(get_pending_research(self.temp_db_path), [])

    def test_get_pending_publish_requires_completed_research(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/pub-no-res"
        record_article(norm, norm, status="completed", db_path=self.temp_db_path)

        self.assertEqual(get_pending_publish(self.temp_db_path), [])

    def test_get_pending_publish_returns_pending_and_failed(self):
        init_db(self.temp_db_path)
        norm1 = "https://example.com/pub-p"
        norm2 = "https://example.com/pub-f"

        record_article(norm1, norm1, status="completed", db_path=self.temp_db_path)
        mark_research_status(norm1, "completed", db_path=self.temp_db_path)
        save_research_data(norm1, {"body": "b1"}, self.temp_db_path)

        record_article(norm2, norm2, status="completed", db_path=self.temp_db_path)
        mark_research_status(norm2, "completed", db_path=self.temp_db_path)
        mark_publish_status(norm2, "failed", db_path=self.temp_db_path)
        save_research_data(norm2, {"body": "b2"}, self.temp_db_path)

        pending = get_pending_publish(self.temp_db_path)
        self.assertEqual(len(pending), 2)

    def test_new_columns_nullable_by_default(self):
        init_db(self.temp_db_path)
        norm = "https://example.com/nullable-defaults"
        record_article(norm, norm, db_path=self.temp_db_path)

        conn = get_connection(self.temp_db_path)
        row = conn.execute("SELECT * FROM articles WHERE normalized_url = ?", (norm,)).fetchone()
        conn.close()

        self.assertIsNone(row["article_data"])
        self.assertIsNone(row["research_data"])
        self.assertEqual(row["research_status"], "pending")
        self.assertEqual(row["publish_status"], "pending")


if __name__ == "__main__":
    unittest.main()
