#!/usr/bin/env python
"""scripts/clear_mse_stale.py — เคลียร์ stale last_bar_ts ใน data/mse_state.json (false-block).

ปัญหา: _maybe_enter (ก่อน fix 3e6b9a1) set last_bar_ts แม้ open ล้มเหลว → combo ที่ลองเปิดตอน
symbol ยัง DISABLED (fail) ถูก mark ว่า "จัดการบาร์นี้แล้ว" → บล็อกเข้า order ถาวรจน D1 flip ใหม่.

วิธีแก้ปลอดภัย: ลบ last_bar_ts เฉพาะ combo ที่ **ไม่เคยเปิดสำเร็จ** (ไม่มี key "tickets") — นั่นคือ
false-block แท้ (ถ้าเคยเปิดจริง = มี tickets = ปล่อยไว้ กันเข้าซ้ำ signal ที่ปิดไปแล้ว เช่น โดน SL).

⚠️ รันตอนบอท**หยุด**เท่านั้น (ไม่งั้น live process เขียนทับ). ไม่แตะ MT5/order.
รัน: python scripts/clear_mse_stale.py
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATE = os.path.join(_BASE, "data", "mse_state.json")


def main():
    if not os.path.exists(_STATE):
        print("ไม่มี mse_state.json — ไม่ต้องเคลียร์")
        return
    state = json.load(open(_STATE, encoding="utf-8"))
    cleared = []
    for combo, cs in state.items():
        if not isinstance(cs, dict):
            continue
        has_ticket = bool(cs.get("tickets"))                 # เคยเปิดสำเร็จ
        if cs.get("last_bar_ts") and not has_ticket:
            bar = cs.pop("last_bar_ts")
            cs.pop("retry_after", None)
            cleared.append(f"{combo} (last_bar_ts={bar})")
    if not cleared:
        print("ไม่มี stale last_bar_ts (ทุก combo ที่ dedup มี ticket = เปิดจริง) — ไม่ต้องเคลียร์")
        return
    json.dump(state, open(_STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    print(f"เคลียร์ stale dedup {len(cleared)} combo → เข้า order ได้เมื่อมี signal:")
    for c in cleared:
        print(f"  · {c}")
    print("→ restart บอทได้เลย (combo พวกนี้จะ re-evaluate signal ปัจจุบัน)")


if __name__ == "__main__":
    main()
