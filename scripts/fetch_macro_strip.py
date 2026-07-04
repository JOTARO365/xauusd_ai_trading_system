#!/usr/bin/env python
"""Fetch macro strip data: DXY proxy (UUP ETF), 10Y Treasury Yield, and real yield.
Writes data/macro_strip.json for the /api/macro-strip dashboard endpoint.

Usage:
    python scripts/fetch_macro_strip.py           # fetch + write
    python scripts/fetch_macro_strip.py --dry-run  # print, do not write

Data sources (3 AlphaVantage REST requests — inside the free 25 req/day quota):
  1. UUP ETF via TIME_SERIES_DAILY  — DXY proxy (Invesco DB US Dollar Index
     Bullish Fund; tracks DXY with high correlation; available on free tier).
     chg = day-over-day close change.
  2. TREASURY_YIELD maturity=10year — 10-year nominal yield (monthly series).
     chg = latest month minus previous month.
  3. CPI monthly                    — for real yield estimate:
       real_yield ≈ 10Y − CPI_YoY
     NOTE: TIPS breakeven / inflation-swap data is NOT available on the
     AlphaVantage free tier, so we approximate real yield as the Fisher
     decomposition: nominal_10Y − rolling_CPI_YoY.  This overstates
     real yields when CPI leads bond repricing.

Intended: run once per day via Task Scheduler / cron.  Stays inside the
shared 25-req/day AlphaVantage quota (this script uses exactly 3 requests).

ALPHAVANTAGE_API_KEY must be set in .env or environment.

On quota exhaustion / network error: the old data/macro_strip.json is kept
unchanged and the script exits 0 (graceful — scheduler should not treat this
as a crash).
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

API      = "https://www.alphavantage.co/query"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "macro_strip.json"


# ── Internal exception for quota / data-shape issues ─────────────────────────
class _QuotaError(Exception):
    pass


def _get(params: dict) -> dict:
    """One Alpha Vantage REST call with a 1.5 s courtesy delay and one
    rate-limit retry.  Raises _QuotaError instead of sys.exit() so the
    caller can keep the existing output file intact."""
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        raise _QuotaError("ALPHAVANTAGE_API_KEY not set — put it in .env")
    qs = "&".join(f"{k}={v}" for k, v in {**params, "apikey": key}.items())
    for attempt in range(2):
        try:
            with urllib.request.urlopen(f"{API}?{qs}", timeout=25) as r:
                data = json.loads(r.read().decode())
        except Exception as exc:
            raise _QuotaError(f"Network error fetching {params.get('function')}: {exc}") from exc
        # Economic series → "data" key; daily time series → "Time Series (Daily)"
        if "data" in data or "Time Series (Daily)" in data:
            return data
        msg = data.get("Information") or data.get("Note") or str(data)[:120]
        if attempt == 0:
            print(f"  rate-limited, retrying in 3 s... ({msg[:60]})")
            time.sleep(3)
        else:
            raise _QuotaError(f"AlphaVantage quota/rate-limit for {params.get('function')}: {msg}")
    return {}


def _econ_series(fn: str, maturity: str = "") -> list[tuple[str, float]]:
    """Return [(date, value)] newest-first for monthly economic indicators.
    Drops non-numeric ('.') points (same pattern as update_regime.py)."""
    params: dict = {"function": fn, "interval": "monthly"}
    if maturity:
        params["maturity"] = maturity
    out = []
    for row in _get(params).get("data", []):
        try:
            out.append((row["date"], float(row["value"])))
        except (KeyError, ValueError):
            continue
    time.sleep(1.5)   # courtesy delay — stay under free-tier burst limit
    return out


def _uup_series() -> list[tuple[str, float]]:
    """Return [(date, close)] newest-first for UUP ETF daily closes."""
    data = _get({"function": "TIME_SERIES_DAILY", "symbol": "UUP", "outputsize": "compact"})
    ts   = data.get("Time Series (Daily)", {})
    rows = sorted(ts.items(), reverse=True)   # newest first
    result = []
    for d, v in rows:
        try:
            result.append((d, float(v["4. close"])))
        except (KeyError, ValueError):
            continue
    time.sleep(1.5)
    return result


def _cpi_yoy_at(cpi_series: list[tuple[str, float]], idx: int) -> float:
    """CPI year-over-year at position idx (newest = 0).
    Matches the same calendar month one year prior; fallback to nearest 365 days
    (same gap-tolerant logic as _yoy_base in update_regime.py)."""
    from datetime import datetime as _dt
    latest = _dt.strptime(cpi_series[idx][0], "%Y-%m-%d")
    for d, v in cpi_series[idx + 1:]:
        dt = _dt.strptime(d, "%Y-%m-%d")
        if dt.year == latest.year - 1 and dt.month == latest.month:
            return (cpi_series[idx][1] - v) / v * 100 if v else 0.0
    # fallback: nearest point to 365 days prior
    candidates = cpi_series[idx + 1:]
    if not candidates:
        return 0.0
    near = min(candidates, key=lambda dv: abs(
        (_dt.strptime(dv[0], "%Y-%m-%d") - latest).days + 365))
    return (cpi_series[idx][1] - near[1]) / near[1] * 100 if near[1] else 0.0


def build_payload() -> dict:
    """Fetch all 3 series and compute the macro strip values."""
    print("Fetching UUP (DXY proxy) from Alpha Vantage...", flush=True)
    uup = _uup_series()
    if len(uup) < 2:
        raise _QuotaError("Insufficient UUP daily data (need >= 2 rows)")

    print("Fetching 10Y Treasury Yield from Alpha Vantage...", flush=True)
    ten = _econ_series("TREASURY_YIELD", maturity="10year")
    if len(ten) < 2:
        raise _QuotaError("Insufficient TREASURY_YIELD data (need >= 2 rows)")

    print("Fetching CPI from Alpha Vantage...", flush=True)
    cpi = _econ_series("CPI")
    if len(cpi) < 14:
        raise _QuotaError("Insufficient CPI data (need >= 14 rows for YoY)")

    # ── DXY proxy (UUP) — day-over-day close change ───────────────────
    dxy_val = round(uup[0][1], 4)
    dxy_chg = round(uup[0][1] - uup[1][1], 4)

    # ── 10Y nominal yield — month-over-month change ────────────────────
    y10_val = round(ten[0][1], 4)
    y10_chg = round(ten[0][1] - ten[1][1], 4)

    # ── Real yield ≈ 10Y − CPI YoY (approximation — see module docstring)
    cpi_yoy_now  = _cpi_yoy_at(cpi, 0)
    cpi_yoy_prev = _cpi_yoy_at(cpi, 1)
    real_now     = round(y10_val          - cpi_yoy_now,  4)
    real_prev    = round(ten[1][1]        - cpi_yoy_prev, 4)
    real_chg     = round(real_now - real_prev, 4)

    return {
        "ok":         True,
        "dxy":        {"val": dxy_val, "chg": dxy_chg},
        "y10":        {"val": y10_val, "chg": y10_chg},
        "real_yield": {"val": real_now, "chg": real_chg},
        "updated":    datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()

    try:
        payload = build_payload()
    except _QuotaError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)
        print("Keeping existing data/macro_strip.json unchanged.", file=sys.stderr)
        sys.exit(0)   # graceful — not a crash
    except Exception as exc:
        print(f"ERROR: unexpected failure: {exc}", file=sys.stderr)
        print("Keeping existing data/macro_strip.json unchanged.", file=sys.stderr)
        sys.exit(0)

    print("\n--- macro_strip payload ---")
    print(json.dumps(payload, indent=2))

    if args.dry_run:
        print("\n[dry-run] data/macro_strip.json NOT written.")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(OUT_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, str(OUT_PATH))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
