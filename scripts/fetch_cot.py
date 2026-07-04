#!/usr/bin/env python
"""Fetch CFTC Commitments of Traders (COT) data — Legacy Futures-Only report.

Fetches the two most recent weekly COT reports for GOLD - COMMODITY EXCHANGE INC.
from the CFTC public Socrata API (no API key required, anonymous access).

Writes data/cot.json for the /api/cot dashboard endpoint (§3.5, §3.6).

Usage:
    python scripts/fetch_cot.py             # fetch + write data/cot.json
    python scripts/fetch_cot.py --dry-run   # print payload, do not write

Data source:
    CFTC public Socrata API, dataset 6dca-aqww (Legacy Futures-Only report)
    URL: https://publicreporting.cftc.gov/resource/6dca-aqww.json
    Fields used:
        report_date_as_yyyy_mm_dd  — CFTC release date (Friday)
        noncomm_positions_long_all — Non-commercial long contracts
        noncomm_positions_short_all — Non-commercial short contracts
    Filter: market_and_exchange_names = 'GOLD - COMMODITY EXCHANGE INC.'
    Sorted by date DESC, limit 2 (current + prior week for net_chg).

Output schema (data/cot.json — FROZEN §3.6):
    {
      "ok": true,
      "report_date": "YYYY-MM-DD",
      "noncomm_long": <int>,
      "noncomm_short": <int>,
      "net": <int>,               # noncomm_long - noncomm_short
      "net_chg": <int>,           # net(latest) - net(prior)
      "updated": "<iso>"          # UTC timestamp of this fetch
    }

Behavior on error:
    - Network error / timeout: keep old data/cot.json unchanged, exit 0.
    - HTTP 429 (rate limit): same — keep old file, exit 0.
    - Malformed response: keep old file, exit 0.
    If no prior file exists and the fetch fails, no file is written (endpoint
    will return the empty-payload stub — never 500).

Scheduled: weekly, e.g. Friday 18:00 UTC after CFTC releases new data.
No AlphaVantage quota is consumed; no AI calls are made.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Output file path ──────────────────────────────────────────────────────────
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "cot.json"

# ── CFTC Socrata endpoint ─────────────────────────────────────────────────────
_SOCRATA_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# The exact market name in the CFTC Legacy Futures-Only dataset for COMEX gold.
_GOLD_MARKET = "GOLD - COMMODITY EXCHANGE INC."

_TIMEOUT_SEC = 30


# ── Internal exception ────────────────────────────────────────────────────────
class _FetchError(Exception):
    pass


def _build_url() -> str:
    """Build the Socrata SoQL query URL for the two latest gold COT rows."""
    params = {
        "$select": (
            "report_date_as_yyyy_mm_dd,"
            "noncomm_positions_long_all,"
            "noncomm_positions_short_all"
        ),
        "$where": f"market_and_exchange_names='{_GOLD_MARKET}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": "2",
    }
    return _SOCRATA_URL + "?" + urllib.parse.urlencode(params)


def _fetch_rows() -> list:
    """Fetch up to 2 rows from the CFTC Socrata API.

    Returns a list of dicts sorted newest-first.
    Raises _FetchError on network/HTTP/parse failures.
    """
    url = _build_url()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "xauusd-cot-fetcher/1.0 (github.com/JOTARO365)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise _FetchError(f"HTTP 429 rate-limited by Socrata (CFTC)") from exc
        raise _FetchError(f"HTTP {exc.code} from Socrata: {exc.reason}") from exc
    except Exception as exc:
        raise _FetchError(f"Network error fetching COT data: {exc}") from exc

    if status != 200:
        raise _FetchError(f"Unexpected HTTP {status} from Socrata")

    try:
        rows = json.loads(body)
    except json.JSONDecodeError as exc:
        raise _FetchError(f"JSON parse error: {exc}") from exc

    if not isinstance(rows, list):
        raise _FetchError(f"Expected JSON array, got: {type(rows).__name__}")

    return rows


def _parse_date(raw: str) -> str:
    """Normalise Socrata date to YYYY-MM-DD (handles both date-only and ISO-datetime)."""
    return str(raw).strip()[:10]


def _parse_int(value) -> int:
    """Parse Socrata numeric field (may be string or int/float)."""
    return int(float(str(value).replace(",", "")))


def _build_payload(rows: list) -> dict:
    """Build the cot.json payload from the (up to) 2 newest rows.

    Raises _FetchError if the data is missing or malformed.
    """
    if not rows:
        raise _FetchError("No COT rows returned for GOLD from Socrata")

    latest = rows[0]
    try:
        report_date   = _parse_date(latest["report_date_as_yyyy_mm_dd"])
        noncomm_long  = _parse_int(latest["noncomm_positions_long_all"])
        noncomm_short = _parse_int(latest["noncomm_positions_short_all"])
    except (KeyError, ValueError, TypeError) as exc:
        raise _FetchError(f"Malformed latest row: {exc}  row={latest}") from exc

    net = noncomm_long - noncomm_short

    # net_chg requires a prior-week row
    net_chg = None
    if len(rows) >= 2:
        prior = rows[1]
        try:
            prior_long  = _parse_int(prior["noncomm_positions_long_all"])
            prior_short = _parse_int(prior["noncomm_positions_short_all"])
            net_chg = net - (prior_long - prior_short)
        except (KeyError, ValueError, TypeError):
            net_chg = None  # graceful: report without chg

    updated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return {
        "ok":            True,
        "report_date":   report_date,
        "noncomm_long":  noncomm_long,
        "noncomm_short": noncomm_short,
        "net":           net,
        "net_chg":       net_chg,
        "updated":       updated,
    }


def _write_atomic(path: Path, payload: dict) -> None:
    """Atomic write: write to .tmp then os.replace (same-dir, safe on NTFS)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print payload without writing data/cot.json")
    args = parser.parse_args()

    print(f"[fetch_cot] Fetching COT data from CFTC Socrata ({_SOCRATA_URL})")
    print(f"[fetch_cot] Filter: {_GOLD_MARKET!r}")

    try:
        rows = _fetch_rows()
    except _FetchError as exc:
        print(f"[fetch_cot] ERROR: {exc}")
        print("[fetch_cot] Keeping existing data/cot.json unchanged (if any).")
        return 0  # graceful — scheduler should not treat this as a crash

    print(f"[fetch_cot] Received {len(rows)} row(s) from Socrata.")

    try:
        payload = _build_payload(rows)
    except _FetchError as exc:
        print(f"[fetch_cot] ERROR parsing rows: {exc}")
        print("[fetch_cot] Keeping existing data/cot.json unchanged (if any).")
        return 0

    print(
        f"[fetch_cot] Report date: {payload['report_date']}  "
        f"Long={payload['noncomm_long']:,}  "
        f"Short={payload['noncomm_short']:,}  "
        f"Net={payload['net']:+,}  "
        f"Net chg={payload['net_chg']:+,}" if payload["net_chg"] is not None
        else f"[fetch_cot] Report date: {payload['report_date']}  "
             f"Long={payload['noncomm_long']:,}  "
             f"Short={payload['noncomm_short']:,}  "
             f"Net={payload['net']:+,}  "
             f"Net chg=N/A (only 1 row)"
    )

    if args.dry_run:
        print("[fetch_cot] --dry-run: not writing file.")
        print(json.dumps(payload, indent=2))
        return 0

    _write_atomic(OUT_PATH, payload)
    print(f"[fetch_cot] Written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
