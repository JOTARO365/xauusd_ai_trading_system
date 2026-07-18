#!/usr/bin/env python
"""
fetch_btc.py — ดึง BTC OHLCV จาก Binance public API (ฟรี ไม่ต้อง key) → data/btc_{daily,hourly}_raw.json

ใช้เป็น data source สำหรับ scripts/btc_backtest.py + BTC-gold intermarket feature (F8).
รัน: & $PY scripts\\fetch_btc.py            (ดึงทั้ง daily + hourly 1 ปี)
     & $PY scripts\\fetch_btc.py PAXGUSDT   (ดึง symbol อื่น เช่น gold-proxy)
"""
import json
import os
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.binance.com/api/v3/klines"


def _get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def fetch(symbol: str, interval: str, days: int) -> list:
    """paginate klines ย้อนหลัง `days` วัน (limit 1000/call)."""
    now_ms = _get(f"{API}?symbol={symbol}&interval={interval}&limit=1")[-1][0]
    per_ms = {"1d": 86400_000, "1h": 3600_000}[interval]
    target = now_ms - days * 86400_000
    cur_end, acc = now_ms, []
    for _ in range(30):
        k = _get(f"{API}?symbol={symbol}&interval={interval}&limit=1000&endTime={cur_end}")
        if not k:
            break
        acc = k + acc
        cur_end = k[0][0] - 1
        if k[0][0] <= target:
            break
        time.sleep(0.3)
    m = {x[0]: x for x in acc if x[0] >= target}
    return [m[t] for t in sorted(m)]


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    tag = symbol.replace("USDT", "").lower()
    for interval, days, suffix in [("1d", 365, "daily"), ("1h", 365, "hourly")]:
        kl = fetch(symbol, interval, days)
        out = os.path.join(_BASE, "data", f"{tag}_{suffix}_raw.json")
        json.dump(kl, open(out, "w"))
        print(f"✅ {symbol} {suffix}: {len(kl)} candles → {out}")


if __name__ == "__main__":
    main()
