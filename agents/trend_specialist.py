"""
trend_specialist.py — owns UPTREND + DOWNTREND lanes of the specialist-agents feature.

Pure Python, 0 tokens. Runs PER TIMEFRAME LANE (H1/H4/D1): if a lane's deterministic regime is
BULLISH/BEARISH, it looks for a trend-continuation entry = price pulled back to a same-side zone of
that TF + a fresh PA confirmation. Returns a list of entry CANDIDATES; it does NOT place orders and
does NOT gate — every candidate still funnels through decision_maker (conf floor 62, daily cap 6).
Multi-TF is how "more entries" happens without loosening any threshold.

Design of record: docs/DESIGN_specialist_agents.md (§2.2, §2.4). Consumes chart_data (no `df` — it's
stripped) + the ZoneMapper `zone_map`. Ships flag-OFF, unwired.

Consumed fields (must match chart_watcher output exactly):
  chart_data["trend"]            H4 bias  BULLISH/BEARISH/SIDEWAYS
  chart_data["d1_trend"]         BULLISH/BEARISH/NEUTRAL
  chart_data["momentum_tf"][tf]  {direction:UP/DOWN/FLAT, strength, ema_align:BULL/BEAR/MIXED}
  chart_data["candle_pat"]       {bias:BULLISH/BEARISH/NEUTRAL, patterns, bullish}
  chart_data["sr_actions"]       [{action:REJECTION/BREAKOUT, direction:BUY/SELL, zone, level}]
  zone_map["ladder"]             [{level, tf:H4/H1, side:R/S, strength, dist_pct, confluence}]
  zone_map["htf_anchor"]         {tf, level, zone_type:RESISTANCE/SUPPORT, dist_pct} | None
"""
from __future__ import annotations

from agents.specialist_common import tf_regime, pa_confirms

_PULLBACK_PCT = 0.40   # price must be within this % of the zone to count as "pulled back to it"
_LANES = ("h1", "h4", "d1")


def _lane_zone(zone_map: dict, tf: str, side: str) -> dict | None:
    """Nearest same-side zone for this TF that price has pulled back to.
    h1/h4 come from the ladder; d1 comes from the single htf_anchor."""
    if tf == "d1":
        a = zone_map.get("htf_anchor")
        if not a:
            return None
        want_type = "SUPPORT" if side == "S" else "RESISTANCE"
        if a.get("zone_type") != want_type or abs(a.get("dist_pct", 99)) > _PULLBACK_PCT:
            return None
        return {"level": a.get("level"), "tf": a.get("tf"), "side": side,
                "strength": None, "dist_pct": a.get("dist_pct"), "confluence": False}
    cands = [z for z in zone_map.get("ladder", [])
             if (z.get("tf") or "").upper() == tf.upper() and z.get("side") == side
             and abs(z.get("dist_pct", 99)) <= _PULLBACK_PCT]
    return min(cands, key=lambda z: abs(z["dist_pct"])) if cands else None


def _quality(zone: dict, chart_data: dict, tf: str) -> str:
    """Advisory A/B/C for the candidate — metadata only, NOT a gate (decision_maker gates decide)."""
    score = 0
    if (zone.get("strength") or 0) >= 70:
        score += 1
    if zone.get("confluence"):
        score += 1
    if (chart_data.get("momentum_tf") or {}).get(tf, {}).get("strength") == "STRONG":
        score += 1
    return "A" if score >= 2 else "B" if score == 1 else "C"


def _trend_entry(chart_data: dict, zone_map: dict, tf: str, direction: str) -> dict | None:
    side, want_zone = ("S", "SUPPORT") if direction == "BUY" else ("R", "RESISTANCE")

    # momentum must not be strongly AGAINST the entry direction on this TF
    mom = (chart_data.get("momentum_tf") or {}).get(tf) or {}
    against = (direction == "BUY" and mom.get("direction") == "DOWN" and mom.get("strength") == "STRONG") or \
              (direction == "SELL" and mom.get("direction") == "UP" and mom.get("strength") == "STRONG")
    if against:
        return None

    zone = _lane_zone(zone_map, tf, side)          # pulled back to a same-side zone of this TF?
    if not zone:
        return None
    if not pa_confirms(chart_data, direction, want_zone):   # fresh PA confirmation?
        return None

    return {
        "specialist":    "TREND",
        "tf":            tf.upper(),
        "direction":     direction,
        "regime":        "BULLISH" if direction == "BUY" else "BEARISH",
        "entry_level":   zone["level"],
        "zone_strength": zone.get("strength"),
        "quality":       _quality(zone, chart_data, tf),
        "reason":        f"{tf.upper()} trend-{'up' if direction=='BUY' else 'down'} pullback to "
                         f"{want_zone.lower()} {zone['level']} + PA confirm",
    }


def evaluate(chart_data: dict, zone_map: dict) -> list[dict]:
    """Per-lane trend entries. Returns 0..3 candidates (H1/H4/D1). Fail-soft: never raises."""
    if not isinstance(chart_data, dict) or not isinstance(zone_map, dict):
        return []
    out = []
    for tf in _LANES:
        regime = tf_regime(chart_data, tf)
        if regime == "BULLISH":
            c = _trend_entry(chart_data, zone_map, tf, "BUY")
        elif regime == "BEARISH":
            c = _trend_entry(chart_data, zone_map, tf, "SELL")
        else:
            c = None            # SIDEWAYS/TRANSITION lane → RangeSpecialist's job, not ours
        if c:
            out.append(c)
    return out
