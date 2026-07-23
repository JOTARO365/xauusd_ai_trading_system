"""agents/shadow_cost.py — Batch B (T-03): measured per-symbol cost, in POINTS.

cost_pips(symbol) = median of that symbol's recorded spread (data/pairs/spread_log.jsonl, written by
pair_collector as spread_pts = round((ask-bid)/point)). Same unit as an algo's sl_pips (both are
POINTS), so shadow_resolve uses it directly: realized_R = r_gross − cost_pips / sl_pips.

D3 (locked 2026-07-23): **spread-only**. Swap / overnight financing is NOT modelled — the matrix must
flag "net of spread only". A measured swap table is a prerequisite before ANY combo is promoted to LIVE.
Cache 5 min (spread drifts slowly); fail-soft to a conservative default.
"""
import json
import os
import statistics
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPREAD_LOG = os.path.join(_BASE, "data", "pairs", "spread_log.jsonl")
_TTL = 300
_DEFAULT_COST_PIPS = 30.0            # conservative fallback (≈ gold spread+commission) when no data yet
_cache = {"t": 0.0, "map": {}}

# swap is intentionally excluded in v1 (D3). Exposed so consumers can render the gap honestly.
SWAP_MODELLED = False


def _refresh():
    """One pass over spread_log → {symbol: median spread_pts}. fail-soft → {}."""
    acc = {}
    try:
        with open(_SPREAD_LOG, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                    sp = r.get("spread_pts")
                    sym = r.get("sym")
                    if sym is not None and sp is not None:
                        acc.setdefault(sym, []).append(float(sp))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        return {}
    return {sym: statistics.median(v) for sym, v in acc.items() if v}


def cost_pips(symbol):
    """Median measured spread (points) for `symbol`; fallback _DEFAULT_COST_PIPS if no data. Cache 5 min."""
    now = time.time()
    if now - _cache["t"] >= _TTL:
        _cache["map"] = _refresh()
        _cache["t"] = now
    return _cache["map"].get(symbol, _DEFAULT_COST_PIPS)


def has_data(symbol):
    """True if `symbol` has any recorded spread (⇒ cost_pips is measured, not the fallback)."""
    if time.time() - _cache["t"] >= _TTL:
        _cache["map"] = _refresh()
        _cache["t"] = time.time()
    return symbol in _cache["map"]


if __name__ == "__main__":
    m = _refresh()
    print("measured cost_pips (median spread, points):")
    for sym in sorted(m):
        print(f"  {sym:8s} {m[sym]:.1f}")
    print(f"swap modelled: {SWAP_MODELLED} (spread-only per D3)")
