"""agents/regime_tick.py — per-tick executor (daemon thread, flag REGIME_LIVE_TICK, default OFF).

realtime entry: **level คำนวณต่อ bar-close (cache), ต่อ tick แค่เทียบราคา vs level** → เข้าเร็วกว่ารอ cycle.
0 LLM, 0 recompute-per-tick (fetch bars แค่ตอนขึ้น H1 bar ใหม่). mirror position_guardian (thread + stop Event).
ต้องมี REGIME_LIVE=true ด้วย. per-cycle executor ปิดอัตโนมัติเมื่อ tick ON (กันเข้าซ้ำ). ⚠️ LIVE MONEY.
kill = REGIME_LIVE_TICK=false. ดู docs/DESIGN_phase2_algo_live.md.
"""
import logging
import os
import sys
import threading

import numpy as np

import config

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R

logger = logging.getLogger(__name__)
_stop = threading.Event()
_thread: threading.Thread | None = None
_cache = {"hour": None, "armed": False, "buy": None, "sell": None, "sl_pips": 0, "tp_pips": 0}
_last_traded_hour = None            # dedup: เข้าได้ 1 ไม้ / H1 bar
_started = False                     # cold-start gate: กันเข้าเมื่อราคาทะลุ level ไปแล้วก่อนบอทเริ่ม (stale break)


def _algo_pos_protected(p):
    """ไม้ ALGO ทอง (dict จาก get_open_positions) trailing เลย BE แล้ว (risk-free) → ไม่กิน entry-slot."""
    try:
        sl = p.get("sl") or 0
        entry = p.get("open_price") or 0
        if not sl or not entry:
            return False
        buf = float(getattr(config, "BE_BUFFER_PIPS", 200)) * 0.01   # gold point = 0.01
        return (sl >= entry + buf) if p.get("direction") == "BUY" else (sl <= entry - buf)
    except Exception:
        return False


def _refresh_levels(hour: int) -> None:
    """คำนวณ regime + Donchian levels ที่ bar-close (เรียกเมื่อขึ้น H1 bar ใหม่) → cache."""
    from agents.regime_shadow import _bars_from_feed
    bars = _bars_from_feed()
    if bars is None:
        return
    high, low, close, _t = bars
    n = len(close)
    if n < R.VOL_LOOKBACK + 40:
        return
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    i = n - 2                                          # แท่งปิดล่าสุด (n-1 = กำลังก่อตัว)
    regime = R.detect_regime(er[i], adx_v[i], volpct[i])
    lv = R.momentum_levels(i, high, low, close, atr_v) if regime == "TREND" else None
    from agents.algo_state import write_state
    if lv:
        _cache.update(hour=hour, armed=True, buy=lv["buy_level"], sell=lv["sell_level"],
                      sl_pips=lv["sl_pips"], tp_pips=lv["tp_pips"], atr=float(atr_v[i]))
        write_state("ARMED", regime="TREND", via="tick",
                    detail=f"เฝ้าการทะลุแนว BUY>{lv['buy_level']:.1f} / SELL<{lv['sell_level']:.1f}")
    else:
        _cache.update(hour=hour, armed=False)
        write_state("STAND-DOWN", regime=regime, via="tick", detail=f"regime={regime} (ไม่ใช่ TREND → งดเข้าออเดอร์)")


def _tick() -> None:
    """เรียกทุก interval. เช็คราคา vs level → เข้า order ถ้าทะลุ. fail-soft (thread ต้องไม่ตาย)."""
    if not (getattr(config, "REGIME_LIVE", False) and getattr(config, "REGIME_LIVE_TICK", False)):
        return
    if getattr(config, "TSMOM_LIVE", False) and not getattr(config, "TSMOM_COEXIST", False):   # TSMOM → tick งดเข้า (เว้นแต่ COEXIST=true → intraday ทำงานคู่ TSMOM)
        return
    if getattr(config, "REGIME_PENDING", False):        # pending mode จัดการ entry แล้ว → tick ไม่เข้าซ้ำ
        return
    from agents.regime_adaptive import is_enabled        # weekly auto-disable (decay kill switch)
    if not is_enabled("momentum_breakout"):
        return
    global _last_traded_hour, _started
    try:
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(config.SYMBOL)
        if not tick:
            return
        hour = int(tick.time // 3600)                  # H1 block (broker time)
        if _cache["hour"] != hour:                     # ขึ้น bar ใหม่ → recompute levels (ครั้งเดียว/ชม.)
            _refresh_levels(hour)
        if not _started:                               # cold-start: ราคาทะลุ level ที่ arm ไว้แล้วตั้งแต่ก่อนบอทเริ่ม
            _started = True                            # = break เกิดก่อนเราดู (stale) → seed ชั่วโมงนี้ รอบาร์/level สดถัดไป
            if _cache["armed"] and ((_cache.get("buy") and tick.ask > _cache["buy"])
                                    or (_cache.get("sell") and tick.bid < _cache["sell"])):
                _last_traded_hour = hour
                logger.info("[REGIME-TICK] cold-start: ราคาทะลุ level ที่ arm ไว้ก่อนบอทเริ่ม (stale) → รอบาร์สด")
                return
        if not _cache["armed"] or _last_traded_hour == hour:
            return
        if tick.ask > _cache["buy"]:
            d = "BUY"
        elif tick.bid < _cache["sell"]:
            d = "SELL"
        else:
            return
        from agents.algo_gate import entry_hour_ok
        if not entry_hour_ok():                              # session gate (ALGO_ENTRY_HOURS · ว่าง=ทุกชม default)
            return
        from connectors.mt5_connector import get_open_positions, open_order
        # stack guard: ถือครบ ALGO_MAX_STACK ไม้ = ข้าม (dict-safe — get_open_positions คืน dict)
        _cmt = lambda p: str((p.get("comment") if isinstance(p, dict) else getattr(p, "comment", "")) or "")
        _pdir = lambda p: (p.get("direction") if isinstance(p, dict) else getattr(p, "direction", None))
        _algo = [p for p in (get_open_positions() or []) if _cmt(p).startswith("ALGO")]
        _active = [p for p in _algo if not _algo_pos_protected(p)]   # ไม้ protected (trailing เลย BE) ไม่กิน slot → เข้าเพิ่มได้
        if len(_active) >= getattr(config, "ALGO_MAX_STACK", 1):
            return
        # same-direction guard: กัน 2 engine (TSMOM/intraday) เข้าซ้อนทิศเดียวกัน (ALGO_MAX_SAME_DIR=1 → ห้ามดับเบิลทางเดียว; ฝั่งตรงข้ามยังเข้าได้)
        if sum(1 for p in _active if _pdir(p) == d) >= getattr(config, "ALGO_MAX_SAME_DIR", 1):
            return
        _structural_on = getattr(config, "STRUCTURAL_SL_GOLD", False)   # structural = SL ปลายไส้ D1 + min lot เสมอ → ข้าม standdown
        if not _structural_on:
            from agents.algo_sizing import standdown_for_size         # small-acct guard: min-lot เสี่ยงเกินเพดาน = ข้าม
            _skip, _si = standdown_for_size(_cache["sl_pips"])
            if _skip:
                _last_traded_hour = hour                              # ถือว่าจัดการชั่วโมงนี้แล้ว (กัน log ซ้ำทุก tick)
                logger.info(f"[REGIME-TICK] SIZE-STANDDOWN {d}: min-lot มีความเสี่ยง {_si.get('risk_pct',0)*100:.1f}% "
                            f"> เพดาน {_si.get('ceiling',0)*100:.0f}% (SL {_cache['sl_pips']}p เงินทุนไม่เพียงพอ) → ข้าม")
                from agents.algo_state import write_state
                write_state("SIZE-STANDDOWN", regime="TREND", via="tick",
                            detail=f"min-lot มีความเสี่ยง {_si.get('risk_pct',0)*100:.1f}% > เพดาน (SL {_cache['sl_pips']}p เงินทุนไม่เพียงพอ)")
                return
        from agents import shadow_switches as _sw                 # unify: dashboard switch = single control
        _st = _sw.gold_state("regime_momentum")
        if _st == _sw.OFF:
            _last_traded_hour = hour                              # ถือว่าจัดการชั่วโมงนี้แล้ว (กัน log ซ้ำ)
            return
        _entry_px_chk = tick.ask if d == "BUY" else tick.bid
        from agents.regime_executor import _too_close_algo
        if _too_close_algo(d, _entry_px_chk, _cache.get("atr")):  # กัน stack เกาะจุดเดิม (≤ n×ATR)
            _last_traded_hour = hour
            logger.info(f"[REGIME-TICK] PROXIMITY-SKIP {d}: มีไม้ ALGO ทิศเดียวใกล้ → งดเข้าจุดเดิม")
            return
        _sent = None                                             # sentiment soft-bias (flag OFF = ไม่แตะ)
        if getattr(config, "SENTIMENT_BIAS", False):
            try:
                from agents.sentiment_score import get_score
                from agents.sentiment_bias import compute as _sbias
                _sent = _sbias(d, (get_score() or {}).get("score", 0))
                if _sent.get("block"):                           # สวน sentiment แรง → veto ทิศผิด (รอทิศถูก)
                    _last_traded_hour = hour
                    logger.info(f"[REGIME-TICK] SENTIMENT-BLOCK {d}: สวน score {_sent['score']} แรง → ไม่เข้าทิศนี้")
                    from agents.algo_state import write_state
                    write_state("SENTIMENT-BLOCK", regime="TREND", via="tick",
                                detail=f"{d} สวน sentiment {_sent['score']} → รอทิศที่ถูก")
                    return
                if not _sent["aligned"] and _sent["extra_margin_atr"] > 0:   # สวน sentiment → ต้องทะลุแรงกว่า
                    _atr = float(_cache.get("atr") or 0)
                    _need = _sent["extra_margin_atr"] * _atr
                    if _need > 0 and ((d == "BUY" and tick.ask <= _cache["buy"] + _need)
                                      or (d == "SELL" and tick.bid >= _cache["sell"] - _need)):
                        logger.info(f"[REGIME-TICK] SENTIMENT-HOLD {d}: สวน score {_sent['score']} → รอ break แรงกว่า (+{_need:.2f})")
                        return                                   # ไม่ set _last_traded_hour → เข้าได้ถ้า break แรงพอในชม.นี้
            except Exception:
                _sent = None
        _last_traded_hour = hour
        from agents.algo_exit import sr_tp_pips                    # P-D: TP ตามแนว S/R (flag OFF → RR2 เดิม)
        from agents.algo_sizing import algo_lot                    # P-E: lot risk-based (flag OFF → fixed เดิม)
        _entry_px = tick.ask if d == "BUY" else tick.bid
        _tp_pips = sr_tp_pips(d, _entry_px, _cache["sl_pips"], _cache["tp_pips"])
        from agents.regime_executor import _structural_sl_gold
        _sl_pips, _tp_pips, _force_min = _structural_sl_gold(d, _entry_px, _cache.get("atr"),
                                                             _cache["sl_pips"], _tp_pips)
        _lot = float(getattr(config, "MIN_LOT", 0.01)) if _force_min else algo_lot(_sl_pips)  # structural = min lot เสมอ
        if _sent and _sent.get("lot_mult", 1.0) < 1.0:          # สวน sentiment (อ่อน) → lot เล็กลง (floor MIN_LOT)
            _lot = max(float(getattr(config, "MIN_LOT", 0.01)), round(_lot * _sent["lot_mult"], 2))
        res = open_order(d, _sl_pips, _tp_pips, comment="ALGO-mom", lot=_lot,
                         shadow=(_st == _sw.SHADOW))               # SHADOW → paper-fill
        from agents.regime_executor import _log
        _log({"ts_hour": hour, "via": "tick", "regime": "TREND",
              "signal": {"algo": "momentum_breakout", "dir": d,
                         "sl_pips": _cache["sl_pips"], "tp_pips": _cache["tp_pips"]},
              "price": tick.ask if d == "BUY" else tick.bid,
              "level": _cache["buy"] if d == "BUY" else _cache["sell"], "order": res})
        logger.warning(f"[REGIME-TICK] เข้าออเดอร์ {d} ทะลุแนว {res}")
        from agents.algo_state import write_state
        write_state("ENTER", regime="TREND", via="tick",
                    detail=f"{d} ทะลุแนว {_cache['buy'] if d=='BUY' else _cache['sell']:.1f}")
    except Exception as e:
        logger.debug(f"[REGIME-TICK] tick error: {e}")


def _loop() -> None:
    interval = max(1, getattr(config, "REGIME_TICK_INTERVAL_SEC", 3))
    logger.info(f"[REGIME-TICK] started — poll ทุก {interval}s")
    while not _stop.wait(interval):
        _tick()
    logger.info("[REGIME-TICK] stopped")


def start_regime_tick() -> bool:
    """สตาร์ท thread ถ้า REGIME_LIVE + REGIME_LIVE_TICK. คืน True ถ้าเริ่ม."""
    global _thread
    if not (getattr(config, "REGIME_LIVE", False) and getattr(config, "REGIME_LIVE_TICK", False)):
        return False
    if _thread and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="regime-tick", daemon=True)
    _thread.start()
    return True


def stop_regime_tick(timeout: float = 5.0) -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=timeout)


def is_running() -> bool:
    return bool(_thread and _thread.is_alive())
