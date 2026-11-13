
FROM python:3.12-slim

WORKDIR /app

# Install missing system library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

ENV PYTHONUNBUFFERED=1

CMD gunicorn -w 1 --threads 4 --timeout 120 -b 0.0.0.0:${PORT:-8000} server:app
