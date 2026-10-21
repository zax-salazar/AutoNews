# AutoNews Content API Server

## What it does
Receives articles from AutoNews via POST and serves them to a frontend via GET.

## JSON contract

### POST `/api/articles` Body Schema (from AutoNews publisher):
```json
{
  "language": "fa",
  "title": "عنوان مقاله",
  "summary": "خلاصه مقاله",
  "body": "متن کامل مقاله که شامل نشانگرهای [[IMG:0]] و [[IMG:1]] برای جایگذاری عکس‌ها می‌باشد.",
  "seo_description": "توضیحات سئو مقاله",
  "keywords": ["گیم", "خبر"],
  "research_notes": "نکات داخلی تحقیق",
  "images": [
    {
      "index": 0,
      "url": "https://cdn.example.com/image1.jpg",
      "alt_fa": "توضیح تصویر اول"
    }
  ]
}
```

> **Note for Frontend:** The `body` field contains `[[IMG:N]]` markers. The frontend rendering layer should substitute `[[IMG:N]]` with `images[i].url` and `images[i].alt_fa` where `images[i].index == N`.

### GET `/api/articles/{article_id}` Response Schema:
```json
{
  "id": "a1b2c3d4e5f6...",
  "language": "fa",
  "title": "عنوان مقاله",
  "summary": "خلاصه مقاله",
  "body": "متن کامل مقاله...",
  "seo_description": "توضیحات سئو مقاله",
  "keywords": ["گیم", "خبر"],
  "images": [
    {
      "index": 0,
      "url": "https://cdn.example.com/image1.jpg",
      "alt_fa": "توضیح تصویر اول"
    }
  ],
  "created_at": "2026-10-21 18:00:00"
}
```
*(Note: Internal `research_notes` field is excluded from GET responses).*

## Local run
```bash
cd api_server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set a strong AUTONEWS_API_TOKEN
export $(cat .env | xargs)
uvicorn main:app --host $AUTONEWS_API_HOST --port $AUTONEWS_API_PORT
```

## Tests
```bash
python3 -m unittest test_api -v
# or
pytest test_api.py -v
```

## Production deploy on a Linux server (systemd example)
1. Create a service user `autonews-api`:
   ```bash
   sudo useradd -r -s /bin/false autonews-api
   ```
2. Copy the `api_server/` directory to `/opt/autonews-api`:
   ```bash
   sudo cp -r api_server /opt/autonews-api
   sudo chown -R autonews-api:autonews-api /opt/autonews-api
   ```
3. Create venv and install dependencies:
   ```bash
   cd /opt/autonews-api
   sudo -u autonews-api python3 -m venv .venv
   sudo -u autonews-api /opt/autonews-api/.venv/bin/pip install -r requirements.txt
   ```
4. Create environment file `/etc/autonews-api.env`:
   ```env
   AUTONEWS_API_TOKEN=your-very-strong-secret-token
   AUTONEWS_API_DB=/var/lib/autonews-api/articles.db
   AUTONEWS_API_HOST=127.0.0.1
   AUTONEWS_API_PORT=8000
   ```
5. Create systemd unit file `/etc/systemd/system/autonews-api.service`:
   ```ini
   [Unit]
   Description=AutoNews Content API
   After=network.target

   [Service]
   User=autonews-api
   Group=autonews-api
   WorkingDirectory=/opt/autonews-api
   EnvironmentFile=/etc/autonews-api.env
   ExecStart=/opt/autonews-api/.venv/bin/uvicorn main:app --host ${AUTONEWS_API_HOST} --port ${AUTONEWS_API_PORT}
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```
6. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now autonews-api
   ```
7. Configure reverse proxy (Nginx with TLS certificate).

## AutoNews side configuration
On the AutoNews scraper/publisher side, set:
```env
AUTONEWS_PUBLISHER=http
AUTONEWS_PUBLISH_URL=https://your-api-domain/api/articles
AUTONEWS_PUBLISH_TOKEN=<same token as AUTONEWS_API_TOKEN>
```
