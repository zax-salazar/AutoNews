import unittest
from unittest.mock import patch, MagicMock
from database import DEFAULT_DB_PATH
from main import (
    parse_args,
    filter_sources,
    summarize,
    main,
)


class TestMain(unittest.TestCase):

    def test_parse_args_defaults(self):
        args = parse_args([])
        self.assertEqual(args.db_path, DEFAULT_DB_PATH)
        self.assertEqual(args.timeout, 10)
        self.assertIsNone(args.source)
        self.assertFalse(args.dry_run)
        self.assertFalse(args.verbose)

    def test_parse_args_db_path_none_string(self):
        args_lower = parse_args(["--db-path", "none"])
        self.assertIsNone(args_lower.db_path)

        args_upper = parse_args(["--db-path", "NONE"])
        self.assertIsNone(args_upper.db_path)

    def test_parse_args_dry_run_sets_flag(self):
        args = parse_args(["--dry-run"])
        self.assertTrue(args.dry_run)

    def test_filter_sources_no_filter(self):
        sources = [{"name": "A"}, {"name": "B"}]
        self.assertEqual(filter_sources(sources, None), sources)
        self.assertEqual(filter_sources(sources, ""), sources)

    def test_filter_sources_matches_case_insensitive(self):
        sources = [{"name": "PC Gamer"}, {"name": "IGN"}]
        filtered = filter_sources(sources, "pc gamer")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "PC Gamer")

    def test_filter_sources_no_match_returns_empty(self):
        sources = [{"name": "PC Gamer"}]
        self.assertEqual(filter_sources(sources, "nope"), [])

    def test_summarize_empty(self):
        self.assertEqual(summarize([]), "No articles processed.")
        self.assertEqual(summarize(None), "No articles processed.")

    def test_summarize_with_articles(self):
        articles = [
            {"title": "T1", "url": "U1"},
            {"url": "U2"},
        ]
        result = summarize(articles)
        self.assertIn("Processed 2 article(s):", result)
        self.assertIn("  - T1  (U1)", result)
        self.assertIn("  - (no title)  (U2)", result)

    @patch("main.run_sources")
    @patch("main.SOURCES", [{"name": "PC Gamer", "url": "https://example.com/rss"}])
    def test_main_calls_run_sources_with_correct_args(self, mock_run_sources):
        mock_run_sources.return_value = [{"title": "T1", "url": "U1"}]

        exit_code = main(["--timeout", "5", "--db-path", "/tmp/x.db"])

        mock_run_sources.assert_called_once_with(
            [{"name": "PC Gamer", "url": "https://example.com/rss"}],
            timeout=5,
            db_path="/tmp/x.db",
        )
        self.assertEqual(exit_code, 0)

    @patch("main.run_sources")
    @patch("main.SOURCES", [{"name": "A", "url": "u"}])
    def test_main_dry_run_forces_none_db_path(self, mock_run_sources):
        mock_run_sources.return_value = []

        exit_code = main(["--dry-run"])

        mock_run_sources.assert_called_once_with(
            [{"name": "A", "url": "u"}],
            timeout=10,
            db_path=None,
        )
        self.assertEqual(exit_code, 0)

    @patch("main.run_sources")
    @patch("main.SOURCES", [
        {"name": "PC Gamer", "url": "u1"},
        {"name": "IGN", "url": "u2"},
    ])
    def test_main_source_filter_applies(self, mock_run_sources):
        mock_run_sources.return_value = []

        exit_code = main(["--source", "pc gamer"])

        mock_run_sources.assert_called_once_with(
            [{"name": "PC Gamer", "url": "u1"}],
            timeout=10,
            db_path=DEFAULT_DB_PATH,
        )
        self.assertEqual(exit_code, 0)

    @patch("main.run_sources")
    @patch("main.SOURCES", [{"name": "PC Gamer", "url": "u"}])
    def test_main_no_matching_source_returns_1(self, mock_run_sources):
        exit_code = main(["--source", "nonexistent"])

        self.assertEqual(exit_code, 1)
        mock_run_sources.assert_not_called()

    @patch("main.run_sources")
    @patch("main.SOURCES", [{"name": "A", "url": "u"}])
    def test_main_handles_run_sources_exception(self, mock_run_sources):
        mock_run_sources.side_effect = RuntimeError("boom")

        exit_code = main([])

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
