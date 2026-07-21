#!/usr/bin/env python
"""strategy_search.py — ทดสอบกลยุทธ์ผู้สมัคร (จาก persona brainstorm) ผ่าน gauntlet เดียวกันทุกตัว.

เกณฑ์ผ่าน (user: WR≥51% + rigor กันหลอกตัวเอง):
  PASS = WR≥51% (net@30p) และ expR>0 ทุก cost และ OOS>0 และ ชนะ null และ PSR>0.95 และ ≥3/4 quartile บวก.
แต่ละกลยุทธ์ = generator คืน list ของ signal {i, dir, sl_pips, tp_pips} บน TF ที่เลือก. harness จัดการที่เหลือ.

รัน: & $PY scripts\strategy_search.py
"""
import json
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R
import regime_backtest as BT

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WR_GATE = 0.51
COST = 30            # pips — cost หลักสำหรับ WR/OOS/quartile
MAX_HOLD = 48


_CACHE = {}


def load_tf(tf):
    if tf not in _CACHE:
        d = np.array(json.load(open(os.path.join(_BASE, "data", f"xau_{tf}.json"))), dtype=float)
        _CACHE[tf] = {"ts": d[:, 0], "o": d[:, 1], "h": d[:, 2], "l": d[:, 3], "c": d[:, 4],
                      "v": d[:, 5] if d.shape[1] > 5 else np.ones(len(d))}
    return _CACHE[tf]


def _simulate(signals, high, low, close):
    """คืน list trades {i, dir, sl_pips, R_gross} จาก signals (intrabar)."""
    out = []
    for s in signals:
        i, d, slp, tpp = s["i"], s["dir"], s["sl_pips"], s.get("tp_pips") or round(s["sl_pips"] * 2)
        if slp <= 0 or i < 1 or i >= len(close) - 1:
            continue
        r_g, *_ = BT.simulate_trade(i, d, slp, tpp, MAX_HOLD, high, low, close)
        out.append({"i": i, "dir": d, "sl_pips": slp, "R_gross": r_g})
    return out


def _null_timing(trades, close, seed=0):
    """null: คง dir/sl/tp แต่สุ่ม entry index (timing มี edge จริงไหม vs สุ่ม)."""
    rng = np.random.RandomState(seed)
    high = _NULL["h"]; low = _NULL["l"]
    out = []
    for t in trades:
        ei = int(rng.randint(1, len(close) - 1))
        r_g, *_ = BT.simulate_trade(ei, t["dir"], t["sl_pips"], round(t["sl_pips"] * 2), MAX_HOLD, high, low, close)
        out.append({"i": ei, "dir": t["dir"], "sl_pips": t["sl_pips"], "R_gross": r_g})
    return out


_NULL = {}


def evaluate(name, tf, gen):
    """รัน 1 กลยุทธ์ผ่าน gauntlet เต็ม. คืน dict ผล + verdict."""
    D = load_tf(tf)
    high, low, close = D["h"], D["l"], D["c"]
    global _NULL
    _NULL = D
    try:
        signals = gen(D)
    except Exception as e:
        return {"name": name, "tf": tf, "err": str(e)[:80]}
    trades = _simulate(signals, high, low, close)
    n = len(trades)
    if n < BT.MIN_N:
        return {"name": name, "tf": tf, "n": n, "skip": f"N<{BT.MIN_N}"}
    s = BT.summarize(name, trades, COST)
    # OOS 60/40 (ตาม index เวลา)
    split = int(len(close) * 0.6)
    oos = [t for t in trades if t["i"] >= split]
    so = BT.summarize("oos", oos, COST) if len(oos) >= 30 else {"exp_R": float("nan"), "wr": float("nan")}
    # null (timing สุ่ม)
    ns = BT.summarize("null", _null_timing(trades, close, seed=1), COST)
    # quartile (4 ช่วงเวลาตาม i)
    nb = len(close); qpos = 0; qs = []
    for q in range(4):
        lo, hi = nb * q // 4, nb * (q + 1) // 4
        seg = [t for t in trades if lo <= t["i"] < hi]
        qe = BT.summarize("q", seg, COST)["exp_R"] if len(seg) >= 25 else float("nan")
        qs.append(qe)
        if qe == qe and qe > 0:
            qpos += 1
    # cost robustness
    exp_all_costs = [BT.summarize("c", trades, c)["exp_R"] for c in BT.COST_PIPS_GRID]
    # เกณฑ์
    g_wr = s["wr"] >= WR_GATE
    g_ev = all(e > 0 for e in exp_all_costs)
    g_oos = so["exp_R"] > 0
    g_null = s["exp_R"] > ns["exp_R"]
    g_psr = s["psr0"] >= 0.95
    g_q = qpos >= 3
    passed = bool(g_wr and g_ev and g_oos and g_null and g_psr and g_q)
    return {"name": name, "tf": tf, "n": n, "wr": float(s["wr"]), "expR": float(s["exp_R"]), "psr": float(s["psr0"]),
            "oos": float(so["exp_R"]), "null": float(ns["exp_R"]), "qpos": qpos, "qs": qs,
            "gates": {"WR≥51": bool(g_wr), "EV+": bool(g_ev), "OOS+": bool(g_oos),
                      "null": bool(g_null), "PSR": bool(g_psr), "Q≥3": bool(g_q)},
            "PASS": passed}


def report(results):
    print("=" * 100)
    print(f"STRATEGY SEARCH — gate: WR≥51% + EV+(net) + OOS+ + beat-null + PSR>0.95 + quartile≥3/4")
    print("=" * 100)
    print(f"{'strategy':<30}{'TF':>4}{'N':>6}{'WR':>7}{'expR':>8}{'OOS':>7}{'null':>7}{'PSR':>6}{'Q+':>4}  gates/PASS")
    print("-" * 100)
    ok = []
    for r in sorted(results, key=lambda x: (-(x.get("PASS", False)), -(x.get("wr") or 0))):
        if r.get("err"):
            print(f"{r['name']:<30}{r['tf']:>4}  ERR: {r['err']}"); continue
        if r.get("skip"):
            print(f"{r['name']:<30}{r['tf']:>4}{r.get('n',0):>6}  {r['skip']}"); continue
        fg = " ".join(k for k, v in r["gates"].items() if v)
        mark = "✅PASS" if r["PASS"] else "❌"
        print(f"{r['name']:<30}{r['tf']:>4}{r['n']:>6}{r['wr']*100:>6.1f}%{r['expR']:>+8.3f}"
              f"{r['oos']:>+7.3f}{r['null']:>+7.3f}{r['psr']:>6.2f}{r['qpos']:>3}/4  {mark} [{fg}]")
        if r["PASS"]:
            ok.append(r["name"])
    print("-" * 100)
    print(f"ผ่านเกณฑ์: {len(ok)} กลยุทธ์" + (f" → {', '.join(ok)}" if ok else " (ไม่มี — ไม่มี validated edge)"))


# ============================================================
# STRATEGIES — เสียบจาก persona brainstorm (แต่ละตัว: gen(D) -> list {i,dir,sl_pips,tp_pips})
# ============================================================
try:
    import strat_candidates
    STRATEGIES = strat_candidates.ALL
except Exception as _e:
    print(f"[strat_candidates import err] {_e}")
    STRATEGIES = []


def main():
    if not STRATEGIES:
        print("ยังไม่มี STRATEGIES — รอ persona brainstorm แล้วเสียบ generator")
        return
    results = [evaluate(name, tf, gen) for (name, tf, gen) in STRATEGIES]
    report(results)


if __name__ == "__main__":
    main()
