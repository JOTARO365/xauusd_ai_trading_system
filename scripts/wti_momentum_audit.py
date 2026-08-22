#!/usr/bin/env python
"""scripts/wti_momentum_audit.py — WTI momentum edge audit ด้วย rigor เดียวกับทั้ง session (08-22).

memory [[multi-symbol-live-engine]]: WTI momentum SL×0.7 = edge (t15, period-stable) — แต่ claim นั้น
มาก่อน discipline วันนี้ (drift-null/matched-null). t15 สูงน่าสงสัยเหมือน gold breakout t2.56 (=drift ปลอม).
audit นี้: เอา WTI momentum ผ่าน **matched-random-null** (ชนะสุ่มทิศ+exit เดียวกันไหม) + buy-hold + OOS + quartile.

WTI ต่างจากทอง/BTC: drift ขึ้นถาวรน้อยกว่า (น้ำมัน 2-side) → ถ้า momentum ชนะ null = edge จริงกว่า (ไม่ใช่แค่ ride drift).
data: wti_d1.json (MT5 futures OHLC, 16y). causal · intrabar SL-first · point-agnostic R · cost sensitivity.
read-only · offline · 0 order. รัน: python scripts/wti_momentum_audit.py
"""
import json
import math
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import regime_lib as R                                        # noqa: E402

BRK = 20            # Donchian breakout window (D1)
SL_ATR = 0.7        # validated config (memory: WTI SL×0.7)
RR = 2.0
MAX_HOLD = 120
MIN_N = 100


def _load():
    d = json.load(open(os.path.join(_BASE, "data", "wti_d1.json")))
    return (np.array([x[2] for x in d], float), np.array([x[3] for x in d], float),
            np.array([x[4] for x in d], float))


def _atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(len(c), np.nan)
    if len(tr) >= n:
        a = np.convolve(tr, np.ones(n) / n, "valid")
        out[n:] = a[:len(out) - n]
    return out


def _sim(entry_i, d, entry, sl, tp, h, l, c):
    """intrabar SL-first, R = ผล/risk (point-agnostic)."""
    risk = abs(entry - sl); end = min(entry_i + MAX_HOLD, len(c) - 1)
    for j in range(entry_i + 1, end + 1):
        hit_sl = l[j] <= sl if d > 0 else h[j] >= sl
        hit_tp = h[j] >= tp if d > 0 else l[j] <= tp
        if hit_sl:
            return -1.0
        if hit_tp:
            return d * (tp - entry) / risk
    return d * (c[end] - entry) / risk


def run(h, l, c, atr, cost_r=0.0, force=None, seed=0):
    """momentum_breakout Donchian(BRK) both-dir, SL 0.7ATR, RR2. force: None=signal · 'rand'=สุ่มทิศ.
    cost_r = cost เป็นสัดส่วน R (spread/sl_dist). คืน (R array, idx)."""
    n = len(c); trades = []; idx = []; rng = np.random.default_rng(seed)
    i = BRK + 20
    while i < n - 1:
        av = atr[i]
        if not (av == av) or av <= 0:
            i += 1; continue
        hh = h[i - BRK:i].max(); ll = l[i - BRK:i].min()
        d = 1 if c[i] > hh else (-1 if c[i] < ll else 0)
        if d == 0:
            i += 1; continue
        if force == "rand":
            d = rng.choice([-1, 1])
        px = c[i]; sl_dist = SL_ATR * av
        sl = px - d * sl_dist; tp = px + d * RR * sl_dist
        r = _sim(i, d, px, sl, tp, h, l, c) - cost_r
        trades.append(r); idx.append(i)
        i += 1                                               # non-overlap ผ่อน (momentum ยิงต่อเนื่องได้ — เหมือน live)
    return np.array(trades), np.array(idx)


def _stat(a):
    n = len(a)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    sd = a.std(ddof=1); t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t


def main():
    h, l, c = _load(); atr = _atr(h, l, c); nbars = len(c)
    # cost: WTI spread ~ 3-5 cents; sl_dist ~ 0.7×ATR(D1) ~ $1-2 → cost_r ~ 0.03-0.05
    cost_r = 0.04
    print(f"=== WTI MOMENTUM AUDIT (D1 Donchian{BRK} SL×{SL_ATR}ATR RR{RR} · matched-null · 16y · cost_r{cost_r}) ===")
    print(f"bars={nbars} · คำถาม: WTI momentum ชนะ matched-random-null ไหม (edge จริง ≠ drift/artifact)\n")
    a, idx = run(h, l, c, atr, cost_r=cost_r)
    n, wr, ex, t = _stat(a)
    k = int(n * 0.7); oos = _stat(a[k:])[2]
    # per-quartile
    q = [[], [], [], []]
    for ii, rr in zip(idx, a):
        q[min(3, int(ii / nbars * 4))].append(rr)
    qs = [f"{np.mean(x):+.2f}" if len(x) >= 2 else "-" for x in q]
    npos = sum(1 for x in q if len(x) >= 2 and np.mean(x) > 0)
    # buy/sell legs
    bl = np.array([r for r, ii in zip(a, idx) if (h[ii - BRK:ii].max() < c[ii])])
    print(f"  WTI momentum      n{n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} OOS{oos:+.4f} "
          f"Q{qs} [{'stable' if npos>=3 else '%d/4'%npos}]")
    # matched-null: random direction, same breakout bars + exit + cost
    nexp = []
    for s in range(300):
        ar, _ = run(h, l, c, atr, cost_r=cost_r, force="rand", seed=1000 + s)
        nexp.append(ar.mean() if len(ar) else 0.0)
    nexp = np.array(nexp); p = float((nexp >= ex).mean())
    print(f"  null(random-dir)  exp_R mean{nexp.mean():+.4f} sd{nexp.std():.4f} 95p{np.percentile(nexp,95):+.4f}")
    print(f"  >>> WTI vs matched-random: p={p:.3f}  {'EDGE จริง (ชนะสุ่มทิศ)' if p<0.05 else 'ไม่ชนะสุ่ม = drift/artifact'}")
    # buy-hold benchmark (daily)
    dr = np.diff(c) / c[:-1]
    _, _, bh_mean, bh_t = _stat(dr)
    print(f"  buy-hold(daily)   mean{bh_mean*100:+.4f}%/วัน t{bh_t:+.2f} (drift benchmark — WTI ควร drift น้อย)")
    # cost sensitivity
    for cx in (0.0, 0.08):
        a2, _ = run(h, l, c, atr, cost_r=cx)
        print(f"  cost_r={cx}: exp_R{_stat(a2)[2]:+.4f} t{_stat(a2)[3]:+.2f}")
    print("\nPASS = n≥100 + exp_R>0 + t>2 + OOS>0 + p<0.05 + stable≥3/4 + ทน cost×2")
    print("ถ้า p≥0.05 = WTI 'edge' เป็น drift/artifact เหมือน gold breakout (t15 หลอก) → ไม่ push")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
