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


def _zone_touches(z, high, low, band):
    """ความแข็งโซน = จำนวนแท่งใน lookback ที่แตะโซน (±band)."""
    return int(np.count_nonzero((low <= z + band) & (high >= z - band)))


def _zone_outcome(z, fh, fl, fc, atr, band):
    """forward: 'respect' (react ถูกทางก่อนทะลุ) / 'break' (ปิดทะลุ) / None (ไม่ถูก test/ไม่ชี้ขาด)."""
    hit = None
    for j in range(1, len(fc)):
        if fl[j] <= z + band and fh[j] >= z - band:
            hit = j; break
    if hit is None:
        return None
    from_above = fc[hit - 1] > z                                # ลงมาจากบน = test support
    seg_hi = fh[hit:hit + BOUNCE_K]; seg_lo = fl[hit:hit + BOUNCE_K]; seg_c = fc[hit:hit + BOUNCE_K]
    if len(seg_hi) == 0:
        return None
    if from_above:
        broke = bool(np.any(seg_c < z - band)); bounced = seg_hi.max() >= z + BOUNCE_R * atr
    else:
        broke = bool(np.any(seg_c > z + band)); bounced = seg_lo.min() <= z - BOUNCE_R * atr
    return "respect" if (bounced and not broke) else ("break" if broke else None)


_BUCKETS = [(6, 9, "6-9 อ่อน"), (10, 15, "10-15 กลาง"), (16, 25, "16-25 แข็ง"), (26, 9999, "26+ แข็งมาก")]


def evaluate(high, low, close, vol, method_fn, n_anchors=400, seed=0):
    """rolling OOS: detect zones → **stratify ตาม touches** → respect% ต่อ bucket + null."""
    rng = np.random.RandomState(seed)
    atr_a = R.atr(high, low, close)
    n = len(close)
    anchors = rng.randint(LOOKBACK, n - FWD, size=n_anchors)
    rec = {b[2]: [0, 0] for b in _BUCKETS}          # label → [respect, break]
    nrec = {b[2]: [0, 0] for b in _BUCKETS}

    def _bucket(tch):
        for lo, hi, lab in _BUCKETS:
            if lo <= tch <= hi:
                return lab
        return None

    for t in anchors:
        atr = float(atr_a[t])
        if not np.isfinite(atr) or atr <= 0:
            continue
        win = slice(t - LOOKBACK, t)
        hw, lw, cw, vw = high[win], low[win], close[win], vol[win]
        zones = method_fn(hw, lw, cw, vw, atr)
        if not zones:
            continue
        band = HIST_BW_ATR * atr
        fh, fl, fc = high[t:t + FWD], low[t:t + FWD], close[t:t + FWD]
        rlo, rhi = cw.min(), cw.max()
        for z in zones:
            lab = _bucket(_zone_touches(z, hw, lw, band))
            if lab:
                o = _zone_outcome(z, fh, fl, fc, atr, band)
                if o == "respect": rec[lab][0] += 1
                elif o == "break": rec[lab][1] += 1
            zr = sorted(rng.uniform(rlo, rhi, 1))[0]              # null: 1 random level/zone, bucket by touches
            lab2 = _bucket(_zone_touches(zr, hw, lw, band))
            if lab2:
                o2 = _zone_outcome(zr, fh, fl, fc, atr, band)
                if o2 == "respect": nrec[lab2][0] += 1
                elif o2 == "break": nrec[lab2][1] += 1
    return rec, nrec


def main():
    print("โหลด xau_h1 (70k H1 bars)...")
    high, low, close, vol = _load()
    print(f"bars={len(close)}\n")
    for name, fn in (("histogram", histogram_zones), ("KDE", kde_zones)):
        rec, nrec = evaluate(high, low, close, vol, fn)
        print(f"=== {name} — respect% แยกตามความแข็งโซน (touches) ===")
        print(f"  {'bucket':>14} | {'tested':>6} {'respect%':>8} | {'null%':>6} {'edge':>7}  (breakeven fade RR1=50%)")
        for _lo, _hi, lab in _BUCKETS:
            re, br = rec[lab]; nr, nb = nrec[lab]
            tot = re + br; ntot = nr + nb
            rr = re / tot if tot else 0; nn = nr / ntot if ntot else 0
            flag = " ← > breakeven!" if rr > 0.50 and tot >= 30 else ""
            print(f"  {lab:>14} | {tot:>6} {rr*100:>7.1f}% | {nn*100:>5.1f}% {(rr-nn)*100:>+6.1f}%{flag}")
        print()
    print("อ่าน: ถ้า respect% เพิ่มตามความแข็ง + bucket แข็ง>50% (RR1) = โซนแข็งมี edge fade ได้ (validate _weak veto)")
    print("ถ้าแบนทุก bucket ~39% = ความแข็งไม่ทำนาย respect → ทองไม่มี mechanical S/R edge (จบเรื่อง fade)")


if __name__ == "__main__":
    main()
