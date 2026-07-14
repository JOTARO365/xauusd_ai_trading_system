"""
range_specialist.py — owns the SIDEWAYS lane of the specialist-agents feature.

Pure Python, 0 tokens. When the H4 lane is SIDEWAYS and the ZoneMapper `box` is valid, it looks for
edge entries: BUY near the lower band / SELL near the upper band, each needing a fresh rejection PA.
If price has broken OUT of the box, the range is invalidated → no range entry (that's the trend
lane's job). Returns entry CANDIDATES; it does NOT place orders and does NOT gate — every candidate
still funnels through decision_maker (conf floor 62, daily cap 6).

Design of record: docs/DESIGN_specialist_agents.md (§2.3). Mirrors the intent of decision_maker gate
5 (SIDEWAYS handling, :581-606) + manage_range_pending, now centralized on the shared `zone_map`.
The box is H4-level (from sr_zones H4+H1); a per-TF H1 range box is a later phase.

Consumes: zone_map["box"] {upper, lower, width_pips, valid}, zone_map["current"],
          chart_data via specialist_common.tf_regime / pa_confirms.
"""
from __future__ import annotations

from agents.specialist_common import tf_regime, pa_confirms

_EDGE_FRAC = 0.15      # within this fraction of box width from an edge = "at the edge"
_A_WIDTH_PIPS = 3000   # a wide, clean range earns quality A; narrower = B


def _quality(box: dict) -> str:
    return "A" if (box.get("width_pips") or 0) >= _A_WIDTH_PIPS else "B"


def _edge_candidate(current, level, direction, box, chart_data) -> dict | None:
    want_zone = "SUPPORT" if direction == "BUY" else "RESISTANCE"
    if not pa_confirms(chart_data, direction, want_zone):
        return None
    return {
        "specialist":    "RANGE",
        "tf":            "H4",          # box is H4-level in v1
        "direction":     direction,
        "regime":        "SIDEWAYS",
        "entry_level":   level,
        "zone_strength": None,
        "quality":       _quality(box),
        "reason":        f"range {direction} at {want_zone.lower()} edge {level} "
                         f"(box {box.get('lower')}–{box.get('upper')}) + PA confirm",
    }


def evaluate(chart_data: dict, zone_map: dict) -> list[dict]:
    """Range edge entries. Returns 0..2 candidates (buy@lower / sell@upper). Fail-soft: never raises.

    Guards, in order:
      - box must be valid (width ≥ 2000p, ATR not too big — ZoneMapper already checked)
      - H4 lane must be SIDEWAYS (range is an H4 phenomenon here)
      - if price has broken OUT of the box, the range is invalid → return [] (no range entry)
      - otherwise, an edge entry needs price AT the band + a fresh rejection PA
    """
    if not isinstance(chart_data, dict) or not isinstance(zone_map, dict):
        return []
    box = zone_map.get("box") or {}
    if not box.get("valid"):
        return []
    current = zone_map.get("current")
    upper, lower = box.get("upper"), box.get("lower")
    if not (current and upper and lower and upper > lower):
        return []

    # range only when the H4 lane is genuinely sideways (don't fight an active trend)
    if tf_regime(chart_data, "h4") != "SIDEWAYS":
        return []

    # breakout invalidation — price outside the box means the range is gone, not an edge entry
    if current > upper or current < lower:
        return []

    width = upper - lower
    edge = width * _EDGE_FRAC
    out = []
    if (current - lower) <= edge:                      # sitting on the lower band → buy the range
        c = _edge_candidate(current, lower, "BUY", box, chart_data)
        if c:
            out.append(c)
    if (upper - current) <= edge:                      # sitting on the upper band → sell the range
        c = _edge_candidate(current, upper, "SELL", box, chart_data)
        if c:
            out.append(c)
    return out
