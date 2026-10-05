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

    # --- 1 & 5 & 11. Image inside <figure>, caption, and duplicate prevention ---
    def test_figure_image_and_caption_no_duplicate(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>First paragraph detailing important news events that passed validation thresholds comfortably for testing purposes.</p>
                <figure>
                    <img src="https://example.com/figure_img.png" alt="Figure Alt">
                    <figcaption>Figure Caption Text</figcaption>
                </figure>
                <p>Second paragraph following the figure element in article sequence with sufficient character count to exceed minimums easily.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        img_blocks = [b for b in data["blocks"] if b["type"] == "image"]
        self.assertEqual(len(img_blocks), 1)
        self.assertEqual(img_blocks[0]["url"], "https://example.com/figure_img.png")
        self.assertEqual(img_blocks[0]["alt"], "Figure Alt")
        self.assertEqual(img_blocks[0]["caption"], "Figure Caption Text")

    # --- 2 & 3 & 4. Image with src, lazy-loading, srcset, and picture ---
    def test_image_url_resolution_sources(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>First paragraph detailing important news events that passed validation thresholds comfortably for testing purposes.</p>
                <img src="https://example.com/direct_src.png" alt="Direct Src">
                <p>Second paragraph separating image elements with sufficient character count to exceed minimums easily.</p>
                <img data-src="https://example.com/lazy_src.png" alt="Lazy Src">
                <p>Third paragraph separating image elements with sufficient character count to exceed minimums easily.</p>
                <picture>
                    <source srcset="https://example.com/picture_srcset.png 1200w">
                    <img src="data:image/svg+xml;base64,123" alt="Picture Alt">
                </picture>
                <p>Fourth paragraph concluding the image resolution test section with sufficient character count to exceed minimums easily.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        img_blocks = [b for b in data["blocks"] if b["type"] == "image"]
        self.assertEqual(len(img_blocks), 3)
        self.assertEqual(img_blocks[0]["url"], "https://example.com/direct_src.png")
        self.assertEqual(img_blocks[1]["url"], "https://example.com/lazy_src.png")
        self.assertEqual(img_blocks[2]["url"], "https://example.com/picture_srcset.png")

    # --- 6. Missing alt / caption evaluates to None ---
    def test_image_missing_alt_caption_none(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>First paragraph detailing important news events that passed validation thresholds comfortably for testing purposes.</p>
                <img src="https://example.com/no_attributes.png">
                <p>Second paragraph following image without alt or caption attributes with sufficient character count to exceed minimums easily.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        img_blocks = [b for b in data["blocks"] if b["type"] == "image"]
        self.assertEqual(len(img_blocks), 1)
        self.assertEqual(img_blocks[0]["url"], "https://example.com/no_attributes.png")
        self.assertIsNone(img_blocks[0]["alt"])
        self.assertIsNone(img_blocks[0]["caption"])

    # --- 7 & 8 & 9. Video with src, <source>, and iframe ---
    def test_video_extraction_types(self):
        html = """
        <html><body>
            <article>
                <h1>Article Title</h1>
                <p>First paragraph detailing important news events that passed validation thresholds comfortably for testing purposes.</p>
                <video src="https://example.com/video1.mp4" title="Video 1 Title"></video>
                <p>Second paragraph separating video elements with sufficient character count to exceed minimums easily.</p>
                <video><source src="https://example.com/video2.mp4"></video>
                <p>Third paragraph separating video elements with sufficient character count to exceed minimums easily.</p>
                <iframe src="https://www.youtube.com/embed/yt123" title="YouTube Video"></iframe>
                <p>Fourth paragraph concluding video extraction tests with sufficient character count to exceed minimums easily.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        vid_blocks = [b for b in data["blocks"] if b["type"] == "video"]
        self.assertEqual(len(vid_blocks), 3)
        self.assertEqual(vid_blocks[0]["url"], "https://example.com/video1.mp4")
        self.assertEqual(vid_blocks[0]["title"], "Video 1 Title")
        self.assertEqual(vid_blocks[1]["url"], "https://example.com/video2.mp4")
        self.assertIsNone(vid_blocks[1]["title"])
        self.assertEqual(vid_blocks[2]["url"], "https://www.youtube.com/embed/yt123")
        self.assertEqual(vid_blocks[2]["title"], "YouTube Video")

    # --- 10. Media DOM ordering ---
    def test_media_dom_ordering(self):
        html = """
        <html><body>
            <article>
                <h2>Heading 1</h2>
                <p>First paragraph detailing important news events that passed validation thresholds comfortably for testing purposes.</p>
                <figure><img src="https://example.com/image1.png"><figcaption>Cap 1</figcaption></figure>
                <p>Second paragraph separating media elements with sufficient character count to exceed minimums easily.</p>
                <video src="https://example.com/video1.mp4"></video>
                <p>Third paragraph concluding media DOM ordering test section with sufficient character count to exceed minimums easily.</p>
            </article>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        block_types = [b["type"] for b in data["blocks"]]
        self.assertEqual(
            block_types,
            ["heading", "paragraph", "image", "paragraph", "video", "paragraph"],
        )

    # --- 12. Unrelated media outside article container ignored ---
    def test_unrelated_media_outside_container_ignored(self):
        html = """
        <html><body>
            <header>
                <img src="https://example.com/site_logo.png" alt="Site Logo">
            </header>
            <article>
                <h1>Article Title</h1>
                <p>First paragraph detailing important news events that passed validation thresholds comfortably for testing purposes.</p>
                <p>Second paragraph inside article body container with sufficient character count to exceed minimums easily.</p>
            </article>
            <footer>
                <img src="https://example.com/footer_banner.png" alt="Footer Banner">
            </footer>
        </body></html>
        """
        data = extract_article_data(html)
        self.assertIsNotNone(data)
        media_blocks = [b for b in data["blocks"] if b["type"] in ("image", "video")]
        self.assertEqual(len(media_blocks), 0)

    # --- PC Gamer Structure Test with Images and Videos ---
    def test_pcgamer_structure_with_media(self):
        pcgamer_html = """
        <html>
        <head>
            <meta property="og:description" content="Are you ready to make some socks?">
        </head>
        <body>
            <header><a href="/">PC Gamer Header Navigation</a></header>
            <h1>A 'fundamental' update for this 34-year-old survival game is coming in October</h1>
            <div id="article-body">
                <div class="text-copy bodyCopy auto">
                    <h2>Test Heading</h2>
                    <p>First paragraph detailing the new mechanics coming to the classic 34-year-old survival game update this autumn.</p>

                    <figure>
                        <picture>
                            <source srcset="https://cdn.mos.cms.futurecdn.net/image_large.png 1200w">
                            <img src="data:image/svg+xml;base64,123" alt="Test image">
                        </picture>
                        <figcaption>Test caption</figcaption>
                    </figure>

                    <p>Second paragraph explaining the crafting overhaul and player feedback regarding socks and clothing.</p>

                    <video src="https://example.com/video.mp4" title="Gameplay Video"></video>

                    <p>Third paragraph providing additional details regarding server architecture and testing phases.</p>
                </div>
            </div>
        </body>
        </html>
        """
        data = extract_article_data(pcgamer_html)
        self.assertIsNotNone(data)
        self.assertEqual(
            data["title"],
            "A 'fundamental' update for this 34-year-old survival game is coming in October",
        )
        self.assertEqual(data["description"], "Are you ready to make some socks?")
        self.assertTrue(len(data["content"].replace(" ", "")) >= 100)

        # Check block ordering: heading, paragraph, image, paragraph, video, paragraph
        block_types = [b["type"] for b in data["blocks"]]
        self.assertEqual(
            block_types,
            ["heading", "paragraph", "image", "paragraph", "video", "paragraph"],
        )

        # Verify image block details
        img_block = [b for b in data["blocks"] if b["type"] == "image"][0]
        self.assertEqual(img_block["url"], "https://cdn.mos.cms.futurecdn.net/image_large.png")
        self.assertEqual(img_block["alt"], "Test image")
        self.assertEqual(img_block["caption"], "Test caption")

        # Verify video block details
        vid_block = [b for b in data["blocks"] if b["type"] == "video"][0]
        self.assertEqual(vid_block["url"], "https://example.com/video.mp4")
        self.assertEqual(vid_block["title"], "Gameplay Video")

        # Verify text-only content field does NOT contain media URLs
        self.assertNotIn("https://cdn.mos.cms.futurecdn.net", data["content"])
        self.assertNotIn("https://example.com/video.mp4", data["content"])

    # --- HTTP 404 & Timeout ---
    @patch("article_extractor.requests.get")
    def test_http_404(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        self.assertIsNone(fetch_article_html("https://example.com/404"))

    @patch("article_extractor.requests.get")
    def test_http_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout("Timed out")
        self.assertIsNone(fetch_article_html("https://example.com/timeout"))

    # --- Backward compatibility extract_article() ---
    @patch("article_extractor.fetch_article_html")
    def test_extract_article_compatibility(self, mock_fetch):
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

    # --- Batch extraction ---
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
