# ─────────────────────────────────────────────────────────────
# Dashboard container (Linux)
# ใช้กับ docker-compose.yml → docker compose up
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Build deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Python packages — ข้าม MetaTrader5 (Windows-only)
COPY requirements.txt .
RUN grep -v "MetaTrader5" requirements.txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt

COPY . .
RUN mkdir -p logs

EXPOSE 5050
CMD ["python", "-u", "dashboard/app.py"]
