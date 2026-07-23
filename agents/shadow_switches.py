"""agents/shadow_switches.py — Batch B (T-03): per-(algo,pair) shadow switch store.

State machine per combo: SHADOW (log+resolve, 0 orders) · LIVE (reserved — engine downgrades to
SHADOW in v1; no non-XAU live path exists yet) · OFF (skip). Stored in data/algo_switches.json,
hot-reloaded every cycle with a 60 s TTL cache (same idiom as regime_adaptive.disabled_strategies),
fail-soft, dashboard-editable later. A MISSING key for an eligible combo defaults to SHADOW
(so a newly-registered pair starts collecting immediately).

Frozen format — docs/ARCHITECTURE_batchB.md §4.4:  { "<algo_id>:<symbol>": "SHADOW"|"LIVE"|"OFF" }
"""
import json
import os
import time
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SWITCHES = os.path.join(_BASE, "data", "algo_switches.json")
_TTL = 60
_cache = {"t": 0.0, "map": {}}

SHADOW, LIVE, OFF = "SHADOW", "LIVE", "OFF"
_VALID = {SHADOW, LIVE, OFF}


def _key(algo_id, symbol):
    return f"{algo_id}:{symbol}"


def _load():
    """switch map (cache 60 s). fail-soft → {} (⇒ everything defaults SHADOW)."""
    now = time.time()
    if now - _cache["t"] < _TTL:
        return _cache["map"]
    try:
        with open(_SWITCHES, "r", encoding="utf-8") as f:
            m = json.load(f)
            _cache["map"] = m if isinstance(m, dict) else {}
    except Exception:
        _cache["map"] = {}
    _cache["t"] = now
    return _cache["map"]


def state_of(algo_id, symbol, default=SHADOW):
    """Combo state; missing/invalid → default (SHADOW). Read-side is hot (cache 60 s)."""
    st = _load().get(_key(algo_id, symbol))
    return st if st in _VALID else default


def combos_in(state, eligible):
    """Of the `eligible` (algo_id, symbol) tuples, those currently in `state`
    (missing keys count as SHADOW). `eligible` typically = algo_registry.combos(universe)."""
    return [(a, s) for (a, s) in eligible if state_of(a, s) == state]


def all_states(eligible):
    """{(algo_id,symbol): state} over eligible combos — for the dashboard/matrix."""
    return {(a, s): state_of(a, s) for (a, s) in eligible}


def set_state(algo_id, symbol, state):
    """Persist one combo's state (dashboard toggle / seeding). Forces cache reload. Returns ok."""
    if state not in _VALID:
        raise ValueError(f"invalid state {state!r}; expected one of {_VALID}")
    try:
        m = {}
        if os.path.exists(_SWITCHES):
            with open(_SWITCHES, "r", encoding="utf-8") as f:
                m = json.load(f) or {}
        m[_key(algo_id, symbol)] = state
        m["_updated"] = datetime.now(timezone.utc).isoformat()
        os.makedirs(os.path.dirname(_SWITCHES), exist_ok=True)
        with open(_SWITCHES, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        _cache["t"] = 0.0                    # force reload
        return True
    except Exception:
        return False
