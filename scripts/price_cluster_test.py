#!/usr/bin/env python
"""
price_cluster_test.py — ทดสอบเทคนิค owner แบบ implement ถูกวิธี: **price cluster จริง** (dwell zone จาก histogram)
+ momentum deceleration ที่ cluster → sell แนวต้าน / buy แนวรับ. (ก่อนหน้าใช้ min/max หยาบ = ไม่ยุติธรรมกับไอเดีย)

cluster = bin ราคาย้อนหลัง LOOKBACK แท่ง (กว้าง ~0.5·ATR) → bin ที่ touch เยอะ (≥MIN_TOUCH) = S/R นัยสำคัญ.
entry: ราคาแตะ cluster + rejection (ปิดสวน) + momentum ช้าลง (แรงหมดที่ level) → fade.
gauntlet: backtest cost + OOS + null. รัน:  python scripts\\price_cluster_test.py [tf]
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

COST = 30; LOOKBACK = 200; MIN_TOUCH = 8; HOLD = 48; SPLIT = 0.60


def cluster_levels(window, atr):
    """histogram → คืน list ราคา cluster (bin center) ที่ touch ≥ MIN_TOUCH."""
    bw = max(0.25 * atr, 1e-6)
    lo = window.min()
    counts = {}
    for px in window:
        b = int((px - lo) / bw)
        counts[b] = counts.get(b, 0) + 1
    return [lo + (b + 0.5) * bw for b, c in counts.items() if c >= MIN_TOUCH]


def sig(i, high, low, close, atr_v, trend_filter):
    a = atr_v[i]
    if i < LOOKBACK or np.isnan(a) or a == 0:
        return None
    levels = cluster_levels(close[i - LOOKBACK:i], a)
    if not levels:
        return None
    px = close[i]
    res = [lv for lv in levels if lv > px]
    sup = [lv for lv in levels if lv < px]
    mid = (high[i] + low[i]) / 2
    decel_dn = close[i] < close[i - 1] < close[i - 2]        # โมเมนตัมขึ้นหมดแรง (3-bar)
    decel_up = close[i] > close[i - 1] > close[i - 2]
    up = close[i] > close[i - 100] if i >= 100 else True
    dn = close[i] < close[i - 100] if i >= 100 else True
    if res:
        r = min(res)                                        # cluster ต้านที่ใกล้สุด
        if (r - high[i]) <= 0.3 * a and close[i] < mid and decel_dn and (not trend_filter or dn):
            sl = max(round(((r + 0.5 * a) - close[i]) / R.POINT), round(a / R.POINT))
            return "SELL", sl, round(sl * 1.5)
    if sup:
        s = max(sup)                                        # cluster รับที่ใกล้สุด
        if (low[i] - s) <= 0.3 * a and close[i] > mid and decel_up and (not trend_filter or up):
            sl = max(round((close[i] - (s - 0.5 * a)) / R.POINT), round(a / R.POINT))
            return "BUY", sl, round(sl * 1.5)
    return None


def run(high, low, close, atr_v, trend):
    trades = []
    for i in range(max(R.VOL_LOOKBACK, LOOKBACK) + 2, len(close) - 1):
        s = sig(i, high, low, close, atr_v, trend)
        if not s:
            continue
        d, sl, tp = s
        rg, *_ = BT.simulate_trade(i, d, sl, tp, HOLD, high, low, close)
        trades.append({"i": i, "sl_pips": sl, "R_gross": rg})
    return trades


def null_test(trend, high, low, close, real, B=120, blk=20):
    logret = np.concatenate([[0.0], np.diff(np.log(close))])
    hr = high / close; lor = low / close
    rng = np.random.default_rng(321); n = len(close); null = []
    for _ in range(B):
        idx = []
        while len(idx) < n:
            st = rng.integers(0, n); idx.extend((st + k) % n for k in range(blk))
        idx = np.array(idx[:n]); lr = logret[idx]
        c = np.empty(n); c[0] = 100.0; c[1:] = 100.0 * np.exp(np.cumsum(lr[1:]))
        h = c * hr[idx]; l = c * lor[idx]
        tr = run(h, l, c, R.atr(h, l, c), trend)
        if len(tr) >= 30:
            null.append(float(BT.net_R(tr, COST).mean()))
    null = np.array(null)
    return ((null >= real).mean() if len(null) else 1.0), (null.mean() if len(null) else 0.0)


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json")))
    high = np.array([r[2] for r in rows], float); low = np.array([r[3] for r in rows], float)
    close = np.array([r[4] for r in rows], float)
    atr_v = R.atr(high, low, close)
    split = int(len(close) * SPLIT)
    print("=" * 74)
    print(f"PRICE CLUSTER + MOMENTUM (owner technique, proper impl) — gold {tf.upper()} {len(close)} bars")
    print("=" * 74)
    for name, trend in (("cluster_fade", False), ("cluster_fade+trend", True)):
        trades = run(high, low, close, atr_v, trend)
        n = len(trades)
        print(f"\n── {name} ── ({n} trades)")
        if n < BT.MIN_N:
            print(f"  ⚠ N<{BT.MIN_N}"); continue
        for c in (20, 30, 40):
            r = BT.net_R(trades, c); print(f"  cost={c}p: expR={r.mean():+.3f} WR={(r>0).mean()*100:4.1f}%")
        tr = [t for t in trades if t["i"] < split - 200]; te = [t for t in trades if t["i"] >= split]
        etr = BT.net_R(tr, COST).mean() if len(tr) >= 30 else float("nan")
        ete = BT.net_R(te, COST).mean() if len(te) >= 30 else float("nan")
        print(f"  OOS: train={etr:+.3f}(N={len(tr)}) | test={ete:+.3f}(N={len(te)})")
        real = float(BT.net_R(trades, COST).mean())
        if real > 0 and ete > 0:
            p, nm = null_test(trend, high, low, close, real)
            print(f"  NULL: real={real:+.3f} vs null={nm:+.3f} → p={p:.3f} {'✅ ผ่าน!' if p < 0.05 else '❌ artifact'}")
        else:
            print("  → −EV (full/OOS) → ไม่ผ่าน")
    print("\n" + "=" * 74)


if __name__ == "__main__":
    main()
