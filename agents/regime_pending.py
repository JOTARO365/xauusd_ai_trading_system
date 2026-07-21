"""agents/regime_pending.py — algo-placed pending orders, regime-routed (DESIGN_algo_v2 P-C).

routed ตาม regime (SELECTION):
  • TREND  (flag REGIME_PENDING)      → **STOP straddle** BUY_STOP@Donchian-high + SELL_STOP@low (breakout, momentum)
  • RANGE  (flag REGIME_PENDING_FADE) → **LIMIT fade** BUY_LIMIT@support + SELL_LIMIT@resistance (fade แนวแข็ง)
    - veto แนวอ่อน (break_pct≥60) · vol/momentum gate: ราคาใกล้ level + momentum break → cancel รอ (ข้อ 6 owner)
    - ⚠️ RANGE-fade ยังไม่ผ่าน validation (naive fade −EV) → เปิดหลัง journal (REGIME_SR_ENTRY) พิสูจน์ edge

SAFETY (owner 07-19): (1) มีไม้ ALGO เปิด → cancel ALGO-P* ที่เหลือ (กัน fill 2 ทาง) · (2) MAX_OPEN guard ต่อทิศ.
comment tag: STOP="ALGO-P" · fade LIMIT="ALGO-PF" (startswith "ALGO-P" → safety-cancel ครอบทั้งคู่).
ต้องมี REGIME_LIVE=true. ⚠️ LIVE MONEY. ผ่าน place_pending_order เดิม (DRY_RUN/expiry). kill = flag=false.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

import config as _cfg

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R

logger = logging.getLogger(__name__)
_last_bar_hour = None


def _same_dir_count(positions, direction):
    return sum(1 for p in positions if str(p.get("direction", "")).upper() == direction)


def _cancel_algo_pendings(prefix="ALGO-P"):
    from connectors.mt5_connector import get_pending_orders, cancel_pending_order
    n = 0
    for o in (get_pending_orders() or []):
        cmt = o.get("comment") if isinstance(o, dict) else getattr(o, "comment", "")
        tk = o.get("ticket") if isinstance(o, dict) else getattr(o, "ticket", None)
        if str(cmt or "").startswith(prefix) and tk and cancel_pending_order(tk):
            n += 1
    return n


def _max_open_limit():
    try:
        from connectors.mt5_connector import MONEY_MANAGEMENT, count_protected_slots
        return MONEY_MANAGEMENT["max_open_trades"] + count_protected_slots()
    except Exception:
        return getattr(_cfg, "MAX_OPEN_TRADES", 2)


def _weak(lvl):
    """แนวอ่อน = ประวัติมัก break (break_pct≥60, n≥4) → ไม่ fade."""
    bp = lvl.get("break_pct"); nt = int(lvl.get("n_tests") or 0)
    return bp is not None and nt >= 4 and float(bp) >= 60


def _bot_status():
    try:
        with open(os.path.join(_BASE, "logs", "bot_status.json"), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def _sr_view(high, low, close, atr, st):
    """สร้าง sr_view จาก sr_meta (bot_status) + cluster (bars). คืน {ok:False} ถ้าไม่พร้อม."""
    sr_meta = ((st.get("zones") or {}).get("sr_meta")) or []
    if not sr_meta:
        return {"ok": False}
    from agents.sr_engine import build_sr_view
    from agents.cluster_map import compute_cluster_map
    cluster = compute_cluster_map(high, low, close)
    if not (cluster or {}).get("ok"):
        cluster = None
    return build_sr_view(sr_meta, float(close[-1]), float(atr), cluster)


def _gate_cancel_fades(price, atr, market):
    """per-cycle: ราคาใกล้ fade level (≤near·ATR) + momentum break สวน fade → cancel ALGO-PF รอ. คืนจำนวน cancel."""
    from connectors.mt5_connector import get_pending_orders, cancel_pending_order
    from agents.entry_gate import vol_momentum_gate, W
    near = W["near_atr"] * atr
    n = 0
    for o in (get_pending_orders() or []):
        cmt = str(o.get("comment") or "")
        if not cmt.startswith("ALGO-PF"):
            continue
        lvl = o.get("price"); pt = str(o.get("pending_type") or ""); tk = o.get("ticket")
        if lvl is None or tk is None or abs(price - lvl) > near:
            continue                                        # ยังไม่ใกล้ → ปล่อยรอ
        direction = "BUY" if "BUY" in pt else "SELL"
        if not vol_momentum_gate(market, direction)["pass"] and cancel_pending_order(tk):
            n += 1
            logger.warning(f"[REGIME-FADE] cancel {pt}@{lvl:.2f} — momentum break ใกล้แนว รอข้อมูลใหม่")
    return n


def _place_trend_straddle(positions, i, high, low, close, atr, hour, bar_ts=None):
    """TREND: STOP straddle breakout ที่ Donchian level (momentum). MAX_OPEN guard ต่อทิศ."""
    from connectors.mt5_connector import place_pending_order
    from agents.algo_exit import sr_tp_pips                   # P-D: TP ตามแนว S/R (flag OFF → RR2 เดิม)
    from agents.algo_sizing import algo_lot                   # P-E: lot risk-based (flag OFF → fixed เดิม)
    from agents.algo_journal import record_pending            # เก็บ lifecycle pending (placed→fill→TP/SL)
    lv = R.momentum_levels(i, high, low, close, atr)
    if not lv:
        return 0
    limit = _max_open_limit()
    _lot = algo_lot(lv["sl_pips"])
    _sh = getattr(_cfg, "REGIME_SHADOW_FILL", False)
    placed = 0
    if _same_dir_count(positions, "BUY") < limit:
        _btp = sr_tp_pips("BUY", lv["buy_level"], lv["sl_pips"], lv["tp_pips"])
        if place_pending_order("BUY_STOP", lv["buy_level"], lv["sl_pips"], _btp,
                               comment="ALGO-P", expiry_hours=2, lot=_lot, shadow=_sh).get("success"):
            placed += 1
            record_pending("BUY_STOP", lv["buy_level"], lv["sl_pips"], _btp or lv["tp_pips"], "STOP", "TREND", bar_ts)
    else:
        logger.info("[REGIME-PENDING] งดวาง BUY_STOP — BUY เต็ม MAX_OPEN")
    if _same_dir_count(positions, "SELL") < limit:
        _stp = sr_tp_pips("SELL", lv["sell_level"], lv["sl_pips"], lv["tp_pips"])
        if place_pending_order("SELL_STOP", lv["sell_level"], lv["sl_pips"], _stp,
                               comment="ALGO-P", expiry_hours=2, lot=_lot, shadow=_sh).get("success"):
            placed += 1
            record_pending("SELL_STOP", lv["sell_level"], lv["sl_pips"], _stp or lv["tp_pips"], "STOP", "TREND", bar_ts)
    else:
        logger.info("[REGIME-PENDING] งดวาง SELL_STOP — SELL เต็ม MAX_OPEN")
    if placed:
        from agents.regime_executor import _log
        _log({"via": "pending", "mode": "TREND-STOP", "ts_hour": hour,
              "buy_level": lv["buy_level"], "sell_level": lv["sell_level"],
              "sl_pips": lv["sl_pips"], "tp_pips": lv["tp_pips"], "placed": placed})
        logger.warning(f"[REGIME-PENDING] ส่งคำสั่ง STOP straddle {placed} ขา @ {lv['buy_level']:.2f}/{lv['sell_level']:.2f}")
    return placed


def _place_range_fade(positions, sr_view, atr, hour, bar_ts=None, htf_trend=None):
    """RANGE: LIMIT fade ที่ S/R แข็ง (veto อ่อน). BUY_LIMIT@support / SELL_LIMIT@resistance. MAX_OPEN guard.
    **HTF-trend gate:** ไม่ fade สวนเทรนด์ (finding: counter-trend/short ขาดทุน; deterministic ไม่ใช่ sentiment)."""
    if not sr_view.get("ok"):
        return 0
    from connectors.mt5_connector import place_pending_order
    from agents.sr_engine import pick_tp_target
    from agents.entry_gate import W
    from agents.algo_journal import record_pending            # เก็บ lifecycle pending (placed→fill→TP/SL)
    limit = _max_open_limit()
    sl_pips = max(1, round(0.6 * atr / R.POINT))             # SL 0.6·ATR เลย level (กัน stop-hunt เบื้องต้น; P-E refine)
    _tr = str(htf_trend or "").upper()
    placed = 0

    def _one(lvl_obj, direction, otype):
        nonlocal placed
        if "BULL" in _tr and direction == "SELL":            # เทรนด์ขึ้น → ไม่ SELL แนวต้าน (สวนเทรนด์)
            return
        if "BEAR" in _tr and direction == "BUY":             # เทรนด์ลง → ไม่ BUY แนวรับ
            return
        if not lvl_obj or _weak(lvl_obj) or _same_dir_count(positions, direction) >= limit:
            return
        lvl = lvl_obj["level"]
        tp = pick_tp_target(sr_view, direction, lvl, sl_pips, W["rr_floor"])
        if not tp or tp["rr"] < W["rr_floor"]:
            return
        tp_pips = max(1, round(abs(tp["tp"] - lvl) / R.POINT))
        from agents.algo_sizing import algo_lot               # P-E: lot risk-based (flag OFF → fixed เดิม)
        if place_pending_order(otype, lvl, sl_pips, tp_pips, comment="ALGO-PF", expiry_hours=6,
                               lot=algo_lot(sl_pips), shadow=getattr(_cfg, "REGIME_SHADOW_FILL", False)).get("success"):
            placed += 1
            record_pending(otype, lvl, sl_pips, tp_pips, "FADE", "RANGE", bar_ts, grade=lvl_obj.get("grade"))
            logger.warning(f"[REGIME-FADE] {otype}@{lvl:.2f} SL={sl_pips}p TP={tp_pips}p (RR={tp['rr']}) grade={lvl_obj.get('grade')}")

    _one(sr_view.get("support"), "BUY", "BUY_LIMIT")         # fade: ซื้อที่แนวรับ
    _one(sr_view.get("resistance"), "SELL", "SELL_LIMIT")    # fade: ขายที่แนวต้าน
    if placed:
        from agents.regime_executor import _log
        _log({"via": "pending", "mode": "RANGE-FADE", "ts_hour": hour, "placed": placed})
    return placed


def manage_algo_pending():
    """เรียกทุก cycle จาก node_position_mgmt. routed ตาม regime. คืนจำนวน pending ที่วางรอบนี้. fail-soft."""
    if not (getattr(_cfg, "REGIME_LIVE", False)
            and (getattr(_cfg, "REGIME_PENDING", False) or getattr(_cfg, "REGIME_PENDING_FADE", False))):
        return 0
    if getattr(_cfg, "TSMOM_LIVE", False):                  # TSMOM = engine เดียว → fade pending งดวาง
        _cancel_algo_pendings("ALGO-P")                     # เก็บ pending fade ที่ค้างออก
        return 0
    global _last_bar_hour
    try:
        import MetaTrader5 as mt5
        from connectors.mt5_connector import get_open_positions
        from agents.regime_shadow import _bars_from_feed
        positions = get_open_positions() or []
        # SAFETY 1: ถือครบ ALGO_MAX_STACK ไม้ → cancel ALGO-P* ที่เหลือ + ไม่วางเพิ่ม (no over-stack)
        _algo_open = sum(1 for p in positions if str(p.get("comment") or "").startswith("ALGO"))
        if _algo_open >= getattr(_cfg, "ALGO_MAX_STACK", 1):
            _cancel_algo_pendings("ALGO-P")
            return 0
        tick = mt5.symbol_info_tick(_cfg.SYMBOL)
        if not tick:
            return 0
        bars = _bars_from_feed()
        if bars is None:
            return 0
        high, low, close, _t = bars
        n = len(close)
        if n < R.VOL_LOOKBACK + 40:
            return 0
        er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
        vp = R.vol_percentile(close); atr_a = R.atr(high, low, close)
        i = n - 2
        atr = float(atr_a[i])
        try:
            _bar_ts = datetime.fromtimestamp(int(_t[i]), timezone.utc).isoformat()
        except Exception:
            _bar_ts = None
        regime = R.detect_regime(er[i], adx[i], vp[i])
        # algo_state → terminal panel (pending mode ชัด แทน HAND-OFF จาก executor)
        _fade_on = regime == "RANGE" and getattr(_cfg, "REGIME_PENDING_FADE", False)
        _stop_on = regime == "TREND" and getattr(_cfg, "REGIME_PENDING", False)
        if _fade_on or _stop_on:                            # เขียน state เฉพาะตอน pending เป็น path จริง
            try:                                            # (hybrid: TREND ให้ tick เขียน ARMED — ไม่ทับ)
                from agents.algo_state import write_state
                _pd = "ส่งคำสั่ง LIMIT fade แนวแข็ง" if _fade_on else "ส่งคำสั่ง STOP breakout Donchian"
                write_state("PENDING", regime=regime, via="pending", detail=f"regime={regime} — {_pd}")
            except Exception:
                pass
        st = _bot_status()
        market = dict(st.get("market") or {})
        market.setdefault("fast_move_pips", (st.get("last_signal") or {}).get("fast_move_pips", 0))
        market["volume_profile"] = st.get("volume_profile")
        # per-cycle: vol/momentum gate cancel fade (รันทุก cycle เพื่อ react เร็ว ไม่รอ bar ใหม่)
        if getattr(_cfg, "REGIME_PENDING_FADE", False) and atr > 0:
            _gate_cancel_fades(float(tick.bid), atr, market)
        # per-bar: (re)placement 1 ครั้ง/H1 bar
        hour = int(tick.time // 3600)
        if hour == _last_bar_hour:
            return 0
        _last_bar_hour = hour
        _cancel_algo_pendings("ALGO-P")                     # clear pending เก่า (level เลื่อนตาม bar/regime ใหม่)
        # TREND → STOP breakout (ต้องผ่าน weekly auto-disable ของ momentum)
        if regime == "TREND" and getattr(_cfg, "REGIME_PENDING", False):
            from agents.regime_adaptive import is_enabled
            if not is_enabled("momentum_breakout"):
                return 0
            return _place_trend_straddle(positions, i, high, low, close, atr_a, hour, _bar_ts)
        # RANGE → LIMIT fade (gate ด้วย HTF trend — ไม่ fade สวนเทรนด์)
        if regime == "RANGE" and getattr(_cfg, "REGIME_PENDING_FADE", False):
            _htf = market.get("d1_trend") or market.get("trend")
            return _place_range_fade(positions, _sr_view(high, low, close, atr, st), atr, hour, _bar_ts, _htf)
        return 0
    except Exception as e:
        logger.error(f"[REGIME-PENDING] {e}")
        return 0
