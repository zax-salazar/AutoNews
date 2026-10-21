import os
import tempfile
import unittest

# Set token env var BEFORE importing main.py
os.environ["AUTONEWS_API_TOKEN"] = "test-secret-token"

try:
    from fastapi.testclient import TestClient
    from api_server.main import app
    from api_server.db import init_db
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


if HAS_FASTAPI:
    class TestAPI(unittest.TestCase):

        def setUp(self):
            self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
            os.environ["AUTONEWS_API_DB"] = self.temp_db_path
            init_db(self.temp_db_path)
            self.client = TestClient(app)

        def tearDown(self):
            os.close(self.temp_db_fd)
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)

        # --- Health check ---
        def test_health(self):
            res = self.client.get("/health")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"ok": True, "service": "autonews-api"})

        # --- Authentication tests ---
        def test_post_requires_auth(self):
            payload = {"title": "Title", "body": "Body"}
            res = self.client.post("/api/articles", json=payload)
            self.assertEqual(res.status_code, 403)
            self.assertEqual(res.json(), {"detail": "invalid token"})

        def test_post_rejects_wrong_token(self):
            payload = {"title": "Title", "body": "Body"}
            headers = {"Authorization": "Bearer wrong-token"}
            res = self.client.post("/api/articles", json=payload, headers=headers)
            self.assertEqual(res.status_code, 403)
            self.assertEqual(res.json(), {"detail": "invalid token"})

        # --- POST Article validation tests ---
        def test_post_valid_returns_id_and_url(self):
            payload = {
                "title": "Sample Title",
                "body": "Sample Body Text",
                "language": "fa",
                "summary": "Sample summary",
                "keywords": ["tag1", "tag2"],
                "images": [{"index": 0, "url": "https://example.com/img.jpg", "alt_fa": "توضیح"}],
            }
            headers = {"Authorization": "Bearer test-secret-token"}
            res = self.client.post("/api/articles", json=payload, headers=headers)
            self.assertEqual(res.status_code, 201)
            data = res.json()
            self.assertIn("id", data)
            self.assertTrue(data["id"])
            self.assertEqual(data["url"], f"/api/articles/{data['id']}")

        def test_post_rejects_missing_title(self):
            payload = {"body": "Body without title"}
            headers = {"Authorization": "Bearer test-secret-token"}
            res = self.client.post("/api/articles", json=payload, headers=headers)
            self.assertEqual(res.status_code, 422)

        def test_post_rejects_missing_body(self):
            payload = {"title": "Title without body"}
            headers = {"Authorization": "Bearer test-secret-token"}
            res = self.client.post("/api/articles", json=payload, headers=headers)
            self.assertEqual(res.status_code, 422)

        def test_post_rejects_empty_title(self):
            payload = {"title": "", "body": "Body"}
            headers = {"Authorization": "Bearer test-secret-token"}
            res = self.client.post("/api/articles", json=payload, headers=headers)
            self.assertEqual(res.status_code, 422)

        def test_post_rejects_negative_image_index(self):
            payload = {
                "title": "Title",
                "body": "Body",
                "images": [{"index": -1, "url": "https://example.com/img.jpg"}],
            }
            headers = {"Authorization": "Bearer test-secret-token"}
            res = self.client.post("/api/articles", json=payload, headers=headers)
            self.assertEqual(res.status_code, 422)

        def test_post_accepts_minimal_payload(self):
            payload = {"title": "Minimal Title", "body": "Minimal Body"}
            headers = {"Authorization": "Bearer test-secret-token"}
            res = self.client.post("/api/articles", json=payload, headers=headers)
            self.assertEqual(res.status_code, 201)
            article_id = res.json()["id"]

            get_res = self.client.get(f"/api/articles/{article_id}")
            self.assertEqual(get_res.status_code, 200)
            art = get_res.json()
            self.assertEqual(art["title"], "Minimal Title")
            self.assertEqual(art["body"], "Minimal Body")
            self.assertEqual(art["language"], "fa")
            self.assertEqual(art["keywords"], [])
            self.assertEqual(art["images"], [])

        # --- GET Article tests ---
        def test_get_article_returns_full_payload(self):
            payload = {
                "title": "Full Article",
                "body": "Full Body",
                "summary": "Summary text",
                "seo_description": "SEO description",
                "keywords": ["game", "news"],
                "research_notes": "Top secret internal research notes",
                "images": [{"index": 0, "url": "https://example.com/img1.jpg", "alt_fa": "عکس"}],
            }
            headers = {"Authorization": "Bearer test-secret-token"}
            post_res = self.client.post("/api/articles", json=payload, headers=headers)
            article_id = post_res.json()["id"]

            get_res = self.client.get(f"/api/articles/{article_id}")
            self.assertEqual(get_res.status_code, 200)
            art = get_res.json()

            self.assertEqual(art["id"], article_id)
            self.assertEqual(art["title"], "Full Article")
            self.assertEqual(art["body"], "Full Body")
            self.assertEqual(art["summary"], "Summary text")
            self.assertEqual(art["seo_description"], "SEO description")
            self.assertEqual(art["keywords"], ["game", "news"])
            self.assertEqual(len(art["images"]), 1)
            self.assertEqual(art["images"][0]["url"], "https://example.com/img1.jpg")
            self.assertIn("created_at", art)

            # Confirm research_notes is NOT present
            self.assertNotIn("research_notes", art)

        def test_get_article_404_for_unknown_id(self):
            res = self.client.get("/api/articles/nonexistent-id-999")
            self.assertEqual(res.status_code, 404)
            self.assertEqual(res.json(), {"detail": "article not found"})

        # --- List Articles tests ---
        def test_list_articles_empty(self):
            res = self.client.get("/api/articles")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json(), {"total": 0, "limit": 20, "offset": 0, "items": []})

        def test_list_articles_pagination(self):
            headers = {"Authorization": "Bearer test-secret-token"}
            for i in range(3):
                self.client.post("/api/articles", json={"title": f"Title {i}", "body": f"Body {i}"}, headers=headers)

            res_page1 = self.client.get("/api/articles?limit=2&offset=0")
            self.assertEqual(res_page1.status_code, 200)
            data1 = res_page1.json()
            self.assertEqual(data1["total"], 3)
            self.assertEqual(data1["limit"], 2)
            self.assertEqual(data1["offset"], 0)
            self.assertEqual(len(data1["items"]), 2)

            res_page2 = self.client.get("/api/articles?limit=2&offset=2")
            self.assertEqual(res_page2.status_code, 200)
            data2 = res_page2.json()
            self.assertEqual(data2["total"], 3)
            self.assertEqual(data2["limit"], 2)
            self.assertEqual(data2["offset"], 2)
            self.assertEqual(len(data2["items"]), 1)

        def test_list_articles_language_filter(self):
            headers = {"Authorization": "Bearer test-secret-token"}
            self.client.post("/api/articles", json={"title": "Fa 1", "body": "Body", "language": "fa"}, headers=headers)
            self.client.post("/api/articles", json={"title": "Fa 2", "body": "Body", "language": "fa"}, headers=headers)
            self.client.post("/api/articles", json={"title": "En 1", "body": "Body", "language": "en"}, headers=headers)

            res_fa = self.client.get("/api/articles?language=fa")
            self.assertEqual(res_fa.json()["total"], 2)

            res_en = self.client.get("/api/articles?language=en")
            self.assertEqual(res_en.json()["total"], 1)

            res_all = self.client.get("/api/articles")
            self.assertEqual(res_all.json()["total"], 3)

        def test_list_articles_does_not_leak_research_notes(self):
            headers = {"Authorization": "Bearer test-secret-token"}
            payload = {
                "title": "Title",
                "body": "Body",
                "research_notes": "Internal classified notes",
            }
            self.client.post("/api/articles", json=payload, headers=headers)

            res = self.client.get("/api/articles")
            self.assertEqual(res.status_code, 200)
            items = res.json()["items"]
            self.assertEqual(len(items), 1)
            self.assertNotIn("research_notes", items[0])
else:
    class TestAPI(unittest.TestCase):
        @unittest.skip("fastapi or pydantic not installed in current environment")
        def test_api_server_requires_fastapi(self):
            pass


if __name__ == "__main__":
    unittest.main()
