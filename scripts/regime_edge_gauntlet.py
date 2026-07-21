#!/usr/bin/env python
"""regime_edge_gauntlet.py — หา edge จาก vol/regime: กลยุทธ์ทิศ (momentum/mean-rev) ทำงานเฉพาะ regime ไหน?

⚠️ OFFLINE. หลัก (skill §5 + Chan): volatility ทำนายได้ ทิศไม่ได้ → edge (ถ้ามี) = กลยุทธ์ทิศที่ทำงาน
"เฉพาะ vol-regime ที่เหมาะ" (momentum ใน high-vol/trending, mean-rev ใน low-vol/ranging).
เทสต์ momentum_breakout + mean_reversion **แยกตาม vol_percentile bucket** (low/mid/high) → EV/WR/PSR/null/OOS.

เจอ (regime × กลยุทธ์) ที่ +EV + PSR>0.95 + ชนะ null + OOS ยืน = regime-routed edge (คุ้มทำต่อ).
รัน: & $PY scripts\regime_edge_gauntlet.py
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MAX_HOLD = 24
LO, HI = 0.33, 0.67          # vol_percentile terciles → low / mid / high vol


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4]


def _bucket(vp):
    if not np.isfinite(vp):
        return None
    return "low-vol" if vp < LO else ("high-vol" if vp > HI else "mid-vol")


def gen(high, low, close, atr_v, er, adx_v, volpct, strat, random_time=False, seed=0):
    """สร้างสัญญาณ strat ทุกบาร์ + bucket ตาม vol. random_time=null (เข้าบาร์สุ่มแทน). คืน list (bucket, trade)."""
    rng = np.random.RandomState(seed)
    n = len(close); start = max(R.VOL_LOOKBACK, R.BRK_WIN, R.MR_WIN) + 2
    out = []
    for i in range(start, n - 1):
        if strat == "momentum":
            sig = R.algo_momentum_breakout(i, high, low, close, atr_v)
        else:
            sig = R.algo_mean_reversion(i, close, atr_v)
        if not sig:
            continue
        buck = _bucket(volpct[i])
        if buck is None:
            continue
        entry_i = rng.randint(start, n - 1) if random_time else i     # null = timing สุ่ม
        mh = sig.get("max_hold_bars", MAX_HOLD)
        r_g, bars, mfe, mae, why = BT.simulate_trade(entry_i, sig["dir"], sig["sl_pips"], sig["tp_pips"],
                                                     mh, high, low, close)
        out.append((buck, {"i": i, "dir": sig["dir"], "sl_pips": sig["sl_pips"], "R_gross": r_g, "why": why}))
    return out


def main():
    high, low, close = _load()
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    n = len(close); split = int(n * 0.6)
    print("=" * 88)
    print(f"REGIME-EDGE GAUNTLET — กลยุทธ์ทิศ × vol-regime | gold H1 {n} bars | intrabar+cost, null=timing สุ่ม")
    print("=" * 88)
    for strat in ("momentum", "mean_rev"):
        real = gen(high, low, close, atr_v, er, adx_v, volpct, strat)
        null = gen(high, low, close, atr_v, er, adx_v, volpct, strat, random_time=True, seed=1)
        print(f"\n── {strat} ── ({len(real)} signals)")
        print(f"  {'vol-regime':>10} | {'N':>5} {'WR':>6} {'expR@30p':>9} {'PSR0':>6} | {'null':>8} | {'OOS-out':>9}")
        for buck in ("low-vol", "mid-vol", "high-vol"):
            rt = [t for b, t in real if b == buck]
            nt = [t for b, t in null if b == buck]
            if len(rt) < BT.MIN_N:
                print(f"  {buck:>10} | N={len(rt)} < {BT.MIN_N} — noise"); continue
            s = BT.summarize(buck, rt, 30)
            ns = BT.summarize("n", nt, 30) if len(nt) >= 30 else {"exp_R": float("nan")}
            out = [t for t in rt if t["i"] >= split]
            so = BT.summarize("o", out, 30) if len(out) >= 30 else {"exp_R": float("nan")}
            edge = s["exp_R"] > 0 and s["exp_R"] > ns["exp_R"] and so["exp_R"] > 0 and s["psr0"] > 0.90
            print(f"  {buck:>10} | {s['n']:>5} {s['wr']*100:5.1f}% {s['exp_R']:>+9.3f} {s['psr0']:>6.2f} | "
                  f"{ns['exp_R']:>+8.3f} | {so['exp_R']:>+8.3f} {'✅ EDGE!' if edge else ''}")
    print("\n" + "=" * 88)
    print("เจอ ✅ EDGE (expR>0 + ชนะ null + OOS ยืน + PSR>0.9) = regime-routed edge จริง → ทำต่อ (calibrate+sweep)")
    print("ถ้าไม่มี = ทิศไม่มี edge แม้แยก regime → เหลือแค่ vol-sizing/risk-mgmt (ไม่ใช่ directional)")


if __name__ == "__main__":
    main()
