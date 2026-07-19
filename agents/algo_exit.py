"""agents/algo_exit.py — P-D exit: TP ตามความสำคัญแนว + trailing vol+S/R (DESIGN_algo_v2). flag REGIME_SR_EXIT.

สอง piece สำหรับไม้ ALGO (comment เริ่ม "ALGO"):
  A. sr_tp_pips() — TP = แนว S/R เป้าหมายตามความสำคัญ (H1 ใกล้ / W1·กระจุก ไกล) แทน RR2 คงที่. ใช้ตอนวาง order.
  B. manage_algo_trailing() — เลื่อน SL ตาม vol + S/R แข็ง: long → ใต้ support − buffer·ATR, short → เหนือ resistance.
     only-tighten + protective (ไม่ขยับสวน, ขยับเมื่อกำไรแล้ว). เรียกทุก cycle จาก node_position_mgmt.

deterministic, 0 LLM, 0 token. default OFF (REGIME_SR_EXIT) — เปิด = พี่ควบคุมเอง. reuse sr_engine (P-A) + _set_sl_tp.
"""
import json
import os
import sys

import config as _cfg

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R

try:
    from loguru import logger
except Exception:                                           # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

_TRAIL_BUFFER_ATR = 0.3                                      # SL ห่างจากแนว = buffer·ATR (กันแกว่งชน)
_MIN_STOP_ATR = 0.3                                         # SL ต้องห่างราคาปัจจุบัน ≥ นี้ (กัน broker reject/ชิดเกิน)


def _sr_view_now():
    """สร้าง sr_view สด: bars (MT5) + sr_meta (bot_status). คืน (sr_view, atr) หรือ None. fail-soft."""
    try:
        from agents.regime_shadow import _bars_from_feed
        bars = _bars_from_feed()
        if bars is None:
            return None
        high, low, close, _t = bars
        with open(os.path.join(_BASE, "logs", "bot_status.json"), encoding="utf-8") as f:
            st = json.load(f)
        sr_meta = ((st.get("zones") or {}).get("sr_meta")) or []
        if not sr_meta:
            return None
        from agents.cluster_map import compute_cluster_map
        from agents.sr_engine import build_sr_view
        cluster = compute_cluster_map(high, low, close)
        if not (cluster or {}).get("ok"):
            cluster = None
        atr = (cluster or {}).get("atr") or float(R.atr(high, low, close)[-1])
        if not atr or atr <= 0:
            return None
        sr_view = build_sr_view(sr_meta, float(close[-1]), float(atr), cluster)
        return (sr_view, float(atr)) if sr_view.get("ok") else None
    except Exception:
        return None


def sr_tp_pips(direction, entry_price, sl_pips, default_tp_pips=None, min_rr=1.5):
    """A: คืน tp_pips ที่ยิงไปแนว S/R เป้าหมาย (ตามความสำคัญ). ถ้า flag OFF / ไม่พร้อม → default_tp_pips.
    เรียกตอนวาง order (executor/tick/pending-STOP). deterministic."""
    if not getattr(_cfg, "REGIME_SR_EXIT", False):
        return default_tp_pips
    try:
        res = _sr_view_now()
        if not res:
            return default_tp_pips
        sr_view, _atr = res
        from agents.sr_engine import pick_tp_target
        tp = pick_tp_target(sr_view, direction, float(entry_price), sl_pips, min_rr)
        if not tp:
            return default_tp_pips
        tpp = max(1, round(abs(tp["tp"] - float(entry_price)) / R.POINT))
        logger.debug(f"[ALGO-EXIT] TP→แนว {tp.get('level')} ({tp.get('tf')} {tp.get('entry_sig')}) "
                     f"tp={tpp}p RR={tp.get('rr')} src={tp.get('source')}")
        return tpp
    except Exception:
        return default_tp_pips


def manage_algo_trailing():
    """B: เลื่อน SL ไม้ ALGO ตาม vol + S/R แข็ง (only-tighten, protective). คืนจำนวนที่ขยับ. fail-soft."""
    if not (getattr(_cfg, "REGIME_LIVE", False) and getattr(_cfg, "REGIME_SR_EXIT", False)):
        return 0
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import get_open_positions, _set_sl_tp
        positions = [p for p in (get_open_positions() or [])
                     if str(p.get("comment") or "").startswith("ALGO")]
        if not positions:
            return 0
        res = _sr_view_now()
        if not res:
            return 0
        sr_view, atr = res
        from agents.sr_engine import sr_trailing_stop
        tick = mt5.symbol_info_tick(_cfg.SYMBOL)
        if not tick:
            return 0
        n = 0
        for p in positions:
            d = str(p.get("direction", "")).upper()
            entry = float(p.get("open_price") or 0)
            cur_sl = float(p.get("sl") or 0)
            tp = float(p.get("tp") or 0)
            tk = p.get("ticket")
            if d not in ("BUY", "SELL") or not tk:
                continue
            price = float(tick.bid if d == "BUY" else tick.ask)
            new_sl = sr_trailing_stop(sr_view, d, atr, _TRAIL_BUFFER_ATR)
            if new_sl is None or abs(price - new_sl) < _MIN_STOP_ATR * atr:
                continue                                    # ไม่มีแนว / ชิดราคาเกิน
            if d == "BUY":
                if price <= entry:                          # ยังไม่กำไร → ไม่ trail (กันตัดหมู)
                    continue
                if new_sl <= cur_sl or new_sl >= price:      # only-tighten (ขึ้น) + SL ต้องใต้ราคา
                    continue
            else:
                if price >= entry:
                    continue
                if (cur_sl and new_sl >= cur_sl) or new_sl <= price:   # only-tighten (ลง) + SL ต้องเหนือราคา
                    continue
            if _set_sl_tp(tk, new_sl, tp):
                n += 1
                logger.warning(f"[ALGO-EXIT] trail {d} ticket={tk} SL {cur_sl:.2f}→{new_sl:.2f} "
                               f"(ใต้/เหนือแนว − {_TRAIL_BUFFER_ATR}·ATR)")
        return n
    except Exception as e:
        logger.error(f"[ALGO-EXIT] trailing: {e}")
        return 0
