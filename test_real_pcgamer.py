import os
import unittest
from article_extractor import extract_article_data


class TestRealPCGamer(unittest.TestCase):

    def test_real_pcgamer_local_fixture(self):
        """Test extraction against the local pcgamer_test.html fixture if present."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        fixture_path = os.path.join(base_dir, "pcgamer_test.html")

        if not os.path.exists(fixture_path):
            self.skipTest("Local HTML fixture 'pcgamer_test.html' not found.")

        with open(fixture_path, "r", encoding="utf-8") as f:
            html = f.read()

        data = extract_article_data(html)

        self.assertIsNotNone(data, "Expected extract_article_data to return non-None for real PC Gamer fixture.")
        self.assertTrue(data.get("title"), "Extracted article title should not be empty.")
        self.assertTrue(data.get("description"), "Extracted article description should not be empty.")
        self.assertTrue(
            len(data["content"].replace(" ", "")) >= 100,
            "Extracted content length should meet or exceed 100 non-whitespace characters.",
        )
        self.assertTrue(
            len(data.get("blocks", [])) > 0,
            "Extracted blocks list should contain structured content blocks.",
        )


if __name__ == "__main__":
    unittest.main()
