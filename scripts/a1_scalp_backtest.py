#!/usr/bin/env python
"""a1_scalp_backtest.py — A1 band-edge scalp proper net-of-cost backtest (Phase 0 redesign: structure-gate).

Phase 0 พบ: gate ที่ regime label = โมฆะ (noisy); gate ที่ box-STRUCTURE = 81% reversion proxy.
อันนี้คือ test จริง: LIMIT entry ที่ box edge (Donchian≥2500p), SL 25%w beyond edge, TP 30%w toward mid,
**TP-before-SL intrabar pessimistic**, net spread 31p → WR/expR จริง vs breakeven 48.6%. + OOS 60/40 + quartile.
measure-only. RR = 0.30/0.25 = 1.2 (breakeven 45.5% gross, ~48.6% net).
รัน: & $PY scripts\a1_scalp_backtest.py
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

POINT = R.POINT
DON = 20
WIDTH_MIN = 2500          # box width floor (points)
TP_FRAC = 0.30            # TP = 30% width toward mid
SL_FRAC = 0.25            # SL = 25% width beyond edge
FILL_WIN = 6             # limit fill ภายใน 6 บาร์ (TTL) ไม่งั้น cancel
COOL = 6
MAXHOLD = 60
COSTS = [31, 40, 20]      # spread grid (31 measured floor)


def _load():
    d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
    return d[:, 2], d[:, 3], d[:, 4]


def _sim(fi, entry, direction, sl, tp, high, low, close):
    """TP-before-SL intrabar จาก fill bar (pessimistic: SL_TP บาร์เดียว → SL). คืน (R_gross, why)."""
    sign = 1.0 if direction == "BUY" else -1.0
    risk = abs(entry - sl)
    end = min(fi + MAXHOLD, len(close) - 1)
    for j in range(fi, end + 1):
        hit_sl = low[j] <= sl if direction == "BUY" else high[j] >= sl
        hit_tp = high[j] >= tp if direction == "BUY" else low[j] <= tp
        if hit_sl and hit_tp:
            return -1.0, "SL_TP"
        if hit_sl:
            return -1.0, "SL"
        if hit_tp:
            return round((tp - entry) / risk * sign, 3), "TP"
    return round(sign * (close[end] - entry) / risk, 3), "TIME"


def gen(high, low, close, random_time=False, seed=0):
    """box edge limit-fade. random_time = null (fill bar สุ่ม)."""
    rng = np.random.RandomState(seed); n = len(close); out = []; last = -10 ** 9
    for i in range(DON, n - FILL_WIN):
        if i - last < COOL:
            continue
        bh = high[i - DON:i].max(); bl = low[i - DON:i].min(); w = bh - bl
        if w / POINT < WIDTH_MIN:
            continue
        fill = None
        for j in range(i, min(i + FILL_WIN, n)):           # limit fill แรก (touch edge)
            if low[j] <= bl:
                fill = (j, "BUY", bl); break
            if high[j] >= bh:
                fill = (j, "SELL", bh); break
        if not fill:
            continue
        fj, d, edge = fill
        if d == "BUY":
            sl = bl - SL_FRAC * w; tp = bl + TP_FRAC * w
        else:
            sl = bh + SL_FRAC * w; tp = bh - TP_FRAC * w
        ei = int(rng.randint(DON, n - 1)) if random_time else fj
        r, why = _sim(ei, edge, d, sl, tp, high, low, close)
        out.append({"i": ei, "dir": d, "sl_pips": max(1, round(abs(edge - sl) / POINT)),
                    "R_gross": r, "why": why}); last = fj
    return out


def main():
    high, low, close = _load()
    n = len(close)
    trades = gen(high, low, close)
    null = gen(high, low, close, random_time=True, seed=1)
    print("=" * 90)
    print(f"A1 BAND-EDGE SCALP — net-of-cost | gold H1 {n} bars | box≥{WIDTH_MIN}p, RR {TP_FRAC/SL_FRAC:.1f} (breakeven gross 45.5%)")
    print("=" * 90)
    if len(trades) < BT.MIN_N:
        print(f"N={len(trades)} < {BT.MIN_N}"); return
    print(f"{'cost':>5}{'N':>6}{'WR':>7}{'expR':>9}{'Sharpe':>8}{'PSR':>6}{'sumR':>8}{'breakeven_net':>15}  verdict")
    for c in COSTS:
        s = BT.summarize("a1", trades, c)
        be_net = 1 / (1 + (TP_FRAC / SL_FRAC)) + c / (abs(TP_FRAC / SL_FRAC) * 1000)  # approx net breakeven
        # exact net breakeven WR: WR·(RR − c/risk_avg) − (1−WR)·(1+c/risk_avg) = 0
        avg_slp = np.mean([t["sl_pips"] for t in trades])
        cR = c / avg_slp
        rr = TP_FRAC / SL_FRAC
        be = (1 + cR) / (1 + rr)                            # net breakeven WR
        v = "＋EV" if s["exp_R"] > 0 else "－EV"
        print(f"{c:>5}{s['n']:>6}{s['wr']*100:>6.1f}%{s['exp_R']:>+9.3f}{s['sharpe']:>+8.3f}"
              f"{s['psr0']:>6.2f}{s['sum_R']:>+8.1f}{be*100:>13.1f}%  {v} (WR {'>' if s['wr']>be else '<'} breakeven)")
    # OOS + quartile + null (ที่ cost 31)
    split = int(n * 0.6)
    oos = [t for t in trades if t["i"] >= split]
    so = BT.summarize("oos", oos, 31) if len(oos) >= 30 else {"exp_R": float("nan"), "wr": float("nan")}
    ns = BT.summarize("null", null, 31)
    print(f"\nOOS(40%): WR {so['wr']*100:.1f}% expR {so['exp_R']:+.3f} | null(timing สุ่ม): WR {ns['wr']*100:.1f}% expR {ns['exp_R']:+.3f}")
    qs = []
    for q in range(4):
        lo, hi = n * q // 4, n * (q + 1) // 4
        seg = [t for t in trades if lo <= t["i"] < hi]
        qs.append(BT.summarize("q", seg, 31)["exp_R"] if len(seg) >= 25 else float("nan"))
    print("quartile expR@31p: " + " ".join(f"Q{i+1}:{v:+.3f}" for i, v in enumerate(qs)))
    print("\n" + "=" * 90)
    s31 = BT.summarize("a1", trades, 31)
    print(f"VERDICT: WR net {s31['wr']*100:.1f}%, expR {s31['exp_R']:+.3f}, PSR {s31['psr0']:.2f}, ชนะ null: {s31['exp_R']>ns['exp_R']}")
    print("ผ่าน = WR > breakeven net + expR>0 + PSR>0.95 + OOS>0 + ชนะ null + quartile บวก. ไม่งั้น A1 ตายด้วย")


if __name__ == "__main__":
    main()
