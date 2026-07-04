"""
build_event_scenarios.py — M2 (rubric): build data/event_scenarios.json
from data/event_sign_table.json + data/event_stats.json.

M2 = rubric only: provenance:"rubric", magnitude from two-sided prior
(avg_up_pct / avg_down_pct), surprise_curve:null, n from event_stats.
Atomic write (tmp + os.replace) per ARCHITECTURE §D8.
Zero AI calls.

Run: & $PY scripts\build_event_scenarios.py
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# ── paths ─────────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SIGN_TABLE  = os.path.join(_ROOT, "data", "event_sign_table.json")
_EVENT_STATS = os.path.join(_ROOT, "data", "event_stats.json")
_OUT_FILE    = os.path.join(_ROOT, "data", "event_scenarios.json")


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _direction_for_sign(sign: str, is_hot: bool) -> str:
    """
    Derive gold direction from the sign token and whether the surprise is hot.

    hot_gold_down:   hot → down, cool → up
    hot_gold_up:     hot → up,   cool → down
    hawkish_gold_down: hot/hawkish → down, cool/dovish → up
    """
    if sign in ("hot_gold_down", "hawkish_gold_down"):
        return "down" if is_hot else "up"
    if sign == "hot_gold_up":
        return "up" if is_hot else "down"
    # fallback: unknown sign token
    raise ValueError(f"Unknown sign token: {sign!r}")


def build_scenarios(sign_table: dict, event_stats: dict) -> dict:
    """
    Join sign table with event_stats and return the scenarios dict
    matching ARCHITECTURE §4.2.

    Only events present in BOTH sign_table (keys, excluding 'note') AND
    event_stats['events'] are included; others are silently skipped so the
    output is never broken by a missing stats entry.
    """
    stats_events = event_stats.get("events", {})

    # Derive the common window from event_stats (use first available window).
    windows = [v.get("window", "") for v in stats_events.values() if v.get("window")]
    combined_window = windows[0] if windows else None

    scenarios: dict = {}

    for event_key, sign in sign_table.items():
        if event_key == "note":
            continue  # metadata field, not an event

        # Look up event stats.  event_stats keys use the same names (NFP, CPI, FOMC).
        stat = stats_events.get(event_key)
        if stat is None:
            # No stats available for this event in event_stats.json — skip gracefully.
            continue

        n             = stat["n"]
        avg_up_pct    = stat["avg_up_pct"]       # positive float, e.g. 0.87
        avg_down_pct  = stat["avg_down_pct"]     # negative float, e.g. -0.92

        # Magnitude for each scenario side:
        #   hot  side → use the directional average for that direction
        #   cool side → use the directional average for the opposite direction
        hot_dir  = _direction_for_sign(sign, is_hot=True)
        cool_dir = _direction_for_sign(sign, is_hot=False)

        # hot direction magnitude
        if hot_dir == "down":
            hot_mag = round(abs(avg_down_pct), 4)
        else:
            hot_mag = round(abs(avg_up_pct), 4)

        # cool direction magnitude
        if cool_dir == "up":
            cool_mag = round(abs(avg_up_pct), 4)
        else:
            cool_mag = round(abs(avg_down_pct), 4)

        scenarios[event_key] = {
            "sign": sign,
            "hot": {
                "dir":           hot_dir,
                "magnitude_pct": hot_mag,
                "provenance":    "rubric",
                "n":             n,
            },
            "cool": {
                "dir":           cool_dir,
                "magnitude_pct": cool_mag,
                "provenance":    "rubric",
                "n":             n,
            },
            "surprise_curve": None,  # M5 will populate this when n >= 30 per cell
        }

    return scenarios


def atomic_write(path: str, payload: dict) -> None:
    """Write payload to path atomically using a sibling tmp file + os.replace."""
    dir_ = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", prefix="event_scenarios_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        # Clean up orphaned tmp file on failure; let the exception propagate.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main() -> None:
    sign_table  = _load_json(_SIGN_TABLE)
    event_stats = _load_json(_EVENT_STATS)

    scenarios = build_scenarios(sign_table, event_stats)

    # Derive window from event_stats metadata.
    stats_events = event_stats.get("events", {})
    windows = [v.get("window", "") for v in stats_events.values() if v.get("window")]
    window_str = windows[0] if windows else None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "ok":      True,
        "updated": today,
        "window":  window_str,
        "min_n":   30,
        "scenarios": scenarios,
    }

    atomic_write(_OUT_FILE, payload)

    print(f"[build_event_scenarios] wrote {len(scenarios)} scenarios to {_OUT_FILE}")
    for ev, sc in scenarios.items():
        hot  = sc["hot"]
        cool = sc["cool"]
        print(
            f"  {ev}: sign={sc['sign']}"
            f"  hot->{hot['dir']} {hot['magnitude_pct']}% (n={hot['n']}, {hot['provenance']})"
            f"  cool->{cool['dir']} {cool['magnitude_pct']}% (n={cool['n']}, {cool['provenance']})"
        )


if __name__ == "__main__":
    main()
