"""agents/shadow_matrix.py — Batch B (T-06): attribution matrix over shadow journals.

Reads logs/shadow/<algo>__<sym>.jsonl (written by shadow_engine) and reports, per (algo, pair):
n, win-rate, net exp_R, ΣR, maxDD, MFE/MAE, avg-hold, and a promotion-readiness badge. Shows ALL
eligible combos (even n=0 → "collecting") so the dashboard reflects the full universe. LIVE and SHADOW
stats are never pooled (v1 = all SHADOW). Also attaches the in-sample backtest exp_R as reference
context (forward shadow is the real, uncontaminated OOS — never merge the two into one number).

Promotion rule (Phase-5): ready ⇔ n ≥ (100 scalp / 20 swing) AND net exp_R > +0.05R AND window spans
≥ MIN_SPAN_DAYS (proxy for ≥2 market regimes). dying ⇔ n ≥ 30 AND exp_R < −0.05. else collecting.
Promotion to LIVE stays manual — this only surfaces readiness.

Consumed by /api/shadow-matrix. Import-safe (no MT5). Run standalone: python agents/shadow_matrix.py
"""
import json
import os
import sys
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)                    # allow standalone run (python agents/shadow_matrix.py)

from agents import algo_registry as _reg     # noqa: E402
from agents import shadow_switches as _sw    # noqa: E402
_LOGDIR = os.path.join(_BASE, "logs", "shadow")
_BACKTEST = os.path.join(_BASE, "docs", "reports", "shadow_backtest.json")
_READY_EXP_R = 0.05
_DYING_EXP_R = -0.05
_MIN_SPAN_DAYS = 60
_N_READY = {"scalp": 100, "swing": 20}


def _read(path):
    out = []
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return out


def _load_backtest():
    """{(algo_id, symbol): row} from the committed backtest json, if present.
    Rows without algo_id default to regime_momentum (backward-compat with pre-MR files)."""
    try:
        rows = json.load(open(_BACKTEST, encoding="utf-8"))
        return {(r.get("algo_id", "regime_momentum"), r["logical"]): r
                for r in rows if r.get("ok") and r.get("n")}
    except Exception:
        return {}


def _span_days(recs):
    ts = [r.get("bar_ts") for r in recs if r.get("bar_ts")]
    if len(ts) < 2:
        return 0.0
    try:
        a = datetime.fromisoformat(min(ts)); b = datetime.fromisoformat(max(ts))
        return round((b - a).total_seconds() / 86400, 1)
    except Exception:
        return 0.0


def _aggregate(recs, klass):
    sig = [r for r in recs if r.get("kind") == "signal"]
    closed = [r for r in sig if (r.get("outcome") or {}).get("result") in ("TP", "SL", "TIMEOUT")]
    n_open = sum(1 for r in sig if (r.get("outcome") or {}).get("result") == "OPEN"
                 or not r.get("outcome"))
    stat = {"n": len(closed), "n_open": n_open, "wr": None, "exp_R": None, "sum_R": 0.0,
            "max_dd_R": 0.0, "avg_hold": None, "mfe_R": None, "mae_R": None,
            "span_days": _span_days(sig), "by_result": {"TP": 0, "SL": 0, "TIMEOUT": 0},
            "badge": "collecting"}
    if not closed:
        return stat
    Rs = [(r["outcome"]["realized_R"]) for r in closed]
    wins = sum(1 for x in Rs if x > 0)
    eq = peak = dd = 0.0
    for x in Rs:
        eq += x; peak = max(peak, eq); dd = min(dd, eq - peak)
    for r in closed:
        stat["by_result"][r["outcome"]["result"]] = stat["by_result"].get(r["outcome"]["result"], 0) + 1
    stat.update({
        "wr": round(wins / len(closed) * 100, 1),
        "exp_R": round(sum(Rs) / len(Rs), 3),
        "sum_R": round(sum(Rs), 1),
        "max_dd_R": round(dd, 1),
        "avg_hold": round(sum(r["outcome"].get("bars_held", 0) for r in closed) / len(closed), 1),
        "mfe_R": round(sum(r["outcome"].get("mfe_R", 0) for r in closed) / len(closed), 2),
        "mae_R": round(sum(r["outcome"].get("mae_R", 0) for r in closed) / len(closed), 2),
    })
    n_ready = _N_READY.get(klass, 100)
    if stat["n"] >= n_ready and stat["exp_R"] > _READY_EXP_R and stat["span_days"] >= _MIN_SPAN_DAYS:
        stat["badge"] = "ready"
    elif stat["n"] >= 30 and stat["exp_R"] < _DYING_EXP_R:
        stat["badge"] = "dying"
    else:
        stat["badge"] = "collecting"
    return stat


def build():
    """Full matrix dict for the dashboard. Import-safe, fail-soft."""
    import config as _cfg
    universe = getattr(_cfg, "SHADOW_UNIVERSE", None) or _reg.UNIVERSE
    eligible = _reg.combos(universe)
    bt = _load_backtest()
    rows = []
    for algo_id, symbol in eligible:
        algo = _reg.get(algo_id)
        klass = getattr(algo, "klass", "scalp")
        recs = _read(os.path.join(_LOGDIR, f"{algo_id}__{symbol}.jsonl"))
        stat = _aggregate(recs, klass)
        b = bt.get((algo_id, symbol))                  # backtest ref ต่อ (algo, คู่) — momentum + mean_reversion
        rows.append({"algo_id": algo_id, "symbol": symbol, "klass": klass,
                     "state": _sw.state_of(algo_id, symbol),
                     "backtest_exp_R": (b.get("exp_R") if b else None),
                     "backtest_n": (b.get("n") if b else None), **stat})
    counts = {"ready": 0, "collecting": 0, "dying": 0}
    for r in rows:
        counts[r["badge"]] = counts.get(r["badge"], 0) + 1
    # ── strategy rollup: แต่ละกลยุทธ์กำไร/ขาดทุนเท่าไหร่รวมทุกคู่ (regime = domain ของ algo) ──
    _REGIME = {"regime_momentum": "TREND", "mean_reversion": "RANGE"}
    by_algo = {}
    for r in rows:
        a = by_algo.setdefault(r["algo_id"], {"algo_id": r["algo_id"], "regime": _REGIME.get(r["algo_id"], "—"),
                                              "n": 0, "wins": 0, "sum_R": 0.0, "pairs_traded": 0,
                                              "pairs_pos": 0, "best": None, "worst": None})
        a["n"] += r["n"]; a["sum_R"] += (r["sum_R"] or 0.0)
        if r["n"]:
            a["pairs_traded"] += 1
            if r["exp_R"] is not None and r["exp_R"] > 0:
                a["pairs_pos"] += 1
            if r["by_result"]:
                a["wins"] += r["by_result"].get("TP", 0)
            if r["exp_R"] is not None:
                if a["best"] is None or r["exp_R"] > a["best"][1]:
                    a["best"] = [r["symbol"], r["exp_R"]]
                if a["worst"] is None or r["exp_R"] < a["worst"][1]:
                    a["worst"] = [r["symbol"], r["exp_R"]]
    for a in by_algo.values():
        a["sum_R"] = round(a["sum_R"], 1)
        a["exp_R"] = round(a["sum_R"] / a["n"], 3) if a["n"] else None
        a["wr"] = round(a["wins"] / a["n"] * 100, 1) if a["n"] else None
    return {"ok": True, "generated": datetime.now(timezone.utc).isoformat()[:16] + "Z",
            "engine_on": getattr(_cfg, "SHADOW_ENGINE", False),
            "n_ready": _N_READY, "ready_exp_R": _READY_EXP_R, "min_span_days": _MIN_SPAN_DAYS,
            "counts": counts, "rows": rows, "by_algo": list(by_algo.values()),
            "note": "forward shadow, net of measured spread, swap excluded. backtest_exp_R = in-sample "
                    "reference only — never pool with shadow."}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa: F401
    m = build()
    print(f"shadow matrix · engine_on={m['engine_on']} · {m['generated']}")
    print(f"{'combo':30s} {'state':7s} {'n':>4s} {'open':>4s} {'exp_R':>7s} {'sumR':>7s} "
          f"{'btR':>6s} {'span_d':>6s}  badge")
    for r in m["rows"]:
        print(f"{r['algo_id']+':'+r['symbol']:30s} {r['state']:7s} {r['n']:>4d} {r['n_open']:>4d} "
              f"{str(r['exp_R']):>7s} {r['sum_R']:>7.1f} {str(r['backtest_exp_R']):>6s} "
              f"{r['span_days']:>6.1f}  {r['badge']}")
    print("counts:", m["counts"])
