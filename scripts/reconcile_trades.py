#!/usr/bin/env python
"""Reconcile orphan OPEN trades for the currently-connected MT5 account.

DB rows stuck at status='OPEN' whose position is actually closed on the broker
get flipped to CLOSED. Scoped strictly to the connected account + SYMBOL — it
can never touch another account's rows (those need manual cleanup).

Usage:
    python scripts/reconcile_trades.py            # DRY-RUN (default, no DB writes)
    python scripts/reconcile_trades.py --commit   # actually apply to Supabase

Needs MT5 connected (uses the login/server from .env, same as main.py).
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
from db.sync import reconcile_open_trades


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--commit", action="store_true",
                    help="apply changes to the DB (default is a dry-run with no writes)")
    args = ap.parse_args()
    dry = not args.commit

    if not connect_mt5():
        sys.exit("ERROR: MT5 connect failed — cannot reconcile.")
    try:
        rc = reconcile_open_trades(dry_run=dry)
    finally:
        disconnect_mt5()

    mode = "DRY-RUN (no writes)" if dry else "COMMITTED"
    print(f"\n=== reconcile_open_trades — {mode} ===")
    print(f"  account_login : {rc.get('login')}")
    print(f"  DB open rows  : {rc.get('db_open')}")
    print(f"  still open    : {rc.get('still_open')}")
    print(f"  -> CLOSED     : {rc.get('reconciled')}  (pnl from MT5 history)")
    print(f"  -> STALE      : {rc.get('stale')}  (beyond history window, pnl=null)")
    for a in rc.get("actions", []):
        print(f"     ticket {a['ticket']:<12}  {a['reason']:<18}  pnl={a['pnl']}")
    if dry and rc.get("actions"):
        print("\n  (dry-run) re-run with --commit to apply these changes.")


if __name__ == "__main__":
    main()
