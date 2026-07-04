"""
build_event_scenarios.py — M2 + M5: build data/event_scenarios.json.

M2 (rubric):  joins data/event_sign_table.json + data/event_stats.json
              → provenance:"rubric", magnitude from two-sided prior,
                surprise_curve:null, n from event_stats.

M5 (calibration overlay, appended below M2):
              reads data/consensus_seed.json + data/realized_moves.json
              + data/xau_daily.json → computes |surprise| → |move| curves,
              flips provenance to "calibrated" ONLY when that cell's n >= 30
              (ARCHITECTURE §8 hard rule).  Below n=30 the rubric magnitude
              is kept unchanged and n is updated to the calibration count so
              the card can show "(rubric · n=7)".

Atomic write (tmp + os.replace) per ARCHITECTURE §D8.
Zero AI calls.  Fail-soft: missing consensus_seed / xau_daily / realized_moves
→ M5 overlay silently skipped, output is pure-M2 rubric.

Run: & $PY scripts\\build_event_scenarios.py
"""

import bisect
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone

# ── paths ─────────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SIGN_TABLE      = os.path.join(_ROOT, "data", "event_sign_table.json")
_EVENT_STATS     = os.path.join(_ROOT, "data", "event_stats.json")
_OUT_FILE        = os.path.join(_ROOT, "data", "event_scenarios.json")
# M5 additional inputs (fail-soft if absent)
_CONSENSUS_SEED  = os.path.join(_ROOT, "data", "consensus_seed.json")
_REALIZED_MOVES  = os.path.join(_ROOT, "data", "realized_moves.json")
_XAU_DAILY       = os.path.join(_ROOT, "data", "xau_daily.json")

# ── M5 constants ───────────────────────────────────────────────────────────────
# ARCHITECTURE §8: minimum calibration sample count for provenance="calibrated".
_MIN_N_CALIBRATED = 30

# Surprise bucket thresholds per event type.
# Format: list of (label, upper_bound_exclusive) where upper_bound is applied
# to |actual - consensus| in native units.
# CPI unit = percentage points (pp);  NFP unit = thousands (k).
_SURPRISE_THRESHOLDS: dict = {
    "CPI": [("small", 0.1), ("medium", 0.3), ("large", float("inf"))],
    "NFP": [("small", 30.0), ("medium", 80.0), ("large", float("inf"))],
}

# FOMC surprise is stance-based; rank diff used for hot/cool classification.
# hawkish=2, neutral=1, dovish=0  (higher rank = tighter/more hawkish).
_FOMC_STANCE_RANK: dict = {"hawkish": 2, "neutral": 1, "dovish": 0}


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


# ═══════════════════════════════════════════════════════════════════════════════
# M5 — surprise-conditioned, realized-move-calibrated magnitudes
# ═══════════════════════════════════════════════════════════════════════════════

def _load_json_safe(path: str) -> dict:
    """Load JSON; return {} on missing file or parse error (fail-soft)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _build_price_index(xau_daily: dict) -> "tuple[list, dict]":
    """
    Build a sorted date list and price dict from xau_daily["data"].
    Returns (sorted_dates: list[str], prices: dict[str, float]).
    """
    raw = xau_daily.get("data", [])
    prices: dict = {}
    for rec in raw:
        if "date" in rec and "price" in rec:
            try:
                prices[rec["date"]] = float(rec["price"])
            except (TypeError, ValueError):
                pass
    sorted_dates = sorted(prices.keys())
    return sorted_dates, prices


def _get_daily_abs_move_pct(
    date_str: str,
    sorted_dates: list,
    prices: dict,
) -> "float | None":
    """
    Return the absolute daily % change on date_str relative to the previous
    trading day.  Used as historical realized-move proxy when realized_moves.json
    has no 60-min record for this event date.
    Returns None when date_str is absent or has no prior trading day.
    """
    if date_str not in prices:
        return None
    idx = bisect.bisect_left(sorted_dates, date_str)
    if idx == 0:
        return None
    prev_date   = sorted_dates[idx - 1]
    price_today = prices[date_str]
    price_prev  = prices[prev_date]
    if price_prev == 0:
        return None
    return abs((price_today - price_prev) / price_prev * 100.0)


def _get_realized_move_from_log(
    event: str,
    date_str: str,
    realized_records: list,
) -> "float | None":
    """
    Search realized_moves.json records for an economic anchor matching
    (event, date).  Returns the 60-min |move_pct| if complete, else None.
    anchor_ts_utc starts with the ISO date string (e.g. "2026-07-14T12:30:00Z").
    """
    for rec in realized_records:
        if rec.get("kind") != "economic":
            continue
        if rec.get("subtype") != event:
            continue
        anchor_ts = rec.get("anchor_ts_utc", "")
        if not anchor_ts.startswith(date_str):
            continue
        moves = rec.get("moves") or {}
        m60   = moves.get("60") or {}
        pct   = m60.get("move_pct")
        if pct is not None:
            return abs(float(pct))
    return None


def _surprise_bucket(event: str, surprise_val: float) -> str:
    """
    Return the bucket label for a given surprise value.
    FOMC: surprise_val = signed stance rank difference (positive = hawkish).
    CPI/NFP: surprise_val = (actual - consensus) in native units.
    """
    if event == "FOMC":
        if surprise_val > 0:
            return "hawkish_surprise"
        elif surprise_val < 0:
            return "dovish_surprise"
        return "inline"
    thresholds = _SURPRISE_THRESHOLDS.get(event, _SURPRISE_THRESHOLDS["CPI"])
    abs_s = abs(surprise_val)
    for label, upper in thresholds:
        if abs_s < upper:
            return label
    return "large"  # fallback (should not reach if last threshold is inf)


def compute_m5_stats(
    consensus_seed: dict,
    realized_moves: dict,
    xau_daily: dict,
) -> dict:
    """
    Join consensus_seed records with realized/historical price moves.
    Returns per-event calibration data:
    {
      "CPI": {
        "hot":  {"avg_abs_move_pct": float|None, "n": int},
        "cool": {"avg_abs_move_pct": float|None, "n": int},
        "surprise_curve": [{surprise_bucket, avg_abs_move_pct, n}] | None
      },
      ...
    }
    Events absent from consensus_seed are not in the return dict.
    """
    sorted_dates, prices  = _build_price_index(xau_daily)
    realized_records: list = realized_moves.get("records", [])

    # Accumulate observations per event
    by_event: dict = defaultdict(list)

    for rec in consensus_seed.get("records", []):
        event = rec.get("event")
        if event not in ("CPI", "NFP", "FOMC"):
            continue

        date_str = rec.get("date", "")

        # Compute surprise and classify hot/cool
        if event == "FOMC":
            stance     = rec.get("stance", "neutral")
            con_stance = rec.get("consensus_stance", "neutral")
            surprise   = float(
                _FOMC_STANCE_RANK.get(stance, 1) - _FOMC_STANCE_RANK.get(con_stance, 1)
            )
            is_hot  = surprise > 0   # hawkish surprise = hawkish > consensus
            is_cool = surprise < 0   # dovish surprise
        else:
            consensus_val = rec.get("consensus")
            actual_val    = rec.get("actual")
            if consensus_val is None or actual_val is None:
                continue
            try:
                surprise = float(actual_val) - float(consensus_val)
            except (TypeError, ValueError):
                continue
            is_hot  = surprise > 0
            is_cool = surprise < 0

        # Realized move: prefer realized_moves.json 60-min record, else daily proxy
        abs_move = _get_realized_move_from_log(event, date_str, realized_records)
        if abs_move is None and date_str:
            abs_move = _get_daily_abs_move_pct(date_str, sorted_dates, prices)

        by_event[event].append({
            "surprise":     surprise,
            "is_hot":       is_hot,
            "is_cool":      is_cool,
            "abs_move_pct": abs_move,
        })

    # Summarise per event
    result: dict = {}
    for event, observations in by_event.items():
        has_move = [o for o in observations if o["abs_move_pct"] is not None]
        hot_moves  = [o["abs_move_pct"] for o in has_move if o["is_hot"]]
        cool_moves = [o["abs_move_pct"] for o in has_move if o["is_cool"]]

        def _avg(xs: list) -> "float | None":
            return round(sum(xs) / len(xs), 4) if xs else None

        # Surprise curve — all observations that have a realized move
        bucket_groups: dict = defaultdict(list)
        for o in has_move:
            b = _surprise_bucket(event, o["surprise"])
            bucket_groups[b].append(o["abs_move_pct"])

        if bucket_groups:
            curve = [
                {
                    "surprise_bucket":  bucket,
                    "avg_abs_move_pct": round(sum(mvs) / len(mvs), 4),
                    "n":                len(mvs),
                }
                for bucket, mvs in sorted(bucket_groups.items())
            ]
        else:
            curve = None

        result[event] = {
            "hot":  {"avg_abs_move_pct": _avg(hot_moves),  "n": len(hot_moves)},
            "cool": {"avg_abs_move_pct": _avg(cool_moves), "n": len(cool_moves)},
            "surprise_curve": curve,
        }

    return result


def apply_m5(scenarios: dict, m5_stats: dict) -> dict:
    """
    Overlay M5 calibration data onto the M2 scenarios dict (mutates in place).

    Rules (ARCHITECTURE §8 — HARD):
    - surprise_curve is always written when M5 data exists (shows progress even if n<30).
    - provenance flips to "calibrated" ONLY when that side's calibration n >= _MIN_N_CALIBRATED.
      - calibrated: replace magnitude_pct with the calibrated average; update n.
    - When n < _MIN_N_CALIBRATED and n > 0:
      - Keep existing rubric magnitude_pct unchanged.
      - Keep provenance "rubric".
      - Update n to the calibration count (enables card to display "(rubric · n=7)").
    - When calibration n == 0 for a side: leave that side entirely unchanged (rubric prior n kept).
    - Events with no M5 data: left fully unchanged (surprise_curve stays null).
    """
    for event, sc in scenarios.items():
        stats = m5_stats.get(event)
        if stats is None:
            # No M5 seed data for this event — leave completely unchanged.
            continue

        # Always update surprise_curve when we have any M5 data for this event.
        sc["surprise_curve"] = stats["surprise_curve"]

        for side in ("hot", "cool"):
            side_stats = stats[side]
            calib_n    = side_stats["n"]
            calib_avg  = side_stats["avg_abs_move_pct"]

            if calib_n >= _MIN_N_CALIBRATED and calib_avg is not None:
                # ✅ Enough data: flip to calibrated.
                sc[side]["magnitude_pct"] = calib_avg
                sc[side]["provenance"]    = "calibrated"
                sc[side]["n"]             = calib_n

            elif calib_n > 0:
                # Data exists but below threshold.
                # Keep rubric magnitude; update n to show calibration progress.
                sc[side]["provenance"] = "rubric"
                sc[side]["n"]         = calib_n
                # magnitude_pct intentionally unchanged (rubric value preserved).

            # else calib_n == 0: no M5 data for this side → leave cell unchanged.

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
    # ── M2: rubric scenarios from sign table + event stats ────────────────────
    sign_table  = _load_json(_SIGN_TABLE)
    event_stats = _load_json(_EVENT_STATS)

    scenarios = build_scenarios(sign_table, event_stats)

    # Derive window from event_stats metadata.
    stats_events = event_stats.get("events", {})
    windows = [v.get("window", "") for v in stats_events.values() if v.get("window")]
    window_str = windows[0] if windows else None

    # ── M5: surprise-magnitude calibration overlay (fail-soft) ───────────────
    m5_applied = False
    try:
        consensus_seed = _load_json_safe(_CONSENSUS_SEED)
        realized_moves = _load_json_safe(_REALIZED_MOVES)
        xau_daily      = _load_json_safe(_XAU_DAILY)

        seed_records = consensus_seed.get("records", [])
        # Filter out metadata-only rows (rows with a "_note" key and no "event" key
        # are likely schema comment rows, but we also accept proper rows with _note).
        real_records = [r for r in seed_records if r.get("event") in ("CPI", "NFP", "FOMC")]

        if real_records and xau_daily.get("data"):
            m5_stats = compute_m5_stats(consensus_seed, realized_moves, xau_daily)
            apply_m5(scenarios, m5_stats)
            m5_applied = True
            print(f"[build_event_scenarios] M5 overlay applied ({len(real_records)} seed rows)")
        else:
            print("[build_event_scenarios] M5 skipped: no usable consensus_seed records or xau_daily data")

    except Exception as exc:  # noqa: BLE001
        # Fail-soft: M5 errors never break the rubric output.
        print(f"[build_event_scenarios] M5 overlay error (skipped): {exc}", file=sys.stderr)

    # ── Write output ──────────────────────────────────────────────────────────
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    payload = {
        "ok":      True,
        "updated": today,
        "window":  window_str,
        "min_n":   _MIN_N_CALIBRATED,
        "scenarios": scenarios,
    }

    atomic_write(_OUT_FILE, payload)

    print(f"[build_event_scenarios] wrote {len(scenarios)} scenarios to {_OUT_FILE}")
    for ev, sc in scenarios.items():
        hot  = sc["hot"]
        cool = sc["cool"]
        curve_n = (
            sum(b["n"] for b in sc["surprise_curve"]) if sc.get("surprise_curve") else 0
        )
        print(
            f"  {ev}: sign={sc['sign']}"
            f"  hot->{hot['dir']} {hot['magnitude_pct']}% (n={hot['n']}, {hot['provenance']})"
            f"  cool->{cool['dir']} {cool['magnitude_pct']}% (n={cool['n']}, {cool['provenance']})"
            + (f"  curve_total_n={curve_n}" if curve_n else "  surprise_curve=null")
        )


if __name__ == "__main__":
    main()
