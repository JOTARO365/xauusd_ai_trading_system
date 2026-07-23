"""scripts/char_new_instruments.py — Phase 0/1: characterize BTC + WTI (the trend-family candidates).

FX momentum died at every timeframe (efficient markets). BTC and WTI are persistent trenders
(crypto herding / commodity supply-demand, no fair-value anchor) → momentum SHOULD work, like gold.
This verifies the symbols have data and measures whether momentum (H1 Donchian) and TSMOM-D1 clear the
ML deflated bar — net of measured spread, IS/OOS split. Read-only, 0 order.

python scripts/char_new_instruments.py   (run in background; MT5 may download history on first access)
"""
import os
import sys
from datetime import datetime, timezone
from statistics import NormalDist

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import numpy as np                       # noqa: E402
import config                            # noqa: E402,F401
import regime_lib as R                   # noqa: E402
from agents.shadow_resolve import resolve_signal   # noqa: E402

LOOKBACKS = [63, 126, 252]
_Z = NormalDist()
# candidates: (label, broker_symbol, fallback_spread_pts if market closed)
CANDIDATES = [("BTC", "BTCUSD#", 2250), ("WTI", "OILCash#", 5), ("WTI_alt", "OIL-SEP26", 5)]
N_TRIALS = 6


def _c_n(N):
    g = 0.5772156649
    return (1 - g) * _Z.inv_cdf(1 - 1.0 / N) + g * _Z.inv_cdf(1 - 1.0 / (N * np.e))


def _spread(broker, fallback):
    import MetaTrader5 as mt5
    mt5.symbol_select(broker, True)
    t = mt5.symbol_info_tick(broker); i = mt5.symbol_info(broker)
    if t and i and t.bid > 0 and i.point:
        return round((t.ask - t.bid) / i.point), t.bid
    return fallback, (t.bid if t else 0.0)


def _rates(broker, tf, count):
    import MetaTrader5 as mt5
    return mt5.copy_rates_from_pos(broker, tf, 0, count)


def momentum_h1(broker, cost, point, digits):
    r = _rates(broker, __import__("MetaTrader5").TIMEFRAME_H1, 20000)
    if r is None or len(r) < R.VOL_LOOKBACK + 100:
        return {"n": 0, "note": f"H1 bars={0 if r is None else len(r)}"}
    high = r["high"].astype(float); low = r["low"].astype(float)
    close = r["close"].astype(float); times = r["time"]
    er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
    vp = R.vol_percentile(close); atr = R.atr(high, low, close)
    n = len(close); cut = int(n * 0.6); trades = []; flat = -1
    for i in range(R.VOL_LOOKBACK + 40, n - 1):
        regime, sig = R.route(i, high, low, close, atr, er, adx, vp, point=point)
        if not sig or sig.get("algo") != "momentum_breakout" or i <= flat:
            continue
        rec = {"dir": sig["dir"], "entry": float(close[i]), "sl_pips": sig["sl_pips"],
               "tp_pips": sig["tp_pips"], "bar_ts": ""}
        out = resolve_signal(rec, high, low, close, times, point=point, cost_pips=cost,
                             max_hold_bars=48, price_digits=digits, i0=i)
        if out is None or out.get("result") == "OPEN":
            break
        trades.append((out["realized_R"], i < cut)); flat = i + out["bars_held"]
    return _summ(trades, n / (24 * 252))


def tsmom_d1(broker, cost, point):
    r = _rates(broker, __import__("MetaTrader5").TIMEFRAME_D1, 6000)
    if r is None or len(r) < max(LOOKBACKS) + 60:
        return {"n": 0, "note": f"D1 bars={0 if r is None else len(r)}"}
    high = r["high"].astype(float); low = r["low"].astype(float); close = r["close"].astype(float)
    atr = R.atr(high, low, close); cost_px = cost * point * 2
    n = len(close); cut = int(n * 0.6)
    pos = "FLAT"; entry = sl = risk = 0.0; ei = 0; trades = []

    def _sig(i):
        v = sum(int(np.sign(close[i] - close[i - L])) for L in LOOKBACKS if i - L >= 0)
        return "BUY" if v > 0 else ("SELL" if v < 0 else "FLAT")

    def _ex(px, at):
        s = 1 if pos == "BUY" else -1
        trades.append((s * (px - entry) / risk - cost_px / risk, ei < cut))
    for i in range(max(LOOKBACKS) + 1, n):
        if pos == "BUY" and low[i] <= sl:
            _ex(sl, i); pos = "FLAT"
        elif pos == "SELL" and high[i] >= sl:
            _ex(sl, i); pos = "FLAT"
        sg = _sig(i)
        if sg != pos:
            if pos != "FLAT":
                _ex(close[i], i); pos = "FLAT"
            if sg != "FLAT" and np.isfinite(atr[i]) and atr[i] > 0:
                entry = close[i]; risk = 3.0 * atr[i]; sl = entry - risk if sg == "BUY" else entry + risk
                pos = sg; ei = i
    return _summ(trades, n / 252)


def _summ(trades, years):
    if not trades:
        return {"n": 0, "note": "no trades"}
    allR = np.array([x for x, _ in trades]); isR = [x for x, i_ in trades if i_]; ooR = [x for x, i_ in trades if not i_]
    sd = float(allR.std(ddof=1)) if len(allR) > 1 else 0.0
    exp = float(allR.mean()); bar = sd * (_c_n(N_TRIALS) + 1.65) / np.sqrt(len(allR)) if sd > 0 else None
    return {"n": len(allR), "exp_R": round(exp, 3), "sd_R": round(sd, 2),
            "t": round(exp / sd * np.sqrt(len(allR)), 2) if sd > 0 else 0,
            "bar": round(bar, 3) if bar else None, "sum_R": round(float(allR.sum()), 1),
            "is": round(float(np.mean(isR)), 3) if isR else None,
            "oos": round(float(np.mean(ooR)), 3) if ooR else None,
            "believe": bar is not None and exp > bar and len(allR) >= 100, "years": round(years, 1)}


def _line(tag, d):
    if d["n"] == 0:
        return f"    {tag:10s} {d.get('note','')}"
    v = "BELIEVE" if d["believe"] else ("underpowered" if d["n"] < 100 else "reject")
    return (f"    {tag:10s} yrs={d['years']:<5.1f} n={d['n']:<4d} exp_R={d['exp_R']:+.3f} σ={d['sd_R']:<4.2f} "
            f"t={d['t']:+.2f} bar={d['bar']} IS={d['is']} OOS={d['oos']}  {v}")


def main():
    import MetaTrader5 as mt5
    print(f"New-instrument characterization · {datetime.now(timezone.utc).isoformat()[:16]}Z\n")
    for label, broker, fb in CANDIDATES:
        i = mt5.symbol_info(broker)
        if i is None:
            print(f"── {label} ({broker}): SYMBOL NOT FOUND\n"); continue
        sp, bid = _spread(broker, fb)
        print(f"── {label} = {broker} · point={i.point} digits={i.digits} spread={sp}pt "
              f"price≈{bid or '(closed)'} contract={getattr(i,'trade_contract_size',None)}")
        print(_line("mom-H1", momentum_h1(broker, sp, float(i.point), int(i.digits))))
        print(_line("tsmom-D1", tsmom_d1(broker, sp, float(i.point))))
        print()
    print("trend-family expectation: BTC/WTI should show momentum surviving OOS (unlike efficient FX).")
    print("verdict per instrument feeds Phase-2 algo assignment. N_TRIALS accounting: +2 cells each.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
