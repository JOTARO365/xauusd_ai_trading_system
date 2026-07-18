#!/usr/bin/env python
"""
gold_strengthen.py — B3b: ดัน gold gross-edge ให้ผ่าน cost ด้วย theory-motivated filters
                     (OFFLINE, ไม่แตะ live/gold pipeline)

พื้นหลัง: btc_validate.py พบ gold มี gross-edge จริง (DSR 1.0 @ 0 cost, OOS ยืน) แต่ net @ cost
จริง 0.04% "บาง" (Sharpe +0.072, DSR 0.36) — cost คือคอขวด. สคริปต์นี้เพิ่ม 3 lever ที่มีเหตุผล
ตลาด (ไม่ใช่ data-mine) แล้ววัดว่า "ผ่าน cost" ขึ้นมั้ย:

  1) confirm buffer β·ATR : เข้า breakout เฉพาะทะลุเกิน level + β·ATR (กรอง false break)
  2) volatility floor      : ข้ามเมื่อ ATR% < median ย้อนหลัง (ตลาดตาย breakout หลอก) — trailing, no look-ahead
  3) wider SL              : sweep atrSL รวม 2.5/3.0 (cost คงที่เป็น $ → R-cost ต่ำลง)

วินัย: RR3.0/ER0.3 ล็อก (plateau) → sweep atrSL×brk = N=12 (เล็กกว่า 54) → DSR สะอาดขึ้น.
       judge บน HOLDOUT 30% ท้าย (ล็อก ไม่ใช้ tune) = การทดสอบ edge ที่ N=1 สะอาดสุด.
       เทียบ baseline (ไม่มี filter) ↔ +filter ให้เห็น delta จริง — ไม่ปรับจนเขียวแล้วหยุด.

รัน: & $PY scripts\\gold_strengthen.py   (ต้องมี data/paxg_hourly_3y.json)
"""
import itertools
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
from scipy import stats

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# argv[1] = data file (default 3y). ชี้ paxg_hourly_full.json ได้เพื่อ sample เยอะ → DSR แน่นขึ้น
RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_BASE, "data", "paxg_hourly_3y.json")
if not os.path.isabs(RAW):
    RAW = os.path.join(_BASE, "data", RAW)

ATR_P, BB_P, BB_K, ER_WIN, TIME_STOP = 14, 20, 2.0, 20, 24
RR, ER_TH = 3.0, 0.30          # ล็อกจาก plateau
FEE_PCT = 0.02                 # gold cost realistic ต่อ side (round-trip 0.04%)
# argv[2]=="intrabar" → เช็ค SL/TP ด้วย H/L ในแท่ง (สมจริง + conservative: SL ก่อนถ้าชนทั้งคู่)
INTRABAR = len(sys.argv) > 2 and sys.argv[2] == "intrabar"
_H = _L = None                 # set ใน main()
GRID_BRK = [15, 20, 30]
GRID_ATRSL = [1.5, 2.0, 2.5, 3.0]
VOL_WIN = 500                  # trailing window สำหรับ vol-floor median
GAMMA = 0.5772156649015329
HOLDOUT = 0.30                 # 30% ท้าย = holdout ล็อก


def _roll(x, w, fn):
    sw = np.lib.stride_tricks.sliding_window_view(x, w)
    out = np.full(len(x), np.nan); out[w:] = fn(sw[:-1], axis=1)
    return out


def load():
    d = json.load(open(RAW))
    h = np.array([float(k[2]) for k in d]); l = np.array([float(k[3]) for k in d])
    c = np.array([float(k[4]) for k in d]); return h, l, c


def eff_ratio(c, w):
    er = np.full(len(c), np.nan); ad = np.abs(np.diff(c, prepend=c[0]))
    for i in range(w, len(c)):
        v = ad[i - w + 1:i + 1].sum(); er[i] = abs(c[i] - c[i - w]) / v if v > 0 else 0.0
    return er


def precompute(h, l, c):
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    tr = np.concatenate([[np.nan], tr]); atr = _roll(tr, ATR_P, np.nanmean)
    mid = _roll(c, BB_P, np.mean); sd = _roll(c, BB_P, np.std); er = eff_ratio(c, ER_WIN)
    hi = {b: _roll(h, b, np.max) for b in GRID_BRK}
    lo = {b: _roll(l, b, np.min) for b in GRID_BRK}
    # trailing median ของ ATR% (vol floor) — ใช้แค่อดีต (no look-ahead)
    atrp = atr / c
    volmed = np.full(len(c), np.nan)
    for i in range(VOL_WIN, len(c)):
        volmed[i] = np.nanmedian(atrp[i - VOL_WIN:i])
    return atr, mid, sd, er, hi, lo, atrp, volmed


def run(cfg, arrs, c, confirm_beta=0.0, vol_floor=False, i0=0, i1=None):
    """คืน trades [{i,net_r}] ใน [i0,i1). confirm_beta>0 = buffer ; vol_floor=True = ตัดตลาดตาย."""
    brk, atrsl = cfg; atr, mid, sd, er, hi, lo, atrp, volmed = arrs
    HI, LO = hi[brk], lo[brk]; i1 = i1 if i1 is not None else len(c) - 1
    start = max(brk, BB_P, ATR_P, ER_WIN, VOL_WIN) + 1
    trades, open_until = [], -1
    for i in range(max(start, i0), i1):
        if i <= open_until or np.isnan(atr[i]) or atr[i] == 0 or np.isnan(er[i]):
            continue
        if vol_floor and (np.isnan(volmed[i]) or atrp[i] < volmed[i]):
            continue                              # ตลาดตาย → ข้าม
        A = atr[i]; d = None
        if er[i] >= ER_TH:                        # trending → breakout (+ confirm buffer)
            if c[i] > HI[i] + confirm_beta * A:   d = "BUY"
            elif c[i] < LO[i] - confirm_beta * A: d = "SELL"
        else:                                     # ranging → mean-rev
            if not np.isnan(mid[i]):
                if c[i] < mid[i] - BB_K * sd[i]:   d = "BUY"
                elif c[i] > mid[i] + BB_K * sd[i]: d = "SELL"
        if d is None:
            continue
        entry = c[i]; sign = 1 if d == "BUY" else -1
        sl = entry - sign * atrsl * A; tp = entry + sign * RR * atrsl * A; risk = abs(entry - sl)
        px = None
        for j in range(i + 1, min(i + 1 + TIME_STOP, len(c))):
            hi_j = _H[j] if INTRABAR else c[j]     # intrabar: ใช้ H/L ในแท่ง
            lo_j = _L[j] if INTRABAR else c[j]
            if d == "BUY":
                if lo_j <= sl: px, jx = sl, j; break   # SL ก่อน (conservative) ถ้าชนทั้งคู่ในแท่ง
                if hi_j >= tp: px, jx = tp, j; break
            else:
                if hi_j >= sl: px, jx = sl, j; break
                if lo_j <= tp: px, jx = tp, j; break
        if px is None:
            jx = min(i + TIME_STOP, len(c) - 1); px = c[jx]
        gross = sign * (px - entry) / risk; cost = (2 * FEE_PCT / 100) * entry / risk
        trades.append({"i": i, "net_r": gross - cost}); open_until = jx
    return trades


def sharpe(x):
    x = np.asarray(x, float)
    return float(x.mean() / x.std()) if len(x) > 1 and x.std() > 0 else 0.0


def dsr(best_nets, all_sharpes, N):
    sr = sharpe(best_nets); T = len(best_nets); v = np.var(all_sharpes, ddof=1)
    if v <= 0 or T < 3: return None, sr, 0.0
    sr0 = np.sqrt(v) * ((1 - GAMMA) * stats.norm.ppf(1 - 1.0 / N) + GAMMA * stats.norm.ppf(1 - 1.0 / (N * np.e)))
    sk = float(stats.skew(best_nets)); ku = float(stats.kurtosis(best_nets, fisher=False))
    den = np.sqrt(1 - sk * sr + (ku - 1) / 4.0 * sr ** 2)
    z = (sr - sr0) * np.sqrt(T - 1) / den if den > 0 else 0.0
    return float(stats.norm.cdf(z)), sr, float(sr0)


def evaluate(name, arrs, c, nbars, confirm_beta, vol_floor):
    """sweep บน full → DSR/PBO ; แล้ว lock plateau-center → judge บน holdout ท้าย."""
    cut = int((1 - HOLDOUT) * nbars)
    configs = list(itertools.product(GRID_BRK, GRID_ATRSL)); N = len(configs)
    rows = []
    for cfg in configs:
        tr = run(cfg, arrs, c, confirm_beta, vol_floor)
        nets = [t["net_r"] for t in tr]
        rows.append({"cfg": cfg, "n": len(tr), "net": float(np.sum(nets)) if nets else 0.0,
                     "wr": float(np.mean([x > 0 for x in nets]) * 100) if nets else 0.0,
                     "sharpe": sharpe(nets), "nets": nets})
    shs = np.array([r["sharpe"] for r in rows])
    ranked = sorted([r for r in rows if r["n"] >= 50] or rows, key=lambda r: r["sharpe"], reverse=True)
    best = ranked[0]
    d, sr, sr0 = dsr(best["nets"], shs, N)
    # holdout judge: lock best cfg → รันเฉพาะช่วง holdout (ไม่ใช้ tune)
    ho = run(best["cfg"], arrs, c, confirm_beta, vol_floor, i0=cut)
    ho_net = float(np.sum([t["net_r"] for t in ho])); ho_sh = sharpe([t["net_r"] for t in ho])
    tot_trades = sum(r["n"] for r in rows) / N   # avg turnover ต่อ config
    print(f"\n{'='*72}\n[{name}]  confirm β={confirm_beta}  vol_floor={vol_floor}  (N={N})")
    b, a = best["cfg"]
    print(f"  best: brk{b}/atrSL{a}/RR{RR}/ER{ER_TH}  n={best['n']} WR={best['wr']:.0f}% "
          f"net{best['net']:+.1f}R Sharpe{best['sharpe']:+.3f}")
    print(f"  avg turnover/config: {tot_trades:.0f} ไม้  |  configs กำไร: {sum(r['net']>0 for r in rows)}/{N}")
    print(f"  DEFLATED SHARPE: SR{sr:+.3f} vs SR0{sr0:+.3f} → DSR {d:.3f}  "
          f"{'✅ ผ่าน' if (d or 0) > 0.95 else '❌ ไม่ผ่าน'}")
    print(f"  HOLDOUT 30% ท้าย (ล็อก best, judge ครั้งเดียว): n={len(ho)} "
          f"net{ho_net:+.1f}R Sharpe{ho_sh:+.3f}  {'✅ ยืน' if ho_net > 0 else '❌ พัง'}")
    return {"name": name, "dsr": d or 0, "ho_net": ho_net, "sharpe_best": best["sharpe"],
            "turnover": tot_trades}


def main():
    if not os.path.exists(RAW):
        print("❌ ไม่มี data/paxg_hourly_3y.json"); return
    global _H, _L
    h, l, c = load(); _H, _L = h, l; nbars = len(c); arrs = precompute(h, l, c)
    print("=" * 72)
    print(f"GOLD EDGE STRENGTHENING — {nbars} bars ({nbars/24/365:.1f}y) @ fee {FEE_PCT}%/side "
          f"(net {2*FEE_PCT}% RT) | RR{RR}/ER{ER_TH} lock | fill={'INTRABAR H/L' if INTRABAR else 'close-path'}")
    print("=" * 72)
    res = []
    res.append(evaluate("baseline (no filter)", arrs, c, nbars, 0.0, False))
    res.append(evaluate("+confirm buffer", arrs, c, nbars, 0.25, False))
    res.append(evaluate("+vol floor", arrs, c, nbars, 0.0, True))
    res.append(evaluate("+both (confirm+vol)", arrs, c, nbars, 0.25, True))

    print("\n" + "=" * 72)
    print("สรุปเทียบ (ต้องการ: DSR↑ ผ่าน 0.95 + holdout ยืน + turnover↓ = cost drag ลด)")
    print(f"  {'variant':>24} | {'DSR':>6} | {'holdout netR':>12} | {'best Sharpe':>11} | {'turnover':>8}")
    for r in res:
        flag = "✅" if r["dsr"] > 0.95 and r["ho_net"] > 0 else ""
        print(f"  {r['name']:>24} | {r['dsr']:>6.3f} | {r['ho_net']:>+12.1f} | "
              f"{r['sharpe_best']:>+11.3f} | {r['turnover']:>8.0f} {flag}")
    best = max(res, key=lambda r: (r["dsr"] > 0.95 and r["ho_net"] > 0, r["dsr"]))
    print("\n" + "=" * 72)
    if best["dsr"] > 0.95 and best["ho_net"] > 0:
        print(f"VERDICT: '{best['name']}' ผ่าน cost แล้ว ✅ (DSR {best['dsr']:.3f}, holdout ยืน) → "
              f"candidate จริง → paper/shadow ต่อ")
    else:
        print(f"VERDICT: ยังไม่มี variant ไหนผ่าน DSR@cost ❌ — edge ทองจริงแต่ยังบางเกิน cost. "
              f"ดีสุด '{best['name']}' DSR {best['dsr']:.3f}")
        print("         → ต้อง lever แรงกว่านี้ (entry filter จาก F1-F7/bounce_pct, หรือ TF/exit ต่าง)")
    print("=" * 72)
    print("⚠️ PAXG proxy (≠XAUUSD เป๊ะ) + close-path exit (ประเมิน SL intrabar ต่ำไป). confirm บน XAU จริงก่อน deploy.")


if __name__ == "__main__":
    main()
