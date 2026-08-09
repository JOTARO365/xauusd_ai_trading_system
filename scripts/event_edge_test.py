"""scripts/event_edge_test.py — validate event-driven edge บนทอง (user 08-09).

event = edge source? ทดสอบ 2 hypothesis บน XAUUSD H1 (deterministic events, ไม่ต้องพึ่ง actual):
  1. post-NFP momentum: NFP = first-Friday 13:30 UTC → release bar (13:00 H1) move → เข้าตามทิศ hold → มี edge?
  2. pre-NFP/post-NFP drift: ทองขยับก่อน/หลัง event เป็นระบบไหม
เทียบกับ baseline (random bar) → มี EXCESS edge รอบ event จริงหรือแค่ vol. causal. standalone.
"""
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def run():
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    if not mt5.initialize():
        print("MT5 init fail"); return
    bm = _broker_map() or {}
    s = bm.get("XAUUSD", "XAUUSD"); mt5.symbol_select(s, True)
    r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 50000)
    si = mt5.symbol_info(s); pt = si.point
    try:
        from agents import shadow_cost as sc; cost = float(sc.cost_price(s))
    except Exception:
        cost = si.spread * pt
    mt5.shutdown()
    h = r["high"].astype(float); l = r["low"].astype(float); c = r["close"].astype(float)
    tm = r["time"]; n = len(c)
    dts = [datetime.fromtimestamp(int(t), timezone.utc) for t in tm]

    # NFP = first Friday of month, release 13:30 UTC → release H1 bar = hour 13
    nfp = [i for i in range(n) if dts[i].weekday() == 4 and dts[i].day <= 7 and dts[i].hour == 13]
    print("=" * 74)
    print("EVENT EDGE · XAUUSD H1 · post-NFP momentum · %d NFP events (%d-%d)" % (
        len(nfp), dts[0].year, dts[-1].year))
    print("=" * 74)

    def res(entry_i, d, mh, sl_atr=1.5, rr=2.0):
        """resolve momentum trade from entry_i dir d. คืน R."""
        atr = (h[entry_i] - l[entry_i])  # proxy vol = release-bar range
        risk = max(sl_atr * atr, 0.5)
        px = c[entry_i]; sl = px - d * risk; tp = px + d * risk * rr
        for j in range(entry_i + 1, min(entry_i + mh, n)):
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                return -1.0 - cost / (risk / pt)
            if (h[j] >= tp) if d > 0 else (l[j] <= tp):
                return rr - cost / (risk / pt)
        return d * (c[min(entry_i + mh, n - 1)] - px) / risk - cost / (risk / pt)

    # hypothesis 1: post-NFP momentum — release bar (13:00) move → เข้าตามทิศที่ 14:00, hold 6h
    Rmom = []
    for i in nfp:
        if i + 6 >= n:
            continue
        move = c[i] - r["open"][i]                          # 13-14 UTC release reaction
        d = 1 if move > 0 else -1
        Rmom.append(res(i, d, mh=6))
    # hypothesis 2: post-NFP reversal (fade release)
    Rfade = []
    for i in nfp:
        if i + 6 >= n:
            continue
        move = c[i] - r["open"][i]; d = -1 if move > 0 else 1
        Rfade.append(res(i, d, mh=6))
    # baseline: random H1 bar momentum (same logic) เทียบ excess
    rng = np.random.default_rng(1)
    base = []
    for _ in range(len(nfp) * 3):
        i = int(rng.integers(50, n - 10))
        move = c[i] - r["open"][i]; d = 1 if move > 0 else -1
        base.append(res(i, d, mh=6))

    def stat(x, lbl):
        a = np.array(x)
        if len(a) < 5:
            print("%-22s n=%d (น้อย)" % (lbl, len(a))); return
        sd = a.std(ddof=1); t = a.mean() / (sd / math.sqrt(len(a))) if sd else 0
        print("%-22s n=%3d exp_R=%+.3f t=%+.2f WR=%.0f%%" % (lbl, len(a), a.mean(), t, (a > 0).mean() * 100))

    stat(Rmom, "post-NFP momentum")
    stat(Rfade, "post-NFP fade")
    stat(base, "baseline (random)")
    print("=" * 74)
    print("edge จริง ⇔ post-NFP t>2 AND exp_R > baseline (excess รอบ event ไม่ใช่แค่ vol).")


if __name__ == "__main__":
    run()
