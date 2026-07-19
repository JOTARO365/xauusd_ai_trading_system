"""agents/algo_state.py — สถานะ algo ล่าสุด (regime + decision) เขียน/อ่านไฟล์เดียว. display-only, 0 token.

executor/tick เขียนทุกครั้งที่ประเมิน → terminal panel + dashboard อ่านแสดง "algo กำลังทำอะไร" แบบ realtime
โดยไม่ต้อง recompute. fail-soft (ไม่กระทบ trading path).
"""
import json
import os
from datetime import datetime, timezone

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "algo_state.json")


def write_state(state, regime=None, detail="", via="cycle", extra=None):
    """เขียนสถานะล่าสุด. state=STAND-DOWN/ARMED/ENTER/HOLD/HAND-OFF/... via=cycle/tick/pending. fail-soft."""
    try:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "state": state,
               "regime": regime, "detail": detail, "via": via}
        if extra:
            rec.update(extra)
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def read_state():
    """อ่านสถานะล่าสุด. คืน dict หรือ {} ถ้าไม่มี/เสีย."""
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
