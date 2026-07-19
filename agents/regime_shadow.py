"""agents/regime_shadow.py — Minimal-AI regime router, SHADOW mode (flag REGIME_SHADOW, default OFF).

เก็บ track record ของ entry design ใหม่ (deterministic regime → ONE-algo → signal) ไปข้างหน้าบน live data
โดย **ไม่วางจริง, 0 LLM, 0 order**. ต่อยอดจาก scripts/regime_lib.py (offline lib) — ไม่ duplicate logic.

CORE INVARIANT: entry = คำนวณจาก data (ER/ADX/vol + Donchian/z-score/OU) ไม่ prediction, ไม่มี AI ในชั้นนี้.
LLM regime override (sentiment ข่าว + ตัวเลขเศรษฐกิจ, event-driven) = P3 (ยังไม่ทำ).

ดู docs/DESIGN_regime_shadow.md. Kill switch: REGIME_SHADOW=false.
"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

import config as _cfg

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R                                   # offline lib (committed) — single source of algo truth

_LOG = os.path.join(_BASE, "logs", "regime_shadow.jsonl")
_MIN_BARS = R.VOL_LOOKBACK + 40                          # ต้องพอสำหรับ vol_percentile lookback + warmup
_last_bar_ts = None                                      # dedup ต่อ H1 bar ภายใน process run เดียว


def _r(x):
    """round + NaN→None (JSON-safe)."""
    return round(float(x), 4) if x == x else None


def _bars_from_feed(count=600):
    """ดึง H1 OHLC จาก MT5 (live). คืน (high, low, close, times) หรือ None ถ้าไม่พร้อม (fail-soft)."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        rates = get_ohlcv(timeframe=mt5.TIMEFRAME_H1, count=count)
        if rates is None or len(rates) < _MIN_BARS:
            return None
        return (rates["high"].astype(float), rates["low"].astype(float),
                rates["close"].astype(float), rates["time"])
    except Exception:
        return None


def compute_shadow_signal(high, low, close, times=None):
    """Deterministic regime + ONE-algo signal ที่ **bar ปิดล่าสุด** (index n-2; n-1 อาจเป็น bar กำลังก่อตัว).
    0 LLM. คืน record dict (signal=None ถ้า STAND-DOWN) หรือ None ถ้า data ไม่พอ."""
    n = len(close)
    if n < _MIN_BARS:
        return None
    er = R.efficiency_ratio(close)
    adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close)
    atr_v = R.atr(high, low, close)
    i = n - 2                                             # last CLOSED bar
    regime, sig = R.route(i, high, low, close, atr_v, er, adx_v, volpct)
    bar_ts = None
    if times is not None:
        try:
            bar_ts = datetime.fromtimestamp(int(times[i]), timezone.utc).isoformat()
        except Exception:
            bar_ts = None
    return {
        "bar_ts": bar_ts,
        "regime": regime,
        "close": _r(close[i]),
        "er": _r(er[i]), "adx": _r(adx_v[i]), "volpct": _r(volpct[i]), "atr": _r(atr_v[i]),
        "signal": sig,
    }


def run_regime_shadow(bars=None):
    """Entry point (เรียกจาก graph node). fetch bars (หรือ inject สำหรับ test) → compute → append log.
    Dedup ต่อ H1 bar. คืน record หรือ None. **ทำงานเมื่อ REGIME_SHADOW=true เท่านั้น**."""
    if not getattr(_cfg, "REGIME_SHADOW", False):
        return None
    global _last_bar_ts
    if bars is None:
        bars = _bars_from_feed()
        if bars is None:
            return None
    high, low, close, times = bars
    rec = compute_shadow_signal(high, low, close, times)
    if rec is None:
        return None
    if rec["bar_ts"] and rec["bar_ts"] == _last_bar_ts:  # bar เดิม log แล้วใน run นี้ → ไม่เขียนซ้ำ
        return rec
    _last_bar_ts = rec["bar_ts"]
    rec["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass
    return rec
