#!/usr/bin/env python
"""scripts/tick_scalp_search.py — tick-level M1-ish scalp search (user 08-22, /loop+fable).

M1 OHLC ไม่มี edge (108 config, Fable confirm). ลอง **tick** — signal sub-minute ที่ M1 มองไม่เห็น
(micro mean-reversion / tick imbalance / micro-breakout). **realistic taker fill**: BUY เข้า@ask ออก@bid,
SELL เข้า@bid ออก@ask → จ่าย spread จริงทุกไม้ (bid/ask จริงจาก tick, ต่ำสุด 24pt ไม่เคยต่ำกว่า).

SL 300pt (user), TP สั้น. gate เดิม: n≥300·exp_R>0·t>2·OOS>0·matched-null p<0.05·drop-best-1%>0·stable≥2/3.
data: scratchpad/xau_ticks.npz (tm,bid,ask · 3.87M ticks 16d). read-only · offline · 0 order.
รัน: python scripts/tick_scalp_search.py
"""
import math
import os
import sys

import numpy as np

_SP = os.path.join(os.environ.get("SCRATCH", ""), "xau_ticks.npz")
if not os.path.exists(_SP):
    _SP = (r"C:/Users/PORNNA~1/AppData/Local/Temp/claude/"
           r"D--claude-workspace-xauusd-ai-trading-system/"
           r"8753aacd-c36b-49f7-88e5-e6a3c9fac75f/scratchpad/xau_ticks.npz")
POINT = 0.01
SL_PTS = 300.0
MAX_HOLD = 40000                                             # ticks (~นาที-ชม. ขึ้นกับ activity)
MIN_N = 300


def _load():
    d = np.load(_SP)
    return d["tm"], d["bid"], d["ask"]


def _roll_mean_std(x, w):
    """rolling mean/std ของ w ticks ก่อนหน้า (causal, ไม่รวม i). cumsum O(n)."""
    cs = np.cumsum(np.insert(x, 0, 0.0))
    cs2 = np.cumsum(np.insert(x * x, 0, 0.0))
    n = len(x); m = np.full(n, np.nan); sd = np.full(n, np.nan)
    i = np.arange(w, n)
    s1 = cs[i] - cs[i - w]; s2 = cs2[i] - cs2[i - w]
    mean = s1 / w; var = np.maximum(s2 / w - mean * mean, 0.0)
    m[i] = mean; sd[i] = np.sqrt(var)
    return m, sd


def _signals(name, mid, bid, ask, **p):
    n = len(mid); side = np.zeros(n)
    if name == "zfade":                                     # micro mean-revert: mid เบี่ยง EMA มาก → fade
        w = p["w"]; m, sd = _roll_mean_std(mid, w)
        z = (mid - m) / np.where(sd == 0, np.nan, sd)
        side = np.where(z >= p["thr"], -1.0, np.where(z <= -p["thr"], 1.0, 0.0))
    elif name == "zmom":                                    # micro momentum: เบี่ยงมาก → follow
        w = p["w"]; m, sd = _roll_mean_std(mid, w)
        z = (mid - m) / np.where(sd == 0, np.nan, sd)
        side = np.where(z >= p["thr"], 1.0, np.where(z <= -p["thr"], -1.0, 0.0))
    elif name == "mbreak":                                  # micro-breakout: mid ทะลุ w-tick range → follow
        w = p["w"]
        hi = np.full(n, np.nan); lo = np.full(n, np.nan)
        # rolling max/min ผ่าน pandas-free: ใช้ strided loop เป็นช่วง (w ticks) — ประหยัดด้วย maximum.accumulate ไม่ได้ตรงๆ
        cs = None
        from numpy.lib.stride_tricks import sliding_window_view as swv
        sw = swv(mid, w)
        hi[w:] = sw.max(axis=1)[:-1]; lo[w:] = sw.min(axis=1)[:-1]
        side = np.where(mid > hi, 1.0, np.where(mid < lo, -1.0, 0.0))
    return side


def _sim(side, mid, bid, ask, tp_pts, warm, thin=1):
    """taker fill: BUY เข้า@ask ออก@bid / SELL เข้า@bid ออก@ask. SL-first. non-overlap.
    thin = ประเมิน signal ทุก thin ticks (ลด over-trade tick ติดกัน). คืน (R array, entry idx)."""
    n = len(mid); trades = []; idx = []
    i = warm
    sl_price_pts = SL_PTS * POINT; tp_price_pts = tp_pts * POINT
    while i < n - 1:
        s = side[i]
        if s == 0:
            i += 1; continue
        if s > 0:
            entry = ask[i]; sl = entry - sl_price_pts; tp = entry + tp_price_pts
            end = min(i + MAX_HOLD, n - 1)
            seg_lo = bid[i + 1:end + 1]                     # ออก long ที่ bid
            sl_hit = np.where(seg_lo <= sl)[0]; tp_hit = np.where(seg_lo >= tp)[0]
        else:
            entry = bid[i]; sl = entry + sl_price_pts; tp = entry - tp_price_pts
            end = min(i + MAX_HOLD, n - 1)
            seg_hi = ask[i + 1:end + 1]                     # ออก short ที่ ask
            sl_hit = np.where(seg_hi >= sl)[0]; tp_hit = np.where(seg_hi <= tp)[0]
        js = sl_hit[0] if len(sl_hit) else 10 ** 12
        jt = tp_hit[0] if len(tp_hit) else 10 ** 12
        if js == jt == 10 ** 12:                            # ไม่โดนทั้งคู่ใน max_hold → exit ราคาปิด
            last_exit = bid[end] if s > 0 else ask[end]
            r = s * (last_exit - entry) / sl_price_pts; ex = end
        elif js <= jt:                                      # SL-first pessimistic (tie → SL)
            r = -1.0; ex = i + 1 + js
        else:
            r = tp_pts / SL_PTS; ex = i + 1 + jt
        trades.append(r); idx.append(i); i = ex + 1
    return np.array(trades), np.array(idx)


def _stat(a):
    n = len(a)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    sd = a.std(ddof=1)
    t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t


def _matched_null(side, mid, bid, ask, tp_pts, warm, n_real, pos_f, neg_f, sims=150):
    n = len(mid); rng = np.random.default_rng(2026)
    cand = np.arange(warm, n - 1); exps = np.empty(sims)
    k = min(n_real, len(cand))
    for s_ in range(sims):
        pick = np.sort(rng.choice(cand, size=k, replace=False))
        u = rng.random(k)
        sides = np.where(u < pos_f, 1.0, np.where(u < pos_f + neg_f, -1.0, 0.0))
        fake = np.zeros(n)
        fake[pick] = sides
        a, _ = _sim(fake, mid, bid, ask, tp_pts, warm)
        exps[s_] = a.mean() if len(a) else 0.0
    return exps


def evaluate(name, mid, bid, ask, warm, tp_pts, do_null=False, **p):
    side = _signals(name, mid, bid, ask, **p)
    a, idx = _sim(side, mid, bid, ask, tp_pts, warm)
    n, wr, ex, t = _stat(a)
    if n < 10:
        return None
    k = int(n * 0.7); oos = _stat(a[k:])[2]
    kk = max(1, n // 100); ex_drop = float(np.sort(a)[:-kk].mean())
    th = n // 3; thirds = [_stat(a[:th])[2], _stat(a[th:2 * th])[2], _stat(a[2 * th:])[2]]
    npos = sum(1 for x in thirds if x > 0)
    pval = float("nan")
    if do_null:                                             # null แพงมาก → รันเฉพาะ pre-survivor
        pos_f = float((side[warm:] > 0).mean()); neg_f = float((side[warm:] < 0).mean())
        null = _matched_null(side, mid, bid, ask, tp_pts, warm, n, pos_f, neg_f)
        pval = float((null >= ex).mean())
    return dict(name=name, params=p, tp=tp_pts, n=n, wr=wr, ex=ex, t=t, oos=oos,
                ex_drop=ex_drop, npos=npos, pval=pval, _side_p=p)


def _passes(r):
    return (r and r["n"] >= MIN_N and r["ex"] > 0 and r["t"] > 2 and r["oos"] > 0
            and r["pval"] < 0.05 and r["ex_drop"] > 0 and r["npos"] >= 2)


def main():
    tm, bid, ask = _load()
    mid = (bid + ask) / 2.0
    warm = 6000
    sp = (ask - bid) / POINT
    print(f"=== TICK SCALP SEARCH (XAU · {len(mid)} ticks 16d · realistic taker fill bid/ask · SL{SL_PTS:.0f}) ===")
    print(f"real spread pts: mean{sp.mean():.1f} med{np.median(sp):.1f} min{sp.min():.1f} — จ่ายจริงทุกไม้ (taker)")
    print(f"PASS = n≥{MIN_N}+exp_R>0+t>2+OOS>0+matched-null p<0.05+drop1%>0+stable≥2/3\n")
    GRID = []
    for tp in (50, 100, 150, 200):
        for w in (200, 1000, 5000):
            for thr in (2.5, 3.5):
                GRID.append(("zfade", dict(w=w, thr=thr), tp))
                GRID.append(("zmom", dict(w=w, thr=thr), tp))
        for w in (500, 2000):
            GRID.append(("mbreak", dict(w=w), tp))
    print(f"testing {len(GRID)} configs (pass1 no-null fast → null เฉพาะ pre-survivor)\n", flush=True)
    rows = []
    for name, p, tp in GRID:
        r = evaluate(name, mid, bid, ask, warm, tp, do_null=False, **p)
        if r:
            rows.append(r)
    # pass2: null เฉพาะ pre-gate (exp_R>0, t>2, oos>0) — ประหยัดเวลามหาศาล
    pre = [r for r in rows if r["ex"] > 0 and r["t"] > 2 and r["oos"] > 0 and r["ex_drop"] > 0 and r["npos"] >= 2]
    print(f"pre-survivors (exp_R>0,t>2,OOS>0,drop>0,stable) = {len(pre)} → run matched-null บนกลุ่มนี้\n", flush=True)
    for r in pre:
        side = _signals(r["name"], mid, bid, ask, **r["_side_p"])
        pos_f = float((side[warm:] > 0).mean()); neg_f = float((side[warm:] < 0).mean())
        null = _matched_null(side, mid, bid, ask, r["tp"], warm, r["n"], pos_f, neg_f)
        r["pval"] = float((null >= r["ex"]).mean())
    rows.sort(key=lambda r: -r["t"])
    print("TOP 15 by t:")
    for r in rows[:15]:
        fl = "PASS" if _passes(r) else "—"
        ps = ",".join(f"{k}{v}" for k, v in r["params"].items())
        print(f"  {r['name']:7s} {ps:14s} TP{r['tp']:3d} n{r['n']:5d} WR{r['wr']:5.1f}% "
              f"exp_R{r['ex']:+.4f} t{r['t']:+.2f} OOS{r['oos']:+.4f} drop1%{r['ex_drop']:+.4f} "
              f"p{r['pval']:.3f} 3rd{r['npos']}/3 [{fl}]")
    passes = [r for r in rows if _passes(r)]
    print(f"\n{'='*60}\nPASS: {len(passes)}/{len(rows)}")
    for r in passes:
        print(f"  {r['name']} {r['params']} TP{r['tp']}: exp_R{r['ex']:+.4f} t{r['t']:+.2f} p{r['pval']:.3f}")
    if not passes:
        print("ไม่มีตัวผ่าน — tick ก็ไม่ช่วย (taker spread ≥24pt ฆ่า).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
