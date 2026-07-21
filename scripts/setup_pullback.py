#!/usr/bin/env python
"""setup_pullback.py — Setup #1 (pro-trader): D1-trend pullback continuation → refine TSMOM entry.

hypothesis: TSMOM พิสูจน์เทรนด์ D1 persist. เข้า "ตอนย่อ" (บน H1) แทนเข้าตามยอด → entry ดี, SL แคบ, RR สูง
= timing alpha บนฐาน trend edge. ทดสอบว่าเพิ่ม Sharpe/EV เหนือ TSMOM core ไหม.

no-lookahead: (1) D1 bias ใช้ D1 บาร์ที่ปิดแล้ว (≥1 วันก่อน) (2) swing ยืนยันช้า k บาร์ (ใช้เฉพาะ confirmed).
รัน: & $PY scripts\setup_pullback.py
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import strat_stats as St

POINT = R.POINT


def _sma(x, n):
    out = np.full(len(x), np.nan); cs = np.cumsum(x)
    out[n - 1:] = (cs[n - 1:] - np.concatenate([[0], cs[:-n]])) / n
    return out


def _d1_bias(h1_ts, mode="sma"):
    """D1 trend bias map ไป H1 (ใช้ D1 บาร์ที่ปิดแล้ว ≥1 วันก่อน = no lookahead)."""
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_d1.json"))), dtype=float)
    dts, dc = d[:, 0], d[:, 4]
    if mode == "sma":
        bias = np.sign(dc - _sma(dc, 50))
    else:                                                  # 20-day momentum (TSMOM)
        bias = np.zeros(len(dc)); bias[20:] = np.sign(dc[20:] - dc[:-20])
    bias = np.nan_to_num(bias)
    idx = np.clip(np.searchsorted(dts, h1_ts - 86400, side="right") - 1, 0, len(dc) - 1)
    return bias[idx]


def _swings(h, l, k=2):
    n = len(h); swl = np.zeros(n, bool); swh = np.zeros(n, bool)
    for i in range(k, n - k):
        if l[i] < l[i - k:i].min() and l[i] < l[i + 1:i + k + 1].min():
            swl[i] = True
        if h[i] > h[i - k:i].max() and h[i] > h[i + 1:i + k + 1].max():
            swh[i] = True
    return swl, swh


def trend_pullback(D, mode="sma", RR=2.0, k=2, COOL=6):
    h, l, c, o, ts = D["h"], D["l"], D["c"], D["o"], D["ts"]
    ema = St.ema(c, 20); atr = R.atr(h, l, c); n = len(c)
    bias = _d1_bias(ts, mode); swl, swh = _swings(h, l, k)
    last_swl = np.full(n, -1, int); last_swh = np.full(n, -1, int); cl = ch = -1
    for i in range(n):                                     # swing ที่ i-k ยืนยันแล้ว ณ บาร์ i
        j = i - k
        if j >= 0 and swl[j]:
            cl = j
        if j >= 0 and swh[j]:
            ch = j
        last_swl[i] = cl; last_swh[i] = ch
    out = []; last = -10 ** 9
    for i in range(60, n - 1):
        if i - last < COOL:
            continue
        b = bias[i]; a = float(atr[i])
        if b == 0 or a <= 0:
            continue
        if b > 0:                                          # เทรนด์ขึ้น → หาจังหวะ pullback+reclaim → long
            if c[i] > ema[i] or c[i] <= h[i - 1]:          # ต้องย่อ (≤EMA) + reclaim (ปิด > high ก่อน)
                continue
            sw = last_swl[i]
            if sw < 0:
                continue
            sl = l[sw] - 0.5 * a; risk = c[i] - sl
            if risk <= 0:
                continue
            out.append({"i": i, "dir": "BUY", "sl_pips": max(1, round(risk / POINT)),
                        "tp_pips": max(1, round(RR * risk / POINT))}); last = i
        else:                                              # เทรนด์ลง → pullback ขึ้น+reject → short
            if c[i] < ema[i] or c[i] >= l[i - 1]:
                continue
            sw = last_swh[i]
            if sw < 0:
                continue
            sl = h[sw] + 0.5 * a; risk = sl - c[i]
            if risk <= 0:
                continue
            out.append({"i": i, "dir": "SELL", "sl_pips": max(1, round(risk / POINT)),
                        "tp_pips": max(1, round(RR * risk / POINT))}); last = i
    return out


ALL = [
    ("Pullback D1-SMA bias RR2", "h1", lambda D: trend_pullback(D, "sma", 2.0)),
    ("Pullback D1-mom bias RR2", "h1", lambda D: trend_pullback(D, "mom", 2.0)),
    ("Pullback D1-SMA bias RR3", "h1", lambda D: trend_pullback(D, "sma", 3.0)),
    ("Pullback D1-SMA bias RR1.5", "h1", lambda D: trend_pullback(D, "sma", 1.5)),
]


def main():
    import strategy_search as SS
    SS.MAX_HOLD = 120                                      # pullback ถือได้นานกว่า (5 วัน H1) ให้ RR ทำงาน
    print("Setup #1 — D1-trend pullback (MAX_HOLD=120 H1 = 5 วัน) เทียบ TSMOM core Sharpe~0.6\n")
    results = [SS.evaluate(name, tf, gen) for (name, tf, gen) in ALL]
    SS.report(results)


if __name__ == "__main__":
    main()
