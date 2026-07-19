#!/usr/bin/env python
"""
regime_lib.py — P1: deterministic regime detector + algorithm-library skeleton (OFFLINE, flag-OFF)

จาก DESIGN_minimal_ai_regime_router.md + RESEARCH_regime_algorithms.md.
**ไม่มี AI, ไม่แตะ live, ยังไม่ validate** — เป็นโครง SELECTION(router)+EXECUTION(algo) ให้ P2 เอาไป backtest.

REGIME DETECTOR (deterministic fusion):
  • Efficiency Ratio (Kaufman): ER=|net|/Σ|Δ| — trend vs chop
  • ADX (Wilder 14): trend strength (>25 trend, <20 range)
  • realized-vol percentile: RISK-OFF overlay (HMM validated จะเสียบแทน slot นี้ตอน P2)
  → TREND / RANGE / RISK-OFF / NEUTRAL + eligible-algo set

ALGO LIBRARY (deterministic, math จาก research):
  • momentum_breakout : Donchian ทะลุ + ATR SL/TP (TSMOM/trend)
  • mean_reversion    : z-score s-score |s|>1.25 (Avellaneda thresholds) + SL/TP (RANGE)
  • range_fade        : fade ที่ขอบ range (RANGE)
  • STAND-DOWN        : RISK-OFF / NEUTRAL / EV ไม่ผ่าน

รัน (demo sanity-check บน xau history — ดู regime distribution + signal counts, ยังไม่ใช่ validation):
  python scripts\\regime_lib.py [tf]   (default h1)
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POINT = 0.01

# ── params (จะเป็น N ที่ต้องนับตอน validate P2) ──
ER_WIN, ADX_WIN = 20, 14
VOL_WIN, VOL_LOOKBACK = 24, 480
BRK_WIN = 20                     # Donchian lookback
ATR_WIN, ATR_SL, RR = 14, 1.5, 2.0
MR_WIN = 20                      # mean-reversion SMA/std window
S_ENTRY, S_EXIT = 1.25, 0.5      # Avellaneda s-score thresholds (verified 3-0)
# regime thresholds
ADX_TREND, ADX_RANGE = 25.0, 20.0
ER_TREND, ER_RANGE = 0.35, 0.25
VOL_RISKOFF_PCT = 0.80           # vol percentile สูงกว่านี้ = RISK-OFF


# ─────────────────────────── indicators (deterministic) ───────────────────────────
def efficiency_ratio(close, n=ER_WIN):
    er = np.full(len(close), np.nan)
    ad = np.abs(np.diff(close, prepend=close[0]))
    for i in range(n, len(close)):
        v = ad[i - n + 1:i + 1].sum()
        er[i] = abs(close[i] - close[i - n]) / v if v > 0 else 0.0
    return er


def atr(high, low, close, n=ATR_WIN):
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    tr = np.concatenate([[np.nan], tr])
    out = np.full(len(close), np.nan)
    for i in range(n, len(close)):
        out[i] = np.nanmean(tr[i - n + 1:i + 1])
    return out


def adx(high, low, close, n=ADX_WIN):
    """Wilder ADX. คืน array (nan ช่วง warmup)."""
    T = len(close)
    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
    # Wilder smoothing
    def wilder(x):
        s = np.full(len(x), np.nan)
        if len(x) < n:
            return s
        s[n - 1] = x[:n].sum()
        for i in range(n, len(x)):
            s[i] = s[i - 1] - s[i - 1] / n + x[i]
        return s
    str_ = wilder(tr); pdm = wilder(plus_dm); mdm = wilder(minus_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * pdm / str_
        mdi = 100 * mdm / str_
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    adx_ = np.full(len(dx), np.nan)
    valid = np.where(~np.isnan(dx))[0]
    if len(valid) >= n:
        start = valid[0] + n - 1
        if start < len(dx):
            adx_[start] = np.nanmean(dx[valid[0]:start + 1])
            for i in range(start + 1, len(dx)):
                if not np.isnan(dx[i]):
                    adx_[i] = (adx_[i - 1] * (n - 1) + dx[i]) / n
    return np.concatenate([[np.nan], adx_])   # align to close (len T)


def vol_percentile(close, w=VOL_WIN, lb=VOL_LOOKBACK):
    ret = np.diff(np.log(close), prepend=np.log(close[0]))
    rv = np.full(len(close), np.nan)
    for i in range(w, len(close)):
        rv[i] = ret[i - w + 1:i + 1].std()
    pct = np.full(len(close), np.nan)
    for i in range(lb, len(close)):
        window = rv[i - lb:i]
        window = window[~np.isnan(window)]
        if len(window) > 20 and not np.isnan(rv[i]):
            pct[i] = (window < rv[i]).mean()
    return pct


# ─────────────────────────── regime detector (fusion) ───────────────────────────
def detect_regime(er, adx_v, volpct):
    """คืน regime label. deterministic rule."""
    if np.isnan(er) or np.isnan(adx_v):
        return "WARMUP"
    if not np.isnan(volpct) and volpct >= VOL_RISKOFF_PCT:
        return "RISK-OFF"                      # HMM validated จะเสียบ slot นี้
    if adx_v >= ADX_TREND and er >= ER_TREND:
        return "TREND"
    if adx_v <= ADX_RANGE and er <= ER_RANGE:
        return "RANGE"
    return "NEUTRAL"


REGIME_ALGOS = {
    "TREND":   ["momentum_breakout"],
    "RANGE":   ["mean_reversion", "range_fade"],
    "RISK-OFF": [], "NEUTRAL": [], "WARMUP": [],
}


# ─────────────────────────── algorithm library (EXECUTION, deterministic) ───────────────────────────
def algo_momentum_breakout(i, high, low, close, atr_v):
    """Donchian breakout + ATR SL/TP. คืน signal dict หรือ None."""
    if i < BRK_WIN or np.isnan(atr_v[i]) or atr_v[i] == 0:
        return None
    hh = high[i - BRK_WIN:i].max(); ll = low[i - BRK_WIN:i].min()
    d = "BUY" if close[i] > hh else ("SELL" if close[i] < ll else None)
    if d is None:
        return None
    sl_pips = round(ATR_SL * atr_v[i] / POINT)
    return {"algo": "momentum_breakout", "dir": d, "sl_pips": sl_pips, "tp_pips": round(sl_pips * RR)}


def algo_mean_reversion(i, close, atr_v):
    """z-score (s-score) fade — Avellaneda thresholds |s|>1.25. คืน signal หรือ None."""
    if i < MR_WIN or np.isnan(atr_v[i]) or atr_v[i] == 0:
        return None
    w = close[i - MR_WIN + 1:i + 1]
    m, sd = w.mean(), w.std()
    if sd == 0:
        return None
    s = (close[i] - m) / sd
    d = "BUY" if s < -S_ENTRY else ("SELL" if s > S_ENTRY else None)
    if d is None:
        return None
    sl_pips = round(ATR_SL * atr_v[i] / POINT)               # SL beyond extreme (~ATR)
    tp_pips = round(abs(close[i] - m) / POINT)                # TP = กลับสู่ mean
    return {"algo": "mean_reversion", "dir": d, "s": round(float(s), 2),
            "sl_pips": sl_pips, "tp_pips": max(tp_pips, round(sl_pips * 1.0))}


def algo_range_fade(i, high, low, close, atr_v):
    """fade ที่ขอบ range (Donchian edge). คืน signal หรือ None."""
    if i < BRK_WIN or np.isnan(atr_v[i]) or atr_v[i] == 0:
        return None
    hh = high[i - BRK_WIN:i].max(); ll = low[i - BRK_WIN:i].min()
    zone = 0.15 * atr_v[i]
    d = "SELL" if close[i] >= hh - zone else ("BUY" if close[i] <= ll + zone else None)
    if d is None:
        return None
    sl_pips = round(ATR_SL * atr_v[i] / POINT)
    tp_pips = round((hh - ll) * 0.6 / POINT)                  # TP = ~ กลาง range
    return {"algo": "range_fade", "dir": d, "sl_pips": sl_pips, "tp_pips": max(tp_pips, sl_pips)}


def route(i, high, low, close, atr_v, er, adx_v, volpct):
    """SELECTION: detect regime → เรียก algo ที่ eligible → คืน (regime, signal|None)."""
    regime = detect_regime(er[i], adx_v[i], volpct[i])
    for name in REGIME_ALGOS.get(regime, []):
        if name == "momentum_breakout":
            sig = algo_momentum_breakout(i, high, low, close, atr_v)
        elif name == "mean_reversion":
            sig = algo_mean_reversion(i, close, atr_v)
        elif name == "range_fade":
            sig = algo_range_fade(i, high, low, close, atr_v)
        else:
            sig = None
        if sig:
            return regime, sig
    return regime, None


# ─────────────────────────── demo / sanity-check (ยังไม่ใช่ validation) ───────────────────────────
def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    p = os.path.join(_BASE, "data", f"xau_{tf}.json")
    if not os.path.exists(p):
        print(f"❌ ไม่มี data/xau_{tf}.json (export_xau_history)"); return
    rows = json.load(open(p))
    high = np.array([r[2] for r in rows]); low = np.array([r[3] for r in rows]); close = np.array([r[4] for r in rows])
    print("=" * 72)
    print(f"REGIME LIB — P1 skeleton sanity-check | gold {tf.upper()} {len(close)} bars")
    print("=" * 72)
    er = efficiency_ratio(close); adx_v = adx(high, low, close); volpct = vol_percentile(close); atr_v = atr(high, low, close)

    from collections import Counter
    reg_count = Counter(); sig_count = Counter(); start = max(VOL_LOOKBACK, BRK_WIN, ER_WIN) + 2
    for i in range(start, len(close) - 1):
        regime, sig = route(i, high, low, close, atr_v, er, adx_v, volpct)
        reg_count[regime] += 1
        if sig:
            sig_count[sig["algo"]] += 1
    n = sum(reg_count.values())
    print("\n── regime distribution ──")
    for r in ("TREND", "RANGE", "RISK-OFF", "NEUTRAL"):
        print(f"  {r:>9}: {reg_count[r]:>6} ({reg_count[r]/n*100:4.0f}%)")
    print("\n── signals ที่ algo จะยิง (per regime routing) ──")
    for a in ("momentum_breakout", "mean_reversion", "range_fade"):
        print(f"  {a:>18}: {sig_count[a]:>5}")
    print(f"\n  รวม signal: {sum(sig_count.values())} จาก {n} bars ({sum(sig_count.values())/n*100:.1f}%)")
    print("\n" + "=" * 72)
    print("✅ skeleton ทำงาน (regime + routing + algo ยิง signal). **ยังไม่ validate edge**.")
    print("⏭️ P2: backtest ทุก algo ต่อ regime ด้วย harness (intrabar+cost+DSR+PBO+null) → คัดตัวรอด.")
    print("   HMM validated จะเสียบแทน vol-percentile ใน RISK-OFF slot. AI (news) เพิ่มใน P3.")


if __name__ == "__main__":
    main()
