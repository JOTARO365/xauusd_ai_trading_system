#!/usr/bin/env python
"""cluster_kde_research.py — เทียบ KDE (density-based) vs histogram (fixed-bin) ในการจำแนกโซน S/R.

⚠️ OFFLINE research (ไม่แตะ live). พิสูจน์ก่อน "KDE จำแนกโซนดีกว่าจริงไหม" ด้วย **OOS forward-reaction test
+ null baseline** (ตาม gauntlet เดิม) — ไม่ใช่แค่ดูภาพสวย.

metric: detect zones บน lookback [t-L:t] → forward [t:t+H] เช็คว่าราคา (ก) แตะโซน (coverage) (ข) **bounce**
(react ≥ R·ATR ภายใน K แท่ง). เทียบ KDE vs histogram vs random-levels (null). โซนดี = bounce-rate สูงกว่า null.

รัน: & $PY scripts\cluster_kde_research.py
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LOOKBACK = 300      # แท่งที่ใช้ detect zones
FWD      = 120      # forward window ทดสอบ reaction
BOUNCE_K = 12       # ต้อง bounce ภายใน K แท่งหลังแตะ
BOUNCE_R = 0.8      # bounce ≥ 0.8·ATR = react จริง
MIN_TOUCH = 6
HIST_BW_ATR = 0.25  # histogram bin width = 0.25·ATR (= cluster_map ปัจจุบัน)


def _load():
    d = json.load(open(os.path.join(_BASE, "data", "xau_h1.json")))
    a = np.array(d, dtype=float)               # [t,o,h,l,c,vol]
    return a[:, 2], a[:, 3], a[:, 4], a[:, 5]  # high, low, close, vol


def histogram_zones(high, low, close, vol, atr):
    """cluster_map ปัจจุบัน: bin 0.25·ATR, นับ close, เก็บ bin ที่ touch ≥ MIN_TOUCH."""
    bw = HIST_BW_ATR * atr
    lo = close.min()
    counts = {}
    for px in close:
        b = int((px - lo) / bw)
        counts[b] = counts.get(b, 0) + 1
    return sorted(lo + (b + 0.5) * bw for b, c in counts.items() if c >= MIN_TOUCH)


def kde_zones(high, low, close, vol, atr):
    """KDE density-based: weight ด้วย tick-volume, bandwidth ~0.25·ATR, peak = โซน (auto จำนวน)."""
    if close.std() == 0 or atr <= 0:
        return []
    kde = gaussian_kde(close, weights=vol)
    kde.set_bandwidth((HIST_BW_ATR * atr) / close.std())   # bandwidth ≈ 0.25·ATR
    grid = np.linspace(close.min(), close.max(), 500)
    dens = kde(grid)
    idx = argrelextrema(dens, np.greater, order=5)[0]      # local maxima
    peaks = [(grid[i], dens[i]) for i in idx if dens[i] >= 0.20 * dens.max()]  # prominence filter
    return sorted(p for p, _ in peaks)


def _reaction(zones, high, low, close, atr, band):
    """forward: วัด **directional respect vs break** (discriminate โซนจริงจากสุ่ม).
    support test (ราคาลงมาจากบน): respect = เด้งขึ้น ≥R·ATR ก่อนปิดหลุดล่าง · break = ปิดหลุด >band.
    resistance test (ขึ้นมาจากล่าง): กลับกัน. คืน (n_zones, respects, breaks)."""
    n_z = len(zones); respects = 0; breaks = 0
    for z in zones:
        hit = None
        for j in range(1, len(close)):
            if low[j] <= z + band and high[j] >= z - band:    # แตะโซน
                hit = j; break
        if hit is None:
            continue
        from_above = close[hit - 1] > z                        # approach จากบน = test support
        seg_hi = high[hit:hit + BOUNCE_K]; seg_lo = low[hit:hit + BOUNCE_K]
        seg_c = close[hit:hit + BOUNCE_K]
        if len(seg_hi) == 0:
            continue
        if from_above:                                         # SUPPORT test
            broke = np.any(seg_c < z - band)                   # ปิดหลุดล่าง = break
            bounced = seg_hi.max() >= z + BOUNCE_R * atr       # เด้งขึ้น = respect
        else:                                                  # RESISTANCE test
            broke = np.any(seg_c > z + band)
            bounced = seg_lo.min() <= z - BOUNCE_R * atr
        if bounced and not broke:
            respects += 1
        elif broke:
            breaks += 1
    return n_z, respects, breaks


def evaluate(high, low, close, vol, method_fn, n_anchors=300, seed=0):
    """rolling OOS: สุ่ม anchors → detect zones บน lookback → วัด reaction บน forward. + null (random levels)."""
    rng = np.random.RandomState(seed)
    atr_a = R.atr(high, low, close)
    n = len(close)
    anchors = rng.randint(LOOKBACK, n - FWD, size=n_anchors)
    Z = Re = Br = 0; nRe = nBr = 0
    for t in anchors:
        atr = float(atr_a[t])
        if not np.isfinite(atr) or atr <= 0:
            continue
        win = slice(t - LOOKBACK, t)
        zones = method_fn(high[win], low[win], close[win], vol[win], atr)
        if not zones:
            continue
        band = HIST_BW_ATR * atr
        fh, fl, fc = high[t:t + FWD], low[t:t + FWD], close[t:t + FWD]
        z, re, br = _reaction(zones, fh, fl, fc, atr, band)
        Z += z; Re += re; Br += br
        rlo, rhi = close[win].min(), close[win].max()            # null: โซนสุ่มจำนวนเท่ากัน
        rnd = sorted(rng.uniform(rlo, rhi, size=len(zones)))
        _, re2, br2 = _reaction(rnd, fh, fl, fc, atr, band)
        nRe += re2; nBr += br2
    respect = Re / (Re + Br) if (Re + Br) else 0                 # respect เมื่อถูก test (respect vs break)
    null_r = nRe / (nRe + nBr) if (nRe + nBr) else 0
    return {
        "zones/anchor": round(Z / n_anchors, 2),
        "tested": Re + Br,                                       # จำนวน test ที่ชี้ขาด (respect หรือ break)
        "respect_rate": round(respect, 3),                      # คุณภาพโซน: react ถูกทางก่อนทะลุ
        "null_respect": round(null_r, 3),                       # โซนสุ่ม (baseline)
        "edge_vs_null": round(respect - null_r, 3),             # โซนดีกว่าสุ่มแค่ไหน (ต้อง > 0 ชัด)
    }


def main():
    print("โหลด xau_h1 (70k H1 bars)...")
    high, low, close, vol = _load()
    print(f"bars={len(close)}  price {close.min():.0f}–{close.max():.0f}\n")
    print(f"{'method':>12} | {'zones/anc':>9} {'tested':>7} {'respect%':>8} | {'null%':>7} {'edge':>8}")
    print("-" * 62)
    for name, fn in (("histogram", histogram_zones), ("KDE", kde_zones)):
        r = evaluate(high, low, close, vol, fn)
        print(f"{name:>12} | {r['zones/anchor']:>9} {r['tested']:>7} {r['respect_rate']*100:>7.1f}% | "
              f"{r['null_respect']*100:>6.1f}% {r['edge_vs_null']*100:>+7.1f}%")
    print("\nrespect% = ถูก test แล้ว react ถูกทาง (เด้ง) ก่อนทะลุ · edge = respect% − null(random level)")
    print("KDE ชนะ = respect% สูงกว่า histogram + edge > 0 ชัด. edge ≈ 0 = โซนไม่ต่างจากสุ่ม (สอดคล้อง finding เดิม)")


if __name__ == "__main__":
    main()
