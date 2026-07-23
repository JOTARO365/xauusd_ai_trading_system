"""agents/shadow_engine.py — Batch B (T-04): multi-pair shadow engine.

Each cycle, for every (algo, pair) whose switch state is SHADOW: fetch that pair's H1 bars, ask the
algo for a VirtualOrder, log a new signal (dedup per bar_ts), and resolve open signals against the
real bars (SL-first, per-pair measured cost). Sends NOTHING to MT5 — this is a paper record only.

Storage: one JSONL per combo, logs/shadow/<algo_id>__<symbol>.jsonl (record schema = ARCHITECTURE §4.3).
Whole-file rewrite on change (outcomes mutate in place), same as algo_journal.

Reuses: algo_registry (signals), shadow_switches (state), shadow_cost (per-pair cost), shadow_resolve
(the parity-tested resolver), pair_collector._broker_map (logical→broker symbol), price_feed.get_ohlcv.
The XAUUSD live pipeline and algo_journal are NOT touched.

Wiring (T-05): trading_graph.node_position_mgmt calls tick() every cycle, gated by config.SHADOW_ENGINE.
"""
import json
import os
from datetime import datetime, timezone

from loguru import logger

from agents import algo_registry as _reg
from agents import shadow_switches as _sw
from agents import shadow_cost as _cost
from agents.shadow_resolve import resolve_signal

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGDIR = os.path.join(_BASE, "logs", "shadow")
_DEFAULT_MAX_HOLD = 48
_BARS_COUNT = 600


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _logpath(algo_id, symbol):
    return os.path.join(_LOGDIR, f"{algo_id}__{symbol}.jsonl")


def _read_rows(path):
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


def _write_rows(path, rows):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _new_record(vo, cost_pips, point, digits):
    """Build an OPEN signal record from a VirtualOrder (schema §4.3). Outcome filled by first resolve."""
    sign = 1 if vo["dir"] == "BUY" else -1
    entry, slp, tpp = vo["entry"], vo["sl_pips"], vo["tp_pips"]
    return {
        "algo_id": vo["algo_id"], "symbol": vo["symbol"], "klass": vo["klass"],
        "kind": "signal", "logged_at": _iso_now(), "bar_ts": vo["bar_ts"],
        "regime": vo["regime"], "dir": vo["dir"], "entry": entry,
        "sl": round(entry - sign * slp * point, digits),
        "tp": round(entry + sign * tpp * point, digits),
        "sl_pips": slp, "tp_pips": tpp,
        "cost_pips": cost_pips, "point": point, "price_digits": digits,
    }


def _apply(algo_id, symbol, bars, point, digits, cost_pips, max_hold=_DEFAULT_MAX_HOLD):
    """Pure-ish core (no MT5): capture new signal + resolve open ones for ONE combo. Returns a summary.
    Testable directly with injected bars. Each signal resolves at the cost/point stored on its record."""
    high, low, close, times = bars
    path = _logpath(algo_id, symbol)
    rows = _read_rows(path)
    seen = {r.get("bar_ts") for r in rows if r.get("kind") == "signal"}
    changed = False
    new = 0

    # 1) capture new signal at the last closed bar (dedup per bar_ts)
    algo = _reg.get(algo_id)
    vo = algo.evaluate(symbol, bars) if algo else None
    if vo and vo.get("bar_ts") and vo["bar_ts"] not in seen:
        rows.append(_new_record(vo, cost_pips, point, digits))
        changed = True
        new = 1

    # 2) resolve every open record against forward bars
    resolved = 0
    for rec in rows:
        if rec.get("kind") != "signal":
            continue
        res = (rec.get("outcome") or {}).get("result")
        if res in ("TP", "SL", "TIMEOUT"):
            continue                                     # terminal — skip
        out = resolve_signal(rec, high, low, close, times,
                             point=rec.get("point", point),
                             cost_pips=rec.get("cost_pips", cost_pips),
                             max_hold_bars=max_hold,
                             price_digits=rec.get("price_digits", digits))
        if out is not None and out != rec.get("outcome"):
            rec["outcome"] = out
            changed = True
            if out.get("result") in ("TP", "SL", "TIMEOUT"):
                resolved += 1

    if changed:
        _write_rows(path, rows)
    return {"combo": f"{algo_id}:{symbol}", "new": new, "resolved": resolved, "rows": len(rows)}


def _bars(broker_symbol, count=_BARS_COUNT):
    """(high, low, close, times) for a broker symbol from MT5 H1, or None. fail-soft."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        rates = get_ohlcv(symbol=broker_symbol, timeframe=mt5.TIMEFRAME_H1, count=count)
        if rates is None or len(rates) < 520:
            return None
        return (rates["high"].astype(float), rates["low"].astype(float),
                rates["close"].astype(float), rates["time"])
    except Exception:
        return None


def _symbol_meta(broker_symbol):
    """(point, digits) for a broker symbol, or (None, None) if unavailable."""
    try:
        import MetaTrader5 as mt5
        info = mt5.symbol_info(broker_symbol)
        if info and info.point:
            return float(info.point), int(info.digits)
    except Exception:
        pass
    return None, None


def tick(force=False):
    """Every-cycle entry. Gated by config.SHADOW_ENGINE (or force=True for tests). fail-soft; 0 orders.
    Returns a summary dict, or None when gated off."""
    import config as _cfg
    if not force and not getattr(_cfg, "SHADOW_ENGINE", False):
        return None
    universe = getattr(_cfg, "SHADOW_UNIVERSE", None) or _reg.UNIVERSE
    max_hold = getattr(_cfg, "SHADOW_MAX_HOLD_BARS", _DEFAULT_MAX_HOLD)
    eligible = _reg.combos(universe)

    active = _sw.combos_in(_sw.SHADOW, eligible)
    live = _sw.combos_in(_sw.LIVE, eligible)             # v1: no non-XAU live path → run LIVE as shadow + warn
    for a, s in live:
        logger.warning(f"[SHADOW] {a}:{s} state=LIVE has no live path in v1 — running as SHADOW")
    active = active + live
    if not active:
        return {"combos": 0, "new": 0, "resolved": 0}

    from connectors.pair_collector import _broker_map
    bmap = _broker_map()

    n_new = n_res = ok = 0
    for algo_id, symbol in active:
        try:
            broker = bmap.get(symbol, symbol)
            bars = _bars(broker)
            if bars is None:
                continue
            point, digits = _symbol_meta(broker)
            if point is None:
                continue
            r = _apply(algo_id, symbol, bars, point, digits, _cost.cost_pips(symbol), max_hold)
            n_new += r["new"]; n_res += r["resolved"]; ok += 1
        except Exception as e:
            logger.debug(f"[SHADOW] {algo_id}:{symbol} fail-soft: {e}")
    if n_new or n_res:
        logger.info(f"[SHADOW] tick: combos={ok}/{len(active)} new={n_new} resolved={n_res}")
    return {"combos": ok, "new": n_new, "resolved": n_res}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa: F401 (load .env)
    r = tick(force=True)
    print("shadow tick:", r)
