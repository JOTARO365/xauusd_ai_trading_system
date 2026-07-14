"""
zone_mapper.py — Stage-1 owner of the specialist-agents feature.

Builds ONE `zone_map` object (unified S/R ladder + range box + HTF anchor) that the
TrendSpecialist and RangeSpecialist consume as the single source of truth. Pure Python —
zone math needs no LLM, so this adds ZERO tokens. It CONSUMES chart_watcher's already-computed
outputs (`sr_meta`, `sr_zones`, `key_levels`, `htf_zone`) rather than re-detecting swings.

Design of record: docs/DESIGN_specialist_agents.md (§2.1). Ships behind a flag; unwired until
the graph node is added. Gold: 1 pip = 1 point = 0.01.

NOTE (continue.md 2026-07-14): this promotes `sr_meta` from display-only to a consumed input.

Box math mirrors pending_manager.manage_range_pending (:714-745) so the two agree; unifying them
into this single source is a later phase (would touch the pending order path — out of phase-1 scope).
"""
from __future__ import annotations

_POINT = 0.01          # gold point/pip size
_MIN_BOX_WIDTH_PIPS = 2000
_ATR_WIDTH_FRAC = 0.60  # ATR > width*0.60 => range too volatile to be a clean box


def _dist_pct(level: float, current: float) -> float:
    """Signed distance of a level from current price, in percent (+ above, - below)."""
    if not current:
        return 0.0
    return round((level - current) / current * 100, 3)


def _build_ladder(sr_meta: list, current: float) -> list:
    """Enrich sr_meta (H1/H4 zones) into a distance-sorted ladder. Fail-soft on bad input."""
    ladder = []
    for m in sr_meta or []:
        lv = m.get("level")
        if lv is None:
            continue
        ladder.append({
            "level":      lv,
            "tf":         m.get("tf"),
            "side":       m.get("side"),          # "R" / "S"
            "strength":   m.get("strength"),
            "touches":    m.get("touches"),
            "dist_pct":   _dist_pct(lv, current),
            "confluence": bool(m.get("confluence")),
            "why":        m.get("why", ""),
        })
    ladder.sort(key=lambda z: abs(z["dist_pct"]))   # nearest first
    return ladder


def _nearest(ladder: list, side: str, current: float) -> dict | None:
    """Nearest R above / S below current, from the ladder."""
    if side == "R":
        cands = [z for z in ladder if z["side"] == "R" and z["level"] > current]
    else:
        cands = [z for z in ladder if z["side"] == "S" and z["level"] < current]
    return min(cands, key=lambda z: abs(z["dist_pct"])) if cands else None


def _build_box(chart_data: dict, current: float) -> dict:
    """Range box from sr_zones + PDH/PDL, mirroring manage_range_pending. Returns valid=False
    (with a reason) rather than raising when a clean box can't be formed."""
    sr_zones = chart_data.get("sr_zones", {}) or {}
    key_lvl  = chart_data.get("key_levels", {}) or {}
    h4_atr   = (chart_data.get("indicators", {}) or {}).get("h4", {}).get("atr", 0) or 0

    res_list = sorted([r for r in sr_zones.get("resistance", []) if r > current])
    sup_list = sorted([s for s in sr_zones.get("support",    []) if s < current], reverse=True)

    pdh, pdl = key_lvl.get("pdh"), key_lvl.get("pdl")
    if pdh and pdh > current:
        res_list = sorted(set(res_list + [round(pdh, 2)]))
    if pdl and pdl < current:
        sup_list = sorted(set(sup_list + [round(pdl, 2)]), reverse=True)

    if not res_list or not sup_list:
        return {"upper": None, "lower": None, "width_pips": 0, "valid": False,
                "reason": "no bounds both sides"}

    upper, lower = res_list[0], sup_list[0]
    width = upper - lower
    width_pips = round(width / _POINT)

    if width_pips < _MIN_BOX_WIDTH_PIPS:
        return {"upper": upper, "lower": lower, "width_pips": width_pips, "valid": False,
                "reason": f"width {width_pips}p < {_MIN_BOX_WIDTH_PIPS}p"}
    if h4_atr > 0 and h4_atr > width * _ATR_WIDTH_FRAC:
        return {"upper": upper, "lower": lower, "width_pips": width_pips, "valid": False,
                "reason": f"ATR {h4_atr:.1f} > width*{_ATR_WIDTH_FRAC}"}

    return {"upper": upper, "lower": lower, "width_pips": width_pips, "valid": True, "reason": "ok"}


def build_zone_map(chart_data: dict, current: float) -> dict:
    """Single source of truth for the specialists. Pure, side-effect-free, 0 tokens.

    Returns:
      {
        "current": float,
        "ladder": [ {level, tf, side, strength, touches, dist_pct, confluence, why}, ... ]  # nearest first
        "nearest": {"resistance": <zone|None>, "support": <zone|None>},
        "box": {"upper","lower","width_pips","valid","reason"},
        "htf_anchor": <chart_data["htf_zone"] | None>,   # nearest D1/W1 zone
      }
    Fail-soft: bad/empty chart_data yields an empty-but-valid map, never raises.
    """
    if not isinstance(chart_data, dict) or not current:
        return {"current": current or 0.0, "ladder": [], "nearest": {"resistance": None, "support": None},
                "box": {"upper": None, "lower": None, "width_pips": 0, "valid": False, "reason": "no data"},
                "htf_anchor": None}

    ladder = _build_ladder(chart_data.get("sr_meta", []), current)
    return {
        "current":     current,
        "ladder":      ladder,
        "nearest":     {"resistance": _nearest(ladder, "R", current),
                        "support":    _nearest(ladder, "S", current)},
        "box":         _build_box(chart_data, current),
        "htf_anchor":  chart_data.get("htf_zone"),
    }
