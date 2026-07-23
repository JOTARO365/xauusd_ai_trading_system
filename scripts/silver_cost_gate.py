"""scripts/silver_cost_gate.py — can a spread-budget gate rescue silver's real (gross+) momentum?

XAGUSD momentum is gross-POSITIVE (+0.141R) but net-NEGATIVE (−0.070R) — a pure cost problem (51-pt
spread), not a broken signal. The gate: take a breakout only when its ATR-sized SL is ≥ G× the spread
(so cost is ≤ 1/G of risk). Sweep a few principled G and — the anti-bias part — split IN-SAMPLE (first
60%) vs OOS (last 40%): a gate that only helps in-sample is overfit and rejected.

EURUSD/AUDUSD run as NEGATIVE CONTROLS: they are gross-negative (no signal), so no cost gate should
rescue them. If the gate "fixes" them too, it's cutting noise by luck → distrust the silver result.

Reuses regime_lib (signal) + shadow_resolve (resolver). Read-only, 0 order.  Run: python scripts/silver_cost_gate.py
"""
import os
import sys
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import numpy as np                       # noqa: E402
import config                            # noqa: E402,F401
import regime_lib as R                   # noqa: E402
from agents.shadow_resolve import resolve_signal   # noqa: E402
from connectors.pair_collector import _broker_map  # noqa: E402

_MIN = R.VOL_LOOKBACK + 40
COUNT = 20000
SPREAD = {"XAGUSD": 51, "EURUSD": 19, "AUDUSD": 24}
GATES = [1, 3, 5, 7, 10]                 # G = min SL / spread (1 = no gate baseline)


def _bars(broker):
    import MetaTrader5 as mt5
    r = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_H1, 0, COUNT)
    if r is None or len(r) < _MIN + 100:
        return None
    info = mt5.symbol_info(broker)
    return r, float(info.point), int(info.digits)


def run_pair(logical, broker):
    got = _bars(broker)
    if got is None:
        return None
    r, point, digits = got
    high = r["high"].astype(float); low = r["low"].astype(float)
    close = r["close"].astype(float); times = r["time"]
    cost = SPREAD[logical]
    er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
    vp = R.vol_percentile(close); atr = R.atr(high, low, close)
    n = len(close)
    # collect all momentum trades once (non-overlapping), tag each with sl_pips + in/out-of-sample
    cut_i = int(n * 0.6)
    trades = []
    flat_until = -1
    for i in range(_MIN, n - 1):
        regime, sig = R.route(i, high, low, close, atr, er, adx, vp, point=point)
        if not sig or sig.get("algo") != "momentum_breakout" or i <= flat_until:
            continue
        rec = {"dir": sig["dir"], "entry": float(close[i]), "sl_pips": sig["sl_pips"],
               "tp_pips": sig["tp_pips"], "bar_ts": ""}
        out = resolve_signal(rec, high, low, close, times, point=point, cost_pips=cost,
                             max_hold_bars=48, price_digits=digits, i0=i)
        if out is None or out.get("result") == "OPEN":
            break
        trades.append((sig["sl_pips"], out["realized_R"], i < cut_i))
        flat_until = i + out["bars_held"]

    rows = []
    for G in GATES:
        sel = [(rr, is_) for (slp, rr, is_) in trades if slp >= G * cost]
        allR = [rr for rr, _ in sel]; isR = [rr for rr, i_ in sel if i_]; oosR = [rr for rr, i_ in sel if not i_]
        def stat(v):
            return (len(v), round(sum(v) / len(v), 3), round(sum(v), 1)) if v else (0, None, 0.0)
        rows.append((G, stat(allR), stat(isR), stat(oosR)))
    return rows


def main():
    bmap = _broker_map()
    print(f"Silver cost-gate screen · {datetime.now(timezone.utc).isoformat()[:16]}Z · H1 · "
          "gate G = min(SL / spread)\n")
    for logical in ["XAGUSD", "EURUSD", "AUDUSD"]:
        tag = "PRIMARY" if logical == "XAGUSD" else "negative-control"
        print(f"── {logical}  ({tag}, spread={SPREAD[logical]}) " + "─" * 30)
        rows = run_pair(logical, bmap.get(logical, logical))
        if rows is None:
            print("   no data\n"); continue
        print(f"   {'G':>3s} | {'n':>4s} {'exp_R':>7s} {'ΣR':>7s} | {'IS n':>5s} {'IS exp':>7s} | {'OOS n':>6s} {'OOS exp':>8s}")
        for G, a, i_, o in rows:
            print(f"   {G:>3d} | {a[0]:>4d} {str(a[1]):>7s} {a[2]:>7.1f} | "
                  f"{i_[0]:>5d} {str(i_[1]):>7s} | {o[0]:>6d} {str(o[1]):>8s}")
        print()
    print("read: silver is REAL only if exp_R turns +positive at a principled G AND stays + in BOTH")
    print("      IS and OOS. If EURUSD/AUDUSD also flip +, the gate is cutting noise by luck → distrust.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
