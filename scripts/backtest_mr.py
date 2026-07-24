"""scripts/backtest_mr.py — backtest the mean_reversion (RANGE z-score fade) algo across the universe.

Fills the Shadow Matrix "backtest R" column for algo_id=mean_reversion (was "—" — only momentum was
backtested). Reuses shadow_backtest.backtest_pair_mr (EXACT live shadow-algo path: detect_regime==RANGE
→ algo_mean_reversion → parity resolver + measured cost, non-overlapping). Read-only on MT5 (no orders).

Merges into docs/reports/shadow_backtest.json (tags every row with algo_id; regenerates fresh MR rows)
and writes docs/reports/shadow_backtest_mr.md.

Run:  python scripts/backtest_mr.py
"""
import json
import os
import sys
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
sys.path.insert(0, _BASE)

import config                                     # noqa: E402,F401  (loads .env)
from connectors.pair_collector import _broker_map, COLLECT   # noqa: E402
import shadow_backtest as SB                       # noqa: E402

_OUTDIR = os.path.join(_BASE, "docs", "reports")
_JSON = os.path.join(_OUTDIR, "shadow_backtest.json")
_MD = os.path.join(_OUTDIR, "shadow_backtest_mr.md")


def _load_existing():
    try:
        return json.load(open(_JSON, encoding="utf-8"))
    except Exception:
        return []


def _report_md(rows):
    L = ["# Shadow Backtest — mean_reversion (RANGE z-score fade), per pair (net of measured spread)\n"]
    L.append(f"_generated {datetime.now(timezone.utc).isoformat()[:16]}Z · H1 · SL-first · zone-SL + OU "
             "time-stop max_hold · non-overlapping single-position · fires only in RANGE regime_\n")
    L.append("\n| pair | broker | n | trades/yr | WR% | exp_R (net) | exp_R gross | sum_R | maxDD_R | avg hold | TP/SL/TO | cost_pips | span |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|--:|")
    for r in rows:
        if not r.get("ok"):
            L.append(f"| **{r['logical']}** | {r.get('broker','')} | — | — | — | — | — | — | — | — | — | — | {r.get('note','')} |")
            continue
        if not r.get("n"):
            L.append(f"| **{r['logical']}** | {r['broker']} | 0 | — | — | — | — | — | — | — | — | {r['cost_pips']} | {r.get('note','')} |")
            continue
        b = r["by_result"]
        L.append(f"| **{r['logical']}** | {r['broker']} | {r['n']} | {r['trades_per_year']} | {r['wr']} | "
                 f"**{r['exp_R']:+.3f}** | {r['exp_R_gross']:+.3f} | {r['sum_R']:+.1f} | {r['max_dd_R']:.1f} | "
                 f"{r['avg_hold']} | {b['TP']}/{b['SL']}/{b['TIMEOUT']} | {r['cost_pips']} | {r['span_years']}y |")
    L.append("\n## Read this before trusting any number\n")
    L.append("- **mean_reversion was CUT from live routing 07-19** (P2 OOS proved −EV, 0/27 combos). This "
             "backtest is IN-SAMPLE reference / shadow data-collection only — NOT a case to re-enable it.\n")
    L.append("- Same caveats as the momentum report: no deflated-Sharpe / OOS / PBO / purge-embargo, swap "
             "excluded, in-sample multiple testing. A positive in-sample exp_R here is a hypothesis, not an edge.\n")
    L.append("- **momentum_bars** column = RANGE bars with a fade signal (overlapping); **n** = non-overlapping "
             "trades actually taken. Pairs with few RANGE spells will have small n.\n")
    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)

    existing = _load_existing()
    for r in existing:                               # tag legacy momentum rows so the json is uniform
        r.setdefault("algo_id", "regime_momentum")
    non_mr = [r for r in existing if r.get("algo_id") != "mean_reversion"]

    bmap = _broker_map()
    mr_rows = []
    for logical in COLLECT:
        broker = bmap.get(logical, logical)
        print(f"  · mean_reversion {logical} ({broker}) …", flush=True)
        try:
            row = SB.backtest_pair_mr(logical, broker)
        except Exception as e:
            row = {"algo_id": "mean_reversion", "logical": logical, "broker": broker,
                   "ok": False, "note": f"{type(e).__name__}: {e}"}
        mr_rows.append(row)
        print(f"    → ok={row.get('ok')} n={row.get('n')} exp_R={row.get('exp_R')} {row.get('note','')}")

    merged = non_mr + mr_rows
    os.makedirs(_OUTDIR, exist_ok=True)
    with open(_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2, default=str)
    with open(_MD, "w", encoding="utf-8") as f:
        f.write(_report_md(mr_rows))
    ok_n = sum(1 for r in mr_rows if r.get("ok") and r.get("n"))
    print(f"\n→ wrote {_JSON} ({len(merged)} rows total)")
    print(f"→ wrote {_MD} (mean_reversion: {ok_n}/{len(mr_rows)} pairs with trades)")


if __name__ == "__main__":
    main()
