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

from loguru import logger

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


def _hb(state, detail=""):
    """Heartbeat: log ว่า algo executor ยังหายใจ + ตัดสินใจอะไร (DEBUG, 0 token, 0 order).
    ให้แยกออกว่า 'ยืนดูถูกต้อง' vs 'พังเงียบ'. grep '[ALGO]' ใน system.log เพื่อดู."""
    logger.debug(f"[ALGO] {state}" + (f" — {detail}" if detail else ""))


def run_regime_executor():
    """เรียกทุก cycle จาก node_position_mgmt. ทำงานเมื่อ REGIME_LIVE=true เท่านั้น. fail-soft.
    บาร์ปิดใหม่ + momentum signal + ไม่มีไม้ ALGO ค้าง → open_order (lot config, SL/TP จาก algo)."""
    if not getattr(_cfg, "REGIME_LIVE", False):
        return None
    if getattr(_cfg, "REGIME_LIVE_TICK", False) or getattr(_cfg, "REGIME_PENDING", False):
        _hb("HAND-OFF", "per-tick/pending คุม entry แล้ว → per-cycle ปิด")
        return None                                     # per-tick / pending จัดการ entry แล้ว → per-cycle ไม่เข้าซ้ำ
    global _last_bar
    bars = _bars_from_feed()
    if bars is None:
        _hb("NO-BARS", "ดึง H1 bars ไม่ได้ (feed ไม่พร้อม)")
        return None
    high, low, close, times = bars
    rec = compute_shadow_signal(high, low, close, times)
    if not rec:
        _hb("NO-SIGNAL", "คำนวณ regime/signal ไม่ได้")
        return None
    regime = rec.get("regime")
    sig = rec.get("signal")
    if not sig or sig.get("algo") != "momentum_breakout":   # เข้าเฉพาะ momentum ใน TREND (mean_rev ตัดแล้ว)
        _hb("STAND-DOWN", f"regime={regime} (ไม่ใช่ TREND → ยืนดู)")
        return None
    from agents.regime_adaptive import is_enabled                 # weekly auto-disable (decay kill switch)
    if not is_enabled("momentum_breakout"):
        _hb("DISABLED", f"regime={regime} · momentum ถูกปิดโดย weekly-adaptive")
        return None
    if rec["bar_ts"] and rec["bar_ts"] == _last_bar:        # บาร์นี้เข้าไปแล้ว → ไม่ซ้ำ
        _hb("ARMED", f"regime=TREND {sig.get('dir')} · เข้าไม้บาร์นี้แล้ว (รอบาร์ถัดไป)")
        return None
    try:                                                    # ไม่ stack: มีไม้ ALGO เปิดอยู่ = ข้าม
        from connectors.mt5_connector import get_open_positions
        for p in (get_open_positions() or []):
            if str(getattr(p, "comment", "") or "").startswith("ALGO"):
                _hb("HOLD", f"regime=TREND {sig.get('dir')} · มีไม้ ALGO เปิดอยู่ → ไม่ stack")
                return None
    except Exception:
        pass
    _hb("ENTER", f"regime=TREND {sig.get('dir')} SL={sig.get('sl_pips')}p TP={sig.get('tp_pips')}p → วาง order")
    _last_bar = rec["bar_ts"]
    from connectors.mt5_connector import open_order
    from agents.algo_exit import sr_tp_pips                  # P-D: TP ตามแนว S/R (flag OFF → RR2 เดิม)
    from agents.algo_sizing import algo_lot                  # P-E: lot risk-based (flag OFF → fixed เดิม)
    tp_pips = sr_tp_pips(sig["dir"], rec["close"], sig["sl_pips"], sig["tp_pips"])
    res = open_order(sig["dir"], sig["sl_pips"], tp_pips, comment="ALGO-mom",
                     lot=algo_lot(sig["sl_pips"]))          # DRY_RUN/cap/lot-clamp ในตัว
    out = {"ts": datetime.now(timezone.utc).isoformat(), "bar_ts": rec["bar_ts"],
           "regime": rec["regime"], "close": rec["close"], "signal": sig, "order": res}
    _log(out)
    return out
