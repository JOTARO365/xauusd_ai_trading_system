"""scripts/backtest_missing.py — fill backtest gaps for pairs missing from shadow_backtest.json.

Reuses scripts/shadow_backtest.backtest_pair (EXACT live signal path + parity resolver + measured
cost) for ONLY the pairs not yet present in docs/reports/shadow_backtest.json, then MERGES the new
rows into the existing file (preserving the already-valid pairs) and regenerates the .md report.

Read-only on MT5 (copy_rates only — no orders). Does not touch live logic. Safe to run alongside the bot.

Run:  python scripts/backtest_missing.py            → updates docs/reports/shadow_backtest.{json,md}
"""
import json
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
sys.path.insert(0, _BASE)

import config                                     # noqa: E402,F401  (loads .env)
from connectors.pair_collector import _broker_map, COLLECT   # noqa: E402
import shadow_backtest as SB                       # noqa: E402

_OUTDIR = os.path.join(_BASE, "docs", "reports")
_JSON = os.path.join(_OUTDIR, "shadow_backtest.json")
_MD = os.path.join(_OUTDIR, "shadow_backtest.md")


def _load_existing():
    try:
        return json.load(open(_JSON, encoding="utf-8"))
    except Exception:
        return []


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)

    existing = _load_existing()
    have = {r.get("logical") for r in existing if r.get("ok") and r.get("n")}
    missing = [p for p in COLLECT if p not in have]
    print(f"existing ok pairs: {sorted(have)}")
    print(f"missing → backtest: {missing or '(none)'}")

    bmap = _broker_map()
    by_logical = {r.get("logical"): r for r in existing}
    for logical in missing:
        broker = bmap.get(logical, logical)
        print(f"  · backtesting {logical} ({broker}) …", flush=True)
        try:
            row = SB.backtest_pair(logical, broker)
        except Exception as e:
            row = {"logical": logical, "broker": broker, "ok": False, "note": f"{type(e).__name__}: {e}"}
        by_logical[logical] = row
        n = row.get("n"); exp = row.get("exp_R")
        print(f"    → ok={row.get('ok')} n={n} exp_R={exp} {row.get('note','')}")

    # rebuild rows in COLLECT order, keeping any extra pairs already present
    merged = [by_logical[p] for p in COLLECT if p in by_logical]
    for r in existing:
        if r.get("logical") not in COLLECT and r.get("logical") not in {m.get("logical") for m in merged}:
            merged.append(r)

    os.makedirs(_OUTDIR, exist_ok=True)
    with open(_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2, default=str)
    with open(_MD, "w", encoding="utf-8") as f:
        f.write(SB._report_md(merged))
    ok_n = sum(1 for r in merged if r.get("ok") and r.get("n"))
    print(f"\n→ wrote {_JSON} ({len(merged)} pairs, {ok_n} with trades)")
    print(f"→ wrote {_MD}")


if __name__ == "__main__":
    main()
