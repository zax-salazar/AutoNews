import time
import unittest
from parser import parse_entry, parse_entries


class TestParser(unittest.TestCase):

    def test_valid_entry(self):
        struct_time = time.gmtime(1700000000)  # 2023-11-14T22:13:20Z
        raw_entry = {
            "title": "  Half-Life 3 Announced  ",
            "link": " https://example.com/hl3 ",
            "published_parsed": struct_time,
            "summary": "<p>Valve has finally announced <strong>Half-Life 3</strong> &amp; more!</p>",
        }
        parsed = parse_entry(raw_entry)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "Half-Life 3 Announced")
        self.assertEqual(parsed["url"], "https://example.com/hl3")
        self.assertEqual(parsed["published"], "2023-11-14T22:13:20Z")
        self.assertEqual(parsed["summary"], "Valve has finally announced Half-Life 3 & more!")

    def test_missing_title(self):
        raw_entry_none = {"title": None, "link": "https://example.com/1"}
        raw_entry_empty = {"title": "   ", "link": "https://example.com/1"}
        raw_entry_absent = {"link": "https://example.com/1"}

        self.assertIsNone(parse_entry(raw_entry_none))
        self.assertIsNone(parse_entry(raw_entry_empty))
        self.assertIsNone(parse_entry(raw_entry_absent))

    def test_missing_url(self):
        raw_entry_none = {"title": "Article Title", "link": None}
        raw_entry_empty = {"title": "Article Title", "link": "  "}
        raw_entry_absent = {"title": "Article Title"}

        self.assertIsNone(parse_entry(raw_entry_none))
        self.assertIsNone(parse_entry(raw_entry_empty))
        self.assertIsNone(parse_entry(raw_entry_absent))

    def test_missing_date_and_fallbacks(self):
        # Fallback to updated_parsed
        struct_time = time.gmtime(1700000000)
        entry_updated = {
            "title": "Title",
            "link": "https://example.com/1",
            "updated_parsed": struct_time,
        }
        parsed_updated = parse_entry(entry_updated)
        self.assertEqual(parsed_updated["published"], "2023-11-14T22:13:20Z")

        # Fallback to raw string
        entry_raw_date = {
            "title": "Title",
            "link": "https://example.com/1",
            "published": "Tue, 14 Nov 2023 22:13:20 GMT",
        }
        parsed_raw_date = parse_entry(entry_raw_date)
        self.assertEqual(parsed_raw_date["published"], "Tue, 14 Nov 2023 22:13:20 GMT")

        # Missing date completely
        entry_no_date = {
            "title": "Title",
            "link": "https://example.com/1",
        }
        parsed_no_date = parse_entry(entry_no_date)
        self.assertIsNone(parsed_no_date["published"])

    def test_missing_summary_and_html_cleaning(self):
        # Summary with nested HTML, unescaping, and extra whitespace
        entry_html = {
            "title": "Title",
            "link": "https://example.com/1",
            "summary": "  <div><p>Game &lt;Update&gt; is   out now! \n\n</p></div>  ",
        }
        parsed_html = parse_entry(entry_html)
        self.assertEqual(parsed_html["summary"], "Game <Update> is out now!")

        # Missing summary completely
        entry_no_summary = {
            "title": "Title",
            "link": "https://example.com/1",
        }
        parsed_no_summary = parse_entry(entry_no_summary)
        self.assertIsNone(parsed_no_summary["summary"])

    def test_malformed_incomplete_entry(self):
        self.assertIsNone(parse_entry(None))
        self.assertIsNone(parse_entry({}))
        self.assertIsNone(parse_entry("invalid input string"))

    def test_parse_entries_batch(self):
        entries = [
            {"title": "Valid 1", "link": "https://example.com/1"},
            {"title": "Invalid No Link"},
            {"title": "Valid 2", "link": "https://example.com/2", "summary": "Cool game"},
            {"link": "https://example.com/invalid_no_title"},
        ]
        articles = parse_entries(entries)
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0]["title"], "Valid 1")
        self.assertEqual(articles[1]["title"], "Valid 2")


if __name__ == "__main__":
    unittest.main()
