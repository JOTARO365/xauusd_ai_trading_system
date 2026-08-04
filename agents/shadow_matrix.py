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

# display metadata — ให้เมทริกซ์โชว์ตรงกับที่เทรดจริง (ชื่อ + สถานะ live). ไม่แตะ algo_id/data pipeline.
_ALGO_META = {
    "regime_momentum": {"name": "Momentum Breakout", "regime": "TREND", "live_symbol": "XAUUSD",
                        "note": "= algo ที่เทรดจริงบน XAUUSD (intraday · signal momentum_breakout · tag ALGO-mom)"},
    "mean_reversion":  {"name": "Mean-Reversion (z-fade)", "regime": "RANGE", "live_symbol": None,
                        "note": "CUT 07-19 (OOS −EV) — shadow/reference เท่านั้น ไม่ได้ใช้จริง"},
}


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
    Rows without algo_id default to regime_momentum (backward-compat with pre-MR files).
    Also merges SMC candidate in-sample backtest (data/smc_backtest.json) for the shadow
    algos regime_momentum_fvg / sweep_reversal (XAU only) so their matrix row shows a ref exp_R."""
    out = {}
    try:
        rows = json.load(open(_BACKTEST, encoding="utf-8"))
        out = {(r.get("algo_id", "regime_momentum"), r["logical"]): r
               for r in rows if r.get("ok") and r.get("n")}
    except Exception:
        pass
    try:
        smc = json.load(open(os.path.join(_BASE, "data", "smc_backtest.json"), encoding="utf-8"))
        for m in (smc.get("matrix_backtest") or []):        # list of {algo_id,symbol,exp_R,n,wr}
            if m.get("n"):
                out[(m["algo_id"], m.get("symbol", "XAUUSD"))] = {
                    "exp_R": m.get("exp_R"), "n": m.get("n"), "wr": m.get("wr"),
                    "managed": m.get("managed", False)}
    except Exception:
        pass
    return out


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


def orders(algo_id, symbol, limit=80):
    """Per-order detail for one (algo,symbol) — drives the Shadow Matrix row dropdown.
    Reads logs/shadow/<algo>__<sym>.jsonl, returns latest-first list of the individual
    signals with their resolved P&L. Import-safe, 0 token (compute-in-code)."""
    recs = [r for r in _read(os.path.join(_LOGDIR, f"{algo_id}__{symbol}.jsonl"))
            if r.get("kind") == "signal"]
    out = []
    for r in recs:
        o = r.get("outcome") or {}
        out.append({
            "bar_ts": r.get("bar_ts"), "regime": r.get("regime"), "dir": r.get("dir"),
            "entry": r.get("entry"), "sl": r.get("sl"), "tp": r.get("tp"),
            "result": o.get("result") or "OPEN", "realized_R": o.get("realized_R"),
            "exit_price": o.get("exit_price"), "bars_held": o.get("bars_held"),
            "mfe_R": o.get("mfe_R"), "mae_R": o.get("mae_R"),
        })
    out.sort(key=lambda x: x.get("bar_ts") or "", reverse=True)
    closed = [x for x in out if x["result"] in ("TP", "SL", "TIMEOUT")]
    sum_R = round(sum(x["realized_R"] or 0 for x in closed), 2)
    return {"ok": True, "algo_id": algo_id, "symbol": symbol,
            "n": len(closed), "n_open": len(out) - len(closed), "sum_R": sum_R,
            "orders": out[:limit]}


def build():
    """Full matrix dict for the dashboard. Import-safe, fail-soft."""
    import config as _cfg
    universe = getattr(_cfg, "SHADOW_UNIVERSE", None) or _reg.UNIVERSE
    eligible = _reg.combos(universe)
    bt = _load_backtest()
    try:
        from agents import real_edge as _re                 # edge จริงจากไม้ปิดเงินจริง (join ต่อ combo)
        real = {(r["algo_id"], r["symbol"]): r for r in _re.build().get("rows", [])}
    except Exception:
        real = {}
    rows = []
    for algo_id, symbol in eligible:
        algo = _reg.get(algo_id)
        klass = getattr(algo, "klass", "scalp")
        recs = _read(os.path.join(_LOGDIR, f"{algo_id}__{symbol}.jsonl"))
        stat = _aggregate(recs, klass)
        b = bt.get((algo_id, symbol))                  # backtest ref ต่อ (algo, คู่) — momentum + mean_reversion
        st = _sw.state_of(algo_id, symbol)
        # exec_mode = "เทรดจริงยังไง" (แยกจาก switch): engine ทองเทรด live เอง (switch ไม่คุม) vs MSE (switch=LIVE) vs paper/off
        engine_live = (symbol == _ALGO_META.get(algo_id, {}).get("live_symbol"))
        exec_mode = ("LIVE_ENGINE" if engine_live else
                     "LIVE_MSE" if st == _sw.LIVE else
                     "OFF" if st == _sw.OFF else "SHADOW")
        # unify: ทองใช้ switch เดียวกับทุกคู่ (shadow_switches SHADOW/LIVE/OFF). engine อ่าน gold_state เดียวกัน → display/engine ตรงกัน
        switch_kind, switch_state = "combo", st
        if engine_live:
            gst = _sw.gold_state(algo_id)
            switch_state = gst
            exec_mode = ("LIVE_ENGINE" if gst == _sw.LIVE else
                         "PAPER_ENGINE" if gst == _sw.SHADOW else "OFF")
        rows.append({"algo_id": algo_id, "symbol": symbol, "klass": klass,
                     "state": st, "exec_mode": exec_mode,
                     "switch_kind": switch_kind, "switch_state": switch_state,
                     # live = คู่ที่เทรดจริง: gold intraday engine (live_symbol) หรือ combo ที่ toggle=LIVE (MSE เช่น WTI)
                     "live": engine_live or st == _sw.LIVE,
                     "backtest_exp_R": (b.get("exp_R") if b else None),
                     "backtest_n": (b.get("n") if b else None),
                     "backtest_wr": (b.get("wr") if b else None),
                     "backtest_managed": bool(b.get("managed")) if b else False,
                     "real_n": (real.get((algo_id, symbol)) or {}).get("n", 0),
                     "real_exp_R": (real.get((algo_id, symbol)) or {}).get("exp_R"),
                     "real_wr": (real.get((algo_id, symbol)) or {}).get("wr"),
                     "real_regime": (real.get((algo_id, symbol)) or {}).get("by_regime", {}), **stat})
    # +row สำหรับ algo ที่ไม่ใช่ registry combo — มี real fills (decision_ai/tsmom_d1) หรือมี backtest ต่อคู่ (tsmom_d1)
    # → Shadow Matrix = ทุกกลยุทธ์จริง + เทียบ backtest-promise vs real ต่อคู่ (registry combo จัดการใน loop บนแล้ว)
    _have = {(r["algo_id"], r["symbol"]) for r in rows}
    _reg_ids = {a for a, _ in eligible}                    # algo ids ที่ registry จัดการใน loop บนแล้ว
    _extra = set(real) | {k for k in bt if k[0] not in _reg_ids}
    for (a, s) in _extra:
        if (a, s) in _have:
            continue
        b = bt.get((a, s))
        rr = real.get((a, s)) or {}
        zero = _aggregate([], "scalp")
        # tsmom_d1:XAUUSD = engine ทอง (tsmom_manager อ่าน shadow_switches) → combo switch เหมือนทุกคู่ · อื่น = reference (no switch)
        if a == "tsmom_d1" and s == "XAUUSD":
            gst = _sw.gold_state("tsmom_d1")
            sk, ss, lv = "combo", gst, (gst == _sw.LIVE)
            em = ("LIVE_ENGINE" if gst == _sw.LIVE else "PAPER_ENGINE" if gst == _sw.SHADOW else "OFF")
        else:
            sk, ss, em, lv = "none", "—", ("LIVE_ENGINE" if rr else "SHADOW"), bool(rr)
        rows.append({"algo_id": a, "symbol": s, "klass": "scalp", "state": "—",
                     "exec_mode": em, "live": lv, "switch_kind": sk, "switch_state": ss,
                     "backtest_exp_R": (b.get("exp_R") if b else None),
                     "backtest_n": (b.get("n") if b else None),
                     "backtest_wr": (b.get("wr") if b else None),
                     "backtest_managed": bool(b.get("managed")) if b else False,
                     "real_n": rr.get("n", 0), "real_exp_R": rr.get("exp_R"),
                     "real_wr": rr.get("wr"), "real_regime": rr.get("by_regime", {}), **zero})
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
        # ใช้ real edge ต่อ combo ถ้ามีไม้จริง (LIVE) — ไม่งั้น shadow paper (SHADOW) → รวมเห็นภาพจริงครบ
        use_real = (r.get("real_n") or 0) > 0
        n = r["real_n"] if use_real else r["n"]
        expR = r["real_exp_R"] if use_real else r["exp_R"]
        sumR = (r["real_exp_R"] * r["real_n"]) if use_real else (r["sum_R"] or 0.0)
        wins = round((r.get("real_wr") or 0) / 100 * r["real_n"]) if use_real else (r["by_result"].get("TP", 0) if r["by_result"] else 0)
        a["n"] += n; a["sum_R"] += (sumR or 0.0)
        if n:
            a["pairs_traded"] += 1
            if expR is not None and expR > 0:
                a["pairs_pos"] += 1
            a["wins"] += wins
            if expR is not None:
                if a["best"] is None or expR > a["best"][1]:
                    a["best"] = [r["symbol"], expR]
                if a["worst"] is None or expR < a["worst"][1]:
                    a["worst"] = [r["symbol"], expR]
    for a in by_algo.values():
        a["sum_R"] = round(a["sum_R"], 1)
        a["exp_R"] = round(a["sum_R"] / a["n"], 3) if a["n"] else None
        a["wr"] = round(a["wins"] / a["n"] * 100, 1) if a["n"] else None
        m = _ALGO_META.get(a["algo_id"], {})
        a["name"] = m.get("name", a["algo_id"])
        a["note"] = m.get("note")
        a["live_symbol"] = m.get("live_symbol")
        a["live"] = bool(m.get("live_symbol"))          # momentum = live บน XAUUSD (engine แยก)
    by_algo_list = list(by_algo.values())
    # TSMOM-D1 = engine ที่ 2 ที่เทรดจริงบนทอง (metric = Sharpe/equity คนละแบบ momentum → field headline แยก)
    try:
        from agents.shadow_tsmom import summary as _ts_summary
        _g = next((r for r in (_ts_summary().get("rows") or [])
                   if str(r.get("symbol", "")).upper().startswith("XAU")), None)
        if _g and _g.get("sharpe") is not None:
            _hl = f"Sharpe {_g['sharpe']} · OOS {'+' if (_g.get('sr_oos') or 0) > 0 else ''}{_g.get('sr_oos')}"
        else:
            _hl = (_g or {}).get("note") or "เก็บ data"
        _tn = (_g or {}).get("n_days")
    except Exception:
        _hl, _tn = "เก็บ data", None
    by_algo_list.append({"algo_id": "TSMOM-D1", "name": "TSMOM-D1 (daily)", "regime": "TREND · D1",
                         "live": getattr(_cfg, "TSMOM_LIVE", False), "live_symbol": "XAUUSD",
                         "note": "directional รายวัน · เทรดจริงบนทอง · ดูรายละเอียด TSMOM section",
                         "headline": _hl, "n": _tn, "wr": None, "exp_R": None, "sum_R": None,
                         "pairs_pos": None, "pairs_traded": None, "best": None, "worst": None})
    return {"ok": True, "generated": datetime.now(timezone.utc).isoformat()[:16] + "Z",
            "engine_on": getattr(_cfg, "SHADOW_ENGINE", False),
            "n_ready": _N_READY, "ready_exp_R": _READY_EXP_R, "min_span_days": _MIN_SPAN_DAYS,
            "counts": counts, "rows": rows, "by_algo": by_algo_list,
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
