"""scripts/regime_gate_test.py — A1: regime-gate momentum test (user 08-09, จาก quant-sat ch10 Hurst).

Hypothesis: gold momentum breakout กินเงินตอน "trend regime" เสียตอน "chop" → ถ้า gate เข้าเฉพาะตอน
Hurst>0.5 (trending) จะ exp_R ดีขึ้น. พิสูจน์ก่อนแตะ gate จริง (validation-first).

วิธี: Donchian breakout บนทอง H1 (causal) → ที่ entry คำนวณ Hurst + realized-vol ของ window ก่อนหน้า
→ resolve trade (causal, RR2 fixed, structural SL, timeout) → bucket exp_R/WR/t ตาม regime → เทียบ.
read-only. 0 token. standalone: python scripts/regime_gate_test.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from scripts.cointegration_scan import _hurst  # noqa: E402

BRK = 48          # Donchian breakout window (H1)
SL_LB = 24        # structural SL lookback
RR = 2.0
MH = 120          # max hold
HURST_WIN = 250   # window คำนวณ Hurst ที่ entry
VOL_WIN = 48


def _cost_price(mt5, sym):
    try:
        from agents import shadow_cost as sc
        return float(sc.cost_price(sym))
    except Exception:
        si = mt5.symbol_info(sym)
        return (si.spread * si.point) if si else 0.0


def _stats(Rs):
    if len(Rs) < 3:
        return {"n": len(Rs), "exp_R": None, "wr": None, "t": None}
    a = np.array(Rs, float); sd = a.std(ddof=1)
    return {"n": len(a), "exp_R": round(float(a.mean()), 4),
            "wr": round(float((a > 0).mean()) * 100, 1),
            "t": round(float(a.mean() / (sd / math.sqrt(len(a)))), 2) if sd > 0 else 0.0}


def run():
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    if not mt5.initialize():
        print("MT5 init fail"); return
    bm = _broker_map() or {}
    sym = bm.get("XAUUSD", "XAUUSD"); mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
    mt5.shutdown()
    if r is None or len(r) < 2000:
        print("data ไม่พอ"); return
    c = r["close"].astype(float); h = r["high"].astype(float); l = r["low"].astype(float)
    n = len(c)
    cost = 0.30  # ~spread ทอง (price units) — conservative
    # rolling Donchian extremes (prev BRK bars)
    hi = np.full(n, np.nan); lo = np.full(n, np.nan)
    for i in range(BRK, n):
        hi[i] = h[i - BRK:i].max(); lo[i] = l[i - BRK:i].min()

    trades = []   # (R, hurst, vol)
    i = HURST_WIN + 1
    while i < n - 1:
        if not (np.isfinite(hi[i]) and np.isfinite(lo[i])):
            i += 1; continue
        px = c[i]
        direction = 1 if px > hi[i] else (-1 if px < lo[i] else 0)
        if direction == 0:
            i += 1; continue
        # regime features ที่ entry (causal — window ก่อน i)
        hurst = _hurst(c[i - HURST_WIN:i])
        vol = float(np.std(np.diff(np.log(c[i - VOL_WIN:i])))) if i > VOL_WIN else 0.0
        seg = c[max(0, i - SL_LB):i + 1]
        slp = seg.min() if direction == 1 else seg.max()
        risk = (px - slp) if direction == 1 else (slp - px)
        if risk <= 0.5:
            i += 1; continue
        tp = px + direction * RR * risk
        # resolve causal
        R = None
        for j in range(i + 1, min(i + MH, n)):
            if direction == 1:
                if c[j] <= slp: R = -(risk + cost) / risk; break
                if c[j] >= tp: R = (RR * risk - cost) / risk; break
            else:
                if c[j] >= slp: R = -(risk + cost) / risk; break
                if c[j] <= tp: R = (RR * risk - cost) / risk; break
        if R is None:
            R = ((c[min(i + MH, n - 1)] - px) * direction - cost) / risk   # timeout mark-out
        trades.append((R, hurst, vol))
        i += 1                                        # allow re-entry next bar (matches breakout family)

    Rall = [t[0] for t in trades]
    Rtrend = [t[0] for t in trades if t[1] > 0.5]      # Hurst>0.5 = trending
    Rchop = [t[0] for t in trades if t[1] <= 0.5]
    volmed = np.median([t[2] for t in trades]) if trades else 0
    Rhivol = [t[0] for t in trades if t[2] >= volmed]
    Rtrend_hivol = [t[0] for t in trades if t[1] > 0.5 and t[2] >= volmed]

    print("=" * 74)
    print("REGIME-GATE MOMENTUM TEST · ทอง H1 · Donchian%d RR%.0f · Hurst win %d" % (BRK, RR, HURST_WIN))
    print("=" * 74)
    print("%-26s %6s %9s %7s %7s" % ("bucket", "n", "exp_R", "WR%", "t"))
    for name, Rs in [("ALL (ungated)", Rall), ("Hurst>0.5 (trend, GATED)", Rtrend),
                     ("Hurst<=0.5 (chop)", Rchop), ("high-vol", Rhivol),
                     ("trend + high-vol", Rtrend_hivol)]:
        s = _stats(Rs)
        print("%-26s %6d %9s %7s %7s" % (name, s["n"], s["exp_R"], s["wr"], s["t"]))
    print("=" * 74)
    su = _stats(Rall); sg = _stats(Rtrend)
    if su["exp_R"] is not None and sg["exp_R"] is not None:
        lift = sg["exp_R"] - su["exp_R"]
        print("regime-gate lift: exp_R %+.4f (%s)" % (
            lift, "ดีขึ้น ✅ คุ้มทำ gate" if lift > 0.01 else "ไม่ต่าง/แย่ลง — Hurst ไม่ช่วย (ตาม quant skill: Hurst noisy)"))
    print("\nchop share:", "%.0f%%" % (len(Rchop) / max(1, len(Rall)) * 100), "ของไม้ (ถ้า gate ตัดทิ้งเยอะ = frequency ลด)")
    return trades


if __name__ == "__main__":
    run()
