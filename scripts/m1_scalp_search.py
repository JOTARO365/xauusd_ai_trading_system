#!/usr/bin/env python
"""scripts/m1_scalp_search.py — M1 scalp algo search (user 08-22, /loop + fable).

โจทย์ user: scalp M1, SL 300 pts, TP สั้น, เข้าบ่อย, t สูง, ไม่มีข้อบกพร่อง.
โครงสร้าง: TP<SL → breakeven WR สูง (SL300/TP100 → >82% หลัง spread 28pt) → ต้อง mean-reversion แรงจริง.
M1 microstructure (bid-ask bounce) mean-revert = จุดที่มีโอกาส (swing direction พิสูจน์แล้วไม่มี edge).

gate (บทเรียน gold+BTC วันนี้ — เข้มตั้งแต่แรก):
  n≥300 · exp_R>0 · t>2 · OOS(30%)>0 · **matched-random null p<0.05** (signal ชนะสุ่มที่ side-dist เท่ากัน) ·
  **drop-best-k robust** (ตัด top-1% ไม้ยัง exp_R>0) · per-third stable (บวก ≥2/3)
cost 28pt/trade (spread จริง) · SL-first intrabar (pessimistic) · non-overlap · causal.
data/xau_m1.json (90k bars, 3mo). read-only · offline · 0 order.
รัน: python scripts/m1_scalp_search.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(_ROOT, "data", "xau_m1.json")
POINT = 0.01
SL_PTS = 300.0
COST_PTS = float(os.environ.get("SCALP_COST", "28"))
MAX_HOLD = 120                                               # M1 bars = 2 ชม. เต็มที่ต่อ scalp
MIN_N = 300


def _load():
    d = json.load(open(DATA))
    o = np.array([x[1] for x in d], float); h = np.array([x[2] for x in d], float)
    l = np.array([x[3] for x in d], float); c = np.array([x[4] for x in d], float)
    return o, h, l, c


def _sma(x, n):
    cs = np.cumsum(np.insert(x, 0, 0.0))
    out = np.full(len(x), np.nan)
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def _rstd(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = x[i - n + 1:i + 1].std()
    return out


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = -np.clip(d, None, 0)
    au = np.full(len(c), np.nan); ad = np.full(len(c), np.nan)
    au[n] = up[1:n + 1].mean(); ad[n] = dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    rs = au / np.where(ad == 0, np.nan, ad)
    return 100 - 100 / (1 + rs)


def _signals(name, o, h, l, c, **p):
    """คืน array side[i] ∈ {-1,0,+1} (fade = สวน). causal (ใช้ถึง i)."""
    n = len(c); side = np.zeros(n)
    if name == "zscore":
        w = p["n"]; thr = p["thr"]; m = _sma(c, w); sd = _rstd(c, w)
        z = (c - m) / np.where(sd == 0, np.nan, sd)
        side = np.where(z >= thr, -1.0, np.where(z <= -thr, 1.0, 0.0))
    elif name == "rsi":
        r = _rsi(c, p["n"]); side = np.where(r >= p["hi"], -1.0, np.where(r <= p["lo"], 1.0, 0.0))
    elif name == "consec":
        k = p["k"]; up = c > np.roll(c, 1)
        runs_up = np.zeros(n); runs_dn = np.zeros(n)
        for i in range(1, n):
            runs_up[i] = runs_up[i - 1] + 1 if up[i] else 0
            runs_dn[i] = runs_dn[i - 1] + 1 if (not up[i]) else 0
        side = np.where(runs_up >= k, -1.0, np.where(runs_dn >= k, 1.0, 0.0))
    elif name == "rangespike":
        w = p["n"]; mv = c - o
        tr = h - l; atr = _sma(tr, w)
        side = np.where(mv >= p["k"] * atr, -1.0, np.where(mv <= -p["k"] * atr, 1.0, 0.0))
    elif name == "confluence":                              # N-bar extreme + RSI extreme (fade แรง)
        w = p["n"]; m = _sma(c, w); sd = _rstd(c, w)
        z = (c - m) / np.where(sd == 0, np.nan, sd); r = _rsi(c, 14)
        side = np.where((z >= p["thr"]) & (r >= p["hi"]), -1.0,
                        np.where((z <= -p["thr"]) & (r <= p["lo"]), 1.0, 0.0))
    elif name == "squeeze":                                 # vol contraction → breakout follow
        w = p["n"]; sd = _rstd(c, w)
        sd_lo = np.full(len(c), np.nan)
        for i in range(300, len(c)):                        # sd percentile ต่ำ (บีบตัว)
            sd_lo[i] = sd[i] <= np.nanpercentile(sd[i - 300:i], 25)
        hi = np.full(len(c), np.nan); lo = np.full(len(c), np.nan)
        for i in range(w, len(c)):
            hi[i] = h[i - w:i].max(); lo[i] = l[i - w:i].min()
        brk_up = (c > hi) & (sd_lo == 1); brk_dn = (c < lo) & (sd_lo == 1)
        side = np.where(brk_up, 1.0, np.where(brk_dn, -1.0, 0.0))   # follow breakout
    return side


def _simulate(side, o, h, l, c, tp_pts, warm):
    """SL-first, non-overlap, entry=close[i]. คืน (list R, list entry_index)."""
    n = len(c); trades = []; idx = []
    i = warm
    while i < n - 1:
        s = side[i]
        if s == 0:
            i += 1; continue
        px = c[i]
        sl = px - s * SL_PTS * POINT
        tp = px + s * tp_pts * POINT
        end = min(i + MAX_HOLD, n - 1); r = None; ex = end
        for j in range(i + 1, end + 1):
            hit_sl = (l[j] <= sl) if s > 0 else (h[j] >= sl)
            hit_tp = (h[j] >= tp) if s > 0 else (l[j] <= tp)
            if hit_sl:                                        # SL-first pessimistic
                r, ex = -1.0 - COST_PTS / SL_PTS, j; break
            if hit_tp:
                r, ex = tp_pts / SL_PTS - COST_PTS / SL_PTS, j; break
        if r is None:
            r = s * (c[end] - px) / (SL_PTS * POINT) - COST_PTS / SL_PTS
        trades.append(r); idx.append(i); i = ex + 1
    return np.array(trades), np.array(idx)


def _stat(a):
    n = len(a)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    sd = a.std(ddof=1)
    t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t


def _matched_null(side, o, h, l, c, tp_pts, warm, n_real, pos_frac, neg_frac, sims=400):
    """สุ่ม entry ที่ side-distribution เท่า signal (คุม direction bias) + exit เดียวกัน → p ของ exp_R."""
    n = len(c); rng = np.random.default_rng(4242)
    cand = np.arange(warm, n - 1)
    exps = np.empty(sims)
    k = min(n_real, len(cand))
    for s_ in range(sims):
        pick = rng.choice(cand, size=k, replace=False)
        rs = rng.random(k)
        sides = np.where(rs < pos_frac, 1.0, np.where(rs < pos_frac + neg_frac, -1.0, 0.0))
        rr = []
        for ii, sd_ in zip(pick, sides):
            if sd_ == 0:
                continue
            px = c[ii]; sl = px - sd_ * SL_PTS * POINT; tp = px + sd_ * tp_pts * POINT
            end = min(ii + MAX_HOLD, n - 1); r = None
            for j in range(ii + 1, end + 1):
                hit_sl = (l[j] <= sl) if sd_ > 0 else (h[j] >= sl)
                hit_tp = (h[j] >= tp) if sd_ > 0 else (l[j] <= tp)
                if hit_sl:
                    r = -1.0 - COST_PTS / SL_PTS; break
                if hit_tp:
                    r = tp_pts / SL_PTS - COST_PTS / SL_PTS; break
            if r is None:
                r = sd_ * (c[end] - px) / (SL_PTS * POINT) - COST_PTS / SL_PTS
            rr.append(r)
        exps[s_] = np.mean(rr) if rr else 0.0
    return exps


def evaluate(name, o, h, l, c, warm, tp_pts, **p):
    side = _signals(name, o, h, l, c, **p)
    if os.environ.get("SCALP_FOLLOW") == "1":                # momentum: follow แทน fade (invert)
        side = -side
    a, idx = _simulate(side, o, h, l, c, tp_pts, warm)
    n, wr, ex, t = _stat(a)
    if n < 10:
        return None
    k = int(n * 0.7); oos = _stat(a[k:])[2]
    # drop-best-1%
    kk = max(1, n // 100); asort = np.sort(a); ex_drop = float(asort[:-kk].mean())
    # per-third stability
    th = n // 3
    thirds = [_stat(a[:th])[2], _stat(a[th:2 * th])[2], _stat(a[2 * th:])[2]]
    npos = sum(1 for x in thirds if x > 0)
    # matched-null
    pos_frac = float((side[warm:] > 0).mean()); neg_frac = float((side[warm:] < 0).mean())
    null = _matched_null(side, o, h, l, c, tp_pts, warm, n, pos_frac, neg_frac)
    p_val = float((null >= ex).mean())
    return dict(name=name, params=p, tp=tp_pts, n=n, wr=wr, ex=ex, t=t, oos=oos,
                ex_drop=ex_drop, thirds=thirds, npos=npos, pval=p_val, null_mean=float(null.mean()))


def _passes(r):
    return (r and r["n"] >= MIN_N and r["ex"] > 0 and r["t"] > 2 and r["oos"] > 0
            and r["pval"] < 0.05 and r["ex_drop"] > 0 and r["npos"] >= 2)


def main():
    o, h, l, c = _load()
    warm = 260
    print(f"=== M1 SCALP SEARCH (XAU · SL{SL_PTS:.0f} · cost{COST_PTS:.0f}pt · SL-first · bars={len(c)} 3mo) ===")
    print(f"PASS = n≥{MIN_N} + exp_R>0 + t>2 + OOS>0 + matched-null p<0.05 + drop-best-1%>0 + stable≥2/3")
    print("cost/trade = 28/300 = 0.093R · breakeven WR สูง (TP<SL) · matched-null = ชนะสุ่มที่ side-dist เท่ากันไหม\n")
    GRID = []
    for tp in (75, 100, 150, 200):
        for n in (30, 60, 120):
            for thr in (2.0, 2.5, 3.0):
                GRID.append(("zscore", dict(n=n, thr=thr), tp))
        for rn in (7, 14):
            for lohi in ((15, 85), (10, 90), (5, 95)):
                GRID.append(("rsi", dict(n=rn, lo=lohi[0], hi=lohi[1]), tp))
        for k in (4, 6, 8):
            GRID.append(("consec", dict(k=k), tp))
        for n in (30, 60):
            for kk in (2.0, 3.0):
                GRID.append(("rangespike", dict(n=n, k=kk), tp))
        for n in (30, 60):
            for thr in (2.0, 2.5):
                GRID.append(("confluence", dict(n=n, thr=thr, lo=20, hi=80), tp))
        for n in (20, 40):
            GRID.append(("squeeze", dict(n=n), tp))
    print(f"testing {len(GRID)} configs (multiple-testing — track for correction)\n")
    rows = []
    for name, p, tp in GRID:
        r = evaluate(name, o, h, l, c, warm, tp, **p)
        if r:
            rows.append(r)
    rows.sort(key=lambda r: -r["t"])
    print("TOP 15 by t-stat:")
    for r in rows[:15]:
        fl = "PASS" if _passes(r) else "—"
        ps = ",".join(f"{k}{v}" for k, v in r["params"].items())
        print(f"  {r['name']:10s} {ps:16s} TP{r['tp']:3d} n{r['n']:5d} WR{r['wr']:5.1f}% "
              f"exp_R{r['ex']:+.4f} t{r['t']:+.2f} OOS{r['oos']:+.4f} drop1%{r['ex_drop']:+.4f} "
              f"p{r['pval']:.3f} 3rd{r['npos']}/3 [{fl}]")
    passes = [r for r in rows if _passes(r)]
    print(f"\n{'='*60}\nPASS count: {len(passes)} / {len(rows)} configs")
    if passes:
        print("PASS configs (survive full gate):")
        for r in passes:
            print(f"  {r['name']} {r['params']} TP{r['tp']}: exp_R{r['ex']:+.4f} t{r['t']:+.2f} "
                  f"p{r['pval']:.3f} drop1%{r['ex_drop']:+.4f}")
    else:
        print("ไม่มีตัวผ่าน gate. flaw ที่พบจะระบุด้านล่างเพื่อ iterate.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
