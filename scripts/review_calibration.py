#!/usr/bin/env python3
"""
review_calibration.py — M6 Calibration Review (ARCHITECTURE §3.5, §4.3)

Reads  data/realized_moves.json  (actual gold moves after anchors, written by
       scripts/realized_move_logger.py).
Reads  data/news_impact.json     (what was predicted for post anchors).
Computes per-magnitude-tier bucket:
  - n          : records with that predicted tier AND a completed 60-min horizon
  - hit_rate_pct : fraction where abs(realized_60min_move) fell in the tier's
                   assumed band  (only filled when n >= MIN_N = 30)
  - mean_realized_abs_move_pct : mean |realized move| for the bucket
Writes data/impact_calibration.json  (ARCHITECTURE §4.3 exact shape, atomic).

Gate (ARCHITECTURE §8, §D6):
  - n < MIN_N  → hit_rate_pct = null  (label: "collecting data (n<30)")
  - n >= MIN_N → hit_rate_pct filled  (label: "calibrated")
  - status "calibrated" only when EVERY tier n >= MIN_N.

Honesty rule: with near-empty realized_moves (records=[]) every bucket is
n=0, so EVERYTHING correctly shows "collecting data (n<30)". That is the
expected, correct state while data accumulates.

No AI calls. Zero side-effects on the bot pipeline (read-only inputs + writes
only impact_calibration.json). Safe to run manually or on a schedule.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REALIZED_MOVES_PATH = os.path.join(BASE_DIR, "data", "realized_moves.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "data", "impact_calibration.json")

MIN_N = 30  # ARCHITECTURE §8: min-n gate for "calibrated" verdict

# Tier assumed bands — magnitude % of XAUUSD price (ARCHITECTURE §4.3)
# tier → (lo_inclusive, hi_exclusive)
TIER_BANDS: dict = {
    "1": (0.0, 0.4),   # minor
    "2": (0.4, 0.9),   # moderate
    "3": (0.9, 9.9),   # major
}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: dict) -> None:
    """Write JSON atomically via tmp + os.replace (ARCHITECTURE §D8)."""
    dir_ = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, encoding="utf-8", suffix=".tmp"
    ) as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        tmp_path = fh.name
    os.replace(tmp_path, path)
    log.info("Wrote %s (atomic)", path)


def load_realized_moves() -> list:
    """Load records list from data/realized_moves.json.
    Returns [] on missing file or any error (fail-soft)."""
    try:
        with open(REALIZED_MOVES_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        records = raw.get("records") or []
        log.info("Loaded %d realized-move records from %s", len(records), REALIZED_MOVES_PATH)
        return records
    except FileNotFoundError:
        log.info("realized_moves.json not found — treating as empty (n=0 collecting state)")
        return []
    except Exception as exc:
        log.warning("Failed to load realized_moves.json: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_tier_buckets(records: list) -> dict:
    """
    Group records by pred.magnitude_tier; for each tier compute:
      n, hits (|move_pct@60min| in band), abs_moves list.

    A record is counted in tier T only if:
      - pred.magnitude_tier == T  (int or str)
      - moves["60"]["move_pct"]   is present (60-min horizon matured)

    Returns:
      { "1": {"n":int, "hits":int, "abs_moves":[float,...]}, ... }
    """
    buckets: dict = {t: {"n": 0, "hits": 0, "abs_moves": []} for t in TIER_BANDS}

    skipped_no_tier = 0
    skipped_no_move = 0

    for rec in records:
        pred = rec.get("pred") or {}
        tier_raw = pred.get("magnitude_tier")
        if tier_raw is None:
            skipped_no_tier += 1
            continue
        tier = str(int(tier_raw))       # normalise 1/2/3 → "1"/"2"/"3"
        if tier not in TIER_BANDS:
            skipped_no_tier += 1
            continue

        moves = rec.get("moves") or {}
        h60 = moves.get("60") or {}
        move_pct = h60.get("move_pct")
        if move_pct is None:
            skipped_no_move += 1
            continue  # 60-min horizon not yet logged; retry next run

        abs_move = abs(move_pct)
        lo, hi = TIER_BANDS[tier]
        hit = 1 if lo <= abs_move < hi else 0

        buckets[tier]["n"] += 1
        buckets[tier]["hits"] += hit
        buckets[tier]["abs_moves"].append(abs_move)

    if skipped_no_tier:
        log.info("  Skipped %d records: no predicted magnitude_tier", skipped_no_tier)
    if skipped_no_move:
        log.info("  Skipped %d records: 60-min horizon not yet filled", skipped_no_move)

    return buckets


def build_output(buckets: dict) -> dict:
    """
    Convert raw buckets → §4.3 impact_calibration.json shape.

    hit_rate_pct is filled ONLY when n >= MIN_N (honesty gate).
    status = "calibrated" iff every tier n >= MIN_N.
    """
    tiers_out: dict = {}
    for tier, (lo, hi) in TIER_BANDS.items():
        bkt = buckets[tier]
        n = bkt["n"]
        hits = bkt["hits"]
        abs_moves = bkt["abs_moves"]

        hit_rate_pct: float | None = None
        mean_realized: float | None = None
        if n >= MIN_N:
            hit_rate_pct = round(hits / n * 100, 1)
        if abs_moves:
            mean_realized = round(sum(abs_moves) / len(abs_moves), 4)

        tiers_out[tier] = {
            "assumed_band_pct": [lo, hi],
            "hit_rate_pct": hit_rate_pct,       # null until n >= MIN_N
            "n": n,
            "mean_realized_abs_move_pct": mean_realized,  # informational
        }

    all_calibrated = all(buckets[t]["n"] >= MIN_N for t in TIER_BANDS)
    status = "calibrated" if all_calibrated else "collecting"

    return {
        "ok": True,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "min_n": MIN_N,
        "tiers": tiers_out,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Logging summary
# ---------------------------------------------------------------------------

def log_summary(output: dict) -> None:
    log.info("== Calibration summary ==")
    log.info("  status: %s", output["status"])
    for tier, info in output["tiers"].items():
        lo, hi = info["assumed_band_pct"]
        n = info["n"]
        hr = info["hit_rate_pct"]
        verdict = f"hit_rate={hr}%" if hr is not None else "collecting data (n<30)"
        log.info(
            "  Tier %s  band=[%.1f%%,%.1f%%)  n=%-3d  %s",
            tier, lo, hi, n, verdict,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> dict:
    records = load_realized_moves()
    buckets = compute_tier_buckets(records)
    output = build_output(buckets)
    log_summary(output)
    _atomic_write(OUTPUT_PATH, output)
    return output


if __name__ == "__main__":
    main()
