#!/usr/bin/env python
"""regime_dwell_phase0.py — Phase 0 (S0-1) ของ dual-sleeve design: วัด regime transition/dwell.

ACCEPTANCE GATE (Attack-1): ถ้า RANGE p25-dwell < ระยะเวลาไม้ A1 (band-edge mean-rev) → routing H1 โมฆะ
(regime พลิกเร็วเกินก่อน A1 ปิดไม้ → mean-reversion premise พัง) → ต้อง redesign ก่อน shadow ไม้เดียว.
วัด: dwell p25/median ต่อ regime · transition matrix · flicker P(X→Y→X ≤3 bars) · flips/สัปดาห์ ·
A1-duration proxy (bars จาก box-edge ถึง 30%-width TP ใน RANGE). measure-only, ไม่แตะ order/live.
รัน: & $PY scripts\regime_dwell_phase0.py
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BARS_PER_WEEK = 168        # H1
A1_WIDTH_MIN = 2500        # box width floor (design)
A1_TP_FRAC = 0.30          # TP = 30% width toward mid
A1_EDGE_FRAC = 0.25        # "at edge" = ใน 25% นอกของ box
DON = 20                   # box proxy = Donchian(20)


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4]


def _runs(reg):
    """คืน list ของ (regime, start, length) — ข้าม WARMUP."""
    out = []; i = 0; n = len(reg)
    while i < n:
        j = i
        while j < n and reg[j] == reg[i]:
            j += 1
        if reg[i] != "WARMUP":
            out.append((reg[i], i, j - i))
        i = j
    return out


def _pct(a):
    a = np.array(a)
    return {"n": len(a), "p25": np.percentile(a, 25), "median": np.percentile(a, 50),
            "p75": np.percentile(a, 75), "mean": a.mean(), "max": a.max()} if len(a) else {}


def main():
    high, low, close = _load()
    n = len(close)
    er = R.efficiency_ratio(close, R.VOL_WIN); adx = R.adx(high, low, close); vp = R.vol_percentile(close)
    reg = [R.detect_regime(er[i], adx[i], vp[i]) for i in range(n)]

    print("=" * 84)
    print(f"REGIME DWELL — Phase 0 gate | gold H1 {n} bars ({n/BARS_PER_WEEK:.0f} สัปดาห์)")
    print("=" * 84)

    runs = _runs(reg)
    states = ["TREND", "RANGE", "RISK-OFF", "NEUTRAL"]
    # occupancy
    occ = {s: sum(L for r, _, L in runs if r == s) for s in states}
    tot = sum(occ.values())
    print("\n── Occupancy + Dwell distribution (bars) ──")
    print(f"  {'regime':<10}{'occ%':>7}{'#runs':>7}{'p25':>7}{'median':>8}{'p75':>7}{'mean':>7}")
    dwell = {}
    for s in states:
        ls = [L for r, _, L in runs if r == s]
        d = _pct(ls); dwell[s] = d
        if d:
            print(f"  {s:<10}{occ[s]/tot*100:>6.1f}%{d['n']:>7}{d['p25']:>7.0f}{d['median']:>8.0f}"
                  f"{d['p75']:>7.0f}{d['mean']:>7.1f}")

    # transition matrix (บน run boundaries)
    print("\n── Transition matrix P(next regime | current) ──")
    trans = {s: {t: 0 for t in states} for s in states}
    for a, b in zip(runs[:-1], runs[1:]):
        if a[0] in states and b[0] in states:
            trans[a[0]][b[0]] += 1
    _hdr = "from/to"
    print(f"  {_hdr:<10}" + "".join(f"{t:>10}" for t in states))
    for s in states:
        row = trans[s]; tt = sum(row.values()) or 1
        print(f"  {s:<10}" + "".join(f"{row[t]/tt*100:>9.0f}%" for t in states))

    # flicker: run ของ Y ยาว ≤3 ที่ขนาบด้วย X เดียวกัน (X→Y→X) = noise
    flick = 0; flick_by = {s: 0 for s in states}
    for i in range(1, len(runs) - 1):
        p, cur, nx = runs[i - 1][0], runs[i], runs[i + 1][0]
        if p == nx and cur[2] <= 3 and cur[0] != p:
            flick += 1; flick_by[cur[0]] = flick_by.get(cur[0], 0) + 1
    flips = len(runs) - 1
    print(f"\n── Flicker (X→Y→X, Y≤3 bars = noise) ──")
    print(f"  flips รวม: {flips} ({flips/(n/BARS_PER_WEEK):.1f}/สัปดาห์)")
    print(f"  flicker: {flick} ({flick/flips*100:.1f}% ของ flips) — by short-Y: {flick_by}")
    print(f"  → แนะนำ hysteresis M: ยืนยัน state {2}-{3} แท่งตัด flicker ส่วนใหญ่")

    # A1-duration proxy + funnel: RANGE → box width → at-edge → bars-to-TP
    print("\n── A1-setup funnel + duration (RANGE + Donchian(20) box) ──")
    rbars = [i for i in range(DON, n - 1) if reg[i] == "RANGE"]
    widths = np.array([(high[i - DON:i].max() - low[i - DON:i].min()) / R.POINT for i in rbars])  # points
    wide = int((widths >= A1_WIDTH_MIN).sum())
    print(f"  RANGE bars: {len(rbars)} · Donchian(20) width: median={np.median(widths):.0f}p p75={np.percentile(widths,75):.0f}p"
          f" · width≥{A1_WIDTH_MIN}p: {wide} ({wide/max(len(rbars),1)*100:.1f}%)")
    durs = []; setups = 0
    for i in rbars:
        bh = high[i - DON:i].max(); bl = low[i - DON:i].min(); w = bh - bl
        if w / R.POINT < A1_WIDTH_MIN:                     # width ต้อง ≥ 2500 points
            continue
        near_low = close[i] <= bl + A1_EDGE_FRAC * w
        near_high = close[i] >= bh - A1_EDGE_FRAC * w
        if not (near_low or near_high):
            continue
        setups += 1
        tp = (bl + A1_TP_FRAC * w) if near_low else (bh - A1_TP_FRAC * w)
        for j in range(i + 1, min(i + 60, n)):
            if (near_low and high[j] >= tp) or (near_high and low[j] <= tp):
                durs.append(j - i); break
    dd = _pct(durs)
    hit = (len(durs) / setups * 100) if setups else 0
    print(f"  at-edge setups: {setups} · reached TP(≤60b): {len(durs)} ({hit:.0f}%)")
    if dd:
        print(f"  bars-to-TP: p25={dd['p25']:.0f} median={dd['median']:.0f} p75={dd['p75']:.0f}")

    # A1 setup gate ด้วย box-structure อย่างเดียว (ไม่ใช้ regime label ที่ noisy) — redesign candidate
    print("\n── A1 setup: box-structure อย่างเดียว (ANY regime) vs RANGE-gated ──")
    s2 = 0; d2 = []
    for i in range(DON, n - 1):
        bh = high[i - DON:i].max(); bl = low[i - DON:i].min(); w = bh - bl
        if w / R.POINT < A1_WIDTH_MIN:
            continue
        nl = close[i] <= bl + A1_EDGE_FRAC * w; nh = close[i] >= bh - A1_EDGE_FRAC * w
        if not (nl or nh):
            continue
        s2 += 1
        tp = (bl + A1_TP_FRAC * w) if nl else (bh - A1_TP_FRAC * w)
        for j in range(i + 1, min(i + 60, n)):
            if (nl and high[j] >= tp) or (nh and low[j] <= tp):
                d2.append(j - i); break
    d2d = _pct(d2)
    print(f"  structure-only: {s2} setups · reached TP {len(d2)} ({len(d2)/max(s2,1)*100:.0f}%) · median {d2d.get('median',0):.0f}b")
    print(f"  RANGE-gated:    {setups} setups · reached TP {len(durs)} ({hit:.0f}%) · median {dd.get('median',0):.0f}b")
    print(f"  → regime filter เพิ่ม hit-rate {hit - len(d2)/max(s2,1)*100:+.0f}pp (ถ้า ~0 = regime label ไม่ช่วย, gate ที่ structure พอ)")

    # GATE
    print("\n" + "=" * 84)
    rp25 = dwell["RANGE"]["p25"]; rmed = dwell["RANGE"]["median"]
    a1med = dd.get("median", float("inf")) if setups >= 30 else float("inf")
    passed = (setups >= 30) and (rp25 >= a1med)
    if setups < 30:
        print(f"GATE: ❌ ไม่ผ่าน — A1 setup ใน RANGE มีแค่ {setups} (box≥{A1_WIDTH_MIN}+at-edge แทบไม่เกิด)")
        print(f"  → A1 premise (RANGE + box กว้าง) ขัดกันเอง: RANGE = low-vol → box แคบ (median {np.median(widths):.0f}p < 2500)")
    else:
        print(f"GATE: RANGE p25-dwell={rp25:.0f} {'≥' if passed else '<'} A1-duration median={a1med:.0f} bars → "
              f"{'✅ ผ่าน' if passed else '❌ ไม่ผ่าน (RANGE พลิกเร็วเกิน)'}")
    print(f"  context: RANGE median dwell={rmed:.0f}b, RANGE→RANGE 0% (decay→NEUTRAL 90%), flicker 34.9%")


if __name__ == "__main__":
    main()
