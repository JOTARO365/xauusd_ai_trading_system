"""scripts/tune_confluence.py — confluence_15m sweep (XAU+BTC focus) + anti-overfit (user 08-09).

focus ทอง+BTC ต้องหา +EV robust (ไม่ hardcode). sweep session(structural liquidity)×SL×RR
+ deflated-t + OOS discipline. เลือกจาก OOS ไม่ใช่ in-sample peak. standalone: python scripts/tune_confluence.py
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import backtest_all as B         # noqa: E402


def _split(tr):
    n = len(tr)
    if n < 50:
        return None
    a = np.array(tr, float); k = int(n * 0.7); ins, oos = a[:k], a[k:]
    sd = ins.std(ddof=1) if len(ins) > 1 else 0
    return {"n": n, "is": float(ins.mean()), "t": float(ins.mean() / (sd / math.sqrt(len(ins))) if sd else 0),
            "oos": float(oos.mean()), "wr": float((a > 0).mean()) * 100}


def run():
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    if not mt5.initialize():
        print("MT5 init fail"); return
    bm = _broker_map() or {}
    eb = bm.get("EURUSD", "EURUSD")

    def cost_of(lg):
        s = bm.get(lg, lg); si = mt5.symbol_info(s)
        try:
            from agents import shadow_cost as sc
            return float(sc.cost_price(s))
        except Exception:
            return (si.spread * si.point) if si else 0.3

    # XAU: session (structural liquidity windows) × SL × RR · BTC: SL × RR × VK (24/7)
    plan = {
        "XAUUSD": [{"session": ss, "sl_atr": sl, "rr": rr}
                   for ss in ("13-21", "13-17", "12-20", "14-21", "13-19", "7-16")
                   for sl in (0.8, 1.0, 1.3) for rr in (1.5, 2.0, 2.5)],
        "BTCUSD": [{"vk": vk, "sl_atr": sl, "rr": rr}
                   for vk in (1.2, 1.5, 2.0) for sl in (0.8, 1.0, 1.3) for rr in (1.5, 2.0, 2.5)],
    }
    for pair, cfgs in plan.items():
        s = bm.get(pair, pair); mt5.symbol_select(s, True)
        pt = mt5.symbol_info(s).point; cost = cost_of(pair)
        N = len(cfgs); defl = math.sqrt(2 * math.log(N))
        print("=" * 82)
        print("CONFLUENCE TUNE · %s · %d configs · deflated-t=%.2f" % (pair, N, defl))
        print("=" * 82)
        rows = []
        for cf in cfgs:
            tr = B.bt_conf15m(mt5, s, eb, cost, pt, brk=12,
                              rr=cf.get("rr", 2.0), sl_atr=cf.get("sl_atr", 1.0),
                              vk=cf.get("vk", 1.5), session=cf.get("session"))
            st = _split(tr)
            if st:
                st["cfg"] = cf; rows.append(st)
        if not rows:
            print("  ไม่มีไม้พอ"); continue
        rows.sort(key=lambda x: -x["is"])
        print("%-34s %5s %7s %6s %7s %5s" % ("config", "n", "expR_is", "t_is", "expR_oos", "WR%"))
        for x in rows[:10]:
            tag = "✅" if (x["t"] >= defl and x["oos"] > 0) else ""
            print("%-34s %5d %7.3f %6.2f %7.3f %5.1f %s" % (
                str(x["cfg"]), x["n"], x["is"], x["t"], x["oos"], x["wr"], tag))
        ok = [x for x in rows if x["t"] >= defl and x["oos"] > 0]
        peak = rows[0]
        print("-" * 82)
        print("PEAK in-sample: %s expR_is=%.3f t=%.2f oos=%.3f" % (peak["cfg"], peak["is"], peak["t"], peak["oos"]))
        if ok:
            best = max(ok, key=lambda x: x["oos"])
            print("✅ ROBUST (deflated-t+OOS, rank by OOS): %s oos=%.3f t=%.2f n=%d" % (
                best["cfg"], best["oos"], best["t"], best["n"]))
        else:
            print("❌ ไม่มี config ผ่าน deflated-t(%.2f)+OOS>0 → ไม่ robust (อย่า tune ฝืน)" % defl)
    mt5.shutdown()


if __name__ == "__main__":
    run()
