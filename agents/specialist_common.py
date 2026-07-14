"""
specialist_common.py — shared pure helpers for the specialist agents (Trend + Range).

0 tokens, no side effects, no `df` needed (chart_data has it stripped). Kept here so both
specialists route regime and read PA confirmation the SAME way — divergence between them would be a
subtle bug. Design of record: docs/DESIGN_specialist_agents.md.
"""
from __future__ import annotations


def tf_regime(chart_data: dict, tf: str) -> str:
    """Deterministic per-TF regime → BULLISH / BEARISH / SIDEWAYS (free, replay-able).
      h4 → chart_data["trend"] (the field gates 4/5 already enforce)
      d1 → chart_data["d1_trend"] (NEUTRAL treated as SIDEWAYS)
      h1 → EMA stack AND momentum must agree (no explicit h1 trend field exists)
    """
    if tf == "h4":
        return (chart_data.get("trend") or "SIDEWAYS").upper()
    if tf == "d1":
        d1 = (chart_data.get("d1_trend") or "NEUTRAL").upper()
        return d1 if d1 in ("BULLISH", "BEARISH") else "SIDEWAYS"
    mom = (chart_data.get("momentum_tf") or {}).get("h1") or {}
    align, direction = mom.get("ema_align"), mom.get("direction")
    if align == "BULL" and direction == "UP":
        return "BULLISH"
    if align == "BEAR" and direction == "DOWN":
        return "BEARISH"
    return "SIDEWAYS"


def pa_confirms(chart_data: dict, direction: str, want_zone: str) -> bool:
    """Fresh PA confirmation in `direction`: a matching candle bias OR an S/R rejection at the
    wanted zone. want_zone = 'SUPPORT' for BUY, 'RESISTANCE' for SELL."""
    cp = chart_data.get("candle_pat") or {}
    if (cp.get("bias") == "BULLISH" and direction == "BUY") or \
       (cp.get("bias") == "BEARISH" and direction == "SELL"):
        return True
    for a in chart_data.get("sr_actions") or []:
        if a.get("action") == "REJECTION" and a.get("direction") == direction and a.get("zone") == want_zone:
            return True
    return False
