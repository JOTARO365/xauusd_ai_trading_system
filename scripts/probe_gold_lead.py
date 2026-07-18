#!/usr/bin/env python
"""
probe_gold_lead.py — วัด M15/H1 lead-lag ของ driver ต่อทอง + net-of-spread tradeable test (OFFLINE)

ตอบช่องเดียวที่ deep research ยังไม่เทส: มี driver ไหน "นำ" ทองจริงระดับ M15/H1 + **ชนะ spread** มั้ย?
(deep research refute แค่ tick + monthly; ยืนยัน correlation ส่วนใหญ่ coincident + lead จริงโดน spread กิน).

ใช้ gold (xau_*.json) + driver (drv_*_*.json) จาก **MT5 feed เดียวกัน** (timestamp ตรง align ได้จริง).
ต่อ driver ต่อ TF วัด:
  1) contemporaneous corr (วิ่งพร้อมกันมั้ย)
  2) lead-lag cross-corr (lag>0 = driver นำทอง) → มี lead จริงมั้ย
  3) PREDICTIVE corr(driver[t], gold[t+1]) → tradeable ต้องตัวนี้ ≠ 0
  4) **net-spread test:** expected gold move (points) จาก 1σ driver = |ρ_pred|·σ_gold·price
     เทียบ spread ~30pt → ถ้าน้อยกว่า = โดน spread กิน (ไม่เทรดได้ ตรง Huth&Abergel)
  5) rolling corr stability (คงที่ตาม regime มั้ย)

รัน: python scripts\\probe_gold_lead.py            (spread 30pt)
     python scripts\\probe_gold_lead.py 40
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POINT = 0.01
SPREAD_PT = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
MAX_LAG = 6
ROLL_W = {"m15": 480, "h1": 240}   # ~5 วัน m15 / ~10 วัน h1


def load(path):
    if not os.path.exists(path):
        return None
    rows = json.load(open(path))
    return {int(r[0]): float(r[4]) for r in rows}   # {epoch: close}


def aligned_ret(a, b):
    ts = sorted(set(a) & set(b))
    if len(ts) < 200:
        return None, None, None
    ca = np.array([a[t] for t in ts]); cb = np.array([b[t] for t in ts])
    ra = np.diff(ca) / ca[:-1]; rb = np.diff(cb) / cb[:-1]
    return ra, rb, ca[-1]


def corr(x, y):
    if len(x) < 20 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def lead_lag(rg, rd, max_lag=MAX_LAG):
    """lag>0 = driver นำ gold (driver[t-lag] ~ gold[t]). คืน best lead + table."""
    best = (0, 0.0)
    tbl = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:    x, y = rd[:-lag], rg[lag:]
        elif lag < 0:  x, y = rd[-lag:], rg[:lag]
        else:          x, y = rd, rg
        c = corr(x, y); tbl[lag] = c
        if not np.isnan(c) and abs(c) > abs(best[1]):
            best = (lag, c)
    return best, tbl


def main():
    print("=" * 78)
    print(f"GOLD LEAD-LAG PROBE — driver นำทองระดับ M15/H1 + net-spread {SPREAD_PT}pt tradeable test")
    print("=" * 78)
    meta_p = os.path.join(_BASE, "data", "drv_meta.json")
    if not os.path.exists(meta_p):
        print("❌ ไม่มี data/drv_meta.json — รัน scripts/export_drivers.py (MT5) ก่อน"); return
    drivers = json.load(open(meta_p)).get("drivers", {})
    print(f"drivers: {', '.join(drivers) or '—'}\n")

    any_tradeable = False
    for tf in ("m15", "h1"):
        gold = load(os.path.join(_BASE, "data", f"xau_{tf}.json"))
        if gold is None:
            print(f"[{tf.upper()}] ไม่มี xau_{tf}.json — ข้าม\n"); continue
        print(f"── {tf.upper()} ──")
        print(f"  {'driver':>8} | {'contemp':>7} | {'best lead':>16} | {'ρ_pred(t→t+1)':>13} | "
              f"{'exp move':>9} | tradeable?")
        print("  " + "-" * 78)
        for grp in drivers:
            drv = load(os.path.join(_BASE, "data", f"drv_{grp.lower()}_{tf}.json"))
            if drv is None:
                print(f"  {grp:>8} | ไม่มีไฟล์"); continue
            rg, rd, gprice = aligned_ret(gold, drv)
            if rg is None:
                print(f"  {grp:>8} | overlap น้อยเกิน"); continue
            c0 = corr(rg, rd)
            (blag, bc), _ = lead_lag(rg, rd)
            # predictive: driver[t] → gold[t+1]
            pred = corr(rd[:-1], rg[1:])
            # net-spread: expected gold move (points) จาก 1σ driver signal
            exp_move_pt = abs(pred) * np.std(rg) * gprice / POINT
            tradeable = exp_move_pt > SPREAD_PT and abs(pred) > 0.03 and blag > 0
            if tradeable:
                any_tradeable = True
            lead_txt = (f"driver นำ {blag} ({bc:+.2f})" if blag > 0
                        else f"ทองนำ {-blag} ({bc:+.2f})" if blag < 0 else f"sync ({bc:+.2f})")
            print(f"  {grp:>8} | {c0:>+7.2f} | {lead_txt:>16} | {pred:>+13.3f} | "
                  f"{exp_move_pt:>7.1f}pt | {'✅ อาจได้' if tradeable else '❌ (โดน spread/ไม่นำ)'}")
        # rolling stability ของ driver แรก (ดู regime drift)
        print()

    print("=" * 78)
    if any_tradeable:
        print("VERDICT: เจอ driver ที่นำทอง + exp move > spread ⚠️ → ต้อง validate เต็ม (OOS+DSR+PBO+net cost)")
        print("         ก่อนเชื่อ — อย่าลืมบทเรียน close-path/drift; นี่แค่ screening.")
    else:
        print("VERDICT: ไม่มี driver ไหนนำทอง + ชนะ spread ที่ M15/H1 ❌")
        print("         → ยืนยัน deep research: external = coincident/regime-context ไม่ใช่ intraday lead.")
        print("         ปิดช่องสุดท้าย. external data ใช้เป็น regime filter (dashboard GOLD REGIME) พอ.")
    print("=" * 78)
    print(f"อ่าน: contemp=corr พร้อมกัน | best lead: lag>0=driver นำ | ρ_pred=driver[t]→gold[t+1] (tradeable ต้อง≠0)")
    print(f"exp move = |ρ_pred|·σ_gold·price (points ที่คาดจาก 1σ driver) vs spread {SPREAD_PT}pt. rolling corr = regime drift.")


if __name__ == "__main__":
    main()
