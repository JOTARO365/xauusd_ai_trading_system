"""Segment closed trades from DB to locate where losses concentrate.
Usage: python scripts/diagnose_trades.py
"""
import sys
from collections import defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
import config  # noqa: F401  (loads .env)
from db.reader import get_trades


def seg(trades, key_fn, label):
    groups = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)
    print(f"\n== {label} ==")
    rows = []
    for k, g in groups.items():
        pnl = sum(x["pnl"] for x in g)
        wins = sum(1 for x in g if x["pnl"] > 0)
        rows.append((pnl, k, len(g), wins))
    for pnl, k, n, wins in sorted(rows):
        wr = wins / n * 100 if n else 0
        avg = pnl / n if n else 0
        print(f"  {str(k):<28} n={n:<4} WR={wr:5.1f}%  pnl={pnl:+10.2f}  avg={avg:+8.2f}")


def main():
    t = [x for x in (get_trades("XAUUSD") or []) if x.get("pnl") is not None]
    total = sum(x["pnl"] for x in t)
    wins = sum(1 for x in t if x["pnl"] > 0)
    print(f"closed trades={len(t)}  total pnl={total:+.2f}  WR={wins/len(t)*100:.1f}%")

    seg(t, lambda x: x.get("source") or "AI", "source (MANUAL vs AI)")
    seg(t, lambda x: x.get("strategy_version") or 1, "strategy_version")
    ai = [x for x in t if (x.get("source") or "AI").upper() != "MANUAL"]
    print(f"\n--- AI-only below (n={len(ai)}, pnl={sum(x['pnl'] for x in ai):+.2f}) ---")
    seg(ai, lambda x: x.get("direction"), "direction")
    seg(ai, lambda x: x.get("entry_type") or "?", "entry_type")
    seg(ai, lambda x: x.get("close_reason") or "?", "close_reason")
    seg(ai, lambda x: (x.get("trend") or "?"), "trend at entry")

    def hour_bucket(x):
        ts = x.get("timestamp") or ""
        try:
            h = datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
        except Exception:
            return "?"
        if 0 <= h < 7:   return "asian 0-7"
        if 7 <= h < 12:  return "london 7-12"
        if 12 <= h < 16: return "overlap 12-16"
        if 16 <= h < 21: return "ny 16-21"
        return "late 21-24"
    seg(ai, hour_bucket, "session (UTC hour)")

    def conf_bucket(x):
        c = x.get("technical_confidence")
        if c is None: return "?"
        return f"{int(c)//10*10}-{int(c)//10*10+9}"
    seg(ai, conf_bucket, "confidence band")

    def sl_bucket(x):
        e, s = x.get("entry_price"), x.get("sl")
        if not e or not s: return "no-sl"
        pips = abs(e - s) / 0.01
        if pips < 800:    return "sl<800"
        if pips < 1500:   return "sl 800-1500"
        if pips < 2500:   return "sl 1500-2500"
        return "sl>2500"
    seg(ai, sl_bucket, "SL width (pips, entry-vs-sl)")

    # Step 2 — concentration: top 12 losses
    print("\n== top losses (concentration) ==")
    worst = sorted(t, key=lambda x: x["pnl"])[:12]
    wsum = sum(x["pnl"] for x in worst)
    losses = sum(x["pnl"] for x in t if x["pnl"] < 0)
    print(f"  top12 = {wsum:+.2f} of total losses {losses:+.2f} ({wsum/losses*100:.0f}%)")
    for x in worst:
        print(f"  {x.get('timestamp','')[:16]} {x.get('source','')[:6]:<6} "
              f"{x.get('direction','?'):<4} {x.get('entry_type') or '?':<18} "
              f"conf={x.get('technical_confidence')} trend={x.get('trend') or '?':<8} "
              f"pnl={x['pnl']:+9.2f} reason={x.get('close_reason') or '?'}")

    # time clustering of the worst trades
    print("\n== day clustering of negative pnl ==")
    by_day = defaultdict(float)
    for x in t:
        if x["pnl"] < 0:
            by_day[(x.get("timestamp") or "")[:10]] += x["pnl"]
    for d, v in sorted(by_day.items(), key=lambda kv: kv[1])[:8]:
        print(f"  {d}  {v:+10.2f}")


if __name__ == "__main__":
    main()
