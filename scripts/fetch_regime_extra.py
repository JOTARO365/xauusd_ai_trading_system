#!/usr/bin/env python
"""fetch_regime_extra.py — Tier 2 regime context (VIX + gold/silver ratio) จาก Yahoo Finance (ฟรี, ไม่ต้อง key).
เขียน data/regime_extra.json ให้ dashboard endpoint /api/regime-extra (GOLD REGIME panel).

deep research: VIX + gold/silver ratio = **risk-on/off REGIME switch** (ไม่ใช่ tilt/entry signal).
  - VIX สูง = risk-off → ทองมักได้ haven bid (context-supportive)
  - GSR สูง = fear/risk-off (silver underperform)

source: Yahoo chart API (^VIX, GC=F, SI=F) — 3 request ฟรี. 0 token. graceful: fail → เก็บไฟล์เดิม exit 0.
รัน: python scripts\\fetch_regime_extra.py  |  --dry-run
ตั้ง scheduler รันวันละครั้ง (เหมือน fetch_macro_strip.py).
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "regime_extra.json"


def _yahoo_close(symbol: str):
    """คืน (latest_close, prev_close) daily จาก Yahoo chart API. raise ถ้าดึงไม่ได้."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=7d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    q = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    closes = [c for c in q if c is not None]
    if len(closes) < 2:
        raise ValueError(f"{symbol}: closes ไม่พอ")
    return closes[-1], closes[-2]


def build_payload() -> dict:
    vix, vix_prev = _yahoo_close("%5EVIX")
    gold, gold_prev = _yahoo_close("GC=F")
    silv, silv_prev = _yahoo_close("SI=F")
    gsr = gold / silv if silv else None
    gsr_prev = gold_prev / silv_prev if silv_prev else None
    return {
        "ok": True,
        "vix": {"val": round(vix, 2), "chg": round(vix - vix_prev, 2)},
        "gsr": {"val": round(gsr, 1), "chg": round(gsr - gsr_prev, 1)} if gsr and gsr_prev else None,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        payload = build_payload()
    except Exception as exc:
        print(f"WARNING: {exc} — เก็บ regime_extra.json เดิม", file=sys.stderr)
        sys.exit(0)   # graceful
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.dry_run:
        print("[dry-run] ไม่เขียนไฟล์"); return
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(OUT_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, str(OUT_PATH))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
