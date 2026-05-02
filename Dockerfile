FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Python packages — ข้าม MetaTrader5 (Windows only)
COPY requirements.txt .
RUN grep -v "MetaTrader5" requirements.txt > /tmp/req_linux.txt && \
    pip install --no-cache-dir -r /tmp/req_linux.txt

COPY . .

RUN mkdir -p logs

EXPOSE 5050

CMD ["python", "dashboard/app.py"]
