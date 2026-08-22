#!/usr/bin/env python
"""scripts/tick_trail_scalp.py — tick scalp + TRAILING exit (user idea 08-22).

user: ตั้ง trailing หลังไม้เข้าแดน + (หักลบ spread แล้ว) → ล็อกกำไร ปล่อยวิ่ง.
ต่างจาก fixed-TP: ไม่ cap winner (fat right-tail) → ช่วยได้ถ้า M1 มี momentum/trend จริง.
⚠️ ทฤษฎี optional-stopping: ตลาด driftless → exit rule ใดๆ E[gross]=0 → หัก spread = ลบ. วัดจริง.

trail logic (long): เข้า@ask, track max bid. เมื่อ profit(bid−ask) ≥ activate → SL_trail = maxbid − trail.
exit เมื่อ bid ≤ max(SL_trail, hard_SL). ก่อน activate ใช้ hard_SL (−300). realistic taker (ออก@bid/ask จริง).
gate เดิม + matched-null (trail เดียวกัน). data scratchpad/xau_ticks.npz. read-only · 0 order.
รัน: python scripts/tick_trail_scalp.py
"""
import math
import os
import sys

import numpy as np

_SP = (r"C:/Users/PORNNA~1/AppData/Local/Temp/claude/"
       r"D--claude-workspace-xauusd-ai-trading-system/"
       r"8753aacd-c36b-49f7-88e5-e6a3c9fac75f/scratchpad/xau_ticks.npz")
POINT = 0.01
SL_PTS = 300.0
MAX_HOLD = 40000
MIN_N = 300


def _load():
    d = np.load(_SP); return d["bid"], d["ask"]


def _roll_mean_std(x, w):
    cs = np.cumsum(np.insert(x, 0, 0.0)); cs2 = np.cumsum(np.insert(x * x, 0, 0.0))
    n = len(x); m = np.full(n, np.nan); sd = np.full(n, np.nan)
    i = np.arange(w, n); s1 = cs[i] - cs[i - w]; s2 = cs2[i] - cs2[i - w]
    mean = s1 / w; var = np.maximum(s2 / w - mean * mean, 0.0); m[i] = mean; sd[i] = np.sqrt(var)
    return m, sd


def _signals(name, mid, **p):
    n = len(mid); side = np.zeros(n)
    w = p["w"]; m, sd = _roll_mean_std(mid, w); z = (mid - m) / np.where(sd == 0, np.nan, sd)
    if name == "zfade":
        side = np.where(z >= p["thr"], -1.0, np.where(z <= -p["thr"], 1.0, 0.0))
    elif name == "zmom":
        side = np.where(z >= p["thr"], 1.0, np.where(z <= -p["thr"], -1.0, 0.0))
    return side


def _sim_trail(side, bid, ask, warm, activate_pts, trail_pts):
    """trailing exit, realistic taker fill. non-overlap, SL-first. คืน (R array, idx)."""
    n = len(bid); trades = []; idx = []
    sl_d = SL_PTS * POINT; act = activate_pts * POINT; tr = trail_pts * POINT
    i = warm
    while i < n - 1:
        s = side[i]
        if s == 0:
            i += 1; continue
        end = min(i + MAX_HOLD, n - 1)
        if s > 0:
            entry = ask[i]; seg = bid[i + 1:end + 1]          # long ออก@bid
            runmax = np.maximum.accumulate(seg)
            activated = runmax >= entry + act
            trail_line = runmax - tr
            hard = entry - sl_d
            sl_line = np.where(activated, np.maximum(trail_line, hard), hard)
            hit = np.where(seg <= sl_line)[0]
        else:
            entry = bid[i]; seg = ask[i + 1:end + 1]          # short ออก@ask
            runmin = np.minimum.accumulate(seg)
            activated = runmin <= entry - act
            trail_line = runmin + tr
            hard = entry + sl_d
            sl_line = np.where(activated, np.minimum(trail_line, hard), hard)
            hit = np.where(seg >= sl_line)[0]
        if len(hit):
            j = hit[0]; ex_px = seg[j]; ex = i + 1 + j
        else:
            ex_px = seg[-1]; ex = end
        r = s * (ex_px - entry) / sl_d
        trades.append(r); idx.append(i); i = ex + 1
    return np.array(trades), np.array(idx)


def _stat(a):
    n = len(a)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    sd = a.std(ddof=1); t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t


def _null(side, bid, ask, warm, act, tr, n_real, pos_f, neg_f, sims=120):
    n = len(bid); rng = np.random.default_rng(77); cand = np.arange(warm, n - 1)
    exps = np.empty(sims); k = min(n_real, len(cand))
    for s_ in range(sims):
        pick = np.sort(rng.choice(cand, size=k, replace=False)); u = rng.random(k)
        sd_ = np.where(u < pos_f, 1.0, np.where(u < pos_f + neg_f, -1.0, 0.0))
        fake = np.zeros(n); fake[pick] = sd_
        a, _ = _sim_trail(fake, bid, ask, warm, act, tr)
        exps[s_] = a.mean() if len(a) else 0.0
    return exps


def evaluate(name, mid, bid, ask, warm, act, tr, **p):
    side = _signals(name, mid, **p)
    a, idx = _sim_trail(side, bid, ask, warm, act, tr)
    n, wr, ex, t = _stat(a)
    if n < 10:
        return None
    k = int(n * 0.7); oos = _stat(a[k:])[2]
    kk = max(1, n // 100); ex_drop = float(np.sort(a)[:-kk].mean())
    th = n // 3; thirds = [_stat(a[:th])[2], _stat(a[th:2 * th])[2], _stat(a[2 * th:])[2]]
    npos = sum(1 for x in thirds if x > 0)
    return dict(name=name, params=p, act=act, tr=tr, n=n, wr=wr, ex=ex, t=t, oos=oos,
                ex_drop=ex_drop, npos=npos, pval=float("nan"))


def _passes(r):
    return (r and r["n"] >= MIN_N and r["ex"] > 0 and r["t"] > 2 and r["oos"] > 0
            and r["pval"] < 0.05 and r["ex_drop"] > 0 and r["npos"] >= 2)


def main():
    bid, ask = _load(); mid = (bid + ask) / 2.0; warm = 6000
    sp = (ask - bid) / POINT
    print(f"=== TICK TRAIL SCALP (XAU · {len(mid)} ticks · realistic taker · SL{SL_PTS:.0f} · trailing exit) ===")
    print(f"spread med{np.median(sp):.0f} min{sp.min():.0f} · activate=เข้าแดน+หลังหัก spread, trail=ระยะตาม")
    print(f"PASS = n≥{MIN_N}+exp_R>0+t>2+OOS>0+null p<0.05+drop1%>0+stable≥2/3\n", flush=True)
    GRID = []
    for name in ("zfade", "zmom"):
        for w in (200, 1000, 5000):
            for thr in (2.5, 3.5):
                for act in (40, 80, 150):                    # แดน+ หลัง spread(30)
                    for tr in (30, 60, 120):
                        GRID.append((name, dict(w=w, thr=thr), act, tr))
    print(f"testing {len(GRID)} configs (pass1 no-null)\n", flush=True)
    rows = []
    for name, p, act, tr in GRID:
        r = evaluate(name, mid, bid, ask, warm, act, tr, **p)
        if r:
            rows.append(r)
    pre = [r for r in rows if r["ex"] > 0 and r["t"] > 2 and r["oos"] > 0 and r["ex_drop"] > 0 and r["npos"] >= 2]
    print(f"pre-survivors (exp_R>0,t>2,OOS>0,drop>0,stable) = {len(pre)} → null บนกลุ่มนี้\n", flush=True)
    for r in pre:
        side = _signals(r["name"], mid, **r["params"])
        pos_f = float((side[warm:] > 0).mean()); neg_f = float((side[warm:] < 0).mean())
        nu = _null(side, bid, ask, warm, r["act"], r["tr"], r["n"], pos_f, neg_f)
        r["pval"] = float((nu >= r["ex"]).mean())
    rows.sort(key=lambda r: -r["t"])
    print("TOP 15 by t:")
    for r in rows[:15]:
        fl = "PASS" if _passes(r) else "—"
        ps = ",".join(f"{k}{v}" for k, v in r["params"].items())
        print(f"  {r['name']:6s} {ps:14s} act{r['act']*100/POINT:0.0f}? tr{int(r['tr']/POINT):3d} n{r['n']:5d} "
              f"WR{r['wr']:5.1f}% exp_R{r['ex']:+.4f} t{r['t']:+.2f} OOS{r['oos']:+.4f} "
              f"drop1%{r['ex_drop']:+.4f} p{r['pval']:.3f} 3rd{r['npos']}/3 [{fl}]")
    passes = [r for r in rows if _passes(r)]
    print(f"\n{'='*60}\nPASS: {len(passes)}/{len(rows)}")
    for r in passes:
        print(f"  {r['name']} {r['params']} act{int(r['act']/POINT)} tr{int(r['tr']/POINT)}: "
              f"exp_R{r['ex']:+.4f} t{r['t']:+.2f} p{r['pval']:.3f}")
    if not passes:
        print("trailing ก็ไม่พลิก — ยืนยัน optional-stopping: driftless → exit ใดๆ = −spread.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
