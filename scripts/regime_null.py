#!/usr/bin/env python
"""
regime_null.py — NULL test (block-bootstrap) สำหรับ momentum: edge มาจากเทรนด์จริง หรือ artifact?

trend-following กินกำไรจาก "เทรนด์ยาว" (autocorrelation). ทดสอบโดย **block-bootstrap** สลับลำดับ block
ของ bar (คง per-bar return + intrabar range ไว้ แต่ **ทำลายเทรนด์ที่ยาวกว่า block**) → รัน algo เดิม
→ null distribution ของ expR. ถ้า real expR เหนือ null p95 = edge มาจากเทรนด์จริง (ไม่ใช่ drift/artifact).
(บทเรียน session: "+0.030R" เคย = null mean +0.027 → artifact. gate นี้กันซ้ำ.)

รัน:  python scripts\\regime_null.py [tf] [n_boot] [block]     (default d1 300 20)
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
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

COST = 30
ALGO = "momentum_breakout"


def _expR(high, low, close):
    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    trades = BT.run_algo(ALGO, high, low, close, atr_v, er, adx_v, volpct)
    if len(trades) < 30:
        return np.nan, len(trades)
    return float(BT.net_R(trades, COST).mean()), len(trades)


def block_synth(logret, hr, lor, blk, rng):
    """สร้าง synth series โดยสุ่ม circular block ของ bar (คง return+intrabar ratio, สลับลำดับ)."""
    n = len(logret)
    idx = []
    while len(idx) < n:
        start = rng.integers(0, n)
        idx.extend((start + k) % n for k in range(blk))
    idx = np.array(idx[:n])
    close = np.empty(n); close[0] = 100.0
    lr = logret[idx]
    close[1:] = 100.0 * np.exp(np.cumsum(lr[1:]))
    high = close * hr[idx]
    low = close * lor[idx]
    return high, low, close


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "d1"
    B = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    blk = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    rows = json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json")))
    high = np.array([r[2] for r in rows], float); low = np.array([r[3] for r in rows], float)
    close = np.array([r[4] for r in rows], float)

    real, n_real = _expR(high, low, close)
    logret = np.concatenate([[0.0], np.diff(np.log(close))])
    hr = high / close; lor = low / close       # intrabar ratio ต่อ bar (คงรูปแท่ง)
    rng = np.random.default_rng(12345)          # seed คงที่ = reproducible

    print("=" * 70)
    print(f"NULL TEST — {ALGO} | gold {tf.upper()} {len(close)} bars | block-bootstrap B={B} blk={blk}")
    print("=" * 70)
    print(f"REAL: expR={real:+.3f} (N={n_real} trades, cost={COST}p)")

    null = []
    for b in range(B):
        h, l, c = block_synth(logret, hr, lor, blk, rng)
        e, _ = _expR(h, l, c)
        if e == e:
            null.append(e)
    null = np.array(null)
    p95 = np.percentile(null, 95); p99 = np.percentile(null, 99)
    pval = float((null >= real).mean())
    print(f"NULL: mean={null.mean():+.3f} std={null.std():.3f} p95={p95:+.3f} p99={p99:+.3f}  ({len(null)} valid)")
    print(f"\np-value  P(null ≥ real) = {pval:.3f}")
    if pval < 0.05 and real > p95:
        print("→ ✅ real เหนือ null p95 (p<0.05): edge มาจากเทรนด์จริง ไม่ใช่ artifact")
    else:
        print("→ ❌ real ไม่พ้น null: edge อธิบายได้ด้วย vol/return structure ล้วน (ระวัง artifact)")
    print("\nหมายเหตุ: N เล็ก → null test บอกแค่ 'ไม่ใช่ artifact'; ยัง = ต้อง shadow forward-test ยืนยันบน live")


if __name__ == "__main__":
    main()
