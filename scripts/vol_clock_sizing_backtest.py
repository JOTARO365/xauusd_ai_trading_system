#!/usr/bin/env python
"""scripts/vol_clock_sizing_backtest.py — Candidate #3: vol-clock as SIZING filter (ไม่ใช่ entry).

ไอเดีย (จาก UHAS "ความผันผวนข้างหน้า · ชม.แรงสุด 20:00 · วันนี้ ×1.21"): ปรับขนาด position ตาม vol คาด
(vol-targeting) — vol สูง=ย่อ lot, vol ต่ำ=เพิ่ม → ยก risk-adjusted return (Sharpe) โดยไม่แตะ entry.
เทส 3 ชั้น: (1) premise ทองมี vol-clock จริงไหม + vol predictable ไหม (2) sizing เทียบ constant vs
inverse-vol vs vol-clock บน position ทองจริง หัก cost turnover, in+OOS (3) clock ชนะ generic trailing-vol ไหม.

⚠️ ถึงผ่าน = money-mgmt change (iron rule) ชน LOT_MODE fixed → proposal/shadow ไม่ auto-live.
causal (σ_{t-1}→ret_t · hour factor จาก train เท่านั้น) · cost บน |Δw| · OOS70/30.
read-only · offline (data/xau_h1.json) · 0 token. รัน: python scripts/vol_clock_sizing_backtest.py
"""
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(_ROOT, "data")
BARS_PER_YEAR = 24 * 252                                       # H1 → annualize Sharpe
LEV_CAP = (0.33, 3.0)                                          # กัน size โดดเกินจริง
COST_PER_TURN = 0.0002                                         # realistic: gold spread ~$0.30 บนราคา ~$1.5-4k ≈ 0.0001-0.0002/Δw
DEADBAND = 0.20                                                # resize เฉพาะเมื่อ target เปลี่ยน >20% (เลียนการตั้ง lot ตอนเข้าไม้ ไม่ปรับราย ชม.)


def _load():
    with open(os.path.join(DATA, "xau_h1.json"), "r", encoding="utf-8") as f:
        d = json.load(f)
    t = np.array([int(x[0]) for x in d])
    c = np.array([float(x[4]) for x in d], float)
    return t, c


def _sharpe(r):
    r = np.asarray(r, float)
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(BARS_PER_YEAR)) if sd > 0 else 0.0


def _maxdd(r):
    eq = np.cumsum(np.asarray(r, float))
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min())


def _summ(label, r, w):
    r = np.asarray(r, float)
    wd = _deadband(np.clip(w, *LEV_CAP))                       # แสดง lev/turn จาก w ที่ execute จริง
    sh = _sharpe(r); dd = _maxdd(r); term = float(r.sum())
    k = int(len(r) * 0.7)
    sh_oos = _sharpe(r[k:])
    print(f"  {label:26s} Sharpe {sh:+5.2f} (OOS {sh_oos:+5.2f})  sumRet {term:+7.3f}  maxDD {dd:+6.2f}  "
          f"avgLev {np.mean(wd):.2f}  turn {np.abs(np.diff(wd)).sum():.0f}")
    return sh, sh_oos


def _deadband(w, band=DEADBAND):
    """คง w เดิมจนกว่า target จะเปลี่ยน >band (เลียนการตั้ง lot ตอนเข้าไม้ ไม่ rebalance ราย ชม.)."""
    out = np.empty_like(w); cur = w[0]
    for i in range(len(w)):
        if cur <= 0 or abs(w[i] / cur - 1.0) > band:
            cur = w[i]
        out[i] = cur
    return out


def _apply(pos, ret, w, cost=COST_PER_TURN):
    """return stream ของ position*size หัก cost บนการเปลี่ยน size (|Δw|). w ผ่าน deadband+cap."""
    w = _deadband(np.clip(w, *LEV_CAP))
    dw = np.abs(np.diff(np.concatenate([[0.0], w])))
    gross = pos * w * ret
    return gross - dw * cost


def main():
    t, c = _load()
    ret = np.concatenate([[0.0], np.diff(np.log(c))])          # log-ret รายชั่วโมง
    aret = np.abs(ret)
    hours = np.array([datetime.fromtimestamp(int(ts), timezone.utc).hour for ts in t])
    n = len(c)
    print(f"\n=== VOL-CLOCK SIZING backtest (XAU H1 · vol-targeting · causal · cost บน Δw · OOS70/30) ===")
    print(f"bars={n}\n")

    # ── (1) PREMISE ──
    print("── (1) PREMISE: ทองมี vol-clock + vol predictable ไหม ──")
    med = np.median(aret[aret > 0])
    print("  hour-of-day |ret| (× median, UTC):")
    line = ""
    for hh in range(24):
        m = aret[hours == hh]
        fac = (np.mean(m) / med) if len(m) and med > 0 else 0.0
        line += f"{hh:02d}:{fac:.2f} "
        if hh % 8 == 7:
            print("   ", line); line = ""
    # vol autocorrelation (predictability)
    ac = [float(np.corrcoef(aret[k:], aret[:-k])[0, 1]) for k in (1, 6, 24)]
    print(f"  |ret| autocorr  lag1 {ac[0]:+.3f}  lag6 {ac[1]:+.3f}  lag24 {ac[2]:+.3f}  "
          f"({'predictable' if ac[0] > 0.05 else 'ไม่ค่อย predictable'})")

    # trailing realized vol (causal, EWMA-ish rolling std of ret)
    win = 72
    sig = np.full(n, np.nan)
    for i in range(win, n):
        sig[i] = ret[i - win:i].std()
    sig_med = np.nanmedian(sig)

    # hour factor จาก TRAIN portion เท่านั้น (causal OOS)
    ktrain = int(n * 0.7)
    hfac = np.ones(24)
    for hh in range(24):
        m = aret[:ktrain][hours[:ktrain] == hh]
        hfac[hh] = (np.mean(m) / np.mean(aret[:ktrain])) if len(m) else 1.0

    # ── (2) SIZING เทียบบน position ทองจริง (long-momentum: long เมื่อ close>SMA200 ไม่งั้น flat) ──
    sma = np.full(n, np.nan)
    W2 = 200
    for i in range(W2, n):
        sma[i] = c[i - W2:i].mean()
    pos = np.where((~np.isnan(sma)) & (c > sma), 1.0, 0.0)
    pos = np.concatenate([[0.0], pos[:-1]])                    # ถือจากแท่งก่อน (causal)

    start = max(win, W2) + 1
    sl = slice(start, n)
    p = pos[sl]; rr = ret[sl]; sg = sig[sl]; hf = hfac[hours[sl]]

    w_const = np.ones(len(rr))
    w_ivol = np.where(sg > 0, sig_med / sg, 1.0)               # generic inverse trailing-vol
    w_clock = np.where(sg > 0, sig_med / (sg * hf), 1.0)       # inverse (trailing-vol × hour factor)

    print("\n── (2) SIZING บน gold long-momentum (SMA200) · หัก cost turnover · long-only ──")
    print("  gate: vol-scaling ต้องยก Sharpe เหนือ constant + OOS ยืน + ไม่พังจาก cost")
    s_c, o_c = _summ("constant (baseline)", _apply(p, rr, w_const), w_const)
    s_i, o_i = _summ("inverse-vol (generic)", _apply(p, rr, w_ivol), w_ivol)
    s_k, o_k = _summ("vol-clock (hour-aware)", _apply(p, rr, w_clock), w_clock)

    # ── (2b) บน buy&hold ทอง (pure vol-targeting demo) ──
    ph = np.ones(len(rr))
    print("\n── (2b) SIZING บน buy&hold ทอง (pure vol-targeting) ──")
    _summ("constant (baseline)", _apply(ph, rr, w_const), w_const)
    _summ("inverse-vol (generic)", _apply(ph, rr, w_ivol), w_ivol)
    _summ("vol-clock (hour-aware)", _apply(ph, rr, w_clock), w_clock)

    print("\n── VERDICT ──")
    imp_i = s_i - s_c; imp_k = s_k - s_c; clk = s_k - s_i
    print(f"  inverse-vol ยก Sharpe {imp_i:+.2f} (OOS {o_i - o_c:+.2f}) · vol-clock ยก {imp_k:+.2f} (OOS {o_k - o_c:+.2f})")
    print(f"  clock เพิ่มเหนือ generic: {clk:+.2f}  → {'clock คุ้ม' if clk > 0.1 else 'clock ไม่เพิ่ม (generic พอ)'}")
    print("  ⚠️ vol-targeting = risk tool ไม่ใช่ alpha; ไม่สร้าง edge ที่ไม่มี. ถึงยก Sharpe ก็ยังเป็น money-mgmt (iron rule).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
