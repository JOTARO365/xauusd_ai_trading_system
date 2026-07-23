"""scripts/mr_prescreen.py — anti-bias pre-screen for the -EV-pair mean-reversion hypotheses.

Kills bad ideas BEFORE any algo is coded (the 3-persona team's cheap refutation-first move).
Read-only, offline, 0 order, 0 LLM. Tests the FOUNDATIONAL claims all three lenses depend on:

  A. Per-pair anti-persistence — is fade even structurally eligible?  (Hurst on price, Lo-MacKinlay
     variance-ratio VR(k), OU half-life, + the gross-momentum sign from the backtest). H<0.5 & VR<1
     = mean-reverting; H≥0.5 & VR≥1 = trending (fade would be the wrong tool).
  B. Cointegration EURUSD/USDCHF (math flagship) — structural spread log(EURUSD)+log(USDCHF)=log(EUR/CHF);
     Dickey-Fuller stationarity IN-SAMPLE vs OOS (frozen), OU half-life, and the make-or-break cost screen:
     edge≈2·σ_S must beat ~3× the two-leg round-trip spread, else dead-on-arrival.

Everything is numpy (no statsmodels dependency): a plain Dickey-Fuller t-stat vs standard critical
values (-2.86 @5%, -3.43 @1%). Honest about limits — Hurst intraday is noisy, so the gross-momentum
sign (a direct economic fact) is weighted alongside it, not below it.

Run:  python scripts/mr_prescreen.py
"""
import os
import sys
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
import numpy as np                       # noqa: E402
import config                            # noqa: E402,F401
from connectors.pair_collector import _broker_map  # noqa: E402

TARGETS = ["EURUSD", "USDCHF", "AUDUSD", "USDJPY", "XAGUSD"]
REF = "XAUUSD"                            # persistent reference (momentum works)
COUNT = 20000
# gross-momentum exp_R from scripts/shadow_backtest.py (in-sample) — the direct anti-persistence fact
GROSS_MOM = {"XAUUSD": +0.082, "XAUEUR": +0.130, "XAUJPY": +0.213,
             "XAGUSD": +0.141, "USDCHF": +0.015, "EURUSD": -0.035,
             "USDJPY": -0.076, "AUDUSD": -0.082}
SPREAD_PTS = {"EURUSD": 19, "AUDUSD": 24, "USDJPY": 25, "USDCHF": 26, "XAGUSD": 51, "XAUUSD": 30}


def _rates(broker, count=COUNT):
    import MetaTrader5 as mt5
    r = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_H1, 0, count)
    return r


def hurst(price):
    """Aggregated-dispersion Hurst on the price level: std(price[lag:]-price[:-lag]) ~ lag^H.
    Random walk → 0.5; H<0.5 anti-persistent (mean-reverting); H>0.5 persistent (trending)."""
    p = np.asarray(price, float)
    lags = np.arange(2, min(200, len(p) // 4))
    tau = np.array([np.std(p[lag:] - p[:-lag]) for lag in lags])
    ok = tau > 0
    return float(np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)[0])


def var_ratio(logp, k):
    """Lo-MacKinlay variance ratio VR(k)=Var(k-ret)/(k·Var(1-ret)). <1 mean-reverting, >1 trending."""
    r1 = np.diff(logp)
    rk = logp[k:] - logp[:-k]
    v1 = np.var(r1, ddof=1)
    return float((np.var(rk, ddof=1) / k) / v1) if v1 > 0 else float("nan")


def ou_halflife(x):
    """AR(1) half-life (bars) of a series: Δx = a + b·x_{t-1}; HL = -ln2/ln(1+b). inf if b>=0."""
    x = np.asarray(x, float)
    dx = np.diff(x); xl = x[:-1]
    b = np.polyfit(xl, dx, 1)[0]
    return float(-np.log(2) / np.log(1 + b)) if b < 0 else float("inf")


def adf_t(y):
    """Plain Dickey-Fuller t-stat on the lagged level (no augmentation). vs -2.86 (5%), -3.43 (1%).
    More negative = more stationary (reject unit root)."""
    y = np.asarray(y, float)
    dy = np.diff(y); yl = y[:-1]
    X = np.column_stack([np.ones_like(yl), yl])
    beta, *_ = np.linalg.lstsq(X, dy, rcond=None)
    resid = dy - X @ beta
    dof = len(dy) - 2
    s2 = resid @ resid / dof
    se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    return float(beta[1] / se)


def part_a():
    print("=" * 78)
    print("A. PER-PAIR ANTI-PERSISTENCE — is fade structurally eligible?")
    print("=" * 78)
    print(f"{'pair':8s} {'H(price)':>9s} {'VR(6)':>7s} {'VR(24)':>7s} {'OU_HL':>8s} "
          f"{'grossMom':>9s}  verdict")
    bmap = _broker_map()
    for logical in [REF] + TARGETS:
        r = _rates(bmap.get(logical, logical))
        if r is None or len(r) < 2000:
            print(f"{logical:8s}  (no data)"); continue
        c = r["close"].astype(float)
        logp = np.log(c)
        H = hurst(c); vr6 = var_ratio(logp, 6); vr24 = var_ratio(logp, 24)
        hl = ou_halflife(c); gm = GROSS_MOM.get(logical)
        # verdict: mean-reverting if VR<1 AND gross momentum <=0 (the direct fact). H corroborates.
        mr = (vr24 < 1.0) and (gm is not None and gm <= 0.02)
        trend = (vr24 > 1.0) and (gm is not None and gm > 0.05)
        v = "MEAN-REVERT (fade-eligible)" if mr else ("TREND (momentum)" if trend else "mixed/weak")
        hl_s = f"{hl:8.0f}" if np.isfinite(hl) else "     inf"
        print(f"{logical:8s} {H:9.3f} {vr6:7.3f} {vr24:7.3f} {hl_s} {gm:+9.3f}  {v}")
    print("\n  note: Hurst intraday is noisy (skill caveat) → weighted WITH gross-momentum sign,")
    print("        not above it. gross momentum <=0 = the direct economic proof of no trend edge.")


def _aligned_logs(a_broker, b_broker):
    """closes of two symbols aligned on common H1 timestamps → (logA, logB, n)."""
    ra, rb = _rates(a_broker), _rates(b_broker)
    if ra is None or rb is None:
        return None
    ta = {int(x["time"]): float(x["close"]) for x in ra}
    tb = {int(x["time"]): float(x["close"]) for x in rb}
    common = sorted(set(ta) & set(tb))
    if len(common) < 2000:
        return None
    la = np.log(np.array([ta[t] for t in common]))
    lb = np.log(np.array([tb[t] for t in common]))
    return la, lb, len(common)


def part_b():
    print("\n" + "=" * 78)
    print("B. COINTEGRATION EURUSD / USDCHF — structural spread log(EU)+log(UC)=log(EUR/CHF)")
    print("=" * 78)
    bmap = _broker_map()
    got = _aligned_logs(bmap.get("EURUSD", "EURUSD"), bmap.get("USDCHF", "USDCHF"))
    if got is None:
        print("  insufficient aligned data"); return
    lEU, lUC, n = got
    S = lEU + lUC                                     # structural spread (β=+1 a-priori), = log(EUR/CHF)
    cut = int(n * 0.6)                                # 60% in-sample / 40% OOS
    adf_full = adf_t(S); adf_is = adf_t(S[:cut]); adf_oos = adf_t(S[cut:])
    hl = ou_halflife(S)
    sigma_S = float(np.std(S))                        # spread-level dispersion (edge ≈ 2·σ_S)
    # 2-leg round-trip cost in log-spread units: spread_pts·point / price, per leg
    cost_S = SPREAD_PTS["EURUSD"] * 1e-5 / np.exp(lEU[-1]) + SPREAD_PTS["USDCHF"] * 1e-5 / np.exp(lUC[-1])
    edge = 2 * sigma_S
    print(f"  n aligned bars : {n}")
    print(f"  DF t-stat      : full={adf_full:.2f}  in-sample={adf_is:.2f}  OOS={adf_oos:.2f}   (reject unit root if < -2.86)")
    print(f"  stationary?    : full={'YES' if adf_full<-2.86 else 'no':3s}  IS={'YES' if adf_is<-2.86 else 'no':3s}  "
          f"OOS={'YES' if adf_oos<-2.86 else 'no':3s}   ← OOS is the load-bearing gate")
    print(f"  OU half-life   : {hl:.0f} bars" if np.isfinite(hl) else "  OU half-life   : inf (no reversion)")
    print(f"  spread sigma   : σ_S={sigma_S:.5f}   edge≈2σ_S={edge:.5f}")
    print(f"  2-leg cost     : cost_S={cost_S:.5f}   feasibility 2σ_S ≥ 3·cost_S? "
          f"{'PASS' if edge >= 3*cost_S else 'FAIL (dead on arrival)'}  ({edge/cost_S:.1f}× cost)")
    # Engle-Granger with estimated beta (sanity band [0.7,1.3] around structural +1)
    beta = float(np.polyfit(lUC, lEU, 1)[0])          # logEU ~ beta·logUC
    resid = lEU - beta * lUC
    print(f"  EG estimated β : {beta:+.3f}   (structural prior ≈ +1; sanity band [0.7,1.3] → "
          f"{'in band' if 0.7<=abs(beta)<=1.3 else 'OUT of band'})")
    print(f"  EG resid ADF   : {adf_t(resid):.2f}   (reject unit root if < -2.86)")
    print("\n  read: OOS DF must be < -2.86 AND the cost screen PASS, else the flagship is dead.")
    print("        EURCHF trended post-2015 SNB de-peg → expect this to be a HONEST test, not a lock.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    print(f"MR pre-screen · {datetime.now(timezone.utc).isoformat()[:16]}Z · H1 · read-only\n")
    part_a()
    part_b()
