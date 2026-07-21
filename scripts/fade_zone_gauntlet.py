#!/usr/bin/env python
"""fade_zone_gauntlet.py — พิสูจน์ขั้นสุดท้าย: fade ที่ KDE mid-strength zones มี edge จริงไหม (full gauntlet).

⚠️ OFFLINE. lead จาก strength-stratify: KDE 16-25 touches → respect 47%, edge +11.6% เหนือ null.
respect เป็น proxy — อันนี้ sim **fade trade จริง** (entry@zone + structural SL + TP@RR + intrabar-fill
pessimistic + net cost) แล้ววัด EV/PSR + OOS + **NULL (fade ที่ random level)**.

ผ่าน = expR>0 ทุก cost + PSR>0.95 + OOS ยืน + ชนะ null ชัด. รัน: & $PY scripts\fade_zone_gauntlet.py
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
import regime_backtest as BT           # simulate_trade, summarize, psr_zero, print_row, MIN_N

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOOKBACK = 300
REFRESH  = 24          # recompute zones ทุก 12 แท่ง (เร็วพอ + zone เลื่อนช้า)
BAND_ATR = 0.25
MIN_TCH, MAX_TCH = 16, 25              # mid-strength sweet spot (จาก strength-stratify)
SL_ATR   = 1.0         # structural SL: เลย zone ออกไป 1·ATR
MAX_HOLD = 24
COOLDOWN = 24          # ไม่เข้า zone เดิมซ้ำใน 24 แท่ง
RR_GRID  = [1.5, 2.0]


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4], d[:, 5]


def _kde_zones(hw, lw, cw, vw, atr):
    """KDE peaks (vol-weighted) → คืน list ของ (price, touches). touches = แท่งที่แตะ ±band."""
    if cw.std() == 0 or atr <= 0:
        return []
    band = BAND_ATR * atr
    kde = gaussian_kde(cw, weights=vw); kde.set_bandwidth(band / cw.std())
    grid = np.linspace(cw.min(), cw.max(), 300); dens = kde(grid)
    idx = argrelextrema(dens, np.greater, order=5)[0]
    out = []
    for i in idx:
        if dens[i] < 0.20 * dens.max():
            continue
        z = grid[i]
        tch = int(np.count_nonzero((lw <= z + band) & (hw >= z - band)))
        out.append((z, tch))
    return out


def gen_signals(high, low, close, vol, atr_v, use_random=False, seed=0):
    """walk-forward → fade signals ที่ mid-strength zones (หรือ random level ถ้า null).
    entry เมื่อราคาเพิ่งแตะ zone (crossing in) + fade (BUY@support จากบน / SELL@resistance จากล่าง)."""
    rng = np.random.RandomState(seed)
    n = len(close)
    start = LOOKBACK + 2
    zones = []               # [(price, touches)]
    last_entry = {}          # round(price,1) → bar index (cooldown)
    sigs = []
    for i in range(start, n - 1):
        atr = float(atr_v[i])
        if not np.isfinite(atr) or atr <= 0:
            continue
        band = BAND_ATR * atr
        if i % REFRESH == 0 or not zones:                    # refresh zones
            win = slice(i - LOOKBACK, i)
            hw, lw, cw, vw = high[win], low[win], close[win], vol[win]
            zall = _kde_zones(hw, lw, cw, vw, atr)
            zones = [(z, t) for z, t in zall if MIN_TCH <= t <= MAX_TCH]
            if use_random and zall:                          # null: random levels จำนวนเท่ากันในช่วง
                zones = [(rng.uniform(cw.min(), cw.max()),
                          20) for _ in range(len(zones))]     # touches dummy (ไม่ filter null)
        for z, _t in zones:
            if abs(close[i] - z) > band:                     # ไม่ได้อยู่ในโซน
                continue
            if abs(close[i - 1] - z) <= band:                # ไม่ใช่การเพิ่งแตะ (อยู่มาก่อนแล้ว)
                continue
            key = round(z, 1)
            if i - last_entry.get(key, -10 ** 9) < COOLDOWN:
                continue
            from_above = close[i - 1] > z
            direction = "BUY" if from_above else "SELL"      # fade: ซื้อแนวรับ / ขายแนวต้าน
            entry = close[i]
            sl = (z - SL_ATR * atr) if direction == "BUY" else (z + SL_ATR * atr)
            sl_pips = max(1, round(abs(entry - sl) / R.POINT))
            last_entry[key] = i
            sigs.append({"i": i, "dir": direction, "sl_pips": sl_pips})
    return sigs


def sim_all(sigs, rr, high, low, close):
    trades = []
    for s in sigs:
        tp_pips = round(s["sl_pips"] * rr)
        r_g, bars, mfe, mae, why = BT.simulate_trade(s["i"], s["dir"], s["sl_pips"], tp_pips,
                                                     MAX_HOLD, high, low, close)
        trades.append({**s, "tp_pips": tp_pips, "R_gross": r_g, "bars": bars, "why": why})
    return trades


def main():
    high, low, close, vol = _load()
    atr_v = R.atr(high, low, close)
    n = len(close); split = int(n * 0.6)
    print("=" * 82)
    print(f"FADE-ZONE GAUNTLET — KDE mid-strength ({MIN_TCH}-{MAX_TCH} touches) | gold H1 {n} bars")
    print(f"  intrabar-fill pessimistic · net cost · OOS 60/40 · NULL=fade random level · SL={SL_ATR}ATR")
    print("=" * 82)

    real = gen_signals(high, low, close, vol, atr_v, use_random=False)
    null = gen_signals(high, low, close, vol, atr_v, use_random=True, seed=1)
    print(f"\nsignals: real={len(real)}  null(random-level)={len(null)}")

    for rr in RR_GRID:
        print(f"\n{'─'*82}\n■ RR={rr}  (breakeven WR={100/(1+rr):.1f}%)")
        rt = sim_all(real, rr, high, low, close)
        nt = sim_all(null, rr, high, low, close)
        if len(rt) < BT.MIN_N:
            print(f"  ⚠ N={len(rt)} < {BT.MIN_N} — noise, ไม่สรุป"); continue
        print("  ── REAL (KDE mid-strength zones) ──")
        for c in BT.COST_PIPS_GRID:
            BT.print_row(BT.summarize("real", rt, c))
        print("  ── NULL (fade random levels) ──")
        BT.print_row(BT.summarize("null", nt, 30))
        # OOS: split by entry bar
        tr_in = [t for t in rt if t["i"] < split]; tr_out = [t for t in rt if t["i"] >= split]
        print(f"  ── OOS (train {len(tr_in)} / test {len(tr_out)}) @ cost 30p ──")
        if len(tr_in) >= 30 and len(tr_out) >= 30:
            si, so = BT.summarize("IN", tr_in, 30), BT.summarize("OUT", tr_out, 30)
            print(f"    IN : expR={si['exp_R']:+.3f} WR={si['wr']*100:.1f}% PSR={si['psr0']:.2f}")
            print(f"    OUT: expR={so['exp_R']:+.3f} WR={so['wr']*100:.1f}% PSR={so['psr0']:.2f}  "
                  f"{'✅ ยืน OOS' if so['exp_R']>0 else '❌ พังOOS'}")
        else:
            print("    N ไม่พอแยก OOS")
    print("\n" + "=" * 82)
    print("ผ่าน = REAL expR>0 ทุก cost + PSR>0.95 + ชนะ NULL ชัด + OOS(OUT) expR>0. ไม่งั้น = ไม่มี edge (จบ fade)")


if __name__ == "__main__":
    main()
