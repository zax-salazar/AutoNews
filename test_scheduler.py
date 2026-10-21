import unittest
from unittest.mock import patch, MagicMock
from database import DEFAULT_DB_PATH
from publisher import NullPublisher
from research import NullProvider
from scheduler import (
    run_once,
    run_forever,
    parse_args,
    main,
)


class TestScheduler(unittest.TestCase):

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
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_happy_path(self, mock_publish, mock_research, mock_run_sources):
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

        summary = run_once(sources, llm, pub)

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

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher())

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

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher())

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

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher())

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

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher())

        self.assertEqual(summary["extracted"], 1)
        self.assertEqual(summary["researched"], 1)
        self.assertEqual(summary["published"], 0)
        self.assertEqual(summary["publish_failures"], 1)

    # --- limit ---
    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_limit_truncates(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = [
            {"title": f"Art {i}", "url": f"U{i}"} for i in range(5)
        ]
        mock_research.return_value = {"title": "Res", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "x", "error": None}

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), limit=2)

        self.assertEqual(summary["extracted"], 5)
        self.assertEqual(summary["researched"], 2)
        self.assertEqual(summary["published"], 2)
        self.assertEqual(mock_research.call_count, 2)
        self.assertEqual(mock_publish.call_count, 2)

    @patch("scheduler.pipeline.run_sources")
    @patch("scheduler.research.research_article")
    @patch("scheduler.publisher.publish_article")
    def test_run_once_limit_zero_means_no_limit(self, mock_publish, mock_research, mock_run_sources):
        mock_run_sources.return_value = [
            {"title": f"Art {i}", "url": f"U{i}"} for i in range(3)
        ]
        mock_research.return_value = {"title": "Res", "body": "B"}
        mock_publish.return_value = {"ok": True, "id": "x", "error": None}

        summary = run_once([{"name": "S"}], NullProvider(), NullPublisher(), limit=0)

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


if __name__ == "__main__":
    unittest.main()
