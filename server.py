"""One-process admin: JSON API + web UI. Run: ADMIN_PASSWORD=secret python server.py
Host: gunicorn -w 1 --threads 4 -b 0.0.0.0:8000 server:app   (keep 1 worker: job state is in memory)

Layout:
  server.py        app setup only
  core.py          shared job state, execution lock, small helpers
  db_setup.py      startup migrations
  templating.py    message template rendering
  routes/          one blueprint per feature (auth, leads, find, runs, send, media, whatsapp, settings)
  static/          index.html, css/*.css, js/*.js
"""
import os, secrets
from flask import Flask, jsonify
from db_setup import migrate
from routes import register

app = Flask(__name__, static_folder="static")
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(16)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE") == "1",
                  MAX_CONTENT_LENGTH=17 << 20)


@app.errorhandler(413)
def too_big(e): return jsonify(error="File is too large (max 16 MB)"), 413


migrate()
register(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
