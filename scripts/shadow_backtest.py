"""scripts/shadow_backtest.py — per-pair historical backtest of the regime momentum-breakout algo.

Reuses the EXACT live signal path (regime_lib route/indicators) + the parity-tested resolver
(agents.shadow_resolve) + measured per-pair cost (agents.shadow_cost). No look-ahead: a signal at
closed bar i is resolved only from bars i+1…, SL-first on ambiguous bars, net of each pair's median
spread. Realistic single-position: after entering, we stay flat until the trade resolves (mirrors the
live ALGO_MAX_STACK=1 guard) — so trades are non-overlapping and tradeable, not overlapping counterfactuals.

⚠️ This is an IN-SAMPLE historical replay, NOT validated edge. It does not deflate for multiple testing,
run OOS/PBO, or model swap. Read scripts/shadow_backtest with §validation caveats in the emitted report.

Run:  python scripts/shadow_backtest.py            → writes docs/reports/shadow_backtest.md + prints table
"""
import json
import os
import sys
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
sys.path.insert(0, _BASE)

import numpy as np                       # noqa: E402
import config                            # noqa: E402,F401  (loads .env)
import regime_lib as R                   # noqa: E402  (single source of algo truth)
from agents.shadow_resolve import resolve_signal   # noqa: E402
from agents import shadow_cost as SC     # noqa: E402
from connectors.pair_collector import _broker_map, COLLECT  # noqa: E402

MAX_HOLD = 48
_MIN_BARS = R.VOL_LOOKBACK + 40          # 520 — same floor as compute_shadow_signal
_COUNT = 20000                           # ~3.4y of H1 (broker-capped)


def _iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()


def _fetch(broker, count=_COUNT):
    import MetaTrader5 as mt5
    rates = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_H1, 0, count)
    if rates is None or len(rates) < _MIN_BARS + 50:
        return None
    info = mt5.symbol_info(broker)
    point = float(info.point) if info and info.point else None
    digits = int(info.digits) if info else 5
    return rates, point, digits


def backtest_pair(logical, broker):
    got = _fetch(broker)
    if got is None:
        return {"logical": logical, "broker": broker, "ok": False, "note": "no/insufficient bars"}
    rates, point, digits = got
    if point is None:
        return {"logical": logical, "broker": broker, "ok": False, "note": "no symbol point"}
    high = rates["high"].astype(float); low = rates["low"].astype(float)
    close = rates["close"].astype(float); times = rates["time"]
    cost_pips = SC.cost_pips(logical)

    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    n = len(close)

    trades = []
    momentum_bars = 0
    flat_until = -1
    for i in range(_MIN_BARS, n - 1):                    # signal at closed bar i (needs i+1.. to resolve)
        regime, sig = R.route(i, high, low, close, atr_v, er, adx_v, volpct, point=point)
        if not sig or sig.get("algo") != "momentum_breakout":
            continue
        momentum_bars += 1
        if i <= flat_until:                              # in a trade → skip (non-overlapping)
            continue
        rec = {"dir": sig["dir"], "entry": float(close[i]),
               "sl_pips": sig["sl_pips"], "tp_pips": sig["tp_pips"], "bar_ts": _iso(times[i])}
        out = resolve_signal(rec, high, low, close, times, point=point, cost_pips=cost_pips,
                             max_hold_bars=MAX_HOLD, price_digits=digits, i0=i)
        if out is None or out.get("result") == "OPEN":   # tail: not enough forward data → stop
            break
        trades.append({"i": i, "dir": rec["dir"], "regime": regime, **out})
        flat_until = i + out["bars_held"]

    return _aggregate(logical, broker, trades, cost_pips, point, times, n, momentum_bars)


def _aggregate(logical, broker, trades, cost_pips, point, times, n, momentum_bars,
               algo_id="regime_momentum"):
    span_years = round((int(times[-1]) - int(times[0])) / (365.25 * 24 * 3600), 2)
    res = {"algo_id": algo_id, "logical": logical, "broker": broker, "ok": True,
           "cost_pips": round(cost_pips, 1), "bars": n, "span_years": span_years,
           "momentum_bars": momentum_bars, "n": len(trades)}
    if not trades:
        res.update({"note": "no non-overlapping trades"})
        return res
    Rs = [t["realized_R"] for t in trades]
    Rg = [t["realized_R_gross"] for t in trades]
    wins = sum(1 for r in Rs if r > 0)
    by = {"TP": 0, "SL": 0, "TIMEOUT": 0}
    for t in trades:
        by[t["result"]] = by.get(t["result"], 0) + 1
    # equity curve (R) → max drawdown
    eq = 0.0; peak = 0.0; maxdd = 0.0
    for r in Rs:
        eq += r; peak = max(peak, eq); maxdd = min(maxdd, eq - peak)
    res.update({
        "wr": round(wins / len(trades) * 100, 1),
        "sum_R": round(sum(Rs), 1),
        "exp_R": round(sum(Rs) / len(Rs), 3),
        "exp_R_gross": round(sum(Rg) / len(Rg), 3),
        "max_dd_R": round(maxdd, 1),
        "avg_hold": round(sum(t["bars_held"] for t in trades) / len(trades), 1),
        "by_result": by,
        "trades_per_year": round(len(trades) / span_years, 1) if span_years else None,
        "first": _iso(times[0])[:10], "last": _iso(times[-1])[:10],
    })
    return res


def backtest_pair_mr(logical, broker):
    """Mean-reversion (RANGE z-score fade) backtest — mirrors agents.MeanReversionAlgo exactly:
    only fires when detect_regime==RANGE, uses algo_mean_reversion's zone-SL + OU time-stop max_hold.
    Same no-look-ahead resolver + measured cost + non-overlapping single-position as momentum."""
    got = _fetch(broker)
    if got is None:
        return {"algo_id": "mean_reversion", "logical": logical, "broker": broker, "ok": False,
                "note": "no/insufficient bars"}
    rates, point, digits = got
    if point is None:
        return {"algo_id": "mean_reversion", "logical": logical, "broker": broker, "ok": False,
                "note": "no symbol point"}
    high = rates["high"].astype(float); low = rates["low"].astype(float)
    close = rates["close"].astype(float); times = rates["time"]
    cost_pips = SC.cost_pips(logical)

    er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
    volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
    n = len(close)

    trades = []
    range_bars = 0
    flat_until = -1
    for i in range(_MIN_BARS, n - 1):
        if R.detect_regime(er[i], adx_v[i], volpct[i]) != "RANGE":
            continue                                     # MR fires only in RANGE (== live shadow algo)
        sig = R.algo_mean_reversion(i, close, atr_v, point=point)
        if not sig:
            continue
        range_bars += 1
        if i <= flat_until:                              # in a trade → non-overlapping
            continue
        rec = {"dir": sig["dir"], "entry": float(close[i]),
               "sl_pips": sig["sl_pips"], "tp_pips": sig["tp_pips"], "bar_ts": _iso(times[i])}
        mh = sig.get("max_hold_bars") or MAX_HOLD        # OU time-stop from the signal itself
        out = resolve_signal(rec, high, low, close, times, point=point, cost_pips=cost_pips,
                             max_hold_bars=mh, price_digits=digits, i0=i)
        if out is None or out.get("result") == "OPEN":
            break
        trades.append({"i": i, "dir": rec["dir"], "regime": "RANGE", **out})
        flat_until = i + out["bars_held"]

    return _aggregate(logical, broker, trades, cost_pips, point, times, n, range_bars,
                      algo_id="mean_reversion")


def run_all():
    bmap = _broker_map()
    out = []
    for logical in COLLECT:
        broker = bmap.get(logical, logical)
        try:
            out.append(backtest_pair(logical, broker))
        except Exception as e:
            out.append({"logical": logical, "broker": broker, "ok": False, "note": f"{type(e).__name__}: {e}"})
    return out


def _report_md(rows):
    L = []
    L.append("# Shadow Backtest — regime momentum-breakout, per pair (net of measured spread)\n")
    L.append(f"_generated {datetime.now(timezone.utc).isoformat()[:16]}Z · H1 · SL-first · max_hold {MAX_HOLD} bars · "
             "non-overlapping single-position_\n")
    L.append("\n| pair | broker | n | trades/yr | WR% | exp_R (net) | exp_R gross | sum_R | maxDD_R | avg hold | TP/SL/TO | cost_pips | span |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|--:|")
    ok_rows = [r for r in rows if r.get("ok") and r.get("n")]
    for r in rows:
        if not r.get("ok"):
            L.append(f"| **{r['logical']}** | {r['broker']} | — | — | — | — | — | — | — | — | — | — | {r.get('note','')} |")
            continue
        if not r.get("n"):
            L.append(f"| **{r['logical']}** | {r['broker']} | 0 | — | — | — | — | — | — | — | — | {r['cost_pips']} | {r.get('note','')} |")
            continue
        b = r["by_result"]
        L.append(f"| **{r['logical']}** | {r['broker']} | {r['n']} | {r['trades_per_year']} | {r['wr']} | "
                 f"**{r['exp_R']:+.3f}** | {r['exp_R_gross']:+.3f} | {r['sum_R']:+.1f} | {r['max_dd_R']:.1f} | "
                 f"{r['avg_hold']} | {b['TP']}/{b['SL']}/{b['TIMEOUT']} | {r['cost_pips']} | {r['span_years']}y |")
    # honest verdict line
    L.append("\n## Read this before trusting any number\n")
    _npairs = len(ok_rows)
    L.append(f"- **In-sample historical replay — NOT validated edge.** No deflated-Sharpe, no OOS/PBO, no "
             f"purge/embargo. With one strategy across {_npairs} pairs this is {_npairs} trials of multiple "
             "testing; the best-looking pair is the most likely to be noise.\n")
    L.append("- **exp_R (net)** already subtracts each pair's measured median spread (cost_pips). A pair is only "
             "interesting if **exp_R net > 0 with a usable sample** (rule of thumb n≥100). exp_R gross shows how "
             "much of the edge the spread eats.\n")
    L.append("- **Swap excluded** (D3). H1 momentum holds ~avg-hold bars; multi-day holds accrue swap "
             "(gold ≈ −81/lot/night) — real net is WORSE than shown. A measured swap table is required before LIVE.\n")
    L.append("- **Prior finding stands:** XAUUSD momentum showed no directional edge OOS. Treat any positive "
             "in-sample exp_R here as a hypothesis to be confirmed by forward SHADOW (n≥100, ≥2 regimes), not a green light.\n")
    L.append("- **momentum_bars** = every bar in a TREND breakout (overlapping); **n** = the non-overlapping "
             "trades actually taken (one position at a time). WR/exp_R are on n.\n")
    return "\n".join(L)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    rows = run_all()
    md = _report_md(rows)
    outdir = os.path.join(_BASE, "docs", "reports")
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, "shadow_backtest.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(md)
    # also dump raw json for the dashboard/matrix later
    with open(os.path.join(outdir, "shadow_backtest.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    print(md)
    print(f"\n→ {outpath}")
