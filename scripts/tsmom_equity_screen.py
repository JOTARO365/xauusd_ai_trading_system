"""scripts/tsmom_equity_screen.py — Phase 2 step 1: judge TSMOM-D1 by EQUITY-CURVE Sharpe, not per-trade R.

The per-trade-R deflation bar is the right tool for fixed-RR strategies but too harsh for a no-TP
trend-follower (fat-tailed trade R -> huge sigma -> unreachable bar; it even rejects the validated gold
TSMOM). The correct metric for trend-following is the annualized Sharpe of the daily mark-to-market
equity curve. This computes it, net of cost, per instrument, with an IS/OOS split and a DEFLATED
Sharpe bar folding in the trial count.

Daily return r_t = pos_{t-1}·(close_t/close_{t-1} − 1) − turnover·cost_pct  (pos ∈ {−1,0,+1} from the
frozen ensemble vote L=63/126/252). Sharpe_ann = mean(r)/std(r)·√252. Believe iff its t-stat
(Sharpe_ann·√years) clears the expected-max-of-N bar (c_N + 1.65), n_days admissible, and IS/OOS agree.
Read-only, 0 order.  python scripts/tsmom_equity_screen.py
"""
import os
import sys
from datetime import datetime, timezone
from statistics import NormalDist

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import numpy as np                       # noqa: E402
import config                            # noqa: E402,F401
from connectors.pair_collector import _broker_map  # noqa: E402

LOOKBACKS = [63, 126, 252]
_Z = NormalDist()
SPREAD = {"XAUUSD": 30, "XAGUSD": 51, "EURUSD": 19, "AUDUSD": 24, "USDCHF": 26, "USDJPY": 25,
          "BTCUSD": 2250, "WTIUSD": 3}
INSTRUMENTS = ["XAUUSD", "BTCUSD", "WTIUSD", "XAGUSD", "USDJPY", "EURUSD"]
N_TRIALS = 6                             # this screen's cells


def _c_n(N):
    g = 0.5772156649
    return (1 - g) * _Z.inv_cdf(1 - 1.0 / N) + g * _Z.inv_cdf(1 - 1.0 / (N * np.e))


def _positions(close):
    """TSMOM ensemble position series pos[i] decided at bar i (effective next bar). +1/-1/0."""
    pos = np.zeros(len(close))
    for i in range(max(LOOKBACKS), len(close)):
        v = sum(int(np.sign(close[i] - close[i - L])) for L in LOOKBACKS if i - L >= 0)
        pos[i] = 1 if v > 0 else (-1 if v < 0 else 0)
    return pos


def screen(logical, broker):
    import MetaTrader5 as mt5
    r = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_D1, 0, 6000)
    if r is None or len(r) < max(LOOKBACKS) + 250:
        return {"n": 0, "note": f"D1 bars={0 if r is None else len(r)}"}
    close = r["close"].astype(float)
    point = float(mt5.symbol_info(broker).point)
    cost_pct = SPREAD[logical] * point / np.median(close)     # one-way spread as fraction of price
    pos = _positions(close)
    # daily mark-to-market returns of the strategy (pos held from prior bar), net of turnover cost
    pct = close[1:] / close[:-1] - 1.0
    p_prev = pos[:-1]
    turnover = np.abs(np.diff(np.concatenate([[0.0], p_prev])))   # position change each day
    ret = p_prev * pct - turnover * cost_pct
    start = max(LOOKBACKS)                                     # only score after signals are live
    ret = ret[start:]
    if len(ret) < 250:
        return {"n": 0, "note": "too few days"}
    cut = int(len(ret) * 0.6)

    def _sharpe(x):
        sd = float(np.std(x, ddof=1))
        return (float(np.mean(x)) / sd * np.sqrt(252)) if sd > 0 else 0.0
    sr = _sharpe(ret); sr_is = _sharpe(ret[:cut]); sr_oos = _sharpe(ret[cut:])
    years = len(ret) / 252
    t = sr * np.sqrt(years)                                    # t-stat of the annualized Sharpe
    bar_t = _c_n(N_TRIALS) + 1.65                              # deflated bar on the t-stat
    # equity + max drawdown (%)
    eq = np.cumprod(1 + ret); peak = np.maximum.accumulate(eq); dd = float(((eq - peak) / peak).min())
    cagr = float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else -1.0
    return {"n": len(ret), "years": round(years, 1), "sharpe": round(sr, 2),
            "sr_is": round(sr_is, 2), "sr_oos": round(sr_oos, 2), "t": round(t, 2),
            "bar_t": round(bar_t, 2), "maxdd": round(dd * 100, 1), "cagr": round(cagr * 100, 1),
            "believe": t > bar_t and sr_oos > 0}


def main():
    bmap = _broker_map()
    print(f"TSMOM-D1 EQUITY-Sharpe screen · {datetime.now(timezone.utc).isoformat()[:16]}Z · frozen "
          f"L={LOOKBACKS} · net cost · N={N_TRIALS} · t-bar={_c_n(N_TRIALS)+1.65:.2f}")
    print("(Sharpe = annualized, daily mark-to-market equity curve — the right metric for trend-following)\n")
    print(f"{'instrument':10s} {'yrs':>4s} {'Sharpe':>7s} {'IS':>6s} {'OOS':>6s} {'t':>5s} {'bar':>5s} "
          f"{'CAGR%':>6s} {'maxDD%':>7s}  verdict")
    for p in INSTRUMENTS:
        d = screen(p, bmap.get(p, p))
        if d["n"] == 0:
            print(f"{p:10s} {d.get('note','')}"); continue
        v = "BELIEVE" if d["believe"] else ("OOS<0" if d["sr_oos"] <= 0 else "reject (t<bar)")
        print(f"{p:10s} {d['years']:>4.1f} {d['sharpe']:>+7.2f} {d['sr_is']:>+6.2f} {d['sr_oos']:>+6.2f} "
              f"{d['t']:>5.2f} {d['bar_t']:>5.2f} {d['cagr']:>+6.1f} {d['maxdd']:>7.1f}  {v}")
    print("\nBELIEVE = annualized-Sharpe t-stat > deflated bar AND OOS Sharpe > 0. Trend-following judged")
    print("on equity Sharpe (fair), not per-trade R. Gold TSMOM is the validated reference to sanity-check.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
