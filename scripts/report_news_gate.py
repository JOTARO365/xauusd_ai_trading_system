"""
report_news_gate.py — NEWS_GATE cohort: trades that passed ONLY because the
News Impact score relaxed the confidence floor (comment tagged "NG ").
Mirrors report_ride_cohort.py exactly — MT5 deal history, segment by tag,
compute n / win / loss / wr / pnl / open. Read-only. Zero AI calls.

Purpose: validate whether NEWS_GATE's relax path (③) actually helped or hurt,
with numbers — not feelings. Run weekly / after the flag has been on a while.

Run: & $PY scripts\report_news_gate.py
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import MetaTrader5 as mt5

LOOKBACK_DAYS = 90
_OUT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "news_gate.json"))


def _empty_payload(note: str = "") -> dict:
    p = {"ok": True, "n": 0, "win": 0, "loss": 0, "wr": None, "pnl": 0.0, "open": 0, "trades": []}
    if note:
        p["note"] = note
    return p


def _is_ng(comment: str) -> bool:
    """NG tag survives an optional leading 'RIDE ' prefix (a trade can be both)."""
    c = str(comment or "")
    if c.startswith("RIDE "):
        c = c[5:]
    return c.startswith("NG ")


def _compute_from_mt5() -> dict:
    from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL  # type: ignore

    already = mt5.terminal_info() is not None
    if not already:
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER, timeout=15000):
            err = mt5.last_error()
            print(f"[WARN] MT5 init failed: {err}", file=sys.stderr)
            return _empty_payload(f"MT5 init failed: {err}")
    try:
        since = datetime.now() - timedelta(days=LOOKBACK_DAYS)
        deals = mt5.history_deals_get(since, datetime.now()) or []

        pos = defaultdict(lambda: {"in": None, "pnl": 0.0, "closed": False})
        for d in deals:
            if d.symbol != SYMBOL:
                continue
            p = pos[d.position_id]
            p["pnl"] += d.profit + d.swap + d.commission
            if d.entry == 0 and p["in"] is None:
                p["in"] = d
            elif d.entry in (1, 2):
                p["closed"] = True

        rows = []
        for _pid, p in pos.items():
            e = p["in"]
            if e is None or not _is_ng(e.comment):
                continue
            rows.append({
                "time":   datetime.fromtimestamp(e.time).isoformat()[:16],
                "dir":    "BUY" if e.type == 0 else "SELL",
                "pnl":    round(p["pnl"], 2),
                "closed": p["closed"],
            })

        closed = [r for r in rows if r["closed"]]
        wins   = [r for r in closed if r["pnl"] > 0]
        n      = len(closed)
        return {
            "ok":     True,
            "n":      n,
            "win":    len(wins),
            "loss":   n - len(wins),
            "wr":     round(len(wins) / n * 100, 1) if n else None,
            "pnl":    float(round(sum(r["pnl"] for r in closed), 2)),
            "open":   sum(1 for r in rows if not r["closed"]),
            "trades": sorted(rows, key=lambda r: r["time"], reverse=True),
        }
    finally:
        if not already:
            mt5.shutdown()


def main() -> None:
    try:
        payload = _compute_from_mt5()
    except Exception as e:   # noqa: BLE001
        payload = _empty_payload(f"error: {e}")
    payload["updated"] = datetime.now().isoformat()[:19]

    tmp = _OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _OUT)

    print(f"Written -> {_OUT}")
    print(f"NEWS_GATE relax-enabled trades (closed): n={payload['n']} "
          f"win={payload['win']} loss={payload['loss']} "
          f"wr={payload['wr']} pnl={payload['pnl']} open={payload['open']}")
    if payload["n"] == 0:
        print("(n=0 is expected until NEWS_GATE=true and its relax path decisively enables a trade)")


if __name__ == "__main__":
    main()
