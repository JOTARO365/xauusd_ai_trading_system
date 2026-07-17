"""
trade_excursion.py — P1c SHADOW excursion logging (ADD-ONLY, 0 behavior change)

Sample unrealized excursion (เป็น R) ของทุก open SYSTEM position ต่อ cycle →
logs/trade_excursions.jsonl. STATELESS: append sample ปัจจุบันเฉย ๆ; MFE/MAE/time-to-peak
คำนวณ offline ทีหลัง (max/min ของ unreal_r ต่อ ticket) เพื่อ fit statistical-exit
(docs/DESIGN_statistical_exit.md — P1c enabler).

⚠️ SHADOW-ONLY: อ่าน MT5 read-only (positions_get / tick) + log อย่างเดียว — ไม่แตะ
order/SL/TP/money ใด ๆ. fail-soft (error = ไม่ทำอะไร, cycle เดินต่อ). ปิดด้วย env TRADE_EXCURSION=false.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

import config as _cfg

_EXC = Path("logs") / "trade_excursions.jsonl"
_PIP = 0.01
_DEFAULT_SL_PIPS = 2000   # fallback denominator เมื่อไม้ยังไม่มี SL (กัน R หาร 0)


def log_excursions() -> None:
    """Append 1 sample ต่อ open SYSTEM position. fail-soft — ห้าม raise ออกไปกระทบ cycle."""
    try:
        if not getattr(_cfg, "TRADE_EXCURSION", True):
            return
        from connectors.mt5_connector import get_open_positions, get_current_price
        cur = get_current_price()
        if not cur or cur <= 0:
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for p in (get_open_positions() or []):
            if p.get("source") != "SYSTEM":
                continue
            entry = p.get("open_price")
            if not entry:
                continue
            direction = p.get("direction")
            sign = 1 if direction == "BUY" else -1
            unreal_pips = (cur - entry) / _PIP * sign          # + = กำไร, − = ขาดทุน (frame ทิศไม้)
            sl = p.get("sl") or 0
            risk_pips = abs(entry - sl) / _PIP if sl else _DEFAULT_SL_PIPS
            unreal_r = round(unreal_pips / risk_pips, 4) if risk_pips else None
            rows.append({
                "at": now, "ticket": p.get("ticket"), "direction": direction,
                "entry": entry, "sl": sl or None, "tp": p.get("tp") or None, "cur": cur,
                "unreal_pips": round(unreal_pips, 1), "unreal_r": unreal_r,
                "profit": p.get("profit"),
            })
        if not rows:
            return
        _EXC.parent.mkdir(parents=True, exist_ok=True)
        with _EXC.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[EXCURSION] fail-soft: {e}")
