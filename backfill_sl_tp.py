"""
One-time backfill: populate sl/tp for closed trades in trades.json
from MT5 history_orders_get.

Run once with: python backfill_sl_tp.py
MT5 must be running and logged in before executing.
"""
import json
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5
from datetime import datetime, timedelta
from connectors.price_feed import connect_mt5
from config import SYMBOL

LOG_FILE = "logs/trades.json"


def build_sl_tp_map(days: int = 90) -> dict[str, dict]:
    """Build {str(order_ticket): {sl, tp}} from MT5 history."""
    date_from = datetime.now() - timedelta(days=days)
    date_to   = datetime.now()

    deals = mt5.history_deals_get(date_from, date_to)
    if deals is None:
        print("ERROR: history_deals_get returned None")
        return {}

    orders = mt5.history_orders_get(date_from, date_to)
    order_map: dict[int, object] = {}
    if orders:
        for o in orders:
            if o.symbol == SYMBOL:
                order_map[o.ticket] = o

    result: dict[str, dict] = {}
    for d in deals:
        if d.symbol != SYMBOL:
            continue
        if d.entry != 0:   # DEAL_ENTRY_IN only
            continue
        o  = order_map.get(d.order)
        sl = o.sl if o and o.sl != 0.0 else None
        tp = o.tp if o and o.tp != 0.0 else None
        result[str(d.order)] = {"sl": sl, "tp": tp}

    return result


def main():
    print("Connecting to MT5...")
    if not connect_mt5():
        print("ERROR: Could not connect to MT5. Make sure MT5 is running.")
        sys.exit(1)

    print("Loading trades.json...")
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    trades = data["trades"]
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    needs_fill = [t for t in closed if t.get("sl") is None or t.get("tp") is None]
    print(f"Closed trades: {len(closed)}  |  Need SL/TP fill: {len(needs_fill)}")

    if not needs_fill:
        print("Nothing to backfill.")
        return

    print("Fetching MT5 order history (90 days)...")
    sl_tp_map = build_sl_tp_map(days=90)
    print(f"Found {len(sl_tp_map)} orders in MT5 history")

    updated = 0
    not_found = 0
    for t in trades:
        if t.get("status") != "CLOSED":
            continue
        if t.get("sl") is not None and t.get("tp") is not None:
            continue   # already filled

        tk = str(t.get("ticket", ""))
        info = sl_tp_map.get(tk)
        if info is None:
            not_found += 1
            continue

        t["sl"] = info["sl"]
        t["tp"] = info["tp"]
        updated += 1
        sl_str = f"{info['sl']:.2f}" if info["sl"] else "None"
        tp_str = f"{info['tp']:.2f}" if info["tp"] else "None"
        print(f"  ticket={tk} {t['direction']:4s} SL={sl_str} TP={tp_str}")

    print(f"\nBackfill complete: {updated} updated, {not_found} not found in MT5 history")

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("trades.json saved.")


if __name__ == "__main__":
    main()
