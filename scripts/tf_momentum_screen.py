"""scripts/tf_momentum_screen.py — does the momentum breakout work on a SLOWER timeframe?

Round-1 tested H1 only. Carry/trend currencies (USDJPY, AUDUSD) may trend on H4/D1 where H1 is noise
(Chan: persistence is timescale-dependent). Reuses the exact live signal (regime_lib) + parity-tested
resolver, per (pair × timeframe), net of measured spread, non-overlapping, IS/OOS split.

Honest caveats: regime_lib windows (VOL_LOOKBACK=480, BRK_WIN=20) were shaped on H1 → on D1 they span
years and the sample is short (D1 may be underpowered / skipped). This is a directional TF probe, not a
tuned D1 system (the bot's real D1 engine is agents/tsmom_manager.py, a different construction).
Every (pair,TF) cell is a TRIAL — counted for the multiple-testing bar. Read-only.  python scripts/tf_momentum_screen.py
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
SPREAD = {"XAUUSD": 30, "XAGUSD": 51, "EURUSD": 19, "AUDUSD": 24, "USDCHF": 26, "USDJPY": 25}
PAIRS = ["XAUUSD", "XAGUSD", "EURUSD", "AUDUSD", "USDCHF", "USDJPY"]


def _tfs():
    import MetaTrader5 as mt5
    return [("H4", mt5.TIMEFRAME_H4, 20000), ("D1", mt5.TIMEFRAME_D1, 20000)]


def run(logical, broker, tf_const, count):
    import MetaTrader5 as mt5
    r = mt5.copy_rates_from_pos(broker, tf_const, 0, count)
    if r is None or len(r) < _MIN + 60:
        return {"n": 0, "note": f"underpowered ({0 if r is None else len(r)} bars < {_MIN+60})"}
    info = mt5.symbol_info(broker); point = float(info.point); digits = int(info.digits)
    high = r["high"].astype(float); low = r["low"].astype(float)
    close = r["close"].astype(float); times = r["time"]
    cost = SPREAD[logical]
    er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
    vp = R.vol_percentile(close); atr = R.atr(high, low, close)
    n = len(close); cut = int(n * 0.6)
    trades = []; flat_until = -1
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
        trades.append((out["realized_R"], i < cut))
        flat_until = i + out["bars_held"]
    if not trades:
        return {"n": 0, "note": "no trades"}
    allR = [x for x, _ in trades]; isR = [x for x, i_ in trades if i_]; ooR = [x for x, i_ in trades if not i_]
    def e(v):
        return round(sum(v) / len(v), 3) if v else None
    return {"n": len(allR), "exp_R": e(allR), "sum_R": round(sum(allR), 1),
            "is_n": len(isR), "is_exp": e(isR), "oos_n": len(ooR), "oos_exp": e(ooR), "bars": n}


def main():
    bmap = _broker_map()
    print(f"TF momentum screen · {datetime.now(timezone.utc).isoformat()[:16]}Z · net spread · non-overlapping\n")
    trials = 0
    for name, tf, cnt in _tfs():
        print(f"══ {name} " + "═" * 60)
        print(f"   {'pair':8s} {'bars':>5s} {'n':>4s} {'exp_R':>7s} {'ΣR':>7s} | {'IS exp':>7s} {'OOS exp':>8s}")
        for p in PAIRS:
            d = run(p, bmap.get(p, p), tf, cnt)
            trials += 1
            if d["n"] == 0:
                print(f"   {p:8s} {'':>5s} {'0':>4s}  {d.get('note','')}")
                continue
            print(f"   {p:8s} {d['bars']:>5d} {d['n']:>4d} {str(d['exp_R']):>7s} {d['sum_R']:>7.1f} | "
                  f"{str(d['is_exp']):>7s} {str(d['oos_exp']):>8s}")
        print()
    print(f"trials this screen: {trials} (add to the multiple-testing budget). "
          f"positive exp_R must hold in BOTH IS & OOS and clear the deflated bar to count.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
