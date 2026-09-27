import unittest
from unittest.mock import patch, MagicMock
import requests
from article_extractor import (
    fetch_article_html,
    extract_article_content,
    extract_article,
    extract_articles,
    DEFAULT_USER_AGENT,
    MIN_CONTENT_LENGTH,
)


class TestArticleExtractor(unittest.TestCase):

    # --- Test 1: Successful HTML fetch ---
    @patch("article_extractor.requests.get")
    def test_fetch_article_html_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.text = "<html><body><h1>Test Article</h1></body></html>"
        mock_get.return_value = mock_response

        url = "https://example.com/article-1"
        html = fetch_article_html(url, timeout=10)

        mock_get.assert_called_once_with(url, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=10)
        mock_response.raise_for_status.assert_called_once()
        self.assertEqual(html, "<html><body><h1>Test Article</h1></body></html>")

    # --- Test 2: HTTP failure ---
    @patch("article_extractor.requests.get")
    def test_fetch_article_html_http_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        html = fetch_article_html("https://example.com/404")
        self.assertIsNone(html)

    # --- Test 3: Network/timeout failure ---
    @patch("article_extractor.requests.get")
    def test_fetch_article_html_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout("Connection timed out")

        html = fetch_article_html("https://example.com/timeout")
        self.assertIsNone(html)

    # --- Test 4: Article extraction ---
    def test_extract_article_content_article_tag(self):
        sample_html = """
        <html>
        <head><title>Page Title</title></head>
        <body>
            <nav><a href="/">Home</a> Navigation Links Here</nav>
            <article>
                <h1>Test Article Heading</h1>
                <p>This is the first paragraph of the article. It contains detailed information about a very interesting event that took place today.</p>
                <p>This is the second paragraph of the article. It expands on the details provided earlier and gives a complete breakdown of the situation.</p>
            </article>
            <footer>Copyright 2026 AutoNews Footer Content</footer>
        </body>
        </html>
        """
        extracted = extract_article_content(sample_html)
        self.assertIsNotNone(extracted)
        self.assertIn("Test Article Heading", extracted)
        self.assertIn("This is the first paragraph of the article.", extracted)
        self.assertIn("This is the second paragraph of the article.", extracted)
        self.assertNotIn("Navigation Links Here", extracted)
        self.assertNotIn("AutoNews Footer Content", extracted)

    # --- Test 5: Script/style removal ---
    def test_extract_article_content_script_style_removal(self):
        sample_html = """
        <html>
        <body>
            <article>
                <script type="text/javascript">
                    var tracker = "DO_NOT_INCLUDE_JAVASCRIPT_IN_OUTPUT";
                    console.log("script block");
                </script>
                <style>
                    body { background-color: red; }
                    .hidden { display: none; }
                </style>
                <p>This paragraph contains valid news text that meets the minimum length requirement for extraction purposes without any script pollution.</p>
                <p>Here is another paragraph filled with additional article details to ensure that total non-whitespace length safely exceeds one hundred characters.</p>
            </article>
        </body>
        </html>
        """
        extracted = extract_article_content(sample_html)
        self.assertIsNotNone(extracted)
        self.assertNotIn("DO_NOT_INCLUDE_JAVASCRIPT_IN_OUTPUT", extracted)
        self.assertNotIn("background-color: red", extracted)
        self.assertIn("This paragraph contains valid news text", extracted)

    # --- Test 6: Empty/invalid HTML ---
    def test_extract_article_content_empty_or_insufficient(self):
        self.assertIsNone(extract_article_content(""))
        self.assertIsNone(extract_article_content("   "))
        self.assertIsNone(extract_article_content(None))

        short_html = """
        <html>
        <body>
            <article>
                <p>Too short.</p>
            </article>
        </body>
        </html>
        """
        self.assertIsNone(extract_article_content(short_html))

    # --- Test 7: Successful extract_article() ---
    @patch("article_extractor.fetch_article_html")
    def test_extract_article_success(self, mock_fetch):
        mock_fetch.return_value = """
        <html>
        <body>
            <article>
                <h1>Breaking News Story</h1>
                <p>This is a long and comprehensive news report about an important global event that occurred earlier today.</p>
                <p>Experts from around the world have analyzed the situation and shared their insights regarding future implications.</p>
            </article>
        </body>
        </html>
        """
        original_article = {
            "title": "Example Article",
            "url": "https://example.com/article",
            "published": "2026-09-27T10:00:00Z",
            "summary": "Example summary",
        }

        result = extract_article(original_article)

        self.assertIsNotNone(result)
        self.assertIsNot(result, original_article)  # Ensure non-mutated copy
        self.assertEqual(result["title"], "Example Article")
        self.assertEqual(result["url"], "https://example.com/article")
        self.assertEqual(result["published"], "2026-09-27T10:00:00Z")
        self.assertEqual(result["summary"], "Example summary")
        self.assertIn("content", result)
        self.assertIn("Breaking News Story", result["content"])
        self.assertNotIn("content", original_article)  # Original dictionary untouched

    # --- Test 8: Missing URL ---
    def test_extract_article_missing_url(self):
        self.assertIsNone(extract_article(None))
        self.assertIsNone(extract_article("not a dict"))
        self.assertIsNone(extract_article({"title": "No URL"}))
        self.assertIsNone(extract_article({"title": "Empty URL", "url": "   "}))

    # --- Test 9: Batch extraction ---
    @patch("article_extractor.fetch_article_html")
    def test_extract_articles_batch(self, mock_fetch):
        def side_effect(url, timeout=10):
            if url == "https://example.com/valid-1":
                return """
                <html><body><article>
                <p>First valid article text containing sufficient character count for successful validation testing.</p>
                <p>Adding a second paragraph to ensure the character threshold of one hundred non-whitespace characters is easily passed.</p>
                </article></body></html>
                """
            elif url == "https://example.com/valid-2":
                return """
                <html><body><article>
                <p>Second valid article text also containing sufficient character count for successful validation testing.</p>
                <p>Adding another paragraph to ensure the threshold is passed without any issues whatsoever in this test.</p>
                </article></body></html>
                """
            else:
                return None  # Failed request or invalid URL

        mock_fetch.side_effect = side_effect

        articles = [
            {"title": "Valid 1", "url": "https://example.com/valid-1"},
            {"title": "Invalid 404", "url": "https://example.com/404"},
            {"title": "Valid 2", "url": "https://example.com/valid-2"},
            {"title": "Missing URL"},
        ]

        results = extract_articles(articles)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Valid 1")
        self.assertEqual(results[1]["title"], "Valid 2")
        self.assertIn("content", results[0])
        self.assertIn("content", results[1])


if __name__ == "__main__":
    unittest.main()
