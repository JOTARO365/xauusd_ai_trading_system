"""
specialist_router.py — routes the specialist lanes and ranks their entry candidates.

Pure Python, 0 tokens. Runs ZoneMapper's output through the Trend + Range specialists, collects the
per-TF candidates (multi-TF = more entry opportunities), and ranks them. It does NOT place orders and
does NOT gate — it hands a ranked list (and a `top` pick) to decision_maker, which applies the real
gates (conf floor 62) + the shared daily cap (6). The cap, not the router, is what keeps "more
entries" from becoming overtrading.

Dormancy invariant (design §2.4): within one TF lane, only ONE specialist owns it — Trend owns
BULLISH/BEARISH lanes, Range owns SIDEWAYS. They are mutually exclusive by regime, so a lane can
never be double-claimed; the router asserts this and logs the active/dormant picture each cycle.

Design of record: docs/DESIGN_specialist_agents.md (§2.4).
"""
from __future__ import annotations

from agents.trend_specialist import evaluate as _trend_eval
from agents.range_specialist import evaluate as _range_eval
from agents.specialist_common import tf_regime

_QUALITY_RANK = {"A": 3, "B": 2, "C": 1}
_TF_RANK = {"H4": 3, "D1": 2, "H1": 1}   # H4 most reliable, H1 the scalp lane


def _rank_key(c: dict):
    return (_QUALITY_RANK.get(c.get("quality"), 0), _TF_RANK.get(c.get("tf"), 0))


def route(chart_data: dict, zone_map: dict) -> dict:
    """Aggregate + rank specialist candidates. Fail-soft: never raises.

    Returns:
      {
        "lanes":      {"h1": <regime>, "h4": <regime>, "d1": <regime>},
        "candidates": [ranked entry candidates, best first],
        "top":        best candidate | None,
        "log":        one-line summary for system.log (0 token),
      }
    """
    if not isinstance(chart_data, dict) or not isinstance(zone_map, dict):
        return {"lanes": {}, "candidates": [], "top": None, "log": "[SPEC] no data"}

    lanes = {tf: tf_regime(chart_data, tf) for tf in ("h1", "h4", "d1")}
    candidates = list(_trend_eval(chart_data, zone_map)) + list(_range_eval(chart_data, zone_map))

    # dormancy invariant: no single TF lane may carry both a Trend and a Range candidate
    seen = {}
    for c in candidates:
        key = (c.get("tf"), c.get("specialist"))
        seen.setdefault(c.get("tf"), set()).add(c.get("specialist"))
    conflict = [tf for tf, specs in seen.items() if len(specs) > 1]

    candidates.sort(key=_rank_key, reverse=True)
    top = candidates[0] if candidates else None

    if candidates:
        parts = ", ".join(f"{c['tf']}:{c['specialist'][0]}{c['direction'][0]}({c['quality']})"
                          for c in candidates)
        log = f"[SPEC] {len(candidates)} cand [{parts}] top={top['tf']} {top['direction']} Q{top['quality']}"
    else:
        active = "/".join(f"{tf}:{r[:4]}" for tf, r in lanes.items())
        log = f"[SPEC] 0 cand — lanes {active}"
    if conflict:
        log += f" | WARN lane conflict {conflict}"

    return {"lanes": lanes, "candidates": candidates, "top": top, "log": log}
