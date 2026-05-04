# FluentISH CRM

A bespoke SMS CRM for the FluentISH French tutoring business. Built with FastAPI + SQLite + HTMX/Alpine.js.

## How it works

1. Leads land in a Google Sheet via Meta Ads.
2. The CRM polls the sheet every 15 seconds, ingests new leads into its SQLite database, and immediately sends them an SMS via ClickSend (Template 1).
3. When a lead replies, ClickSend delivers the message to the `/webhook/inbound` endpoint, which logs it and marks the lead as "Replied".
4. The dashboard shows all leads and their full SMS history in real-time. You can send custom messages or pre-built follow-up templates directly from the UI.

---

## Prerequisites

- Python 3.11+
- A Google Cloud service account with Sheets API enabled
- A ClickSend account with a virtual number configured for inbound SMS
- The Google Sheet must have a header row (row 1) and data starting at row 2, with columns: **Name (A) | Phone (B) | Status (C)**

---

## Setup

### 1. Install dependencies

```bash
cd crm/
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in all values:

| Variable | Description |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Absolute path to your service account JSON key |
| `SPREADSHEET_ID` | The ID from your Google Sheet URL |
| `CLICKSEND_USERNAME` | Your ClickSend account email |
| `CLICKSEND_API_KEY` | Your ClickSend API key |
| `CLICKSEND_FROM` | Sender ID shown to recipients (max 11 chars) |
| `CLICKSEND_WEBHOOK_SECRET` | Optional token to authenticate ClickSend webhooks |
| `TEMPLATE_1/2/3` | Your SMS templates (`{name}` is auto-replaced) |

### 3. Grant Google Sheet access

Share your target Google Sheet with the **service account email address** (found in the JSON key file as `"client_email"`). Grant **Editor** access so the CRM can write the "Ingested" marker back to the sheet.

### 4. Configure the ClickSend inbound webhook

In your ClickSend dashboard → **SMS** → **Settings** → **Inbound SMS**:

- Set the delivery URL to your server:
  ```
  https://yourdomain.com/webhook/inbound
  ```
- If you set `CLICKSEND_WEBHOOK_SECRET`, append it:
  ```
  https://yourdomain.com/webhook/inbound?secret=YOUR_SECRET
  ```

For local development, use [ngrok](https://ngrok.com/) or [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) to get a public URL:
```bash
ngrok http 8001
# or
cloudflared tunnel --url http://localhost:8001
```

---

## Running the app

Always run from the `crm/` directory (relative paths for the DB and templates depend on it).

```bash
cd crm/
source .venv/bin/activate

# Development (auto-reload on file changes)
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 1
```

> **Important:** Use `--workers 1` in production. SQLite does not support concurrent writes from multiple processes. To scale beyond a single worker, migrate to PostgreSQL and switch `DATABASE_URL` to `postgresql+asyncpg://...`.

Open the dashboard at: **http://localhost:8001**

---

## Production deployment (VPS + nginx)

Run the CRM as a systemd service:

```ini
# /etc/systemd/system/fluentish-crm.service
[Unit]
Description=FluentISH CRM
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/fluentish/crm
ExecStart=/home/ubuntu/fluentish/crm/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now fluentish-crm
```

Add an nginx reverse proxy for `crm.fluentish.co.uk`:

```nginx
server {
    listen 443 ssl;
    server_name crm.fluentish.co.uk;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Required for Server-Sent Events
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        chunked_transfer_encoding on;
    }
}
```

---

## Testing the webhook locally

```bash
curl -X POST http://localhost:8001/webhook/inbound \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "from": "+447712345678",
      "to": "+447900000000",
      "body": "Online please!"
    }]
  }'
```

---

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/leads?status=` | List leads (optional filter) |
| `GET` | `/api/leads/{id}/messages` | Message history for a lead |
| `POST` | `/api/leads/{id}/send` | Send a custom SMS |
| `POST` | `/api/leads/{id}/template/{n}` | Send template 2 or 3 |
| `PATCH` | `/api/leads/{id}/status` | Update lead status manually |
| `POST` | `/webhook/inbound` | ClickSend inbound SMS webhook |
| `GET` | `/events` | Server-Sent Events stream |
