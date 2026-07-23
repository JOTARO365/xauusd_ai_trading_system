"""scripts/tsmom_pairs_screen.py — the #1 round-2 lead: does the FROZEN TSMOM-D1 engine (validated on
gold) work on the -EV pairs, judged against the ML persona's DEFLATED significance bar?

Reuses the exact live signal (agents.tsmom_manager._signal: ensemble majority vote of
sign(close[-2] - close[-2-L]) for L in TSMOM_LOOKBACKS, exit-on-flip, no TP, chandelier 3×ATR disaster
SL). Frozen config = 1 trial per pair (no param grid) → keeps N small so the deflation bar stays low.

Per trade R = sign·(exit-entry)/risk − 2·spread/risk, risk = 3×ATR(entry). exit-on-flip; disaster-SL
if breached first (−1R). Net of measured spread (×2, entry+exit). IS/OOS split 60/40. D1 via MT5.

Anti-bias bar (ML round 2): believe a cell ONLY if net exp_R > exp_R*(N,n) = σ_R·(c_N+1.65)/√n, with
c_N the expected-max-of-N-trials multiplier, AND n ≥ 100 (≥250 ideal). +0.05R is noise (0.6σ at n=250).
Read-only, 0 order.  python scripts/tsmom_pairs_screen.py
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
from connectors.pair_collector import _broker_map  # noqa: E402

LOOKBACKS = [63, 126, 252]
SL_ATR = 3.0
SPREAD = {"XAUUSD": 30, "XAGUSD": 51, "EURUSD": 19, "AUDUSD": 24, "USDCHF": 26, "USDJPY": 25}
PAIRS = ["XAUUSD", "XAGUSD", "EURUSD", "AUDUSD", "USDCHF", "USDJPY"]
N_TRIALS = 6                              # this screen = 6 cells (frozen config, no grid)
_Z = NormalDist()


def _c_n(N):
    """expected-max-of-N multiplier c_N (Bailey/LdP): (1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(Ne))."""
    g = 0.5772156649
    return (1 - g) * _Z.inv_cdf(1 - 1.0 / N) + g * _Z.inv_cdf(1 - 1.0 / (N * np.e))


def _signal(close, i):
    """ensemble vote at decision bar i (closed) — mirrors tsmom_manager._signal with ci=i."""
    votes = 0
    for L in LOOKBACKS:
        if i - L >= 0:
            votes += int(np.sign(close[i] - close[i - L]))
    return "BUY" if votes > 0 else ("SELL" if votes < 0 else "FLAT")


def backtest(logical, broker):
    import MetaTrader5 as mt5
    r = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_D1, 0, 6000)
    if r is None or len(r) < max(LOOKBACKS) + 60:
        return {"n": 0, "note": f"underpowered ({0 if r is None else len(r)} D1 bars)"}
    high = r["high"].astype(float); low = r["low"].astype(float); close = r["close"].astype(float)
    info = mt5.symbol_info(broker); point = float(info.point)
    atr = R.atr(high, low, close)
    cost_px = SPREAD[logical] * point * 2            # round-trip (entry+exit)
    n = len(close); cut = int(n * 0.6)
    pos = "FLAT"; entry = sl = 0.0; risk = 0.0; entry_i = 0
    trades = []                                       # (R_net, is_in_sample)

    def _exit(px, at_i):
        sign = 1 if pos == "BUY" else -1
        r_net = sign * (px - entry) / risk - cost_px / risk
        trades.append((r_net, entry_i < cut))

    for i in range(max(LOOKBACKS) + 1, n):
        # disaster SL check intrabar (before flip)
        if pos == "BUY" and low[i] <= sl:
            _exit(sl, i); pos = "FLAT"
        elif pos == "SELL" and high[i] >= sl:
            _exit(sl, i); pos = "FLAT"
        sig = _signal(close, i)
        if sig != pos:
            if pos != "FLAT":
                _exit(close[i], i); pos = "FLAT"
            if sig != "FLAT" and np.isfinite(atr[i]) and atr[i] > 0:
                entry = close[i]; risk = SL_ATR * atr[i]
                sl = entry - risk if sig == "BUY" else entry + risk
                pos = sig; entry_i = i
    if not trades:
        return {"n": 0, "note": "no trades"}
    allR = np.array([x for x, _ in trades]); isR = [x for x, i_ in trades if i_]; ooR = [x for x, i_ in trades if not i_]
    exp_R = float(allR.mean()); sd = float(allR.std(ddof=1)) if len(allR) > 1 else 0.0
    sharpe = exp_R / sd if sd > 0 else 0.0
    bar = sd * (_c_n(N_TRIALS) + 1.65) / np.sqrt(len(allR)) if sd > 0 else None
    return {"n": len(allR), "exp_R": round(exp_R, 3), "sd_R": round(sd, 2),
            "sharpe": round(sharpe, 3), "t": round(sharpe * np.sqrt(len(allR)), 2),
            "sum_R": round(float(allR.sum()), 1), "bar": round(bar, 3) if bar else None,
            "believe": (bar is not None and exp_R > bar and len(allR) >= 100),
            "is_exp": round(float(np.mean(isR)), 3) if isR else None,
            "oos_exp": round(float(np.mean(ooR)), 3) if ooR else None,
            "bars": n, "years": round(n / 252, 1)}


def main():
    bmap = _broker_map()
    print(f"TSMOM-D1 pairs screen · {datetime.now(timezone.utc).isoformat()[:16]}Z · frozen L={LOOKBACKS} · "
          f"exit-on-flip · net 2×spread · N_trials={N_TRIALS} · c_N={_c_n(N_TRIALS):.2f}")
    print(f"deflated bar exp_R*(N={N_TRIALS}, n=250) ≈ {1.3*(_c_n(N_TRIALS)+1.65)/np.sqrt(250):.2f}R "
          f"(uses σ_R=1.3 ref; per-cell bar uses measured σ_R)\n")
    print(f"{'pair':8s} {'yrs':>4s} {'n':>4s} {'exp_R':>7s} {'σ_R':>5s} {'Sharpe':>7s} {'t':>5s} "
          f"{'bar':>6s} {'IS':>7s} {'OOS':>7s}  verdict")
    for p in PAIRS:
        d = backtest(p, bmap.get(p, p))
        if d["n"] == 0:
            print(f"{p:8s} {'—':>4s} {'0':>4s}  {d.get('note','')}"); continue
        v = "BELIEVE" if d["believe"] else ("underpowered" if d["n"] < 100 else "reject (< bar)")
        print(f"{p:8s} {d['years']:>4.1f} {d['n']:>4d} {d['exp_R']:>+7.3f} {d['sd_R']:>5.2f} "
              f"{d['sharpe']:>+7.3f} {d['t']:>5.2f} {str(d['bar']):>6s} "
              f"{str(d['is_exp']):>7s} {str(d['oos_exp']):>7s}  {v}")
    print("\nBELIEVE = exp_R > deflated bar AND n≥100 AND (check IS&OOS both + PBO next). t>2 ≈ naive-signif;")
    print("but the bar already folds in N-trial multiplicity. D1 trend-following → n is low by design.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
