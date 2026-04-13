FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser para o scraper_bca (Playwright)
RUN playwright install --with-deps chromium

COPY *.py .
