# Lead Pipeline v1.2
    pip install streamlit pandas requests phonenumbers playwright
    playwright install chromium

## Run
- Dashboard (admin): `python -m streamlit run app.py`
- Telegram bot (phone control): `python bot.py`
- Windows: double-click `start.bat` (starts both)

## Telegram bot setup (5 min)
1. In Telegram, chat with @BotFather -> /newbot -> copy the token.
2. Copy `.env.example` to `.env`, paste the token. Leave ADMIN_IDS empty for now.
3. Run `python bot.py`, then message your bot. It replies with your chat ID.
4. Put your ID (and your brother's, comma separated) in ADMIN_IDS, restart the bot.
The PC must stay on and online for the bot to work. Only listed IDs can use it.

## Scraper alone
`python maps_scraper.py -q "real estate" -l "Indiranagar, Bengaluru" -n 30 -o leads.json --skip-no-contact`

## Import your own list
Dashboard > Import / Export JSON (see sample_businesses.json), or send "Name, phone, type" to the bot.
