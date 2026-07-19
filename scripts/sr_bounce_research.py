#!/usr/bin/env python
"""
sr_bounce_research.py — ทดสอบสมมติฐานของ owner: "เข้าเพราะอยู่แนวรับสำคัญที่ไม่ทะลุ + volatility ไม่ทะลุลง
เลยซื้อขึ้น" = **support-bounce + vol-no-breakdown filter**. ต่างจาก z-score mean-rev (ที่ตาย) เพราะผูก S/R จริง
+ กรอง breakdown candle. ผ่าน gauntlet (backtest cost + OOS + null) → ค่อยเชื่อ.

V1 = S/R bounce เปล่า (structure อย่างเดียว)
V2 = + vol filter (bar range ไม่ระเบิด = ไม่มี breakdown) ← thesis เต็มของ owner
รัน:  python scripts\\sr_bounce_research.py [tf]
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
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

COST = 30
LOOKBACK = 50          # แนวรับ/ต้าน = low/high ของ N แท่ง (significant)
HOLD = 48
SPLIT = 0.60


def sr_signal(i, high, low, close, atr_v, vol_filter, trend_filter=False):
    a = atr_v[i]
    if i < LOOKBACK or np.isnan(a) or a == 0:
        return None
    sup = low[i - LOOKBACK:i].min()
    res = high[i - LOOKBACK:i].max()
    if vol_filter and (high[i] - low[i]) > 1.8 * a:        # bar ระเบิด = breakout/breakdown → ไม่ใช่ bounce
        return None
    up = close[i] > close[i - 100] if i >= 100 else True   # trend filter: ซื้อรับเฉพาะขาขึ้น (thesis owner)
    dn = close[i] < close[i - 100] if i >= 100 else True
    mid = (high[i] + low[i]) / 2
    near_sup = (low[i] - sup) <= 0.5 * a and close[i] > sup and close[i] > mid   # แตะรับ + ปิดเหนือ (ยืน) + rejection
    near_res = (res - high[i]) <= 0.5 * a and close[i] < res and close[i] < mid
    if near_sup and (not trend_filter or up):
        sl = max(round((close[i] - (sup - 0.5 * a)) / R.POINT), round(a / R.POINT))
        return "BUY", sl, round(sl * 1.5), HOLD
    if near_res and (not trend_filter or dn):
        sl = max(round(((res + 0.5 * a) - close[i]) / R.POINT), round(a / R.POINT))
        return "SELL", sl, round(sl * 1.5), HOLD
    return None


def run(high, low, close, atr_v, vol_filter, trend_filter=False):
    trades = []
    start = max(R.VOL_LOOKBACK, LOOKBACK) + 2
    for i in range(start, len(close) - 1):
        sig = sr_signal(i, high, low, close, atr_v, vol_filter, trend_filter)
        if not sig:
            continue
        d, sl, tp, hold = sig
        rg, *_ = BT.simulate_trade(i, d, sl, tp, hold, high, low, close)
        trades.append({"i": i, "sl_pips": sl, "R_gross": rg})
    return trades


def null_test(vol_filter, tf_flag, high, low, close, real, B=150, blk=20):
    logret = np.concatenate([[0.0], np.diff(np.log(close))])
    hr = high / close; lor = low / close
    rng = np.random.default_rng(555); n = len(close); null = []
    for _ in range(B):
        idx = []
        while len(idx) < n:
            s = rng.integers(0, n); idx.extend((s + k) % n for k in range(blk))
        idx = np.array(idx[:n]); lr = logret[idx]
        c = np.empty(n); c[0] = 100.0; c[1:] = 100.0 * np.exp(np.cumsum(lr[1:]))
        h = c * hr[idx]; l = c * lor[idx]; atr2 = R.atr(h, l, c)
        tr = run(h, l, c, atr2, vol_filter, tf_flag)
        if len(tr) >= 30:
            null.append(float(BT.net_R(tr, COST).mean()))
    null = np.array(null)
    return (null >= real).mean() if len(null) else 1.0, (null.mean() if len(null) else 0.0)


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json")))
    high = np.array([r[2] for r in rows], float); low = np.array([r[3] for r in rows], float)
    close = np.array([r[4] for r in rows], float)
    atr_v = R.atr(high, low, close)
    split = int(len(close) * SPLIT)
    print("=" * 78)
    print(f"S/R BOUNCE RESEARCH (owner thesis) — gold {tf.upper()} {len(close)} bars | gauntlet")
    print("=" * 78)
    variants = (("V1_srbounce", False, False),
                ("V2_+volfilter", True, False),
                ("V3_+vol+trend (owner thesis)", True, True))
    for name, vf, tf_flag in variants:
        trades = run(high, low, close, atr_v, vf, tf_flag)
        n = len(trades)
        print(f"\n── {name} ── ({n} trades)")
        if n < BT.MIN_N:
            print(f"  ⚠ N<{BT.MIN_N}"); continue
        for c in (20, 30, 40):
            r = BT.net_R(trades, c)
            print(f"  cost={c}p: expR={r.mean():+.3f} WR={(r>0).mean()*100:4.1f}% sumR={r.sum():+.0f}")
        tr = [t for t in trades if t["i"] < split - 200]; te = [t for t in trades if t["i"] >= split]
        etr = BT.net_R(tr, COST).mean() if len(tr) >= 30 else float("nan")
        ete = BT.net_R(te, COST).mean() if len(te) >= 30 else float("nan")
        print(f"  OOS: train={etr:+.3f}(N={len(tr)}) | test={ete:+.3f}(N={len(te)})")
        real = float(BT.net_R(trades, COST).mean())
        if real > 0 and ete > 0:
            p, nm = null_test(vf, tf_flag, high, low, close, real)
            print(f"  NULL: real={real:+.3f} vs null={nm:+.3f} → p={p:.3f} {'✅ ผ่าน' if p < 0.05 else '❌ artifact'}")
        else:
            print("  → −EV (full/OOS) → ไม่ผ่าน")
    print("\n" + "=" * 78)
    print("ผ่านครบ (expR>0 ทุก cost + test>0 + null p<0.05) → candidate จริง. ถ้า V2>V1 = vol filter คือ edge.")


if __name__ == "__main__":
    main()
