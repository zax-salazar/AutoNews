import unittest
from unittest.mock import patch, MagicMock
import requests
from article_extractor import (
    fetch_article_html,
    extract_article_content,
    extract_article_data,
    extract_article,
    extract_articles,
    DEFAULT_USER_AGENT,
    MIN_CONTENT_LENGTH,
)


class TestArticleExtractor(unittest.TestCase):

    # --- PC Gamer Regression Structure Test ---
    def test_pcgamer_article_structure(self):
        pcgamer_html = """
        <html>
        <head>
            <meta property="og:description" content="A major update is coming to the classic 34-year-old survival game this autumn.">
        </head>
        <body>
            <header><a href="/">PC Gamer Logo Nav</a></header>
            <h1>A 'fundamental' update for this 34-year-old survival game is coming in October</h1>
            <div id="article-body">
                <div class="text-copy bodyCopy auto">
                    <p>Unreal Unearth and preceding survival games have been classic staples of PC gaming for decades, evolving through multiple engine generations.</p>
                    <h2>Major Overhaul Details</h2>
                    <p>Developers revealed today that October will bring groundbreaking changes to mechanics, graphics, and underlying world generation code.</p>
                    <ul>
                        <li>New crafting system built from scratch</li>
                        <li>Updated multiplayer server architecture</li>
                    </ul>
                    <figure>
                        <img data-srcset="https://cdn.mos.cms.futurecdn.net/game_screenshot_small.jpg 480w, https://cdn.mos.cms.futurecdn.net/game_screenshot_large.jpg 1200w" alt="Survival Game Screenshot">
                        <figcaption>A first look at the newly updated graphics engine in action.</figcaption>
                    </figure>
                    <p>Expect further announcements and public beta testing opportunities to roll out in late September prior to official release.</p>
                    <div class="recirculation-widget">
                        <p>Unrelated Article: Top 10 Graphics Cards 2026</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        data = extract_article_data(pcgamer_html)
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "A 'fundamental' update for this 34-year-old survival game is coming in October")
        self.assertEqual(data["description"], "A major update is coming to the classic 34-year-old survival game this autumn.")
        self.assertTrue(len(data["content"].replace(" ", "")) >= 100)

        # Check block ordering
        block_types = [b["type"] for b in data["blocks"]]
        self.assertEqual(
            block_types,
            ["paragraph", "heading", "paragraph", "paragraph", "paragraph", "image", "paragraph"],
        )

        # Check image block details
        img_blocks = [b for b in data["blocks"] if b["type"] == "image"]
        self.assertEqual(len(img_blocks), 1)
        self.assertEqual(img_blocks[0]["url"], "https://cdn.mos.cms.futurecdn.net/game_screenshot_large.jpg")
        self.assertEqual(img_blocks[0]["alt"], "Survival Game Screenshot")
        self.assertEqual(img_blocks[0]["caption"], "A first look at the newly updated graphics engine in action.")

        # Check exclusion of recirculation ad content
        self.assertNotIn("Top 10 Graphics Cards", data["content"])

    # --- 1. Article title extraction ---
    def test_extract_title(self):
        html = """
        <html><body>
            <article>
                <h1>High Confidence Article Title</h1>
                <p>This paragraph contains sufficient article text to pass the content length validation threshold comfortably for this test.</p>
                <p>Adding another paragraph of text to make sure the non-whitespace character count is well above one hundred characters.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        self.assertEqual(data["title"], "High Confidence Article Title")

    # --- 2. Description extraction ---
    def test_extract_description(self):
        html = """
        <html>
        <head><meta property="og:description" content="This is the Open Graph description of the article."></head>
        <body>
            <article>
                <h1>Article Title</h1>
                <p>This paragraph contains sufficient article text to pass the content length validation threshold comfortably for this test.</p>
                <p>Adding another paragraph of text to make sure the non-whitespace character count is well above one hundred characters.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        self.assertEqual(data["description"], "This is the Open Graph description of the article.")

    # --- 3. Full paragraph extraction ---
    def test_extract_paragraphs(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>First paragraph of the gaming news story with detailed information.</p>
                <p>Second paragraph providing more insights and developer interview quotes.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        p_blocks = [b for b in data["blocks"] if b["type"] == "paragraph"]
        self.assertEqual(len(p_blocks), 2)
        self.assertEqual(p_blocks[0]["content"], "First paragraph of the gaming news story with detailed information.")
        self.assertEqual(p_blocks[1]["content"], "Second paragraph providing more insights and developer interview quotes.")

    # --- 4. Heading extraction ---
    def test_extract_headings(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Introductory paragraph containing sufficient details for validation testing.</p>
                <h2>Subheading Level Two</h2>
                <p>Further details below the subheading section of this article.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        h_blocks = [b for b in data["blocks"] if b["type"] == "heading"]
        self.assertTrue(len(h_blocks) >= 1)
        subheadings = [b for b in h_blocks if b["level"] == 2]
        self.assertEqual(len(subheadings), 1)
        self.assertEqual(subheadings[0]["content"], "Subheading Level Two")

    # --- 5 & 6 & 7. Image extraction with alt and caption ---
    def test_extract_image_with_alt_and_caption(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Introductory paragraph containing sufficient details for validation testing across all requirements.</p>
                <figure>
                    <img src="https://example.com/screenshot.jpg" alt="Game Screenshot Alt">
                    <figcaption>Screenshot showing gameplay action in high resolution.</figcaption>
                </figure>
                <p>Concluding paragraph following the image figure container.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        img_blocks = [b for b in data["blocks"] if b["type"] == "image"]
        self.assertEqual(len(img_blocks), 1)
        self.assertEqual(img_blocks[0]["url"], "https://example.com/screenshot.jpg")
        self.assertEqual(img_blocks[0]["alt"], "Game Screenshot Alt")
        self.assertEqual(img_blocks[0]["caption"], "Screenshot showing gameplay action in high resolution.")

    # --- 8. Lazy-loaded image URL extraction ---
    def test_extract_lazy_loaded_image(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Introductory paragraph containing sufficient details for validation testing across lazy loading features.</p>
                <img data-src="https://example.com/lazy_photo.jpg" alt="Lazy Photo">
                <p>Concluding paragraph following the lazy loaded image tag.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        img_blocks = [b for b in data["blocks"] if b["type"] == "image"]
        self.assertEqual(len(img_blocks), 1)
        self.assertEqual(img_blocks[0]["url"], "https://example.com/lazy_photo.jpg")

    # --- 9 & 10. Video & iframe video extraction ---
    def test_extract_videos(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Introductory paragraph containing sufficient details for validation testing video embed features.</p>
                <video src="https://example.com/trailer.mp4" title="Official Trailer"></video>
                <iframe src="https://www.youtube.com/embed/xyz123" title="Gameplay Video"></iframe>
                <p>Concluding paragraph following video elements inside the article container.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        vid_blocks = [b for b in data["blocks"] if b["type"] == "video"]
        self.assertEqual(len(vid_blocks), 2)
        self.assertEqual(vid_blocks[0]["url"], "https://example.com/trailer.mp4")
        self.assertEqual(vid_blocks[0]["title"], "Official Trailer")
        self.assertEqual(vid_blocks[1]["url"], "https://www.youtube.com/embed/xyz123")
        self.assertEqual(vid_blocks[1]["title"], "Gameplay Video")

    # --- 11. Correct block ordering ---
    def test_block_ordering(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Paragraph 1 text containing enough detail for validation purposes.</p>
                <img src="https://example.com/image1.jpg" alt="Image 1">
                <p>Paragraph 2 text following the first image in the sequence.</p>
                <iframe src="https://www.youtube.com/embed/trailer1" title="Trailer 1"></iframe>
                <p>Paragraph 3 text following the video in the sequence.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        block_types = [b["type"] for b in data["blocks"]]
        expected_types = ["heading", "paragraph", "image", "paragraph", "video", "paragraph"]
        self.assertEqual(block_types, expected_types)

    # --- 12. Removal of nav/header/footer/ads ---
    def test_removal_of_unwanted_elements(self):
        html = """
        <html><body>
            <nav>Nav links</nav>
            <div class="ad-banner"><img src="https://example.com/ad.gif"></div>
            <article>
                <h1>Article Title</h1>
                <p>Main content paragraph 1 with sufficient length for valid extraction.</p>
                <div class="social-share">Share on Twitter</div>
                <p>Main content paragraph 2 with further detailed explanations.</p>
            </article>
            <footer>Footer content</footer>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        self.assertNotIn("Nav links", data["content"])
        self.assertNotIn("Footer content", data["content"])
        self.assertNotIn("Share on Twitter", data["content"])
        urls = [b.get("url") for b in data["blocks"] if b["type"] == "image"]
        self.assertNotIn("https://example.com/ad.gif", urls)

    # --- 13. Duplicate media handling ---
    def test_duplicate_media_handling(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Introductory paragraph containing sufficient details for validation testing.</p>
                <img src="https://example.com/photo.jpg" alt="Photo">
                <img src="https://example.com/photo.jpg" alt="Duplicate Photo">
                <p>Concluding paragraph following duplicate image tags in the markup.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        img_blocks = [b for b in data["blocks"] if b["type"] == "image"]
        self.assertEqual(len(img_blocks), 1)

    # --- 14. Missing title ---
    def test_missing_title(self):
        html = """
        <html><body>
            <article>
                <p>Paragraph 1 text containing enough detail for validation purposes.</p>
                <p>Paragraph 2 text providing additional details to pass length check.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        self.assertIsNone(data["title"])

    # --- 15. Missing description ---
    def test_missing_description(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Paragraph 1 text containing enough detail for validation purposes.</p>
                <p>Paragraph 2 text providing additional details to pass length check.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        self.assertIsNone(data["description"])

    # --- 16. Missing media ---
    def test_missing_media(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>Paragraph 1 text containing enough detail for validation purposes.</p>
                <p>Paragraph 2 text providing additional details to pass length check.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        media_blocks = [b for b in data["blocks"] if b["type"] in ("image", "video")]
        self.assertEqual(len(media_blocks), 0)

    # --- 17 & 18. Invalid HTML & Very short article ---
    def test_invalid_or_short_article(self):
        self.assertIsNone(extract_article_data(""))
        short_html = "<html><body><article><p>Short</p></article></body></html>"
        self.assertIsNone(extract_article_data(short_html))

    # --- 19. HTTP 404 ---
    @patch("article_extractor.requests.get")
    def test_http_404(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        self.assertIsNone(fetch_article_html("https://example.com/404"))

    # --- 20. HTTP timeout ---
    @patch("article_extractor.requests.get")
    def test_http_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout("Timed out")
        self.assertIsNone(fetch_article_html("https://example.com/timeout"))

    # --- 21. Existing content field remains correct ---
    @patch("article_extractor.fetch_article_html")
    def test_extract_article_content_compatibility(self, mock_fetch):
        sample_html = """
        <html><body>
            <article>
                <h1>Title</h1>
                <p>Paragraph one text with sufficient detail to exceed length check easily.</p>
                <p>Paragraph two text expanding on the news story with further quotes.</p>
            </article>
        </body></html>
        """
        mock_fetch.return_value = sample_html

        article_dict = {
            "title": "Original Title",
            "url": "https://example.com/article",
            "published": "2026-09-27T10:00:00Z",
            "summary": "Original summary",
        }

        result = extract_article(article_dict)
        self.assertIsNotNone(result)
        self.assertIn("content", result)
        self.assertIn("blocks", result)
        self.assertIn("description", result)
        self.assertEqual(result["title"], "Title")
        self.assertEqual(result["url"], "https://example.com/article")
        self.assertEqual(result["published"], "2026-09-27T10:00:00Z")

    # --- 22 & 23. Multiple articles & Failed article handling ---
    @patch("article_extractor.fetch_article_html")
    def test_batch_extraction(self, mock_fetch):
        def side_effect(url, timeout=10):
            if url == "https://example.com/1":
                return """
                <html><body><article>
                <h1>Article One</h1>
                <p>Paragraph text for article one containing sufficient characters to validate.</p>
                <p>Second paragraph text for article one ensuring threshold is met easily.</p>
                </article></body></html>
                """
            elif url == "https://example.com/2":
                return None
            elif url == "https://example.com/3":
                return """
                <html><body><article>
                <h1>Article Three</h1>
                <p>Paragraph text for article three containing sufficient characters to validate.</p>
                <p>Second paragraph text for article three ensuring threshold is met easily.</p>
                </article></body></html>
                """

        mock_fetch.side_effect = side_effect

        articles = [
            {"title": "Art 1", "url": "https://example.com/1"},
            {"title": "Art 2", "url": "https://example.com/2"},
            {"title": "Art 3", "url": "https://example.com/3"},
        ]

        results = extract_articles(articles)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Article One")
        self.assertEqual(results[1]["title"], "Article Three")


if __name__ == "__main__":
    unittest.main()
