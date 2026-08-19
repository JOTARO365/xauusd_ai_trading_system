#!/usr/bin/env python
"""scripts/tsmom_mine_silver_btc.py — port FROZEN TSMOM-D1 engine (ที่ validate WTI t-สูง) ไป silver/BTC offline.

reuse signal+bar เดียวกับ tsmom_pairs_screen (ensemble vote L=[63,126,252], exit-on-flip, 3×ATR disaster SL,
cost 2×spread, IS/OOS 60/40, deflated bar Bailey/LdP N=6 believe⇔exp_R>bar & n≥100). ต่างแค่ดึง offline
(silver=data/drv_xag daily agg, BTC=scratchpad cache) ไม่แตะ MT5/live. +long-only variant (live LONG_ONLY_ALL).

momentum = ทิศที่ระบบเจอ edge จริง (WTI momentum, tsmom) ต่างจาก UHAS reversion (mine แล้ว null ทุก symbol).
read-only · 0 order. รัน: python scripts/tsmom_mine_silver_btc.py
"""
import json
import math
import os
import sys
from statistics import NormalDist

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import regime_lib as R                                    # noqa: E402
from tsmom_pairs_screen import _c_n, _signal, LOOKBACKS, SL_ATR, N_TRIALS  # noqa: E402

DATA = os.path.join(_BASE, "data")
_CACHE = r"C:\Users\PORNNA~1\AppData\Local\Temp\claude\D--claude-workspace-xauusd-ai-trading-system\8753aacd-c36b-49f7-88e5-e6a3c9fac75f\scratchpad"
DAY = 86400
_Z = NormalDist()


def _rows(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _daily_agg(rows):
    """รวมเป็นแท่งวัน (กันไฟล์ที่ปน intraday): O=first H=max L=min C=last ต่อ date-bucket."""
    buckets = {}
    for r in rows:
        b = int(r[0]) // DAY
        o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
        if b not in buckets:
            buckets[b] = [o, h, l, c]
        else:
            a = buckets[b]; a[1] = max(a[1], h); a[2] = min(a[2], l); a[3] = c
    ks = sorted(buckets)
    hi = np.array([buckets[k][1] for k in ks], float)
    lo = np.array([buckets[k][2] for k in ks], float)
    cl = np.array([buckets[k][3] for k in ks], float)
    return hi, lo, cl


def _sig_lb(close, i, lookbacks):
    votes = 0
    for L in lookbacks:
        if i - L >= 0:
            votes += int(np.sign(close[i] - close[i - L]))
    return "BUY" if votes > 0 else ("SELL" if votes < 0 else "FLAT")


def backtest(high, low, close, point, spread, long_only=False, use_log=False,
             lookbacks=None, n_trials=N_TRIALS):
    """frozen TSMOM-D1 offline. long_only=True → ไม่เข้า SELL. use_log=True → ทำบน log-price
    (R=log-return/ATR_log = stationary สำหรับ asset ที่ราคาโตหลาย order เช่น BTC).
    lookbacks=None → ใช้ frozen [63,126,252]; ระบุเอง = faster-momentum (ต้องขยับ n_trials สำหรับ bar)."""
    lookbacks = lookbacks or LOOKBACKS
    n = len(close)
    if n < max(lookbacks) + 60:
        return {"n": 0, "note": f"underpowered ({n})"}
    if use_log:
        high, low, close = np.log(high), np.log(low), np.log(close)
        cost_px = (spread * point) / np.exp(np.median(close)) * 2   # spread เป็นสัดส่วน log ≈ px-frac
    else:
        cost_px = spread * point * 2
    atr = R.atr(high, low, close)
    cut = int(n * 0.6)
    pos = "FLAT"; entry = sl = risk = 0.0; entry_i = 0
    trades = []

    def _exit(px, at_i):
        sign = 1 if pos == "BUY" else -1
        trades.append((sign * (px - entry) / risk - cost_px / risk, entry_i < cut))

    for i in range(max(lookbacks) + 1, n):
        if pos == "BUY" and low[i] <= sl:
            _exit(sl, i); pos = "FLAT"
        elif pos == "SELL" and high[i] >= sl:
            _exit(sl, i); pos = "FLAT"
        sig = _sig_lb(close, i, lookbacks)
        if long_only and sig == "SELL":
            sig = "FLAT"                                  # live บล็อก short → ถือเงินสด
        if sig != pos:
            if pos != "FLAT":
                _exit(close[i], i); pos = "FLAT"
            if sig != "FLAT" and np.isfinite(atr[i]) and atr[i] > 0:
                entry = close[i]; risk = SL_ATR * atr[i]
                sl = entry - risk if sig == "BUY" else entry + risk
                pos = sig; entry_i = i
    if not trades:
        return {"n": 0, "note": "no trades"}
    allR = np.array([x for x, _ in trades])
    isR = [x for x, s in trades if s]; ooR = [x for x, s in trades if not s]
    exp_R = float(allR.mean()); sd = float(allR.std(ddof=1)) if len(allR) > 1 else 0.0
    sharpe = exp_R / sd if sd > 0 else 0.0
    bar = sd * (_c_n(n_trials) + 1.65) / math.sqrt(len(allR)) if sd > 0 else None
    wr = round(100.0 * sum(1 for x in allR if x > 0) / len(allR), 1)
    return {"n": len(allR), "exp_R": round(exp_R, 3), "sd_R": round(sd, 2), "wr": wr,
            "sharpe": round(sharpe, 3), "t": round(sharpe * math.sqrt(len(allR)), 2),
            "sum_R": round(float(allR.sum()), 1), "bar": round(bar, 3) if bar else None,
            "believe": (bar is not None and exp_R > bar and len(allR) >= 100),
            "is_exp": round(float(np.mean(isR)), 3) if isR else None,
            "oos_exp": round(float(np.mean(ooR)), 3) if ooR else None,
            "years": round(n / 252, 1)}


def _line(tag, d):
    if not d.get("n"):
        print(f"  {tag:22s} {d.get('note','n=0')}"); return
    v = "BELIEVE" if d["believe"] else ("underpowered" if d["n"] < 100 else "reject(<bar)")
    print(f"  {tag:22s} yrs{d['years']:>4.1f} n{d['n']:>4d} exp_R{d['exp_R']:>+7.3f} σ{d['sd_R']:>4.1f} "
          f"t{d['t']:>+5.2f} bar{str(d['bar']):>6s} IS{str(d['is_exp']):>7s} OOS{str(d['oos_exp']):>7s} [{v}]")


def main():
    print("\n=== TSMOM-D1 (frozen engine ที่ validate WTI) บน silver/BTC · offline · exit-on-flip · 3×ATR SL · "
          "net 2×spread · IS/OOS60/40 ===")
    print(f"BELIEVE = exp_R > deflated bar (Bailey/LdP N={N_TRIALS}) AND n≥100. long+short=full(เทียบ WTI) · "
          "long-only=ที่รันได้จริง (LONG_ONLY_ALL)\n")

    print("███ SILVER (drv_xag daily agg · spread=51) ███")
    hi, lo, cl = _daily_agg(_rows(os.path.join(DATA, "drv_xag_h1.json")))
    _line("full (long+short)", backtest(hi, lo, cl, 0.01, 51))
    _line("long-only", backtest(hi, lo, cl, 0.01, 51, long_only=True))

    print("\n███ BTC (cache daily · spread≈30pt · log-price = scale-stationary) ███")
    hi, lo, cl = _daily_agg(_rows(os.path.join(_CACHE, "btc_d1.json")))
    _line("full log (long+short)", backtest(hi, lo, cl, 1.0, 30, use_log=True))
    _line("long-only log", backtest(hi, lo, cl, 1.0, 30, long_only=True, use_log=True))
    k = 2500                                              # ยุคใหม่ (~2019+, BTC $3k-70k ~1 order)
    print(f"  — recent {k}d (ยุค scale เดียว) —")
    _line("recent full log", backtest(hi[-k:], lo[-k:], cl[-k:], 1.0, 30, use_log=True))
    _line("recent long-only log", backtest(hi[-k:], lo[-k:], cl[-k:], 1.0, 30, long_only=True, use_log=True))

    print("\n███ BTC POWER-UP: faster lookbacks (finer TF ดึงไม่ได้=premium/live · เพิ่ม n ด้วย horizon สั้นลงแทน) ███")
    print("  ⚠️ = คนละ horizon กับ D1-trend เดิม + หลาย config → deflation bar ใช้ n_trials=12 (กัน multiple-testing)")
    hi, lo, cl = _daily_agg(_rows(os.path.join(_CACHE, "btc_d1.json")))
    for lb in ([30, 60, 120], [20, 40, 60], [10, 20, 40]):
        _line(f"long-only L={lb}", backtest(hi, lo, cl, 1.0, 30, long_only=True, use_log=True,
                                            lookbacks=lb, n_trials=12))

    print("\n⚠️ frozen config = 1 trial/symbol (bar โฟลด์ multiplicity แล้ว). believe ต้องผ่าน bar+n≥100+IS&OOS บวกทั้งคู่.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
