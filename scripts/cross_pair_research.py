#!/usr/bin/env python
"""scripts/cross_pair_research.py — research ความเชื่อมโยงราคาข้ามคู่ (stat-arb) — user 08-07.

เรา collect หลายคู่แล้ว → หา edge จากความสัมพันธ์:
  1. correlation matrix (D1 returns) — คู่ไหนไปด้วยกัน/สวนกัน
  2. lead-lag — คู่ไหน "นำ" ทอง (corr(X_ret[t], XAU_ret[t+1..k])) = สัญญาณทำนายทอง
  3. cointegration / pairs-trade — spread XAU−β·XAG (gold-silver) z-fade mean-reversion (cost 2 legs · OOS)

causal · หัก cost · OOS70/30. รัน: python scripts/cross_pair_research.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))


def _aligned(mt5, syms, tf, count=6000):
    """ดึง close ของหลายคู่ align ตาม timestamp ร่วม. คืน (times, {sym: close_arr})."""
    data = {}
    for s in syms:
        mt5.symbol_select(s, True)
        r = mt5.copy_rates_from_pos(s, tf, 0, count)
        if r is None or len(r) < 500:
            continue
        data[s] = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
    if not data:
        return None, {}
    common = set.intersection(*[set(d.keys()) for d in data.values()])
    ts = sorted(common)
    return ts, {s: np.array([data[s][t] for t in ts], float) for s in data}


def _rets(a):
    return np.diff(a) / a[:-1]


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    from connectors.pair_collector import _broker_map
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    bmap = _broker_map() or {}
    logical = ["XAUUSD", "XAGUSD", "EURUSD", "USDJPY", "WTIUSD", "BTCUSD"]
    syms = {lg: bmap.get(lg, lg) for lg in logical}
    inv = {v: k for k, v in syms.items()}

    print("\n=== CROSS-PAIR RESEARCH (stat-arb) ===\n")
    # 1) correlation matrix (D1 returns)
    ts, closes = _aligned(mt5, list(syms.values()), mt5.TIMEFRAME_D1, 3000)
    if not closes:
        print("ข้อมูลไม่พอ"); mt5.shutdown(); return
    rets = {inv.get(s, s): _rets(c) for s, c in closes.items()}
    names = list(rets.keys())
    print("── 1) correlation matrix (D1 returns, n=%d) ──" % len(ts))
    print("        " + " ".join("%8s" % n[:8] for n in names))
    for a in names:
        row = []
        for b in names:
            m = min(len(rets[a]), len(rets[b]))
            row.append("%+8.2f" % np.corrcoef(rets[a][-m:], rets[b][-m:])[0, 1])
        print("%8s %s" % (a[:8], " ".join(row)))

    # 2) lead-lag: X_ret[t] ทำนาย XAU_ret[t+k]?
    print("\n── 2) lead-lag → ทำนาย XAU (corr X_ret[t] กับ XAU_ret[t+k]); |corr|สูง+t>2 = นำทอง ──")
    if "XAUUSD" in rets:
        xau = rets["XAUUSD"]
        for other in names:
            if other == "XAUUSD":
                continue
            xo = rets[other]; m = min(len(xau), len(xo))
            a = xo[-m:]; g = xau[-m:]
            best = None
            for k in (1, 2, 3):
                if m - k < 50:
                    continue
                c = np.corrcoef(a[:-k], g[k:])[0, 1]
                tval = c * math.sqrt((m - k - 2) / max(1e-9, 1 - c * c))
                if best is None or abs(c) > abs(best[1]):
                    best = (k, c, tval)
            if best:
                flag = "★นำทอง" if abs(best[2]) > 2 else ""
                print("  %-8s lag+%d: corr%+.3f t%+.2f %s" % (other, best[0], best[1], best[2], flag))

    # 3) pairs-trade: XAU−β·XAG spread z-fade (+ XAU vs EURUSD-inverse)
    print("\n── 3) pairs-trade spread z-fade (cost 2 legs · OOS70/30) ──")
    ts2, cl2 = _aligned(mt5, [syms["XAUUSD"], syms["XAGUSD"], syms["EURUSD"]], mt5.TIMEFRAME_H1, 40000)
    if len(cl2) >= 2:
        xau = cl2[syms["XAUUSD"]]
        cx = (_sc.cost_pips("XAUUSD") if _sc else 30) or 30
        px = float(mt5.symbol_info(syms["XAUUSD"]).point)
        cost_xau_R = None  # จะคิดต่อ trade เป็น fraction ของ spread SL
        for leg2_lg, arr2 in [("XAGUSD", cl2.get(syms["XAGUSD"])), ("EURUSD", cl2.get(syms["EURUSD"]))]:
            if arr2 is None:
                continue
            y = xau; x = arr2
            beta = np.polyfit(x, y, 1)[0]
            spread = y - beta * x
            win = 100
            trades = []
            i = win; pos = 0; entry_s = 0.0
            cost_frac = (cx * px)  # cost ประมาณ (ทอง leg; silver/eur leg เล็กกว่า) — คิดหยาบต่อ trade
            for i in range(win, len(spread)):
                w = spread[i - win:i]
                m, sd = w.mean(), w.std()
                if sd <= 0:
                    continue
                z = (spread[i] - m) / sd
                if pos == 0:
                    if z > 2:
                        pos = -1; entry_s = spread[i]     # spread สูง → short spread (short XAU/long XAG)
                    elif z < -2:
                        pos = 1; entry_s = spread[i]
                elif (pos == 1 and z >= -0.3) or (pos == -1 and z <= 0.3):
                    pnl = pos * (spread[i] - entry_s) - 2 * cost_frac   # 2 legs cost
                    trades.append(pnl / (2 * sd) if sd else 0)          # normalize ~R
                    pos = 0
            n = len(trades)
            if n >= 30:
                a = np.array(trades, float); sdt = a.std(ddof=1) if n > 1 else 0
                t = a.mean() / (sdt / math.sqrt(n)) if sdt else 0
                k = int(n * 0.7); oe = np.array(trades[k:]).mean()
                fl = "✅+EV" if a.mean() > 0 and oe > 0 else "−"
                print("  XAU~%-7s β=%.2f n=%3d exp%+.3f t%+.2f OOS%+.3f %s" % (leg2_lg, beta, n, a.mean(), t, oe, fl))
            else:
                print("  XAU~%-7s n<30 (ไม่พอ)" % leg2_lg)
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
