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
from agents import shadow_switches as _sw          # unify: dashboard switch คุม real/paper/off เหมือนทุกคู่

_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "regime_live.jsonl")
_last_bar = None                                    # dedup: 1 order / H1 bar ต่อ process run
_ENGINE_START = None                                # cold-start gate: เข้าเฉพาะ signal บาร์ที่ปิดหลัง engine เริ่ม (กัน stale-entry)


def _log(rec):
    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _too_close_algo(direction, entry, atr):
    """True = มีไม้ ALGO ทิศเดียวกันเปิดอยู่ภายใน ALGO_ENTRY_MIN_GAP_ATR·ATR ของ entry → กัน stack เกาะจุดเดิม.
    ใช้ทั้ง regime_executor + regime_tick. fail-soft → False (ไม่บล็อกถ้าเช็คไม่ได้)."""
    try:
        gap = float(getattr(_cfg, "ALGO_ENTRY_MIN_GAP_ATR", 0) or 0)
        if gap <= 0 or not entry or not atr:
            return False
        from connectors.mt5_connector import get_open_positions
        import MetaTrader5 as mt5
        want = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        same = []
        for p in (get_open_positions() or []):
            cm = (p.get("comment") if isinstance(p, dict) else getattr(p, "comment", "")) or ""
            tp = p.get("type") if isinstance(p, dict) else getattr(p, "type", None)
            px = p.get("price_open") if isinstance(p, dict) else getattr(p, "price_open", None)
            if str(cm).startswith("ALGO") and tp == want and px:
                same.append(px)
        from agents import structural_sl
        return structural_sl.near_existing(float(entry), float(atr), same, gap)
    except Exception:
        return False


def _structural_sl_gold(direction, entry, atr, base_sl_pips, base_tp_pips):
    """flag STRUCTURAL_SL_GOLD: วาง SL ทองที่ปลายไส้ D1 ปิดล่าสุด เสมอ. default OFF → base. fail-soft.
    คืน (sl_pips, tp_pips, force_min_lot)."""
    try:
        from connectors.mt5_connector import SYMBOL
        import MetaTrader5 as mt5
        from agents import structural_sl
        info = mt5.symbol_info(SYMBOL)
        point = float(info.point) if info and info.point else 0.0
        sl_pips, tp_pips, meta = structural_sl.live_adjust(
            direction, float(entry or 0), float(atr or 0), point, SYMBOL,
            float(base_sl_pips), float(base_tp_pips), _cfg,
            enabled=getattr(_cfg, "STRUCTURAL_SL_GOLD", False))
        if meta is not None:
            logger.info(f"[ALGO] structural SL {meta['base_pips']}p → {meta['struct_pips']}p "
                        f"(ปลายไส้ D1 @ {meta['sl_price']}) → min lot")
        return sl_pips, tp_pips, (meta is not None and meta.get("force_min_lot", False))
    except Exception as e:
        logger.debug(f"[ALGO] structural SL skip ({e})")
        return base_sl_pips, base_tp_pips, False


def _hb(state, detail="", regime=None):
    """Heartbeat: log ว่า algo executor ยังหายใจ + ตัดสินใจอะไร (DEBUG, 0 token, 0 order) + เขียน algo_state
    ให้ terminal/dashboard อ่าน. แยก 'ยืนดูถูกต้อง' vs 'พังเงียบ'. grep '[ALGO]' ใน system.log."""
    logger.debug(f"[ALGO] {state}" + (f" — {detail}" if detail else ""))
    try:
        from agents.algo_state import write_state
        write_state(state, regime=regime, detail=detail, via="cycle")
    except Exception:
        pass


def run_regime_executor():
    """เรียกทุก cycle จาก node_position_mgmt. ทำงานเมื่อ REGIME_LIVE=true เท่านั้น. fail-soft.
    บาร์ปิดใหม่ + momentum signal + ไม่มีไม้ ALGO ค้าง → open_order (lot config, SL/TP จาก algo)."""
    if not getattr(_cfg, "REGIME_LIVE", False):
        return None
    if getattr(_cfg, "TSMOM_LIVE", False) and not getattr(_cfg, "TSMOM_COEXIST", False):   # TSMOM directional → intraday ยืนดู (เว้นแต่ COEXIST=true → ทำงานคู่กัน)
        _hb("HAND-OFF", "TSMOM-D1 เป็น directional engine → momentum intraday งดเข้า")
        return None
    if getattr(_cfg, "REGIME_LIVE_TICK", False) or getattr(_cfg, "REGIME_PENDING", False):
        _hb("HAND-OFF", "per-tick/pending ควบคุม entry แล้ว → per-cycle หยุดทำงาน")
        return None                                     # per-tick / pending จัดการ entry แล้ว → per-cycle ไม่เข้าซ้ำ
    global _last_bar, _ENGINE_START
    if _ENGINE_START is None:                            # cold-start: จำเวลาที่ engine เริ่มคุม entry
        import time as _t
        _ENGINE_START = _t.time()
    bars = _bars_from_feed()
    if bars is None:
        _hb("NO-BARS", "ไม่สามารถดึง H1 bars ได้ (feed ไม่พร้อม)")
        return None
    high, low, close, times = bars
    rec = compute_shadow_signal(high, low, close, times)
    if not rec:
        _hb("NO-SIGNAL", "ไม่สามารถคำนวณ regime/signal ได้")
        return None
    regime = rec.get("regime")
    sig = rec.get("signal")
    if not sig or sig.get("algo") != "momentum_breakout":   # เข้าเฉพาะ momentum ใน TREND (mean_rev ตัดแล้ว)
        _hb("STAND-DOWN", f"regime={regime} (ไม่ใช่ TREND → งดเข้าออเดอร์)", regime=regime)
        return None
    from agents.regime_adaptive import is_enabled                 # weekly auto-disable (decay kill switch)
    if not is_enabled("momentum_breakout"):
        _hb("DISABLED", f"regime={regime} · momentum ถูกปิดใช้งานโดย weekly-adaptive")
        return None
    if rec["bar_ts"] and rec["bar_ts"] == _last_bar:        # บาร์นี้เข้าไปแล้ว → ไม่ซ้ำ
        _hb("ARMED", f"regime=TREND {sig.get('dir')} · เข้าออเดอร์บาร์นี้แล้ว (รอบาร์ถัดไป)")
        return None
    if _ENGINE_START and rec["bar_ts"]:                     # cold-start: บาร์ปิดก่อน engine เริ่ม = stale → seed + รอบาร์สด
        try:
            if datetime.fromisoformat(rec["bar_ts"]).timestamp() + 3600 <= _ENGINE_START:   # H1 = +3600
                _last_bar = rec["bar_ts"]
                _hb("COLD-START", f"regime=TREND {sig.get('dir')} · signal บาร์ปิดก่อน engine เริ่ม (stale) → รอบาร์สด")
                return None
        except Exception:
            pass
    try:                                                    # stack guard: ถือครบ ALGO_MAX_STACK = ข้าม (dict-safe)
        from connectors.mt5_connector import get_open_positions
        from agents.regime_tick import _algo_pos_protected   # ไม้ protected (trailing เลย BE) ไม่กิน slot
        _algo_open = sum(1 for p in (get_open_positions() or [])
                         if str((p.get("comment") if isinstance(p, dict) else getattr(p, "comment", "")) or "").startswith("ALGO")
                         and not _algo_pos_protected(p))
        if _algo_open >= getattr(_cfg, "ALGO_MAX_STACK", 1):
            _hb("HOLD", f"regime=TREND {sig.get('dir')} · ถือครบ {_algo_open} ออเดอร์ ALGO → ไม่เปิดสถานะซ้อน")
            return None
    except Exception:
        pass
    _structural_on = getattr(_cfg, "STRUCTURAL_SL_GOLD", False)   # structural = SL ปลายไส้ D1 + min lot เสมอ → ข้าม standdown (ยอม risk%)
    if not _structural_on:
        from agents.algo_sizing import standdown_for_size          # small-acct guard: min-lot เสี่ยงเกินเพดาน = ข้าม
        _skip, _si = standdown_for_size(sig["sl_pips"])
        if _skip:
            _hb("SIZE-STANDDOWN", f"regime=TREND {sig.get('dir')} · min-lot มีความเสี่ยง {_si.get('risk_pct',0)*100:.1f}% "
                f"> เพดาน {_si.get('ceiling',0)*100:.0f}% (เงินทุนไม่เพียงพอ SL {sig.get('sl_pips')}p) → ข้าม", regime="TREND")
            return None
    if _too_close_algo(sig["dir"], rec.get("close"), rec.get("atr")):   # กัน stack เกาะจุดเดิม (≤ n×ATR)
        _hb("PROXIMITY-SKIP", f"{sig.get('dir')} · มีไม้ ALGO ทิศเดียวใกล้ ≤{getattr(_cfg,'ALGO_ENTRY_MIN_GAP_ATR',0)}×ATR → งดเข้าจุดเดิม", regime="TREND")
        return None
    from agents.algo_gate import entry_hour_ok
    if not entry_hour_ok():                                   # session gate (ALGO_ENTRY_HOURS · ว่าง=ทุกชม default)
        _hb("SESSION-GATE", "นอกช่วง ALGO_ENTRY_HOURS → งดเข้า", regime="TREND")
        return None
    st = _sw.gold_state("regime_momentum")                   # unify: switch = single control (LIVE=จริง · SHADOW=paper · OFF=งด)
    if st == _sw.OFF:
        _hb("SWITCH-OFF", "dashboard switch = OFF → งดเข้า", regime="TREND")
        return None
    _hb("ENTER", f"{sig.get('dir')} SL={sig.get('sl_pips')}p TP={sig.get('tp_pips')}p → ส่งคำสั่ง", regime="TREND")
    _last_bar = rec["bar_ts"]
    from connectors.mt5_connector import open_order
    from agents.algo_exit import sr_tp_pips                  # P-D: TP ตามแนว S/R (flag OFF → RR2 เดิม)
    from agents.algo_sizing import algo_lot                  # P-E: lot risk-based (flag OFF → fixed เดิม)
    tp_pips = sr_tp_pips(sig["dir"], rec["close"], sig["sl_pips"], sig["tp_pips"])
    sl_pips, tp_pips, _force_min = _structural_sl_gold(sig["dir"], rec.get("close"), rec.get("atr"),
                                                       sig["sl_pips"], tp_pips)
    _lot = float(getattr(_cfg, "MIN_LOT", 0.01)) if _force_min else algo_lot(sl_pips)  # structural = min lot เสมอ
    res = open_order(sig["dir"], sl_pips, tp_pips, comment="ALGO-mom",
                     lot=_lot,                              # DRY_RUN/cap/clamp ในตัว
                     shadow=(st == _sw.SHADOW))              # SHADOW → paper-fill
    out = {"ts": datetime.now(timezone.utc).isoformat(), "bar_ts": rec["bar_ts"],
           "regime": rec["regime"], "close": rec["close"], "signal": sig, "order": res}
    _log(out)
    return out
