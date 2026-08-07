#!/usr/bin/env python
"""scripts/index_scalp.py — หา 15m scalp บน index CFDs (user 08-07 ทำต่อ).

gold scalp ตัน (cost/noise). index = trend แรง + spread เล็กเทียบ range → candidate ดีกว่า.
entry (ไม่ใช้ DXY-macro เพราะ index ไม่ขับด้วย dollar เหมือนทอง):
  A. momentum      : 15m Donchian breakout + TREND-gate + volume surge
  B. tf-confluence : breakout + H1 trend + H4 trend + volume (multi-TF, ไม่มี macro)
RR sweep 1/1.5/2 + adaptive SL. causal · SL-first · cost=spread · OOS. เก็บ +EV.
รัน: python scripts/index_scalp.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402

INDICES = ["US30Cash#", "US100Cash#", "US500Cash#", "GER40Cash#", "JP225Cash#", "US2000Cash#"]


def _ema(a, n):
    e = np.zeros_like(a); e[0] = a[0]; k = 2 / (n + 1)
    for i in range(1, len(a)):
        e[i] = a[i] * k + e[i - 1] * (1 - k)
    return e


def _slope_map(m15t, ht, hc, n=50):
    e = _ema(hc, n); sl = np.sign(e - np.concatenate([e[:3], e[:-3]]))
    return sl[np.clip(np.searchsorted(ht, m15t, "right") - 1, 0, len(sl) - 1)]


def _st(tr):
    n = len(tr)
    if n < 40:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd else 0.0
    k = int(n * 0.7)
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), round(t, 2), round(float(np.array(tr[k:]).mean()), 4)


def run(h, l, c, vol, atr, h1t, h4t, er, adx, vp, cost, pt, mode, rr, sl_atr=1.0, brk=12, vk=1.3, mh=32):
    n = len(c); tr = []; i = 210
    vmed = np.zeros(n)
    for k in range(200, n):
        vmed[k] = np.median(vol[k - 200:k]) or 1
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or vmed[i] <= 0 or vol[i] > 2.0 * vmed[i]:
            i += 1; continue
        px = float(c[i]); hh = float(h[i - brk:i].max()); ll = float(l[i - brk:i].min())
        d = 1 if px > hh else -1 if px < ll else 0
        if not d:
            i += 1; continue
        if mode == "momentum":
            if R.detect_regime(er[i], adx[i], vp[i]) != "TREND" or vol[i] < vk * vmed[i]:
                i += 1; continue
        elif mode == "confluence":
            if h1t[i] != d or h4t[i] != d or vol[i] < vk * vmed[i]:
                i += 1; continue
        slp = max(20, sl_atr * av / pt)
        sl = px - d * slp * pt; tp = px + d * slp * rr * pt
        end = min(i + mh, n - 1); r = None; ei = end
        for j in range(i + 1, end + 1):
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                r = -1.0 - cost / slp; ei = j; break
            if (h[j] >= tp) if d > 0 else (l[j] <= tp):
                r = rr - cost / slp; ei = j; break
        if r is None:
            r = d * (c[end] - px) / (slp * pt) - cost / slp
        tr.append(r); i = ei + 1
    return tr


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    print("\n=== INDEX 15m SCALP (momentum / multi-TF confluence + volume) · causal · cost=spread · OOS ===")
    print("index trend แรง + cost ต่ำเทียบ range. เก็บ +EV (exp_R>0+OOS>0)\n")
    win = []
    for sym in INDICES:
        si = mt5.symbol_info(sym)
        if not si:
            print("%s ไม่เจอ" % sym); continue
        mt5.symbol_select(sym, True)
        m = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 40000)
        if m is None or len(m) < 3000:
            print("%s M15 ไม่พอ" % sym); continue
        h = m["high"].astype(float); l = m["low"].astype(float); c = m["close"].astype(float)
        tm = m["time"].astype(np.int64); vol = m["tick_volume"].astype(float)
        h1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
        h4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 10000)
        if h1 is None or h4 is None:
            print("%s HTF ไม่พอ" % sym); continue
        h1t = _slope_map(tm, h1["time"].astype(np.int64), h1["close"].astype(float))
        h4t = _slope_map(tm, h4["time"].astype(np.int64), h4["close"].astype(float))
        atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
        pt = float(si.point); cost = max(1.0, float(si.spread)) * 1.3      # spread × 1.3 (slippage)
        yrs = (tm[-1] - tm[0]) / (365.25 * 24 * 3600)
        med_atr = float(np.nanmedian(atr[-1000:])) / pt
        print("── %s (bars=%d ~%.1fปี cost≈%.0fp medATR=%.0fp cost/ATR=%.1f%%) ──" % (sym, len(c), yrs, cost, med_atr, cost / med_atr * 100))
        for mode in ("momentum", "confluence"):
            for rr in (1.0, 1.5, 2.0):
                s = _st(run(h, l, c, vol, atr, h1t, h4t, er, adx, vp, cost, pt, mode=mode, rr=rr))
                if not s:
                    print("  %-14s rr%.1f n<40" % (mode, rr)); continue
                n, wr, ex, t, oe = s
                fl = "✅+EV" if ex > 0 and oe > 0 and n >= 60 else "−"
                if fl != "−":
                    win.append((sym, mode, rr, n, wr, ex, t, oe))
                print("  %-14s rr%.1f n=%5d fire%4.0f/ปี WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f %s" % (mode, rr, n, n / yrs, wr, ex, t, oe, fl))
    print("\n=== +EV index scalp ===")
    for w in sorted(win, key=lambda z: -z[5]):
        print("  %-12s %-11s rr%.1f n=%d WR%.1f%% exp_R%+.4f t%+.2f OOS%+.4f" % w)
    if not win:
        print("  ไม่มี +EV")
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
