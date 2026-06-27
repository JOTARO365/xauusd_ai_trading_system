#!/usr/bin/env python
"""Backfill decision metadata (trend/conf/entry_type/...) onto DB trade rows that
were created by the MT5-history sync and therefore have no context.

Source of truth is logs/<symbol>_trades.json (log_trade writes JSON before DB, so
the metadata survives even when the open-time DB write failed). Scoped strictly to
the connected MT5 account + SYMBOL; only rows with trend=NULL are touched.

Usage:
    python scripts/backfill_metadata.py            # DRY-RUN (default, no writes)
    python scripts/backfill_metadata.py --commit   # actually apply to Supabase

Needs MT5 connected (uses login/server from .env, same as main.py).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv()

from connectors.price_feed import connect_mt5, disconnect_mt5
from db.sync import backfill_metadata_from_logs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--commit", action="store_true",
                    help="apply changes to the DB (default is a dry-run with no writes)")
    args = ap.parse_args()
    dry = not args.commit

    if not connect_mt5():
        sys.exit("ERROR: MT5 connect failed — cannot backfill.")
    try:
        r = backfill_metadata_from_logs(dry_run=dry)
    finally:
        disconnect_mt5()

    mode = "DRY-RUN (no writes)" if dry else "COMMITTED"
    print(f"\n=== backfill_metadata — {mode} ===")
    print(f"  account_login     : {r.get('login')}")
    print(f"  DB rows missing   : {r.get('db_missing')}  (trend=NULL)")
    print(f"  -> backfilled     : {r.get('backfilled')}  (matched in trades.json)")
    print(f"  -> no log entry   : {r.get('no_log')}  (ticket not in trades.json)")
    if r.get("failed"):
        print(f"  -> FAILED         : {r.get('failed')}  (DB write error — see log)")
    if dry and r.get("backfilled"):
        print("\n  (dry-run) re-run with --commit to apply.")


if __name__ == "__main__":
    main()
