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
    if lv:
        _cache.update(hour=hour, armed=True, buy=lv["buy_level"], sell=lv["sell_level"],
                      sl_pips=lv["sl_pips"], tp_pips=lv["tp_pips"])
    else:
        _cache.update(hour=hour, armed=False)


def _tick() -> None:
    """เรียกทุก interval. เช็คราคา vs level → เข้า order ถ้าทะลุ. fail-soft (thread ต้องไม่ตาย)."""
    if not (getattr(config, "REGIME_LIVE", False) and getattr(config, "REGIME_LIVE_TICK", False)):
        return
    if getattr(config, "REGIME_PENDING", False):        # pending mode จัดการ entry แล้ว → tick ไม่เข้าซ้ำ
        return
    global _last_traded_hour
    try:
        import MetaTrader5 as mt5
        tick = mt5.symbol_info_tick(config.SYMBOL)
        if not tick:
            return
        hour = int(tick.time // 3600)                  # H1 block (broker time)
        if _cache["hour"] != hour:                     # ขึ้น bar ใหม่ → recompute levels (ครั้งเดียว/ชม.)
            _refresh_levels(hour)
        if not _cache["armed"] or _last_traded_hour == hour:
            return
        if tick.ask > _cache["buy"]:
            d = "BUY"
        elif tick.bid < _cache["sell"]:
            d = "SELL"
        else:
            return
        from connectors.mt5_connector import get_open_positions, open_order
        for p in (get_open_positions() or []):         # no-stack: มีไม้ ALGO เปิดอยู่ = ข้าม
            if str(getattr(p, "comment", "") or "").startswith("ALGO"):
                return
        _last_traded_hour = hour
        res = open_order(d, _cache["sl_pips"], _cache["tp_pips"], comment="ALGO-mom")
        from agents.regime_executor import _log
        _log({"ts_hour": hour, "via": "tick", "regime": "TREND",
              "signal": {"algo": "momentum_breakout", "dir": d,
                         "sl_pips": _cache["sl_pips"], "tp_pips": _cache["tp_pips"]},
              "price": tick.ask if d == "BUY" else tick.bid,
              "level": _cache["buy"] if d == "BUY" else _cache["sell"], "order": res})
        logger.warning(f"[REGIME-TICK] เข้า {d} ทะลุ level {res}")
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
