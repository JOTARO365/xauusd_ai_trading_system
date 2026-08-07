#!/usr/bin/env python
"""scripts/pairs_trade_rigorous.py — re-test pairs-trade แบบเข้ม (แก้ lookahead + ใส่ stop + cost จริง).

จาก cross_pair_research พบ XAU~XAG / XAU~EURUSD spread-fade t4-5 — แต่มี 2 optimism:
  (1) β = full-sample OLS = LOOKAHEAD → ใช้ ROLLING β (causal, trailing window)
  (2) ไม่มี divergence stop → ใส่ z-stop (spread เบี่ยงต่อ=cut); cost 2 legs จริง (ต่อคู่)

causal · rolling β+z · z-stop · cost 2 legs · OOS70/30 · variants (multiple-testing).
รัน: python scripts/pairs_trade_rigorous.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))


def _aligned(mt5, syms, tf, count=40000):
    data = {}
    for s in syms:
        mt5.symbol_select(s, True)
        r = mt5.copy_rates_from_pos(s, tf, 0, count)
        if r is None or len(r) < 500:
            continue
        data[s] = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
    if not data:
        return {}
    common = set.intersection(*[set(d.keys()) for d in data.values()])
    ts = sorted(common)
    return {s: np.array([data[s][t] for t in ts], float) for s in data}


def run(y, x, cost_y, cost_x, win=120, z_in=2.0, z_out=0.5, z_stop=3.5):
    """rolling β + z (causal). enter |z|>z_in, exit |z|<z_out, stop |z|>z_stop.
    R = spread PnL / (SL distance = (z_stop-z_in)*sd) หัก cost 2 legs (fraction ของ notional)."""
    n = len(y); trades = []; pos = 0; entry_s = 0.0; entry_sd = 1.0; beta_at = 1.0
    for i in range(win, n):
        yw = y[i - win:i]; xw = x[i - win:i]                 # trailing เท่านั้น (causal)
        beta = np.polyfit(xw, yw, 1)[0]
        sw = yw - beta * xw
        m, sd = sw.mean(), sw.std()
        if sd <= 0:
            continue
        s_now = y[i] - beta * x[i]
        z = (s_now - m) / sd
        if pos == 0:
            if z > z_in:
                pos = -1; entry_s = s_now; entry_sd = sd; beta_at = beta
            elif z < -z_in:
                pos = 1; entry_s = s_now; entry_sd = sd; beta_at = beta
        else:
            hit_stop = (z >= z_stop) if pos == -1 else (z <= -z_stop)
            hit_exit = (abs(z) <= z_out)
            if hit_stop or hit_exit:
                sl_dist = (z_stop - z_in) * entry_sd          # ระยะ SL ของ spread
                # cost 2 legs: notional ทอง 1 หน่วย + silver/eur β หน่วย → cost รวม (price units)
                cost = cost_y + beta_at * cost_x
                pnl = pos * (s_now - entry_s) - cost
                trades.append(pnl / sl_dist if sl_dist else 0.0)   # R-normalized
                pos = 0
    return trades


def _st(tr):
    n = len(tr)
    if n < 30:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd else 0.0
    k = int(n * 0.7); oe = np.array(tr[k:]).mean()
    return n, round(float((a > 0).mean()) * 100, 1), round(float(a.mean()), 4), t, round(float(oe), 4)


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
    g = bmap.get("XAUUSD", __import__("config").SYMBOL)
    legs = {"XAGUSD": bmap.get("XAGUSD", "XAGUSD"), "EURUSD": bmap.get("EURUSD", "EURUSD")}

    def costp(lg, sym):
        cp = (_sc.cost_pips(lg) if _sc else None) or (30 if "XAU" in lg else 30)
        return cp * float(mt5.symbol_info(sym).point)

    print("\n=== PAIRS-TRADE RIGOROUS (rolling β causal · z-stop · cost 2 legs · OOS70/30) ===")
    print("PASS = exp_R>0 + t>2 + OOS>0 (หลังแก้ lookahead+stop). H1\n")
    for lg, sym in legs.items():
        cl = _aligned(mt5, [g, sym], mt5.TIMEFRAME_H1, 40000)
        if len(cl) < 2:
            print("XAU~%s ข้อมูลไม่พอ" % lg); continue
        y = cl[g]; x = cl[sym]; cy = costp("XAUUSD", g); cx = costp(lg, sym)
        print("── XAU ~ %s (n=%d bars) ──" % (lg, len(y)))
        for nm, kw in [("z2/0.5 stop3.5 w120", dict()),
                       ("z2/0.5 stop3 w120", dict(z_stop=3.0)),
                       ("z2.5/0.5 stop4 w120", dict(z_in=2.5, z_stop=4.0)),
                       ("z2/0.5 stop3.5 w240", dict(win=240)),
                       ("z2/0 stop3.5 w120", dict(z_out=0.0))]:
            s = _st(run(y, x, cy, cx, **kw))
            if not s:
                print("  %-22s n<30" % nm); continue
            n, wr, ex, t, oe = s
            fl = "✅PASS" if ex > 0 and t > 2 and oe > 0 else ("+EV" if ex > 0 and oe > 0 else "−")
            print("  %-22s n=%4d WR%5.1f%% exp_R%+.4f t%+.2f OOS%+.4f %s" % (nm, n, wr, ex, t, oe, fl))
    mt5.shutdown()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
