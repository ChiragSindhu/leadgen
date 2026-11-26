FROM python:3.12-slim

WORKDIR /app

# Install missing system library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# requirements.txt must include psycopg2-binary (Supabase Postgres driver)
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

ENV PYTHONUNBUFFERED=1

# One worker on purpose: search progress is kept in memory. DATABASE_URL is set in the host's env vars.
CMD gunicorn -w 1 --threads 2 --timeout 120 -b 0.0.0.0:${PORT:-8000} server:app
