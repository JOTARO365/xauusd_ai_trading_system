"""agents/regime_pending.py — algo-placed pending orders (flag REGIME_PENDING, default OFF).

algo วาง STOP order ล่วงหน้าที่ Donchian level: **straddle** BUY_STOP@high + SELL_STOP@low → MT5 fill เอง
ตอนราคาแตะ (breakout ทางไหนก็ได้). refresh ต่อ H1 bar (level เลื่อน). mode ที่ 3 (market executors ปิดเมื่อเปิดตัวนี้).

SAFETY (จากคำถาม owner 07-19):
  1. มีไม้ ALGO เปิด → cancel ALGO-P pendings ที่เหลือทุก cycle (กัน whipsaw fill 2 ทาง)
  2. **MAX_OPEN guard** — MT5 fill pending ข้าม open_order check → วางเฉพาะทิศที่ same-dir count ยังไม่เต็ม limit
     (กัน 3rd BUY ทะลุ MAX_OPEN แบบที่เจอ: 2 ไม้ BUY เก่าเปิดอยู่)
ต้องมี REGIME_LIVE=true. ⚠️ LIVE MONEY. ผ่าน place_pending_order เดิม (DRY_RUN/expiry). kill = REGIME_PENDING=false.
"""
import logging
import os
import sys

import config as _cfg

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R

logger = logging.getLogger(__name__)
_last_bar_hour = None


def _same_dir_count(positions, direction):
    return sum(1 for p in positions if str(p.get("direction", "")).upper() == direction)


def _cancel_algo_pendings():
    from connectors.mt5_connector import get_pending_orders, cancel_pending_order
    n = 0
    for o in (get_pending_orders() or []):
        cmt = o.get("comment") if isinstance(o, dict) else getattr(o, "comment", "")
        tk = o.get("ticket") if isinstance(o, dict) else getattr(o, "ticket", None)
        if str(cmt or "").startswith("ALGO-P") and tk and cancel_pending_order(tk):
            n += 1
    return n


def _max_open_limit():
    try:
        from connectors.mt5_connector import MONEY_MANAGEMENT, count_protected_slots
        return MONEY_MANAGEMENT["max_open_trades"] + count_protected_slots()
    except Exception:
        return getattr(_cfg, "MAX_OPEN_TRADES", 2)


def manage_algo_pending():
    """เรียกทุก cycle จาก node_position_mgmt. คืนจำนวน pending ที่วางรอบนี้. fail-soft."""
    if not (getattr(_cfg, "REGIME_LIVE", False) and getattr(_cfg, "REGIME_PENDING", False)):
        return 0
    global _last_bar_hour
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import get_open_positions, place_pending_order
        from agents.regime_shadow import _bars_from_feed
        positions = get_open_positions() or []
        # SAFETY 1: มีไม้ ALGO เปิด → cancel ALGO-P ที่เหลือ (กัน fill ฝั่งตรงข้าม) แล้วจบ
        if any(str(p.get("comment") or "").startswith("ALGO") for p in positions):
            _cancel_algo_pendings()
            return 0
        tick = mt5.symbol_info_tick(_cfg.SYMBOL)
        if not tick:
            return 0
        hour = int(tick.time // 3600)
        if hour == _last_bar_hour:                 # refresh 1 ครั้ง/H1 bar
            return 0
        bars = _bars_from_feed()
        if bars is None:
            return 0
        high, low, close, _t = bars
        n = len(close)
        if n < R.VOL_LOOKBACK + 40:
            return 0
        er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
        vp = R.vol_percentile(close); atr = R.atr(high, low, close)
        i = n - 2
        _last_bar_hour = hour
        _cancel_algo_pendings()                    # cancel straddle เก่า (level เลื่อนตาม bar ใหม่)
        if R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            return 0
        lv = R.momentum_levels(i, high, low, close, atr)
        if not lv:
            return 0
        limit = _max_open_limit()                  # SAFETY 2: MAX_OPEN guard ต่อทิศ
        placed = 0
        if _same_dir_count(positions, "BUY") < limit:
            r = place_pending_order("BUY_STOP", lv["buy_level"], lv["sl_pips"], lv["tp_pips"],
                                    comment="ALGO-P", expiry_hours=2)
            if r.get("success"):
                placed += 1
        else:
            logger.info("[REGIME-PENDING] ข้าม BUY_STOP — BUY เต็ม MAX_OPEN แล้ว")
        if _same_dir_count(positions, "SELL") < limit:
            r = place_pending_order("SELL_STOP", lv["sell_level"], lv["sl_pips"], lv["tp_pips"],
                                    comment="ALGO-P", expiry_hours=2)
            if r.get("success"):
                placed += 1
        else:
            logger.info("[REGIME-PENDING] ข้าม SELL_STOP — SELL เต็ม MAX_OPEN แล้ว")
        if placed:
            from agents.regime_executor import _log
            _log({"via": "pending", "ts_hour": hour, "buy_level": lv["buy_level"], "sell_level": lv["sell_level"],
                  "sl_pips": lv["sl_pips"], "tp_pips": lv["tp_pips"], "placed": placed})
            logger.warning(f"[REGIME-PENDING] วาง straddle {placed} ขา @ {lv['buy_level']:.2f}/{lv['sell_level']:.2f}")
        return placed
    except Exception as e:
        logger.error(f"[REGIME-PENDING] {e}")
        return 0
