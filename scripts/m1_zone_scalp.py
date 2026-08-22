#!/usr/bin/env python
"""scripts/m1_zone_scalp.py — M1 scalp เข้าเฉพาะที่ demand/supply zone (user idea 08-22).

user: เข้า scalp เฉพาะในโซน demand/supply ที่คำนวณไว้ → WR สูงขึ้น?
ทดสอบ: zone = H1 cluster map (compute_cluster_map ตัวเดียวกับ production sr_meta, causal rolling).
map ลง M1 (ใช้ zone set ของ H1 bar ล่าสุด ≤ เวลา M1). เข้า BUY เมื่อ M1 ใกล้ strong support (touches≥min),
SELL เมื่อใกล้ strong resistance. SL300 (user), TP สั้น. real spread 28pt, SL-first.

ตัวตัดสิน (บทเรียนทั้ง session): **matched-null** — zone-entry ชนะ random-entry (exit เดียวกัน) ไหม.
+ เทียบ WR กับ breakeven line (SL/(SL+TP)). WR สูงเฉยๆ ไม่พอ ต้องทะลุ breakeven + ชนะ null.
data: xau_m1.json + xau_h1.json. read-only · offline · 0 order.
รัน: python scripts/m1_zone_scalp.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
from agents.cluster_map import compute_cluster_map            # noqa: E402
import regime_lib as R                                        # noqa: E402

DATA = os.path.join(_ROOT, "data")
POINT = 0.01
SL_PTS = 300.0
COST_PTS = 28.0
MAX_HOLD = 240
MIN_N = 200
H1_WIN = 600                                                  # trailing window คำนวณ cluster (=production)


def _load(fn):
    d = json.load(open(os.path.join(DATA, fn)))
    ts = np.array([x[0] for x in d], np.int64)
    o = np.array([x[1] for x in d], float); h = np.array([x[2] for x in d], float)
    l = np.array([x[3] for x in d], float); c = np.array([x[4] for x in d], float)
    return ts, o, h, l, c


def _build_h1_zones(ts, h, l, c, min_touch):
    """causal: ต่อ H1 bar j คำนวณ cluster จาก [j-WIN, j] → (sup_level, sup_touch, res_level, res_touch).
    None ถ้าไม่มี. คืน dict j -> zones."""
    zones = {}
    for j in range(H1_WIN, len(c)):
        cm = compute_cluster_map(h[j - H1_WIN:j + 1], l[j - H1_WIN:j + 1], c[j - H1_WIN:j + 1],
                                 min_touch=min_touch)
        if not cm.get("ok"):
            continue
        sup = cm.get("support"); res = cm.get("resistance")
        zones[j] = (sup["level"] if sup else None, sup["touches"] if sup else 0,
                    res["level"] if res else None, res["touches"] if res else 0,
                    float(cm.get("atr") or 0))
    return zones


def _m1_zone_side(m_ts, m_o, m_h, m_l, m_c, h1_ts, zones, min_touch, tol_atr, confirm=True):
    """ต่อ M1 bar: หา H1 zone ล่าสุด (causal) → side ถ้าราคาแตะโซนแข็ง + (confirm) มีแท่งกลับตัว.
    buy: low แตะ support + ปิดเด้งครึ่งบน (rejection ล่าง). sell: high แตะ resistance + ปิดครึ่งล่าง."""
    n = len(m_c); side = np.zeros(n)
    h1_keys = sorted(zones.keys())
    h1_ts_sorted = np.array([h1_ts[j] for j in h1_keys])
    for i in range(n):
        # causal: ใช้เฉพาะ H1 bar ที่ "ปิดแล้ว" ก่อนเวลา M1 นี้ (open+3600 ≤ now) — กัน look-ahead แท่งก่อตัว
        pos = np.searchsorted(h1_ts_sorted, m_ts[i] - 3600, side="right") - 1
        if pos < 0:
            continue
        sup, st, res, rt, atr = zones[h1_keys[pos]]
        if atr <= 0:
            continue
        tol = tol_atr * atr
        rng = (m_h[i] - m_l[i]) or 1e-9
        up_close = (m_c[i] - m_l[i]) / rng >= 0.6            # ปิดครึ่งบน = rejection ล่าง (bullish)
        dn_close = (m_h[i] - m_c[i]) / rng >= 0.6            # ปิดครึ่งล่าง = rejection บน (bearish)
        if sup is not None and st >= min_touch and m_l[i] <= sup + tol and m_c[i] >= sup - tol:
            if (not confirm) or up_close:                    # แตะโซน demand + แท่งกลับตัวขึ้น
                side[i] = 1.0
        elif res is not None and rt >= min_touch and m_h[i] >= res - tol and m_c[i] <= res + tol:
            if (not confirm) or dn_close:                    # แตะโซน supply + แท่งกลับตัวลง
                side[i] = -1.0
    return side


def _sim(side, h, l, c, tp_pts, warm):
    n = len(c); trades = []; idx = []
    i = warm
    while i < n - 1:
        s = side[i]
        if s == 0:
            i += 1; continue
        px = c[i]; sl = px - s * SL_PTS * POINT; tp = px + s * tp_pts * POINT
        end = min(i + MAX_HOLD, n - 1); r = None; ex = end
        for j in range(i + 1, end + 1):
            hit_sl = (l[j] <= sl) if s > 0 else (h[j] >= sl)
            hit_tp = (h[j] >= tp) if s > 0 else (l[j] <= tp)
            if hit_sl:
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
    sd = a.std(ddof=1); t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t


def _null(side, h, l, c, tp_pts, warm, n_real, pos_f, neg_f, sims=300):
    n = len(c); rng = np.random.default_rng(99); cand = np.arange(warm, n - 1)
    exps = np.empty(sims); wrs = np.empty(sims); k = min(n_real, len(cand))
    for s_ in range(sims):
        pick = np.sort(rng.choice(cand, size=k, replace=False)); u = rng.random(k)
        sd_ = np.where(u < pos_f, 1.0, np.where(u < pos_f + neg_f, -1.0, 0.0))
        fake = np.zeros(n); fake[pick] = sd_
        a, _ = _sim(fake, h, l, c, tp_pts, warm)
        exps[s_] = a.mean() if len(a) else 0.0
        wrs[s_] = (a > 0).mean() * 100 if len(a) else 0.0
    return exps, wrs


def main():
    print("=== M1 ZONE SCALP (เข้าเฉพาะ demand/supply zone · H1 cluster causal · SL300 · cost28) ===")
    print("ตัวตัดสิน: zone-entry ชนะ matched-random-entry ไหม (WR สูงเฉยๆ ไม่พอ ต้องทะลุ breakeven+null)\n", flush=True)
    m_ts, mo, mh, ml, mc = _load("xau_m1.json")
    h_ts, ho, hh, hl, hc = _load("xau_h1.json")
    # crop H1 ให้คลุมช่วง M1 (+buffer)
    mask = h_ts >= (m_ts[0] - 700 * 3600)
    h_ts, hh, hl, hc = h_ts[mask], hh[mask], hl[mask], hc[mask]
    warm = 300
    for min_touch in (3, 5):
        zones = _build_h1_zones(h_ts, hh, hl, hc, min_touch)
        print(f"--- min_touch={min_touch}: H1 zones={len(zones)} ---", flush=True)
        for tol_atr in (0.2, 0.3):
            side = _m1_zone_side(m_ts, mo, mh, ml, mc, h_ts, zones, min_touch, tol_atr, confirm=True)
            nz = int((side != 0).sum())
            for tp in (200, 250, 300, 400):
                a, idx = _sim(side, mh, ml, mc, tp, warm)
                n, wr, ex, t = _stat(a)
                if n < 50:
                    print(f"  tol{tol_atr} TP{tp}: n={n} (น้อยไป)"); continue
                be = SL_PTS / (SL_PTS + tp) * 100
                k = int(n * 0.7); oos = _stat(a[k:])[2]
                pos_f = float((side[warm:] > 0).mean()); neg_f = float((side[warm:] < 0).mean())
                nexp, nwr = _null(side, mh, ml, mc, tp, warm, n, pos_f, neg_f)
                p_ex = float((nexp >= ex).mean()); p_wr = float((nwr >= wr).mean())
                fl = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oos > 0 and p_ex < 0.05) else ""
                print(f"  tol{tol_atr} TP{tp:3d} n{n:4d} WR{wr:5.1f}%(be{be:.1f}) exp_R{ex:+.4f} t{t:+.2f} "
                      f"OOS{oos:+.4f} | null exp{nexp.mean():+.4f} WR{nwr.mean():.1f}% | "
                      f"p_ex{p_ex:.3f} p_wr{p_wr:.3f} {fl}", flush=True)
    print("\np_ex = zone exp_R ชนะ random กี่%? (<0.05=มี edge) · p_wr = zone WR ชนะ random WR ไหม")
    print("ถ้า WR สูงกว่า null แต่ exp_R ไม่ชนะ = zone ดัน WR แต่ไม่พอชนะ spread (WR trap เดิม)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
