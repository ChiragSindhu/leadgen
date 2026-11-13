# Vansh Lead

Find local businesses, keep a clean lead database, and message them in small human-sized batches.
One Flask server serves the admin web app (works on phone and desktop); an optional Telegram bot controls the same data.

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
| `pipeline.py` | Database, fetchers, dedupe, change detection |
| `maps_scraper.py` | Playwright Google Maps scraper (runs as a subprocess) |
| `bot.py` | Optional Telegram bot |
| `app.py` | Older Streamlit dashboard (optional, needs `streamlit pandas`) |

## Run locally
```
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # then edit ADMIN_PASSWORD and SECRET_KEY
python server.py            # http://127.0.0.1:8000
```
Keep `index.html` in a `static/` folder next to `server.py`.

## Environment variables
| Name | Required | Meaning |
|---|---|---|
| `ADMIN_PASSWORD` | yes | Login password. If unset, a temporary one is printed at startup |
| `SECRET_KEY` | yes (prod) | Signs login sessions. Use a long random string |
| `PORT` | no | Default 8000 (Render sets it) |
| `DATA_DIR` | prod | Folder for `leads.db`. On Render use the disk path `/var/data` |
| `COOKIE_SECURE` | prod | `1` when served over HTTPS |
| `GOOGLE_API_KEY` | no | Or paste it once in Find > Google API |
| `TELEGRAM_TOKEN`, `ADMIN_IDS` | bot only | From @BotFather; allowed chat IDs, comma separated |

## Deploy on Render
Use a **Docker** web service. The scraper needs Chromium and system libraries, which Render's native Python runtime can't install.

1. Push this folder to GitHub (`.gitignore` keeps `.env` and the database out).
2. Render > **New > Blueprint** and pick the repo (it reads `render.yaml`), or **New > Web Service** with:
   - Runtime: **Docker** (uses the `Dockerfile`)
   - Instance: **Starter** or higher
   - **Disk**: name `data`, mount path `/var/data`, 1 GB
   - Health check path: `/`
3. Environment variables: `ADMIN_PASSWORD` (yours), `SECRET_KEY` (generate), `DATA_DIR=/var/data`, `COOKIE_SECURE=1`, optionally `GOOGLE_API_KEY`.
4. Deploy, open the `onrender.com` URL, sign in.

Render notes:
- **Free plan does not work well.** No persistent disk (the database is wiped on every deploy or restart), the service sleeps, and 512 MB RAM is tight for Chromium. Use Starter (or higher if scraping crashes with out-of-memory).
- **Keep one instance and one worker.** SQLite is a single file and search progress is held in memory. Do not scale out.
- **Scraping from a cloud IP** gets CAPTCHAs far more often than from your home PC. If a run stops with a CAPTCHA warning, use OpenStreetMap or the Google API on the server, and run the scraper at home, then import the JSON (Leads > Add).
- The Telegram bot is not part of the Render service (a disk can't be shared between services). Run `bot.py` on your own PC, or add it to the same container if you need it.
- Back up regularly: Render disk snapshots, or copy `leads.db` out.

## Safety and compliance
- Messages are sent by you in WhatsApp (tap-to-send). There is no auto-sender, on purpose: automating WhatsApp for cold outreach gets numbers banned. Keep batches small and include an opt-out line.
- Scraping Google Maps is against Google's terms. Use it modestly, or prefer the official API.
- Check local rules on unsolicited commercial messages (for example India's TRAI and DPDP, GDPR in the EU).

## Troubleshooting
- **404 on `/`**: `index.html` is not in `static/`.
- **Page loads but shows nothing after login**: use the latest `index.html` and hard refresh.
- **"Search already running"**: wait for the current run, or restart the server.
- **Phone numbers rejected**: the default country is India; numbers from other countries need the `+` code.
