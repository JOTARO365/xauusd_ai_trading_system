"""agents/cockpit_executor.py — Discretion Cockpit Phase 2: วางออเดอร์ manual (user ตัดสินใจ, บอท execute).

ดุลยพินิจ user เลือก *ทิศ/จังหวะ* · บอทบังคับ *ความเสี่ยง* (structural-SL + guard เดิมของ open_order).
INVARIANT-safe: มนุษย์ตัดสิน entry (ไม่ใช่บอทเดา). risk guard กลไกเสมอ. Claude ไม่เรียกเอง — ผ่าน
/api/cockpit/order (user กด + confirm) เท่านั้น.

Safety (2 ชั้น):
  1. COCKPIT_LIVE=false (default) → refuse ทุก order
  2. reuse open_order → LONG_ONLY_ALL + margin + cap + min-lot guard ในตัว (block SELL ถ้าเปิด long-only)
structural-SL D1/H4 wick (structural_sl.live_adjust) เหมือนทุก path. own magic (SYSTEM_MAGIC+8). fail-soft.
"""
import os
import sys

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _manual_magic():
    from connectors.mt5_connector import SYSTEM_MAGIC
    return SYSTEM_MAGIC + 8                                # cockpit-manual magic (offset 8; pairs=7, MSE=1-6)


def place_manual(symbol, direction, lot=None, sl_atr_mult=1.5, rr=2.0):
    """วางออเดอร์ manual. gate COCKPIT_LIVE. คืน dict {ok, ...}. reuse open_order (guard ครบ)."""
    import config as _cfg
    if not getattr(_cfg, "COCKPIT_LIVE", False):
        return {"ok": False, "reason": "COCKPIT_LIVE=off (เปิด flag ก่อนถึงจะวางจริง)"}
    direction = str(direction).upper()
    if direction not in ("BUY", "SELL"):
        return {"ok": False, "reason": "direction ต้อง BUY/SELL"}
    try:
        import MetaTrader5 as mt5
        import numpy as np                                 # noqa: F401
        from connectors.pair_collector import _broker_map
        from connectors.mt5_connector import open_order
        sys.path.insert(0, os.path.join(_BASE, "scripts"))
        import regime_lib as R
        broker = (_broker_map() or {}).get(symbol, symbol)
        mt5.symbol_select(broker, True)
        info = mt5.symbol_info(broker); tk = mt5.symbol_info_tick(broker)
        if not info or not tk:
            return {"ok": False, "reason": f"symbol {broker} ไม่พร้อม"}
        point = float(info.point)
        r = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_H1, 0, 120)
        if r is None or len(r) < 40:
            return {"ok": False, "reason": "bars ไม่พอ"}
        hi, lo, cl = r["high"].astype(float), r["low"].astype(float), r["close"].astype(float)
        atr = R.atr(hi, lo, cl); av = float(atr[-2]) if atr[-2] == atr[-2] else 0.0
        if av <= 0:
            return {"ok": False, "reason": "ATR เพี้ยน"}
        entry = tk.ask if direction == "BUY" else tk.bid
        base_sl = (float(sl_atr_mult) * av) / point
        base_tp = base_sl * float(rr)
        # structural-SL D1/H4 wick (เหมือนทุก path) — คง TP เดิม
        sl_pips, tp_pips, meta = base_sl, base_tp, None
        try:
            from agents import structural_sl as _ssl
            sl_pips, tp_pips, meta = _ssl.live_adjust(
                direction, entry, av, point, symbol, base_sl, base_tp, _cfg,
                getattr(_cfg, "STRUCTURAL_SL_GOLD", False))
        except Exception:
            pass
        _lot = float(getattr(_cfg, "MIN_LOT", 0.01)) if (meta and meta.get("force_min_lot")) else lot
        # open_order = guard ครบ (LONG_ONLY_ALL/margin/cap/min-lot/DRY_RUN). min_rr ต่ำ = ยอม structural SL กว้าง
        res = open_order(direction, sl_pips, tp_pips, comment="MANUAL-cockpit", lot=_lot,
                         symbol=broker, min_rr=0.1, magic=_manual_magic())
        if res and res.get("success"):
            logger.warning(f"[COCKPIT] MANUAL {direction} {broker} @ {res.get('price')} "
                           f"SL={sl_pips:.0f}p TP={tp_pips:.0f}p lot={res.get('lot', _lot)} ticket={res.get('ticket')}")
            return {"ok": True, "ticket": res.get("ticket"), "price": res.get("price"),
                    "sl_pips": round(sl_pips), "tp_pips": round(tp_pips), "symbol": broker, "direction": direction}
        return {"ok": False, "reason": (res or {}).get("error", "open_order ไม่สำเร็จ")}
    except Exception as e:                                  # noqa: BLE001
        logger.warning(f"[COCKPIT] place_manual fail-soft: {e}")
        return {"ok": False, "reason": str(e)}
