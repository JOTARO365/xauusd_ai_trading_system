"""scripts/session_fade_screen.py — quant Idea 1: Asian-session mean-reversion fade (gauntlet).

Thesis: FX majors have no persistent directional flow during the low-liquidity Tokyo session
(European/Japanese home markets closed) → price oscillates around a session anchor; fade deviations
back to it and be flat before London. The edge is a market-maker inventory premium; session hours are
exogenous (not tuned).

Spec (quant persona, principled params only):
  window   = Asian [00:00,06:00) UTC ; anchor m,sd = expanding mean/std of session closes (min 3 bars)
  entry    = z=(c-m)/sd ; BUY if z<-k, SELL if z>+k ; k=1.25 (pinned, = existing S_ENTRY, NOT grid-searched)
  TP       = the anchor m (conservative half-round-trip)
  SL       = session extreme so far ± 0.5·ATR
  time-stop= force-flat at window end (never carry a fade into the trending session)
  cost gate= take only if TP-distance ≥ 3 × spread (breakeven-after-cost math, not tuned)
  one position at a time ; net of measured spread ; SL-first intrabar.

Anti-bias gates:
  · London placebo [07:00,13:00): identical rule must be ≤0 — if London fades ALSO profit, it's not
    session structure but snooping → REJECT the whole idea.
  · IS/OOS split (first 60% days / last 40%): Asian edge must hold in BOTH.
  · negative note: Tokyo in-window spread is wider than the 24h median used here → real net is WORSE.

Read-only, 0 order.  Run: python scripts/session_fade_screen.py
"""
import os
import sys
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts")); sys.path.insert(0, _BASE)
import numpy as np                       # noqa: E402
import config                            # noqa: E402,F401
import regime_lib as R                   # noqa: E402
from connectors.pair_collector import _broker_map  # noqa: E402

COUNT = 20000
K = 1.25
RR_SPREAD = 3
SPREAD = {"EURUSD": 19, "USDCHF": 26, "USDJPY": 25, "AUDUSD": 24}
ASIAN = set(range(0, 6))                  # 00:00–05:59 UTC
LONDON = set(range(7, 13))               # 07:00–12:59 UTC (placebo)


def _bars(broker):
    import MetaTrader5 as mt5
    r = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_H1, 0, COUNT)
    if r is None or len(r) < 2000:
        return None
    info = mt5.symbol_info(broker)
    return r, float(info.point), int(info.digits)


def _hour(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).hour


def session_fade(high, low, close, times, atr, hours, point, spread_pts):
    """Return list of (realized_R_net, is_in_sample_bool). Session-anchored fade per spec."""
    cost_px = spread_pts * point
    trades = []
    n = len(close)
    cut_t = int(times[int(n * 0.6)])          # date boundary for IS/OOS
    sess_c = []; s_hi = -np.inf; s_lo = np.inf
    last_wi = None; trade = None; prev_in = False

    def _close(exit_px, entry_i):
        sign = 1 if trade["dir"] == "BUY" else -1
        r_gross = sign * (exit_px - trade["entry"]) / trade["risk"]
        r_net = r_gross - cost_px / trade["risk"]
        trades.append((round(r_net, 3), times[entry_i] < cut_t))

    for i in range(n):
        in_win = _hour(times[i]) in hours
        if in_win and not prev_in:                        # session start → reset
            sess_c = []; s_hi = -np.inf; s_lo = np.inf; trade = None; last_wi = None
        if not in_win:
            if trade is not None and last_wi is not None:  # window ended → time-stop at last in-win close
                _close(close[last_wi], trade["i"]); trade = None
            prev_in = in_win
            continue
        hi, lo, c = float(high[i]), float(low[i]), float(close[i])
        # 1) manage open trade on THIS bar (entered on a prior bar) — SL-first
        if trade is not None:
            if trade["dir"] == "BUY":
                if lo <= trade["sl"]:
                    _close(trade["sl"], trade["i"]); trade = None
                elif hi >= trade["tp"]:
                    _close(trade["tp"], trade["i"]); trade = None
            else:
                if hi >= trade["sl"]:
                    _close(trade["sl"], trade["i"]); trade = None
                elif lo <= trade["tp"]:
                    _close(trade["tp"], trade["i"]); trade = None
        # 2) update session stats with this bar
        sess_c.append(c); s_hi = max(s_hi, hi); s_lo = min(s_lo, lo); last_wi = i
        # 3) entry if flat
        if trade is None and len(sess_c) >= 3 and np.isfinite(atr[i]):
            m = float(np.mean(sess_c)); sd = float(np.std(sess_c))
            if sd > 0:
                z = (c - m) / sd
                d = "BUY" if z < -K else ("SELL" if z > K else None)
                if d is not None:
                    sl = (s_lo - 0.5 * atr[i]) if d == "BUY" else (s_hi + 0.5 * atr[i])
                    risk = abs(c - sl); tp_dist = abs(m - c)
                    if risk > 0 and tp_dist >= RR_SPREAD * cost_px:
                        trade = {"dir": d, "entry": c, "sl": sl, "tp": m, "risk": risk, "i": i}
        prev_in = in_win
    return trades


def _stat(v):
    return (len(v), round(sum(v) / len(v), 3), round(sum(v), 1)) if v else (0, None, 0.0)


def screen(logical, broker):
    got = _bars(broker)
    if got is None:
        print(f"{logical}: no data\n"); return
    r, point, digits = got
    high = r["high"].astype(float); low = r["low"].astype(float)
    close = r["close"].astype(float); times = r["time"]
    atr = R.atr(high, low, close)
    for name, hours in (("ASIAN", ASIAN), ("LONDON(placebo)", LONDON)):
        tr = session_fade(high, low, close, times, atr, hours, point, SPREAD[logical])
        allv = [x for x, _ in tr]; isv = [x for x, i_ in tr if i_]; oov = [x for x, i_ in tr if not i_]
        a, s_is, s_oo = _stat(allv), _stat(isv), _stat(oov)
        print(f"  {name:16s} n={a[0]:>4d}  exp_R={str(a[1]):>7s}  ΣR={a[2]:>7.1f}  | "
              f"IS exp={str(s_is[1]):>7s} (n={s_is[0]})  OOS exp={str(s_oo[1]):>7s} (n={s_oo[0]})")


def main():
    bmap = _broker_map()
    print(f"Session-fade screen · {datetime.now(timezone.utc).isoformat()[:16]}Z · H1 · k={K} · "
          f"reward≥{RR_SPREAD}×spread · net of 24h-median spread\n")
    for logical in ["EURUSD", "USDCHF", "USDJPY", "AUDUSD"]:
        print(f"── {logical} (spread {SPREAD[logical]}pt) " + "─" * 34)
        screen(logical, bmap.get(logical, logical))
        print()
    print("PASS criteria: ASIAN exp_R > 0 net, positive in BOTH IS & OOS, AND LONDON placebo ≤ 0.")
    print("caveat: Tokyo in-window spread > 24h median → real net is WORSE than shown.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
