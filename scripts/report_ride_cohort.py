"""
RIDE Cohort Report — XAUUSD AI Trading System
==============================================================
Segments MOMENTUM_RIDE trades from MT5 deal history, computes
cohort stats, and writes data/ride_cohort.json in the exact
/api/ride-cohort payload shape (ARCHITECTURE §3.4, §3.6).

Segmentation rule — identical to dashboard/app.py /api/ride-stats:
    str(deal.comment or "").startswith("RIDE")

Why MT5 deal history (not DB alone):
    The trades table has no 'comment' column — the RIDE prefix is
    only stored in the MT5 order comment field and was designed
    specifically to survive MT5's 31-char truncation so the tag
    stays at the front (decision_maker.py line ~908-910).
    DB reader.py get_trades() is still called to cross-check open
    positions when available.

Read-only.  Does NOT touch RIDE/gate logic or knob settings.
Does NOT make or suggest knob decisions — numbers only.

Usage:
    python scripts/report_ride_cohort.py

n=0 is a valid, expected result when the experiment just shipped
or the bot was not running.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

OUT_FILE = ROOT / "data" / "ride_cohort.json"
LOOKBACK_DAYS = 90   # mirrors /api/ride-stats lookback

# ── MT5 availability check ────────────────────────────────────────────────────
_MT5_AVAILABLE = False
try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    pass


def _empty_payload(note: str = "") -> dict:
    """Valid n=0 payload matching §3.4 shape exactly."""
    p: dict = {
        "ok":     True,
        "n":      0,
        "win":    0,
        "loss":   0,
        "wr":     None,
        "pnl":    0.0,
        "open":   0,
        "trades": [],
    }
    if note:
        p["note"] = note
    return p


def _compute_from_mt5() -> dict:
    """
    Query MT5 deal history to identify RIDE positions by comment prefix,
    then compute cohort stats.

    Segmentation: str(entry_deal.comment or "").startswith("RIDE")
    Consistent with dashboard/app.py api_ride_stats().
    """
    from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL  # type: ignore

    already_init = mt5.terminal_info() is not None
    if not already_init:
        ok = mt5.initialize(
            login=MT5_LOGIN, password=MT5_PASSWORD,
            server=MT5_SERVER, timeout=15000,
        )
        if not ok:
            err = mt5.last_error()
            print(f"[WARN] MT5 init failed: {err}", file=sys.stderr)
            return _empty_payload(f"MT5 init failed: {err}")

    try:
        since = datetime.now() - timedelta(days=LOOKBACK_DAYS)
        deals = mt5.history_deals_get(since, datetime.now()) or []

        # Group all deals by position_id — reconstruct per-position data
        pos: dict = defaultdict(lambda: {"in": None, "pnl": 0.0, "closed": False})
        for d in deals:
            if d.symbol != SYMBOL:
                continue
            p = pos[d.position_id]
            p["pnl"] += d.profit + d.swap + d.commission
            if d.entry == 0 and p["in"] is None:   # entry deal (DEAL_ENTRY_IN)
                p["in"] = d
            elif d.entry in (1, 2):                  # exit deal (OUT / OUT_BY)
                p["closed"] = True

        # Filter: keep only RIDE-tagged trades (comment starts with "RIDE")
        # Same rule as dashboard/app.py:1077
        rides = []
        for _pid, p in pos.items():
            e = p["in"]
            if e is None or not str(e.comment or "").startswith("RIDE"):
                continue
            rides.append({
                "time":   datetime.fromtimestamp(e.time).isoformat()[:16],
                "dir":    "BUY" if e.type == 0 else "SELL",
                "pnl":    round(p["pnl"], 2),
                "closed": p["closed"],
            })

        closed = [r for r in rides if r["closed"]]
        wins   = [r for r in closed if r["pnl"] > 0]
        losses = [r for r in closed if r["pnl"] <= 0]
        n_open = sum(1 for r in rides if not r["closed"])
        n      = len(closed)
        pnl    = float(round(sum(r["pnl"] for r in closed), 2))
        wr     = round(len(wins) / n * 100, 1) if n > 0 else None

        return {
            "ok":     True,
            "n":      n,
            "win":    len(wins),
            "loss":   len(losses),
            "wr":     wr,
            "pnl":    pnl,
            "open":   n_open,
            "trades": sorted(rides, key=lambda r: r["time"], reverse=True),
        }

    finally:
        if not already_init:
            mt5.shutdown()


def _validate_shape(payload: dict) -> bool:
    """Verify required §3.4 keys are present and types are correct."""
    required = {
        "ok":     bool,
        "n":      int,
        "win":    int,
        "loss":   int,
        "pnl":    float,
        "open":   int,
        "trades": list,
    }
    for key, typ in required.items():
        if key not in payload:
            print(f"[ERROR] Missing key in payload: {key}", file=sys.stderr)
            return False
        if not isinstance(payload[key], typ):
            print(
                f"[ERROR] Key '{key}' has wrong type: "
                f"got {type(payload[key]).__name__}, expected {typ.__name__}",
                file=sys.stderr,
            )
            return False
    # wr may be None (no closed trades) or float
    if "wr" in payload and payload["wr"] is not None:
        if not isinstance(payload["wr"], (int, float)):
            print("[ERROR] 'wr' must be float or None", file=sys.stderr)
            return False
    return True


def main() -> None:
    if not _MT5_AVAILABLE:
        payload = _empty_payload("MetaTrader5 module not installed")
        print("[WARN] MT5 not available — writing n=0 result", file=sys.stderr)
    else:
        payload = _compute_from_mt5()

    # Shape validation
    if not _validate_shape(payload):
        sys.exit(1)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    wr_str = f"{payload['wr']}%" if payload["wr"] is not None else "—"
    print(f"RIDE Cohort Report  ({LOOKBACK_DAYS}d lookback)")
    print(f"  closed:    {payload['n']}")
    print(f"  win:       {payload['win']}")
    print(f"  loss:      {payload['loss']}")
    print(f"  win rate:  {wr_str}")
    print(f"  pnl (THB): {payload['pnl']}")
    print(f"  open:      {payload['open']}")
    print(f"  trades:    {len(payload['trades'])}")
    print(f"Wrote  →  {OUT_FILE}")


if __name__ == "__main__":
    main()
