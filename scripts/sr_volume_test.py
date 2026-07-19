#!/usr/bin/env python
"""
sr_volume_test.py — variant สุดท้าย: ไอเดีย owner "volume ที่แนวต้าน/รับ + ATR range → sell ต้าน/buy รับ".
ทอง = tick_volume เท่านั้น (proxy). ทดสอบ fade S/R เมื่อ tick-volume สูง (ยืนยันการ react ที่ level).
V4 = S/R fade + ATR proximity + tick-volume สูง
V5 = V4 + trend align (buy รับเฉพาะขาขึ้น / sell ต้านเฉพาะขาลง)
gauntlet: backtest cost + OOS. รัน:  python scripts\\sr_volume_test.py [tf]
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

COST = 30; LOOKBACK = 50; HOLD = 48; SPLIT = 0.60


def sig(i, high, low, close, atr_v, tvol, tvma, trend):
    a = atr_v[i]
    if i < LOOKBACK or np.isnan(a) or a == 0 or np.isnan(tvma[i]):
        return None
    if tvol[i] < 1.2 * tvma[i]:                    # ต้อง tick-volume สูง (react แรงที่ level)
        return None
    sup = low[i - LOOKBACK:i].min(); res = high[i - LOOKBACK:i].max()
    mid = (high[i] + low[i]) / 2
    up = close[i] > close[i - 100] if i >= 100 else True
    dn = close[i] < close[i - 100] if i >= 100 else True
    near_sup = (low[i] - sup) <= 0.5 * a and close[i] > sup and close[i] > mid
    near_res = (res - high[i]) <= 0.5 * a and close[i] < res and close[i] < mid
    if near_sup and (not trend or up):
        sl = max(round((close[i] - (sup - 0.5 * a)) / R.POINT), round(a / R.POINT)); return "BUY", sl, round(sl * 1.5)
    if near_res and (not trend or dn):
        sl = max(round(((res + 0.5 * a) - close[i]) / R.POINT), round(a / R.POINT)); return "SELL", sl, round(sl * 1.5)
    return None


def run(high, low, close, atr_v, tvol, tvma, trend):
    trades = []
    for i in range(max(R.VOL_LOOKBACK, LOOKBACK) + 2, len(close) - 1):
        s = sig(i, high, low, close, atr_v, tvol, tvma, trend)
        if not s:
            continue
        d, sl, tp = s
        rg, *_ = BT.simulate_trade(i, d, sl, tp, HOLD, high, low, close)
        trades.append({"i": i, "sl_pips": sl, "R_gross": rg})
    return trades


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json")))
    high = np.array([r[2] for r in rows], float); low = np.array([r[3] for r in rows], float)
    close = np.array([r[4] for r in rows], float); tvol = np.array([r[5] for r in rows], float)
    atr_v = R.atr(high, low, close)
    tvma = np.full(len(tvol), np.nan)
    for i in range(20, len(tvol)):
        tvma[i] = tvol[i - 20:i].mean()
    split = int(len(close) * SPLIT)
    print("=" * 74)
    print(f"S/R + TICK-VOLUME (owner idea) — gold {tf.upper()} {len(close)} bars | gauntlet")
    print("=" * 74)
    for name, trend in (("V4_srfade+tickvol", False), ("V5_+trend", True)):
        trades = run(high, low, close, atr_v, tvol, tvma, trend)
        n = len(trades)
        print(f"\n── {name} ── ({n} trades)")
        if n < BT.MIN_N:
            print(f"  ⚠ N<{BT.MIN_N}"); continue
        for c in (20, 30, 40):
            r = BT.net_R(trades, c); print(f"  cost={c}p: expR={r.mean():+.3f} WR={(r>0).mean()*100:4.1f}%")
        tr = [t for t in trades if t["i"] < split - 200]; te = [t for t in trades if t["i"] >= split]
        etr = BT.net_R(tr, COST).mean() if len(tr) >= 30 else float("nan")
        ete = BT.net_R(te, COST).mean() if len(te) >= 30 else float("nan")
        print(f"  OOS: train={etr:+.3f}(N={len(tr)}) | test={ete:+.3f}(N={len(te)})  "
              f"{'→ ยังไม่ผ่าน' if not (etr>0 and ete>0) else '→ ผ่าน OOS! (ต้อง null ต่อ)'}")


if __name__ == "__main__":
    main()
