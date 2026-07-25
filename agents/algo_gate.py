"""agents/algo_gate.py — entry condition gate (session/hour filter) สำหรับ intraday algo engine.

flag-gated, **default = อนุญาตทุกชั่วโมง (ไม่กระทบ live)**. ตั้ง ALGO_ENTRY_HOURS = allow-list ของชั่วโมง UTC
เพื่อเข้าเฉพาะ session ที่ backtest/segment พิสูจน์ว่า +EV (เช่น "0-13" = Asian+London, "0-7" = Asian).
ใช้กับ regime_tick / regime_executor (intraday). ไม่ใช้กับ TSMOM (ราย D1 — session ไม่เกี่ยว). 0 token.

หลักฐาน (XAUUSD managed 3.4y): ตัด NY (13-20) → exp_R +0.085→+0.122; Asian+BUY → +0.471 (กำไร 90%).
"""
from datetime import datetime, timezone

import config as _cfg


def _parse_ranges(spec):
    """"0-7,13-20" → [(0,7),(13,20)]. ว่าง/พัง → None (= อนุญาตทุกชั่วโมง)."""
    spec = (spec or "").strip()
    if not spec:
        return None
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                out.append((int(a), int(b)))
            else:
                out.append((int(part), int(part) + 1))
        except ValueError:
            continue
    return out or None


def entry_hour_ok(hour=None):
    """True ถ้าชั่วโมง (UTC) นี้อยู่ในช่วงที่อนุญาตให้เข้า (ALGO_ENTRY_HOURS). ว่าง = True เสมอ (default)."""
    rng = _parse_ranges(getattr(_cfg, "ALGO_ENTRY_HOURS", ""))
    if rng is None:
        return True
    if hour is None:
        hour = datetime.now(timezone.utc).hour
    return any(a <= hour < b for a, b in rng)
