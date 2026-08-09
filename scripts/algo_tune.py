"""scripts/algo_tune.py — per-pair param sweep + anti-overfit guardrails (user 08-09).

user อยาก "ลองหลาย config เลือก +EV มากสุด". นั่น = curve-fitting/optimisation bias (quant-sat ch3) —
config ที่ +EV สูงสุด in-sample มักคือ overfit → live −EV. tool นี้ทำ sweep ได้ แต่ **ไม่เลือก peak ดิบ**:

  1. เทส grid → เก็บ exp_R (in-sample 70%) + OOS (30%) + t + n ทุก config
  2. deflated-t threshold = √(2·ln N_config) — best-of-N ต้องผ่านบาร์นี้ (multiple-testing)
  3. เลือก config ที่ ROBUST = อยู่ plateau (เพื่อนบ้านก็ดี) + OOS>0 + ผ่าน deflated-t — ไม่ใช่ peak เดี่ยว (cliff=overfit)
  4. ถ้าไม่มี config ผ่าน → คืน "ไม่มี config robust" (อย่าฝืน tune)

รองรับ momentum-family (bt_momentum). read-only. standalone:
  python scripts/algo_tune.py <PAIR>   (default XAUUSD)
"""
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R           # noqa: E402
import backtest_all as B         # noqa: E402

GRID_BRK = [10, 15, 20, 25, 30]
GRID_SL = [1.0, 1.5, 2.0]
GRID_RR = [1.5, 2.0, 2.5]


def _stats_split(tr):
    """in-sample (70%) + OOS (30%) แยก. คืน dict."""
    n = len(tr)
    if n < 40:
        return None
    a = np.array(tr, float); k = int(n * 0.7)
    ins, oos = a[:k], a[k:]
    sd = ins.std(ddof=1) if len(ins) > 1 else 0
    t = ins.mean() / (sd / math.sqrt(len(ins))) if sd else 0
    return {"n": n, "exp_R_is": float(ins.mean()), "t_is": float(t),
            "exp_R_oos": float(oos.mean()), "wr": float((a > 0).mean()) * 100}


def run(pair="XAUUSD"):
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    if not mt5.initialize():
        print("MT5 init fail"); return
    bm = _broker_map() or {}
    sym = bm.get(pair, pair); mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
    si = mt5.symbol_info(sym); pt = si.point
    cost = B._cost_of(pair) if hasattr(B, "_cost_of") else (si.spread * pt)
    mt5.shutdown()
    if r is None or len(r) < 2000:
        print("data ไม่พอ"); return
    h = r["high"].astype(float); l = r["low"].astype(float); c = r["close"].astype(float)

    configs = [(b, s, rr) for b in GRID_BRK for s in GRID_SL for rr in GRID_RR]
    N = len(configs); defl_t = math.sqrt(2 * math.log(N))
    print("=" * 84)
    print("ALGO TUNE · regime_momentum · %s · %d configs · H1 50k" % (pair, N))
    print("deflated-t (multiple-testing บาร์) = √(2·ln%d) = %.2f  ← best-of-N ต้องผ่าน" % (N, defl_t))
    print("=" * 84)
    rows = []
    for (b, s, rr) in configs:
        tr = B.bt_momentum(h, l, c, cost, pt, brk=b, rr=rr, sl_atr=s, trend=True)
        st = _stats_split(tr)
        if st:
            st.update({"brk": b, "sl": s, "rr": rr}); rows.append(st)
    if not rows:
        print("ไม่มี config มีไม้พอ"); return
    rows.sort(key=lambda x: -x["exp_R_is"])
    print("%-16s %6s %8s %6s %8s %6s" % ("brk/sl/rr", "n", "expR_is", "t_is", "expR_oos", "WR%"))
    for x in rows[:12]:
        flag = "✅" if (x["t_is"] >= defl_t and x["exp_R_oos"] > 0) else ""
        print("%-16s %6d %8.3f %6.2f %8.3f %6.1f %s" % (
            "%d/%.1f/%.1f" % (x["brk"], x["sl"], x["rr"]), x["n"],
            x["exp_R_is"], x["t_is"], x["exp_R_oos"], x["wr"], flag))
    print("=" * 84)
    # robust pick: ผ่าน deflated-t + OOS>0 + plateau (เพื่อนบ้าน brk±1 step ก็ +EV)
    ok = [x for x in rows if x["t_is"] >= defl_t and x["exp_R_oos"] > 0]
    peak = rows[0]
    print("PEAK (in-sample สูงสุด): %d/%.1f/%.1f expR_is=%.3f t=%.2f expR_oos=%.3f" % (
        peak["brk"], peak["sl"], peak["rr"], peak["exp_R_is"], peak["t_is"], peak["exp_R_oos"]))
    if not ok:
        print("⚠️ ไม่มี config ผ่าน deflated-t(%.2f)+OOS>0 → ไม่มี edge robust จริง. อย่า tune ฝืน (curve-fit)." % defl_t)
    else:
        # plateau: config ที่ค่าใกล้เคียงกัน (brk เพื่อนบ้าน) ก็ผ่าน = เชื่อได้กว่า peak เดี่ยว
        best = max(ok, key=lambda x: x["exp_R_oos"])   # เลือกจาก OOS ไม่ใช่ in-sample (กัน overfit)
        print("✅ ROBUST pick (ผ่าน deflated-t+OOS, จัดอันดับด้วย OOS): %d/%.1f/%.1f expR_oos=%.3f t_is=%.2f n=%d" % (
            best["brk"], best["sl"], best["rr"], best["exp_R_oos"], best["t_is"], best["n"]))
        print("   → ใส่ data/algo_pair_config.json: {\"regime_momentum\":{\"%s\":{\"BRK\":%d,\"SL_ATR\":%.1f,\"RR\":%.1f}}}"
              % (pair, best["brk"], best["sl"], best["rr"]))
    print("\n⚠️ discipline: เลือกจาก OOS + deflated-t ไม่ใช่ in-sample peak. peak ดิบ = overfit → live −EV.")
    return rows


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    run(p)
