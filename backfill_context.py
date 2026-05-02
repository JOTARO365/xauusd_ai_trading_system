"""
One-time backfill: parse MT5 order comments for SYSTEM RECOVERED/MANUAL trades
to fill pa_action, technical_signal, sentiment where recoverable.

MT5 comment format: "AI:{signal}|PA:{pa_tag}|{sentiment}"
Example: "AI:SELL|PA:REJECTION|NEUTRAL"  or  "AI:BUY|PA:NOPA|N"

Run: python backfill_context.py
"""
import json
import os
import re

os.chdir(os.path.dirname(os.path.abspath(__file__)))

LOG_FILE = "logs/trades.json"

_PA_MAP = {
    "REJECTION": "REJECTION",
    "REJEC":     "REJECTION",
    "REJECT":    "REJECTION",
    "BREAKOUT":  "BREAKOUT",
    "BREAK":     "BREAKOUT",
    "NOPA":      "NONE",
    "":          "NONE",
}

_SENT_MAP = {
    "NEUTRAL":  "NEUTRAL",
    "BULLISH":  "BULLISH",
    "BEARISH":  "BEARISH",
    "BULL":     "BULLISH",
    "BEAR":     "BEARISH",
    "N":        "NEUTRAL",
    "B":        "BULLISH",
    "S":        "BEARISH",
}


def _parse_comment(comment: str) -> dict | None:
    """Parse 'AI:SELL|PA:REJECTION|NEUTRAL' → {signal, pa_action, sentiment}"""
    if not comment or not comment.startswith("AI:"):
        return None
    parts = comment.split("|")
    result: dict = {}

    # AI:{signal}
    try:
        result["technical_signal"] = parts[0].split(":")[1].strip()
    except (IndexError, ValueError):
        return None

    # PA:{pa_tag}
    for p in parts[1:]:
        if p.startswith("PA:"):
            raw_pa = p[3:].strip().upper()
            result["pa_action"] = _PA_MAP.get(raw_pa, raw_pa if raw_pa else "NONE")

    # {sentiment} — last segment (may be truncated)
    if len(parts) >= 3:
        raw_sent = parts[-1].strip().upper()
        result["sentiment"] = _SENT_MAP.get(raw_sent, None)

    return result


def main():
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    trades = data["trades"]
    updated = 0

    for t in trades:
        comment = (t.get("manual_reason") or "").strip()
        parsed  = _parse_comment(comment)
        if not parsed:
            continue

        changed = False

        if not t.get("technical_signal") or t.get("technical_signal") == t.get("direction"):
            sig = parsed.get("technical_signal")
            if sig and sig in ("BUY", "SELL") and t.get("technical_signal") is None:
                t["technical_signal"] = sig
                changed = True

        if t.get("pa_action") in (None, "NONE"):
            pa = parsed.get("pa_action")
            if pa and pa != "NONE":
                t["pa_action"] = pa
                changed = True

        if t.get("sentiment") is None:
            sent = parsed.get("sentiment")
            if sent:
                t["sentiment"] = sent
                changed = True

        if changed:
            updated += 1
            print(f"  ticket={t['ticket']} {t['direction']:4s} "
                  f"pa_action={t.get('pa_action')} sentiment={t.get('sentiment')}  <- {comment!r}")

    print(f"\nBackfill complete: {updated} trades updated from MT5 comment")

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("trades.json saved.")


if __name__ == "__main__":
    main()
