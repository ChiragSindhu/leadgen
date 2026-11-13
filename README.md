# Vansh Lead

Find local businesses, keep a clean lead database, and message them in small human-sized batches.
One Flask server serves the admin web app (works on phone and desktop); an optional Telegram bot controls the same data.
All data lives in **Supabase (Postgres)**, so the server, the bot and your PC all share one database.

## Features
- **Find** leads from three sources: Google Maps scraper, OpenStreetMap, Google Places API. Live progress and a full **Runs** log.
- **Leads** database: dedupe by phone, change history, quality score, lead profile, JSON import, notes, statuses.
- **Send** flow: one lead at a time, message pre-typed, you press send in WhatsApp (tap-to-send). Daily limit, undo, skipped leads loop.
- Optional **Telegram bot** (`bot.py`) for controlling from a phone.

## Project layout
| File | Purpose |
|---|---|
| `server.py` | Web server and JSON API (the app you deploy) |
| `static/index.html` | The whole front end (responsive, mobile-first) |
| `pipeline.py` | Database (Supabase Postgres), fetchers, dedupe, change detection |
| `maps_scraper.py` | Playwright Google Maps scraper (runs as a subprocess) |
| `bot.py` | Optional Telegram bot |
| `app.py` | Older Streamlit dashboard (optional, needs `streamlit pandas`) |

## Set up Supabase
1. Create a project at supabase.com (the free plan works).
2. Click **Connect** at the top of the dashboard, open **Direct / Connection string**, and copy the **Session pooler** string (recommended for Render and most hosts, which often lack IPv6). Use the **Direct** string only if your host supports IPv6.
3. Replace `[YOUR-PASSWORD]` in it with your database password (Project Settings > Database > Reset password if you forgot it).
4. Put it in `.env` as `DATABASE_URL`.

Tables are created automatically on first run. Row-level security is switched on with no policies, so the public (publishable) API key cannot read your leads. The app connects with the database connection string, which is not affected by that.

Never put the database password or the `sb_secret_...` key in front-end code or commit it to GitHub.

## Run locally
```
pip install -r requirements.txt     # must include psycopg2-binary
playwright install chromium
cp .env.example .env                # then edit ADMIN_PASSWORD, SECRET_KEY, DATABASE_URL
python server.py                    # http://127.0.0.1:8000
```
Keep `index.html` in a `static/` folder next to `server.py`.

## Environment variables
| Name | Required | Meaning |
|---|---|---|
| `DATABASE_URL` | yes | Supabase Postgres connection string (see above) |
| `ADMIN_PASSWORD` | yes | Login password. If unset, a temporary one is printed at startup |
| `SECRET_KEY` | yes (prod) | Signs login sessions. Use a long random string |
| `PORT` | no | Default 8000 (Render sets it) |
| `COOKIE_SECURE` | prod | `1` when served over HTTPS |
| `GOOGLE_API_KEY` | no | Or paste it once in Find > Google API |
| `TELEGRAM_TOKEN`, `ADMIN_IDS` | bot only | From @BotFather; allowed chat IDs, comma separated |

`DATA_DIR` is no longer used.

## Deploy on Render
Use a **Docker** web service. The scraper needs Chromium and system libraries, which Render's native Python runtime can't install.

1. Push this folder to GitHub (`.gitignore` keeps `.env` out).
2. Render > **New > Web Service** with:
   - Runtime: **Docker** (uses the `Dockerfile`)
   - Instance: **Starter** or higher (Chromium needs more than 512 MB)
   - Health check path: `/`
   - No disk needed any more, since data is in Supabase.
3. Environment variables: `DATABASE_URL`, `ADMIN_PASSWORD`, `SECRET_KEY` (generate), `COOKIE_SECURE=1`, optionally `GOOGLE_API_KEY`.
4. Deploy, open the `onrender.com` URL, sign in.

Render notes:
- Your data now survives deploys and restarts, because it is in Supabase and not on the server.
- **Keep one instance and one worker.** Search progress is held in memory, so do not scale out.
- **Scraping from a cloud IP** gets CAPTCHAs far more often than from your home PC. If a run stops with a CAPTCHA warning, use OpenStreetMap or the Google API on the server, or run the scraper at home. Because the database is shared, running `server.py` or `bot.py` on your PC with the same `DATABASE_URL` saves into the same leads.
- The **Telegram bot** can now run anywhere (your PC, a small VPS) with the same `DATABASE_URL`, and it sees the same leads as the web app.
- Backups: Supabase takes daily backups on paid plans. On the free plan, export regularly (Leads > export JSON, or Supabase Table Editor > Export CSV).

## Moving old SQLite data
If you already have a `leads.db`, its data is not copied automatically. Export from the old app (Leads > export JSON) and import into the new one (Leads > Add), or ask for a one-time migration script.

## Safety and compliance
- Messages are sent by you in WhatsApp (tap-to-send). There is no auto-sender, on purpose: automating WhatsApp for cold outreach gets numbers banned. Keep batches small and include an opt-out line.
- Scraping Google Maps is against Google's terms. Use it modestly, or prefer the official API.
- Check local rules on unsolicited commercial messages (for example India's TRAI and DPDP, GDPR in the EU).

## Troubleshooting
- **404 on `/`**: `index.html` is not in `static/`.
- **Page loads but shows nothing after login**: use the latest `index.html` and hard refresh.
- **"Search already running"**: wait for the current run, or restart the server.
- **"DATABASE_URL missing"**: add it to `.env` (or the Render environment).
- **Connection timeout or "Network is unreachable"**: the Direct string is IPv6-only. Switch to the Session pooler string.
- **"password authentication failed"**: wrong password in the URL. Reset it in Supabase and special characters must be URL-encoded (`@` becomes `%40`).
- **Phone numbers rejected**: the default country is India; numbers from other countries need the `+` code.