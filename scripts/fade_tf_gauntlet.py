#!/usr/bin/env python
"""fade_tf_gauntlet.py — ทดสอบสมมติฐาน owner: fade ที่ TF ใหญ่ขึ้น (H4/D1) มี edge กว่า H1 ไหม?

⚠️ OFFLINE. รวม H1→H4/D1 → detect KDE zones ที่ TF นั้น (institutional levels แข็งกว่า) → fade H1 price
ที่โซนพวกนั้น (SL=TF-ATR structural). วัด respect + gauntlet (EV/PSR/OOS/null) ต่อ TF. ตอบว่า TF ใหญ่ช่วยไหม.

รัน: & $PY scripts\fade_tf_gauntlet.py
"""
import json
import os
import sys

import numpy as np
from scipy.stats import gaussian_kde
from scipy.signal import argrelextrema

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOOKBACK_TF = 200      # แท่ง TF ที่ใช้ detect zones
BAND_ATR = 0.25
SL_ATR = 1.0           # SL = 1·TF-ATR เลย zone (structural ตาม TF)
MAX_HOLD_H1 = 48       # ถือได้นานขึ้น (โซนใหญ่ = swing)
COOLDOWN_H1 = 48
RR = 2.0               # ใช้ RR2 (breakeven 33% — เอื้อ fade สุด)


def _load_h1():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4], d[:, 5]              # H,L,C,V


def _aggregate(high, low, close, vol, mult):
    """รวม H1 → TF (mult แท่ง/1 TF-bar). คืน (H,L,C,V) ที่ TF + map: TF index → H1 end index."""
    n = (len(close) // mult) * mult
    H = high[:n].reshape(-1, mult).max(1)
    L = low[:n].reshape(-1, mult).min(1)
    C = close[:n].reshape(-1, mult)[:, -1]
    V = vol[:n].reshape(-1, mult).sum(1)
    return H, L, C, V


def _kde_zones(hw, lw, cw, vw, atr):
    if cw.std() == 0 or atr <= 0:
        return []
    band = BAND_ATR * atr
    kde = gaussian_kde(cw, weights=vw); kde.set_bandwidth(band / cw.std())
    grid = np.linspace(cw.min(), cw.max(), 300); dens = kde(grid)
    idx = argrelextrema(dens, np.greater, order=5)[0]
    return [grid[i] for i in idx if dens[i] >= 0.20 * dens.max()]


def gen_and_sim(high, low, close, vol, mult, rr, use_random=False, seed=0):
    """detect zones ที่ TF (mult) → fade H1 price ที่โซน → sim (intrabar H1). คืน list trades."""
    rng = np.random.RandomState(seed)
    TH, TL, TC, TV = _aggregate(high, low, close, vol, mult)
    tf_atr = R.atr(TH, TL, TC)
    trades = []; last_entry = {}
    for j in range(LOOKBACK_TF, len(TC) - 1):
        atr = float(tf_atr[j])
        if not np.isfinite(atr) or atr <= 0:
            continue
        band = BAND_ATR * atr
        zw = slice(j - LOOKBACK_TF, j)
        zones = _kde_zones(TH[zw], TL[zw], TC[zw], TV[zw], atr)
        if use_random and zones:
            lo, hi = TC[zw].min(), TC[zw].max()
            zones = [rng.uniform(lo, hi) for _ in zones]
        if not zones:
            continue
        h1a, h1b = j * mult, min((j + 1) * mult, len(close) - 1)   # H1 bars ในช่วง TF-bar ถัดไป
        for i in range(h1a, h1b):
            for z in zones:
                if abs(close[i] - z) > band or abs(close[i - 1] - z) <= band:
                    continue
                key = round(z, 1)
                if i - last_entry.get(key, -10 ** 9) < COOLDOWN_H1:
                    continue
                direction = "BUY" if close[i - 1] > z else "SELL"
                sl_pips = max(1, round(SL_ATR * atr / R.POINT))
                tp_pips = round(sl_pips * rr)
                r_g, bars, mfe, mae, why = BT.simulate_trade(i, direction, sl_pips, tp_pips,
                                                             MAX_HOLD_H1, high, low, close)
                trades.append({"i": i, "dir": direction, "sl_pips": sl_pips, "tp_pips": tp_pips,
                               "R_gross": r_g, "why": why})
                last_entry[key] = i
    return trades


def main():
    high, low, close, vol = _load_h1()
    n = len(close); split = int(n * 0.6)
    print("=" * 80)
    print(f"FADE by TIMEFRAME — สมมติฐาน owner: TF ใหญ่ = แนวแข็ง = fade ได้กว่า? | gold {n} H1 bars, RR={RR}")
    print("=" * 80)
    print(f"{'TF':>4} | {'N':>5} {'WR':>6} {'expR@30p':>9} {'PSR0':>6} | {'null expR':>10} | {'OOS-out':>9}")
    print("-" * 80)
    for tf, mult in (("H1", 1), ("H4", 4), ("D1", 24)):
        rt = gen_and_sim(high, low, close, vol, mult, RR, use_random=False)
        if len(rt) < 30:
            print(f"{tf:>4} | N={len(rt)} < 30 — noise"); continue
        s = BT.summarize(tf, rt, 30)
        nt = gen_and_sim(high, low, close, vol, mult, RR, use_random=True, seed=1)
        ns = BT.summarize("null", nt, 30) if len(nt) >= 30 else {"exp_R": float("nan")}
        out = [t for t in rt if t["i"] >= split]
        so = BT.summarize("out", out, 30) if len(out) >= 30 else {"exp_R": float("nan")}
        flag = "✅+EV OOS" if so["exp_R"] > 0 and s["exp_R"] > 0 else "❌"
        print(f"{tf:>4} | {s['n']:>5} {s['wr']*100:5.1f}% {s['exp_R']:>+9.3f} {s['psr0']:>6.2f} | "
              f"{ns['exp_R']:>+10.3f} | {so['exp_R']:>+8.3f} {flag}")
    print("\n" + "=" * 80)
    print("ตอบสมมติฐาน: ถ้า H4/D1 expR>0 + PSR>0.95 + ชนะ null + OOS ยืน = TF ใหญ่ช่วยจริง (เจอ edge!)")
    print("ถ้า H4/D1 ยัง −EV เหมือน H1 = แนวใหญ่ก็ break-prone → ทองไม่มี fade edge ทุก TF")


if __name__ == "__main__":
    main()
