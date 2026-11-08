import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from database import (
    DEFAULT_DB_PATH,
    init_db,
    is_article_completed,
    get_article_status,
    get_article_data,
    save_article_data,
    save_research_data,
    mark_research_status,
    mark_publish_status,
    record_article,
    normalize_url,
)
from publisher import NullPublisher
from research import NullProvider
from scheduler import (
    run_once,
    run_forever,
    parse_args,
    main,
)


class TestScheduler(unittest.TestCase):

    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        init_db(self.temp_db_path)

    def tearDown(self):
        os.close(self.temp_db_fd)
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    # --- run_once basics ---
    def test_run_once_empty_sources(self):
        llm = NullProvider()
        pub = NullPublisher()
        summary = run_once([], llm, pub)
        self.assertEqual(summary["extracted"], 0)
        self.assertEqual(summary["researched"], 0)
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["research_failures"], 0)
        self.assertEqual(summary["publish_failures"], 0)
        self.assertEqual(summary["research_results"], [])
        self.assertEqual(summary["publish_results"], [])

    def test_run_once_requires_llm_provider(self):
        pub = NullPublisher()
        with self.assertRaises(ValueError):
            run_once([{"name": "A"}], None, pub)

    def test_run_once_requires_publisher_provider(self):
        llm = NullProvider()
        with self.assertRaises(ValueError):
            run_once([{"name": "A"}], llm, None)

    # --- happy path ---
    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_happy_path(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": "Art 1", "url": "U1"},
            {"title": "Art 2", "url": "U2"},
        ]
        mock_research.side_effect = [
            {"title": "Res 1", "body": "B1"},
            {"title": "Res 2", "body": "B2"},
        ]
        mock_publish.return_value = {"ok": True, "id": "x", "error": None}

        llm = NullProvider()
        pub = NullPublisher()
        sources = [{"name": "S1"}]

        summary = run_once(sources, llm, pub, db_path=self.temp_db_path)

        self.assertEqual(summary["extracted"], 2)
        self.assertEqual(summary["researched"], 2)
        self.assertEqual(summary["published"], 2)
        self.assertEqual(summary["research_failures"], 0)
        self.assertEqual(summary["publish_failures"], 0)
        self.assertEqual(len(summary["research_results"]), 2)
        self.assertEqual(len(summary["publish_results"]), 2)

    # --- failure handling ---
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_research_returns_none_counts_as_failure(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = [
            {"title": "Art 1", "url": "U1"},
            {"title": "Art 2", "url": "U2"},
        ]
        mock_research.side_effect = [
            None,  # First article fails research
            {"title": "Res 2", "body": "B2"},  # Second article succeeds
        ]
        mock_publish.return_value = {"ok": True, "id": "x", "error": None}

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["extracted"], 2)
        self.assertEqual(summary["researched"], 1)
        self.assertEqual(summary["published"], 1)
        self.assertEqual(summary["research_failures"], 1)
        self.assertEqual(summary["publish_failures"], 0)

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_research_raises_counts_as_failure(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = [{"title": "Art 1", "url": "U1"}]
        mock_research.side_effect = RuntimeError("Research crash")

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["extracted"], 1)
        self.assertEqual(summary["researched"], 0)
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["research_failures"], 1)
        mock_publish.assert_not_called()

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_publish_failure_counts(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = [{"title": "Art 1", "url": "U1"}]
        mock_research.return_value = {"title": "Res 1", "body": "B1"}
        mock_publish.return_value = {"ok": False, "id": None, "error": "Publish error"}

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["extracted"], 1)
        self.assertEqual(summary["researched"], 1)
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["publish_failures"], 1)

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_publish_raises_counts_as_failure(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = [{"title": "Art 1", "url": "U1"}]
        mock_research.return_value = {"title": "Res 1", "body": "B1"}
        mock_publish.side_effect = RuntimeError("Publish crash")

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["extracted"], 1)
        self.assertEqual(summary["researched"], 1)
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["publish_failures"], 1)

    # --- limit ---
    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_limit_truncates(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": f"Art {i}", "url": f"U{i}"} for i in range(5)
        ]
        mock_research.return_value = {"title": "Res", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "x", "error": None}

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), db_path=self.temp_db_path, limit=2)

        self.assertEqual(summary["extracted"], 5)
        self.assertEqual(summary["researched"], 2)
        self.assertEqual(summary["published"], 2)
        self.assertEqual(mock_research.call_count, 2)
        self.assertEqual(mock_publish.call_count, 2)

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_limit_zero_means_no_limit(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": f"Art {i}", "url": f"U{i}"} for i in range(3)
        ]
        mock_research.return_value = {"title": "Res", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "x", "error": None}

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), db_path=self.temp_db_path, limit=0)

        self.assertEqual(summary["extracted"], 3)
        self.assertEqual(summary["researched"], 3)
        self.assertEqual(summary["published"], 3)

    # --- run_forever ---
    def test_run_forever_rejects_non_positive_interval(self):
        with self.assertRaises(ValueError):
            run_forever(0, [], NullProvider(), NullPublisher())
        with self.assertRaises(ValueError):
            run_forever(-1, [], NullProvider(), NullPublisher())

    @patch("scheduler.time.sleep")
    @patch("scheduler.run_once")
    def test_run_forever_calls_run_once_n_times(self, mock_run_once, mock_sleep):
        run_forever(
            interval=10,
            sources=[{"name": "S"}],
            llm_provider=NullProvider(),
            publisher_provider=NullPublisher(),
            max_cycles=3,
        )

        self.assertEqual(mock_run_once.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(10)

    @patch("scheduler.time.sleep")
    @patch("scheduler.run_once")
    def test_run_forever_continues_after_run_once_raises(self, mock_run_once, mock_sleep):
        mock_run_once.side_effect = [RuntimeError("Cycle 1 boom"), {}]

        run_forever(
            interval=5,
            sources=[{"name": "S"}],
            llm_provider=NullProvider(),
            publisher_provider=NullPublisher(),
            max_cycles=2,
        )

        self.assertEqual(mock_run_once.call_count, 2)
        self.assertEqual(mock_sleep.call_count, 1)

    # --- parse_args / main ---
    def test_parse_args_defaults(self):
        args = parse_args([])
        self.assertEqual(args.db_path, DEFAULT_DB_PATH)
        self.assertEqual(args.timeout, 10)
        self.assertEqual(args.interval, 0)
        self.assertEqual(args.language, "fa")
        self.assertIsNone(args.source)
        self.assertIsNone(args.limit)

    def test_parse_args_db_path_none_string(self):
        args1 = parse_args(["--db-path", "none"])
        self.assertIsNone(args1.db_path)

        args2 = parse_args(["--db-path", "NONE"])
        self.assertIsNone(args2.db_path)

    def test_parse_args_interval_positive(self):
        args = parse_args(["--interval", "60"])
        self.assertEqual(args.interval, 60)

    @patch("scheduler.run_once")
    @patch("scheduler.research.get_default_provider")
    @patch("scheduler.publisher.get_default_publisher")
    @patch("scheduler.SOURCES", [{"name": "A", "url": "u"}])
    def test_main_runs_once_by_default(self, mock_get_pub, mock_get_llm, mock_run_once):
        mock_run_once.return_value = {
            "extracted": 1,
            "researched": 1,
            "published": 1,
            "research_failures": 0,
            "publish_failures": 0,
            "research_results": [],
            "publish_results": [],
        }

        exit_code = main([])
        self.assertEqual(exit_code, 0)
        mock_run_once.assert_called_once()

    @patch("scheduler.run_forever")
    @patch("scheduler.research.get_default_provider")
    @patch("scheduler.publisher.get_default_publisher")
    @patch("scheduler.SOURCES", [{"name": "A", "url": "u"}])
    def test_main_uses_interval_when_set(self, mock_get_pub, mock_get_llm, mock_run_forever):
        exit_code = main(["--interval", "5", "--max-cycles", "2"])
        self.assertEqual(exit_code, 0)
        mock_run_forever.assert_called_once()
        self.assertEqual(mock_run_forever.call_args[1]["interval"], 5)
        self.assertEqual(mock_run_forever.call_args[1]["max_cycles"], 2)

    @patch("scheduler.run_once")
    @patch("scheduler.SOURCES", [{"name": "PC Gamer", "url": "u"}])
    def test_main_no_matching_source_returns_1(self, mock_run_once):
        exit_code = main(["--source", "nonexistent"])
        self.assertEqual(exit_code, 1)
        mock_run_once.assert_not_called()

    # --- Persistence tests (failed articles abandoned, not retried) ---
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_does_not_retry_failed_research(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = []
        norm_url = normalize_url("https://example.com/retry-res")
        art_data = {"title": "Pre-seeded", "url": "https://example.com/retry-res"}

        record_article("https://example.com/retry-res", norm_url, status="completed", db_path=self.temp_db_path)
        save_article_data(norm_url, art_data, db_path=self.temp_db_path)
        mark_research_status(norm_url, "failed", error_message="Previous error", db_path=self.temp_db_path)

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["researched"], 0)
        self.assertEqual(summary["published"], 0)
        mock_research.assert_not_called()

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_does_not_retry_failed_publish(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = []
        norm_url = normalize_url("https://example.com/retry-pub")

        record_article("https://example.com/retry-pub", norm_url, status="completed", db_path=self.temp_db_path)
        mark_research_status(norm_url, "completed", db_path=self.temp_db_path)
        save_research_data(norm_url, {"title": "Res", "body": "B"}, db_path=self.temp_db_path)
        mark_publish_status(norm_url, "failed", error_message="Previous pub error", db_path=self.temp_db_path)

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["researched"], 0)
        self.assertEqual(summary["published"], 0)
        mock_research.assert_not_called()
        mock_publish.assert_not_called()

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_skips_completed_articles(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = []
        norm_url = normalize_url("https://example.com/done")

        record_article("https://example.com/done", norm_url, status="completed", db_path=self.temp_db_path)
        mark_research_status(norm_url, "completed", db_path=self.temp_db_path)
        mark_publish_status(norm_url, "completed", db_path=self.temp_db_path)

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["researched"], 0)
        self.assertEqual(summary["published"], 0)
        mock_research.assert_not_called()
        mock_publish.assert_not_called()

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_limit_only_affects_new_extractions(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        norm_url_pending = normalize_url("https://example.com/pending-res-item")
        art_pending = {"title": "Pending", "url": "https://example.com/pending-res-item"}
        record_article("https://example.com/pending-res-item", norm_url_pending, status="completed", db_path=self.temp_db_path)
        save_article_data(norm_url_pending, art_pending, db_path=self.temp_db_path)

        mock_run_sources.return_value = [
            {"title": f"New {i}", "url": f"https://example.com/new-{i}"} for i in range(3)
        ]
        mock_research.return_value = {"title": "Res", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "p", "error": None}

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), limit=1, db_path=self.temp_db_path)

        self.assertEqual(summary["extracted"], 3)
        self.assertEqual(summary["researched"], 2)  # 1 pending from db + 1 new (limited to 1)
        self.assertEqual(summary["published"], 2)

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_none_db_path_skips_retries(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = []
        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), db_path=None)

        self.assertEqual(summary["extracted"], 0)
        self.assertEqual(summary["researched"], 0)
        self.assertEqual(summary["published"], 0)
        mock_research.assert_not_called()
        mock_publish.assert_not_called()

    # --- New tests for pacing delay and daily limit ---
    @patch.dict(os.environ, {"AUTONEWS_RESEARCH_DELAY": "2.5"}, clear=True)
    def test_research_delay_env_override(self):
        from scheduler import _research_delay
        self.assertEqual(_research_delay(), 2.5)

    @patch.dict(os.environ, {"AUTONEWS_DAILY_LIMIT": "10"}, clear=True)
    def test_daily_limit_env_override(self):
        from scheduler import _daily_limit
        self.assertEqual(_daily_limit(), 10)

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_sleeps_between_research_calls(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": "Art 1", "url": "U1"},
            {"title": "Art 2", "url": "U2"},
            {"title": "Art 3", "url": "U3"},
        ]
        mock_research.side_effect = [
            {"title": "R1", "body": "B1"},
            {"title": "R2", "body": "B2"},
            {"title": "R3", "body": "B3"},
        ]
        mock_publish.return_value = {"ok": True, "id": "x"}

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["researched"], 3)
        # 3 articles -> 2 sleeps between them
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(4.0)

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_does_not_sleep_after_last_article(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": "Art 1", "url": "U1"},
        ]
        mock_research.return_value = {"title": "R1", "body": "B1"}
        mock_publish.return_value = {"ok": True, "id": "x"}

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["researched"], 1)
        # Single article -> no sleep
        mock_sleep.assert_not_called()

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_respects_daily_limit(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": f"Art {i}", "url": f"https://example.com/art-{i}"} for i in range(5)
        ]
        mock_research.return_value = {"title": "R", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "x"}

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path, daily_limit=2)

        self.assertEqual(summary["researched"], 2)
        self.assertEqual(mock_research.call_count, 2)

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_daily_limit_zero_means_unlimited(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": f"Art {i}", "url": f"https://example.com/art-{i}"} for i in range(6)
        ]
        mock_research.return_value = {"title": "R", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "x"}

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path, daily_limit=0)

        self.assertEqual(summary["researched"], 6)
        self.assertEqual(mock_research.call_count, 6)

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_daily_limit_already_reached(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        # Pre-seed 3 completed articles today
        for i in range(3):
            url = f"https://example.com/done-{i}"
            record_article(url, url, status="completed", db_path=self.temp_db_path)
            mark_research_status(url, "completed", db_path=self.temp_db_path)

        mock_run_sources.return_value = [
            {"title": "New Art", "url": "https://example.com/new"}
        ]

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path, daily_limit=3)

        self.assertEqual(summary["researched"], 0)
        mock_research.assert_not_called()

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_failed_research_does_not_count_toward_daily_limit(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": "Art 1", "url": "https://example.com/art-1"},
            {"title": "Art 2", "url": "https://example.com/art-2"},
        ]
        # First article fails research, second succeeds
        mock_research.side_effect = [
            None,
            {"title": "R2", "body": "B2"},
        ]
        mock_publish.return_value = {"ok": True, "id": "x"}

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path, daily_limit=2)

        self.assertEqual(summary["researched"], 1)
        self.assertEqual(summary["research_failures"], 1)
        self.assertEqual(mock_research.call_count, 2)

    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_no_db_path_skips_daily_check(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        mock_run_sources.return_value = [
            {"title": "Art 1", "url": "https://example.com/art-1"},
            {"title": "Art 2", "url": "https://example.com/art-2"},
        ]
        mock_research.return_value = {"title": "R", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "x"}

        summary = run_once([], NullProvider(), NullPublisher(), db_path=None, daily_limit=1)

        # db_path=None skips the daily cap check
        self.assertEqual(summary["researched"], 2)
        self.assertEqual(mock_research.call_count, 2)

    def test_main_accepts_daily_limit_flag(self):
        args = parse_args(["--daily-limit", "5"])
        self.assertEqual(args.daily_limit, 5)

    # --- New Tests for Attempt-Based Daily Limits & Abandoning Failures ---
    @patch("scheduler.time.sleep")
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_respects_daily_limit_on_attempts(self, mock_publish, mock_research, mock_run_sources, mock_sleep):
        # Pre-seed DB with 2 articles attempted today (one completed, one failed)
        record_article("https://x/1", "https://x/1", status="completed", db_path=self.temp_db_path)
        mark_research_status("https://x/1", "completed", db_path=self.temp_db_path)

        record_article("https://x/2", "https://x/2", status="completed", db_path=self.temp_db_path)
        mark_research_status("https://x/2", "failed", db_path=self.temp_db_path)

        # Pre-seed 5 pending articles
        for i in range(3, 8):
            url = f"https://x/{i}"
            record_article(url, url, status="completed", db_path=self.temp_db_path)
            save_article_data(url, {"title": f"T{i}", "url": url}, db_path=self.temp_db_path)

        mock_run_sources.return_value = []
        mock_research.return_value = {"title": "R", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "p"}

        # daily_limit = 3; already attempted = 2; remaining = 1
        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path, daily_limit=3)

        self.assertEqual(summary["researched"], 1)
        self.assertEqual(mock_research.call_count, 1)

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_failed_articles_not_retried_next_run(self, mock_publish, mock_research, mock_run_sources):
        for i in range(3):
            url = f"https://x/failed-{i}"
            record_article(url, url, status="completed", db_path=self.temp_db_path)
            save_article_data(url, {"title": f"F{i}", "url": url}, db_path=self.temp_db_path)
            mark_research_status(url, "failed", db_path=self.temp_db_path)

        mock_run_sources.return_value = []

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["researched"], 0)
        mock_research.assert_not_called()

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_failed_publish_not_retried_next_run(self, mock_publish, mock_research, mock_run_sources):
        url = "https://x/failed-pub"
        record_article(url, url, status="completed", db_path=self.temp_db_path)
        mark_research_status(url, "completed", db_path=self.temp_db_path)
        save_research_data(url, {"title": "R", "body": "B"}, db_path=self.temp_db_path)
        mark_publish_status(url, "failed", db_path=self.temp_db_path)

        mock_run_sources.return_value = []

        summary = run_once([], NullProvider(), NullPublisher(), db_path=self.temp_db_path)

        self.assertEqual(summary["published"], 0)
        mock_publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
