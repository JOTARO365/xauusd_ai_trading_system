"""agents/regime_executor.py — algo entry LIVE (flag REGIME_LIVE, default OFF).

algo เป็น "ตัวเดียว" ที่วาง order เมื่อ REGIME_LIVE (LLM/pending/ZRE/swing ปิดหมด). วาง order จริงจาก
momentum breakout signal (deterministic, ONLY TREND) ผ่าน `open_order` เดิม → ได้ DRY_RUN guard +
daily-trade-cap + fixed-lot (0.01) + SL/TP ครบในตัว = ยึด config limits ตามที่สั่ง.

⚠️ LIVE MONEY. default OFF. เปิด = พี่ควบคุมเอง (.env REGIME_LIVE=true + restart). แนะนำ DRY_RUN verify ก่อน.
P2: ยังไม่มี validated edge → lot จิ๋ว เก็บ data จริง หา edge ใหม่. kill switch = REGIME_LIVE=false.
ต่อยอด scripts/regime_lib.py (route) ผ่าน agents/regime_shadow (signal compute). ดู docs/DESIGN_regime_shadow.md.
"""
import json
import os
from datetime import datetime, timezone

import config as _cfg
from agents.regime_shadow import _bars_from_feed, compute_shadow_signal

_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "regime_live.jsonl")
_last_bar = None                                    # dedup: 1 order / H1 bar ต่อ process run


def _log(rec):
    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def run_regime_executor():
    """เรียกทุก cycle จาก node_position_mgmt. ทำงานเมื่อ REGIME_LIVE=true เท่านั้น. fail-soft.
    บาร์ปิดใหม่ + momentum signal + ไม่มีไม้ ALGO ค้าง → open_order (lot config, SL/TP จาก algo)."""
    if not getattr(_cfg, "REGIME_LIVE", False):
        return None
    if getattr(_cfg, "REGIME_LIVE_TICK", False):        # per-tick thread จัดการแล้ว → per-cycle ไม่ต้องเข้าซ้ำ
        return None
    global _last_bar
    bars = _bars_from_feed()
    if bars is None:
        return None
    high, low, close, times = bars
    rec = compute_shadow_signal(high, low, close, times)
    if not rec:
        return None
    sig = rec.get("signal")
    if not sig or sig.get("algo") != "momentum_breakout":   # เข้าเฉพาะ momentum ใน TREND (mean_rev ตัดแล้ว)
        return None
    if rec["bar_ts"] and rec["bar_ts"] == _last_bar:        # บาร์นี้เข้าไปแล้ว → ไม่ซ้ำ
        return None
    try:                                                    # ไม่ stack: มีไม้ ALGO เปิดอยู่ = ข้าม
        from connectors.mt5_connector import get_open_positions
        for p in (get_open_positions() or []):
            if str(getattr(p, "comment", "") or "").startswith("ALGO"):
                return None
    except Exception:
        pass
    _last_bar = rec["bar_ts"]
    from connectors.mt5_connector import open_order
    res = open_order(sig["dir"], sig["sl_pips"], sig["tp_pips"], comment="ALGO-mom")  # DRY_RUN/cap/lot ในตัว
    out = {"ts": datetime.now(timezone.utc).isoformat(), "bar_ts": rec["bar_ts"],
           "regime": rec["regime"], "close": rec["close"], "signal": sig, "order": res}
    _log(out)
    return out
