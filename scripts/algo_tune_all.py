"""scripts/algo_tune_all.py — param sweep ทุก algo family + anti-overfit (user 08-09).

sweep grid ต่อ (algo family × pair candidate) → หา config ที่ ROBUST เท่านั้น
(deflated-t=√(2·lnN) + OOS>0), ไม่ใช่ in-sample peak (curve-fit). candidate = +EV/near-miss จาก backtest.
families: momentum(H1) · macro(H4) · tsmom(D1) · sweep(H1). confluence(M15) แยก (ช้า).
เขียน docs/reviews/algo-tune-all.md. standalone: python scripts/algo_tune_all.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R           # noqa: E402
import backtest_all as B         # noqa: E402


def _split(tr):
    n = len(tr)
    if n < 50:
        return None
    a = np.array(tr, float); k = int(n * 0.7); ins, oos = a[:k], a[k:]
    sd = ins.std(ddof=1) if len(ins) > 1 else 0
    return {"n": n, "is": float(ins.mean()), "t": float(ins.mean() / (sd / math.sqrt(len(ins))) if sd else 0),
            "oos": float(oos.mean())}


def _best(configs, results):
    """robust pick: ผ่าน deflated-t + OOS>0, จัดอันดับด้วย OOS. คืน (dict|None, peak, defl_t)."""
    N = len(configs); defl = math.sqrt(2 * math.log(max(2, N)))
    valid = [r for r in results if r]
    if not valid:
        return None, None, defl
    peak = max(valid, key=lambda x: x["is"])
    ok = [r for r in valid if r["t"] >= defl and r["oos"] > 0]
    best = max(ok, key=lambda x: x["oos"]) if ok else None
    return best, peak, defl


def sweep_momentum(h, l, c, cost, pt):
    cfgs = [(b, s, rr) for b in (10, 15, 20, 25, 30) for s in (1.0, 1.5, 2.0) for rr in (1.5, 2.0, 2.5)]
    res = []
    for b, s, rr in cfgs:
        st = _split(B.bt_momentum(h, l, c, cost, pt, brk=b, rr=rr, sl_atr=s, trend=True))
        if st:
            st["cfg"] = "brk%d/sl%.1f/rr%.1f" % (b, s, rr)
        res.append(st)
    return cfgs, res


def sweep_macro(h, l, c, mac, msign, cost, pt):
    cfgs = [(b, m, s, rr) for b in (15, 20, 25) for m in (12, 24, 36) for s in (1.0, 1.5, 2.0) for rr in (1.5, 2.0, 2.5)]
    res = []
    for b, m, s, rr in cfgs:
        st = _split(B.bt_macro(h, l, c, mac, cost, pt, brk=b, mlb=m, sl_atr=s, rr=rr, msign=msign))
        if st:
            st["cfg"] = "brk%d/mlb%d/sl%.1f/rr%.1f" % (b, m, s, rr)
        res.append(st)
    return cfgs, res


def sweep_tsmom(dh, dl, dc, cost_price):
    sets = [(21, 63, 126), (10, 30, 60), (5, 20, 40), (30, 90, 180)]
    cfgs = [(lb, cf, s) for lb in sets for cf in (10, 21) for s in (2.0, 3.0, 4.0)]
    res = []
    for lb, cf, s in cfgs:
        st = _split(B.bt_tsmom(dh, dl, dc, cost_price, lbs=lb, confirm=cf, sl_atr=s))
        if st:
            st["cfg"] = "lb%s/cf%d/sl%.1f" % ("-".join(map(str, lb)), cf, s)
        res.append(st)
    return cfgs, res


def sweep_sweep(h, l, c, tm, cost, pt):
    cfgs = [(bf, rr) for bf in (0.3, 0.5, 0.8) for rr in (1.0, 1.5, 2.0)]
    res = []
    for bf, rr in cfgs:
        st = _split(B.bt_sweep(h, l, c, tm, cost, pt, rr=rr, buf_atr=bf))
        if st:
            st["cfg"] = "buf%.1f/rr%.1f" % (bf, rr)
        res.append(st)
    return cfgs, res


def run():
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    if not mt5.initialize():
        print("MT5 init fail"); return
    bm = _broker_map() or {}
    # candidate = +EV/near-miss จาก backtest ต่อ family
    bt = json.load(open(os.path.join(_ROOT, "data", "backtest_results.json"), encoding="utf-8"))["results"]
    # ทุกคู่ที่มี data พอ (>=50 ไม้) — sweep ครบ ไม่ใช่แค่ +EV (user: tune คู่ที่เหลือ)
    cand = {r["pair"] for r in bt if (r.get("n") or 0) >= 50 and "~" not in r["pair"]}

    def cost_of(lg):
        s = bm.get(lg, lg); si = mt5.symbol_info(s)
        try:
            from agents import shadow_cost as sc
            return float(sc.cost_price(s))
        except Exception:
            return (si.spread * si.point) if si else 0.3

    def h1(lg):
        s = bm.get(lg, lg); mt5.symbol_select(s, True)
        return mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 50000)

    lines = ["# Algo Tune — all families (anti-overfit sweep)\n",
             "Robust pick = clears deflated-t (√(2·lnN)) AND OOS>0, ranked by OOS. Not the in-sample peak.\n"]
    momentum_pairs = sorted(cand)   # ทุกคู่
    print("candidates:", sorted(cand))

    def report(family, pair, best, peak, defl):
        if peak is None:
            lines.append("- **%s %s**: ไม่มีไม้พอ" % (family, pair)); return
        if best:
            lines.append("- **%s %s**: ✅ ROBUST `%s` OOS=%.3f t=%.2f (defl %.2f) — peak in-sample `%s` %.3f"
                         % (family, pair, best["cfg"], best["oos"], best["t"], defl, peak["cfg"], peak["is"]))
        else:
            lines.append("- **%s %s**: ❌ ไม่มี config ผ่าน (defl-t %.2f + OOS>0). peak `%s` t=%.2f OOS=%.3f = overfit"
                         % (family, pair, defl, peak["cfg"], peak["t"], peak["oos"]))
        print(lines[-1])

    # momentum
    lines.append("\n## regime_momentum (H1)")
    for p in momentum_pairs:
        r = h1(p)
        if r is None or len(r) < 2000:
            continue
        cfgs, res = sweep_momentum(r["high"].astype(float), r["low"].astype(float), r["close"].astype(float),
                                   cost_of(p), mt5.symbol_info(bm.get(p, p)).point)
        report("momentum", p, *_best(cfgs, res))

    # macro (H4)
    lines.append("\n## macro_momentum (H4)")
    for p in [x for x in ("XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "BTCUSD") if x in cand]:   # macro=gold-complex+BTC (FX circular)
        s = bm.get(p, p); mt5.symbol_select(s, True)
        r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H4, 0, 30000)
        if r is None or len(r) < 1000:
            continue
        mlg, msign = R.macro_for(p); eb = bm.get(mlg, mlg); mt5.symbol_select(eb, True)
        em = mt5.copy_rates_from_pos(eb, mt5.TIMEFRAME_H4, 0, 30000)
        emap = {int(t): float(cc) for t, cc in zip(em["time"], em["close"])} if em is not None else {}
        mac = np.array([emap.get(int(t), np.nan) for t in r["time"]], float)
        cfgs, res = sweep_macro(r["high"].astype(float), r["low"].astype(float), r["close"].astype(float),
                                mac, msign, cost_of(p), mt5.symbol_info(s).point)
        report("macro", p, *_best(cfgs, res))

    # tsmom (D1)
    lines.append("\n## tsmom_d1 (D1)")
    for p in sorted(cand):   # tsmom ทุกคู่
        s = bm.get(p, p); mt5.symbol_select(s, True)
        r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 3000)
        if r is None or len(r) < 300:
            continue
        cfgs, res = sweep_tsmom(r["high"].astype(float), r["low"].astype(float), r["close"].astype(float),
                                cost_of(p) * mt5.symbol_info(s).point)
        report("tsmom", p, *_best(cfgs, res))

    # sweep (H1)
    lines.append("\n## sweep_reversal (H1)")
    for p in sorted(cand):   # sweep ทุกคู่
        r = h1(p)
        if r is None or len(r) < 2000:
            continue
        cfgs, res = sweep_sweep(r["high"].astype(float), r["low"].astype(float), r["close"].astype(float),
                                r["time"], cost_of(p), mt5.symbol_info(bm.get(p, p)).point)
        report("sweep", p, *_best(cfgs, res))

    mt5.shutdown()
    lines.append("\n## Verdict\nถ้าส่วนใหญ่ ❌ = edge ไม่รอด param validation → เก็บ default, อย่า tune ฝืน (quant-sat ch3).")
    open(os.path.join(_ROOT, "docs", "reviews", "algo-tune-all.md"), "w", encoding="utf-8").write("\n".join(lines))
    print("\nเขียน docs/reviews/algo-tune-all.md")


if __name__ == "__main__":
    run()
