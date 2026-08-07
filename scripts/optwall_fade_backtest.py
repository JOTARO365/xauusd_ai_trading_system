#!/usr/bin/env python
"""scripts/optwall_fade_backtest.py — proxy backtest ของ "fade ที่ options-wall + hold หลายวัน".

⚠️ ไม่มี historical options OI (AV HISTORICAL_OPTIONS = premium, ไม่ได้เก็บ log) → backtest OI ตรงๆ ไม่ได้.
ใช้ **proxy = round-$ strike levels** (GLD options strikes กระจุกที่ round number → XAU ~$25/$50 grid = ที่ OI wall
มักอยู่) + hold หลายวัน (options pinning เป็นปรากฏการณ์รายวัน/สัปดาห์). ถ้า proxy ยัง −EV → OI version prior ต่ำมาก.

causal · SL-first · หัก cost · OOS 70/30. รัน: python scripts/optwall_fade_backtest.py [--all]
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                   # noqa: E402

MIN_N = 100


def _stats(tr):
    n = len(tr)
    if not n:
        return {"n": 0}
    a = np.array(tr, float); sd = float(a.std(ddof=1)) if n > 1 else 0.0
    return {"n": n, "wr": round(float((a > 0).mean()) * 100, 1), "exp_R": round(float(a.mean()), 4),
            "sum_R": round(float(a.sum()), 1), "t": round(float(a.mean()) / (sd / math.sqrt(n)), 2) if sd else 0.0}


def run(h, l, c, cost, point, grid, tol_atr, rr, max_hold, buf_atr=0.6):
    atr = R.atr(h, l, c); n = len(c); tr = []
    i = 60
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = float(c[i]); lvl = round(px / grid) * grid           # round-$ strike ใกล้สุด (options wall proxy)
        if abs(px - lvl) > tol_atr * av:                          # ต้อง "แตะ" wall
            i += 1; continue
        d = "BUY" if px >= lvl else "SELL"                        # เหนือ wall = support(BUY) · ใต้ = resistance(SELL)
        sign = 1 if d == "BUY" else -1
        sl_price = lvl - sign * buf_atr * av; sl_pips = abs(px - sl_price) / point
        if sl_pips <= 0:
            i += 1; continue
        sl = px - sign * sl_pips * point; tp = px + sign * sl_pips * rr * point
        end = min(i + max_hold, n - 1); r_out = None; ei = end
        for j in range(i + 1, end + 1):
            if (l[j] <= sl) if sign > 0 else (h[j] >= sl):
                r_out, ei = -1.0 - cost / sl_pips, j; break
            if (h[j] >= tp) if sign > 0 else (l[j] <= tp):
                r_out, ei = rr - cost / sl_pips, j; break
        if r_out is None:
            r_out = sign * (c[end] - px) / (sl_pips * point) - cost / sl_pips
        tr.append(r_out); i = ei + 1
    return tr


def _rep(label, tr):
    s = _stats(tr)
    if not s["n"]:
        print(f"{label:26s} n=0"); return
    k = int(len(tr) * 0.7); oos = _stats(tr[k:])
    fl = "PASS" if (s["n"] >= MIN_N and s["exp_R"] > 0 and s["t"] > 2 and oos.get("exp_R", -1) > 0) else "—"
    print(f"{label:26s} n={s['n']:4d} WR {s['wr']:5}% exp_R {s['exp_R']:+.4f} t {s['t']:+.2f} sumR {s['sum_R']:+7.1f} | OOS {oos.get('exp_R','—')} [{fl}]")


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    print("\n=== options-wall fade (proxy=round-$ strike, hold หลายวัน) · causal · SL-first · OOS70/30 ===")
    print("PASS = n≥100 + exp_R>0 + t>2 + OOS>0\n")
    if "--all" in sys.argv:
        from connectors.pair_collector import _broker_map
        bmap = _broker_map() or {}
        syms = ["XAUUSD", "XAGUSD", "XAUEUR"]
    else:
        bmap = {}; syms = ["XAUUSD"]
    # grid ($ strike spacing) ต่อคู่ + variants (tol/rr/hold)
    GRID = {"XAUUSD": 50, "XAUEUR": 50, "XAGUSD": 1}
    for logical in syms:
        sym = bmap.get(logical, logical) if bmap else __import__("config").SYMBOL
        try:
            mt5.symbol_select(sym, True)
            r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 20000)
            info = mt5.symbol_info(sym)
        except Exception:
            r = info = None
        if r is None or len(r) < 800 or not info:
            print(f"{logical} ข้อมูลไม่พอ"); continue
        h = np.array([x["high"] for x in r], float); l = np.array([x["low"] for x in r], float)
        c = np.array([x["close"] for x in r], float)
        cost = (_sc.cost_pips(logical) if _sc else None) or 30.0
        pt = float(info.point); g = GRID.get(logical, 50)
        print(f"── {logical} (grid=${g}, cost={cost}) ──")
        for name, tol, rr, hold in [("hold5d rr1.5", 0.3, 1.5, 120), ("hold10d rr2", 0.3, 2.0, 240),
                                    ("hold10d rr2 tol0.5", 0.5, 2.0, 240), ("hold20d rr3", 0.3, 3.0, 480)]:
            _rep("  " + name, run(h, l, c, cost, pt, g, tol, rr, hold))
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
