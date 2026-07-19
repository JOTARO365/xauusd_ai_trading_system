#!/usr/bin/env python
"""
regime_sweep.py — "ปรับแต่ง algo จากผล backtest" แบบมีวินัย (กัน p-hacking).

จูน param ให้ backtest สวย = overfit บน test set = edge ปลอม. วิธีเดียวที่เชื่อได้:
  1. แบ่ง data: TRAIN (เก่า 60%) / TEST (ใหม่ 40%, out-of-sample ไม่เคยเห็น)
  2. sweep grid param → เลือกตัวที่ดีสุด **บน TRAIN เท่านั้น**
  3. รายงาน expR ของตัวชนะ **บน TEST** (OOS) + **นับ trials**
  → best-train ยัง −EV บน TEST = จูนไม่ช่วย (จบ). +EV บน TEST + ผ่าน null = candidate.

หลักฐานเตือน (skill §6): N trials ที่ไม่มี edge จริง คาดหวัง max Sharpe ~ sqrt(2·ln N) จาก noise ล้วน.

รัน:  python scripts\\regime_sweep.py [tf]
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

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

COST = 30
SPLIT_FRAC = 0.60
EMBARGO = 200        # กัน train trade แอบมองเข้า test รอบรอยต่อ

GRIDS = {
    "momentum_breakout": {"BRK_WIN": [10, 20, 40], "ATR_SL": [1.0, 1.5, 2.5], "RR": [1.5, 2.0, 3.0]},
    "mean_reversion":    {"MR_WIN": [10, 20, 40], "S_ENTRY": [1.0, 1.25, 2.0], "MR_HALFLIFE_MAX": [5, 10, 20]},
}
DEFAULTS = {
    "momentum_breakout": {"BRK_WIN": R.BRK_WIN, "ATR_SL": R.ATR_SL, "RR": R.RR},
    "mean_reversion":    {"MR_WIN": R.MR_WIN, "S_ENTRY": R.S_ENTRY, "MR_HALFLIFE_MAX": R.MR_HALFLIFE_MAX},
}


def eval_combo(algo, params, ctx, split_idx):
    """set params → run_algo → split trades ตาม entry index → expR train/test (net cost)."""
    for k, v in params.items():
        setattr(R, k, v)
    trades = BT.run_algo(algo, *ctx)
    tr = [t for t in trades if t["i"] < split_idx - EMBARGO]
    te = [t for t in trades if t["i"] >= split_idx]
    exp_tr = float(BT.net_R(tr, COST).mean()) if tr else float("nan")
    exp_te = float(BT.net_R(te, COST).mean()) if te else float("nan")
    return {"params": dict(params), "n_train": len(tr), "n_test": len(te),
            "exp_train": exp_tr, "exp_test": exp_te}


def sweep_algo(algo, ctx, split_idx):
    grid = GRIDS[algo]
    keys = list(grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*grid.values())]
    results = [eval_combo(algo, p, ctx, split_idx) for p in combos]
    for k, v in DEFAULTS[algo].items():        # คืนค่า default หลัง sweep
        setattr(R, k, v)
    valid = [r for r in results if r["exp_train"] == r["exp_train"] and r["n_train"] >= 50]
    return results, valid


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "h1"
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json")))
    high = np.array([r[2] for r in rows]); low = np.array([r[3] for r in rows]); close = np.array([r[4] for r in rows])
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    ctx = (high, low, close, atr_v, er, adx_v, volpct)
    split_idx = int(len(close) * SPLIT_FRAC)

    print("=" * 80)
    print(f"REGIME SWEEP — OOS discipline | gold {tf.upper()} {len(close)} bars | "
          f"TRAIN[:{split_idx}] / TEST[{split_idx}:] cost={COST}p")
    print("=" * 80)

    for algo in ("momentum_breakout", "mean_reversion"):
        results, valid = sweep_algo(algo, ctx, split_idx)
        if not valid:
            print(f"\n── {algo} ── ไม่มี trade (algo ตัดออกจาก routing แล้ว) — ข้าม")
            continue
        n_trials = len(results)
        default = next(r for r in results if r["params"] == DEFAULTS[algo])
        best = max(valid, key=lambda r: r["exp_train"])            # เลือกจาก TRAIN เท่านั้น
        pos_train = sum(1 for r in valid if r["exp_train"] > 0)
        pos_test  = sum(1 for r in valid if r["exp_test"] > 0)
        noise_sr = np.sqrt(2 * np.log(n_trials))
        print(f"\n── {algo} ── ({n_trials} trials; noise max-Sharpe~{noise_sr:.2f})")
        print(f"  DEFAULT {default['params']}")
        print(f"    train expR={default['exp_train']:+.3f} (N={default['n_train']}) │ "
              f"test expR={default['exp_test']:+.3f} (N={default['n_test']})")
        print(f"  BEST-ON-TRAIN {best['params']}")
        print(f"    train expR={best['exp_train']:+.3f} (N={best['n_train']}) │ "
              f"test expR={best['exp_test']:+.3f} (N={best['n_test']})  <-- OOS")
        print(f"  combos +EV: train {pos_train}/{len(valid)} │ test {pos_test}/{len(valid)}")
        verdict = ("จูนไม่ช่วย — best-on-train ยัง −EV บน TEST (OOS)" if not (best["exp_test"] > 0)
                   else "best-on-train +EV บน TEST → candidate (ต้องผ่าน null test ต่อ)")
        print(f"  → {verdict}")

    print("\n" + "=" * 80)
    print("อ่าน: ถ้า best-on-train ดีขึ้นบน train แต่ −EV บน test = overfitting (จูนจับ noise).")
    print("นี่คือเหตุผลที่ 'จูนจน backtest สวย' อันตราย — ตัวเลข train โกหกได้, test (OOS) คือความจริง.")


if __name__ == "__main__":
    main()
