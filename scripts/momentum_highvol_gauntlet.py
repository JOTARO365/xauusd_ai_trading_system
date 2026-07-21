#!/usr/bin/env python
"""momentum_highvol_gauntlet.py — พิสูจน์ lead สุดท้าย: momentum breakout เฉพาะ high-vol มี edge จริงไหม?

⚠️ OFFLINE. lead: regime-edge gauntlet โชว์ momentum high-vol OOS +0.035 (แม้ full −EV). อาจ edge จริง หรือ
regime shift ช่วงหลัง. อันนี้ full gauntlet + **quartile consistency** (แบ่ง 4 ช่วงเวลา — edge จริง=บวกหลายช่วง;
regime shift=บวกแค่ช่วงหลัง) + null + vol-threshold sweep.

รัน: & $PY scripts\momentum_highvol_gauntlet.py
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


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4]


def gen(high, low, close, atr_v, volpct, vth, random_time=False, seed=0):
    """momentum breakout เฉพาะ volpct > vth. random_time=null. คืน trades (มี i สำหรับ OOS/quartile)."""
    rng = np.random.RandomState(seed)
    n = len(close); start = max(R.VOL_LOOKBACK, R.BRK_WIN) + 2
    out = []
    for i in range(start, n - 1):
        if not (volpct[i] > vth):
            continue
        sig = R.algo_momentum_breakout(i, high, low, close, atr_v)
        if not sig:
            continue
        ei = rng.randint(start, n - 1) if random_time else i
        r_g, bars, mfe, mae, why = BT.simulate_trade(ei, sig["dir"], sig["sl_pips"], sig["tp_pips"],
                                                     MAX_HOLD, high, low, close)
        out.append({"i": ei, "src_i": i, "dir": sig["dir"], "sl_pips": sig["sl_pips"],
                    "R_gross": r_g, "why": why})
    return out


def main():
    high, low, close = _load()
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    n = len(close)
    print("=" * 84)
    print(f"MOMENTUM × HIGH-VOL GAUNTLET | gold H1 {n} bars | intrabar+cost, null=timing สุ่ม, RR2")
    print("=" * 84)

    for vth in (0.50, 0.67, 0.80):
        real = gen(high, low, close, atr_v, volpct, vth)
        if len(real) < BT.MIN_N:
            print(f"\nvol>{vth}: N={len(real)} < {BT.MIN_N} — noise"); continue
        null = gen(high, low, close, atr_v, volpct, vth, random_time=True, seed=1)
        print(f"\n── momentum vol>{vth} ── ({len(real)} signals)")
        for c in BT.COST_PIPS_GRID:
            BT.print_row(BT.summarize(f"v{vth}", real, c))
        ns = BT.summarize("null", null, 30)
        print(f"  null(timing สุ่ม) @30p: expR={ns['exp_R']:+.3f} WR={ns['wr']*100:.1f}%")
        # quartile consistency (แบ่ง 4 ช่วงเวลาตาม src_i) — edge จริง=บวกหลายช่วง
        print("  ── consistency 4 ช่วงเวลา (expR@30p) — edge จริง=บวกสม่ำเสมอ, regime-shift=บวกแค่ช่วงท้าย ──")
        qs = []
        for q in range(4):
            lo, hi = n * q // 4, n * (q + 1) // 4
            seg = [t for t in real if lo <= t["src_i"] < hi]
            if len(seg) >= 30:
                s = BT.summarize("q", seg, 30)
                qs.append(f"Q{q+1}({len(seg)}): {s['exp_R']:+.3f}")
            else:
                qs.append(f"Q{q+1}: N<30")
        print("    " + " | ".join(qs))
    print("\n" + "=" * 84)
    print("ผ่าน = expR>0 ทุก cost + PSR>0.95 + ชนะ null + **บวกหลาย quartile** (ไม่ใช่แค่ Q4). ไม่งั้น = regime shift/noise")


if __name__ == "__main__":
    main()
