"""scripts/wti_range_screen.py — Phase 2: is WTI a tradeable mean-reverter (fade), net of its tiny spread?

WTI momentum was net-negative (oil ranges + spikes, not a clean trender). But WTI's spread is only ~3pt
— the cost that killed fade on FX (19-26pt) / silver (51pt) barely bites here — so a mean-reversion fade
has a fighting chance it didn't elsewhere. Test honestly:

  A. Diagnostic (free): Hurst / variance-ratio / OU half-life per TF (H1/H4/D1) — is it mean-reverting?
  B. Rolling-z fade: window W, |z|>=k fade to the mean, SL beyond the band, time-stop; net of 3pt spread;
     non-overlapping; IS/OOS split; deflated bar; shuffle control (edge must vanish when z-times permuted).

Params fixed a-priori (W=20, k=1.5, k_stop=2.5, hold=24) => small N. Read-only, 0 order.
python scripts/wti_range_screen.py
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

WTI = "WTIUSD"; SPREAD = 3
W, K, K_STOP, MAX_HOLD = 20, 1.5, 2.5, 24
N_TRIALS = 10; _Z = NormalDist()


def _c_n(N):
    g = 0.5772156649
    return (1 - g) * _Z.inv_cdf(1 - 1.0 / N) + g * _Z.inv_cdf(1 - 1.0 / (N * float(np.e)))


def _hurst(p):
    p = np.asarray(p, float); lags = np.arange(2, min(120, len(p) // 4))
    tau = np.array([np.std(p[l:] - p[:-l]) for l in lags]); ok = tau > 0
    return float(np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)[0])


def _vr(logp, k):
    r1 = np.diff(logp); rk = logp[k:] - logp[:-k]; v1 = np.var(r1, ddof=1)
    return float((np.var(rk, ddof=1) / k) / v1) if v1 > 0 else float("nan")


def _hl(x):
    x = np.asarray(x, float); dx = np.diff(x); xl = x[:-1]
    b = np.polyfit(xl, dx, 1)[0]
    return float(-np.log(2) / np.log(1 + b)) if b < 0 else float("inf")


def _rates(broker, tf, count=20000):
    import MetaTrader5 as mt5
    return mt5.copy_rates_from_pos(broker, tf, 0, count)


def diagnostic(broker):
    import MetaTrader5 as mt5
    print("A. anti-persistence per TF (H<0.5 & VR<1 = mean-reverting):")
    for name, tf in (("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4), ("D1", mt5.TIMEFRAME_D1)):
        r = _rates(broker, tf)
        if r is None or len(r) < 600:
            print(f"   {name}: no data"); continue
        c = r["close"].astype(float); lp = np.log(c)
        print(f"   {name}: H={_hurst(c):.3f}  VR6={_vr(lp,6):.3f}  VR24={_vr(lp,24):.3f}  "
              f"OU_HL={_hl(c):.0f}  bars={len(c)}")


def fade(broker, tf, tfname, rng=None):
    import MetaTrader5 as mt5
    r = _rates(broker, tf)
    if r is None or len(r) < 600:
        return {"n": 0, "note": "no data"}
    info = mt5.symbol_info(broker); point = float(info.point)
    high = r["high"].astype(float); low = r["low"].astype(float); close = r["close"].astype(float)
    cost_px = SPREAD * point
    n = len(close); cut = int(n * 0.6)
    # rolling mean/std
    trades = []; flat = -1
    zsign = None
    if rng is not None:                                  # shuffle control: permute the entry days
        order = np.arange(W, n - MAX_HOLD - 1); rng.shuffle(order)
    else:
        order = range(W, n - MAX_HOLD - 1)
    for i in order:
        if i <= flat:
            continue
        w = close[i - W:i]
        m = float(w.mean()); sd = float(w.std())
        if sd <= 0:
            continue
        z = (close[i] - m) / sd
        d = "BUY" if z <= -K else ("SELL" if z >= K else None)
        if d is None:
            continue
        entry = float(close[i]); tp = m
        sl = m - K_STOP * sd if d == "BUY" else m + K_STOP * sd
        risk = abs(entry - sl); tp_dist = abs(tp - entry)
        if risk <= 0 or tp_dist < 3 * cost_px:            # reward-to-spread gate
            continue
        sign = 1 if d == "BUY" else -1
        res = None
        for j in range(i + 1, min(i + 1 + MAX_HOLD, n)):
            hi, lo = float(high[j]), float(low[j])
            hit_sl = lo <= sl if d == "BUY" else hi >= sl
            hit_tp = hi >= tp if d == "BUY" else lo <= tp
            if hit_sl and hit_tp:
                res = (-1.0, j); break                    # SL-first
            if hit_sl:
                res = (-1.0, j); break
            if hit_tp:
                res = (sign * (tp - entry) / risk, j); break
        if res is None:                                   # time-stop mark-to-market
            j = min(i + MAX_HOLD, n - 1); res = (sign * (close[j] - entry) / risk, j)
        r_net = res[0] - cost_px / risk
        trades.append((r_net, i < cut)); flat = res[1]
    if not trades:
        return {"n": 0}
    allR = np.array([x for x, _ in trades]); isR = [x for x, i_ in trades if i_]; ooR = [x for x, i_ in trades if not i_]
    sd = float(allR.std(ddof=1)) if len(allR) > 1 else 0.0
    exp = float(allR.mean()); bar = sd * (_c_n(N_TRIALS) + 1.65) / np.sqrt(len(allR)) if sd > 0 else None
    return {"n": len(allR), "exp_R": round(exp, 3), "sd": round(sd, 2),
            "t": round(exp / sd * np.sqrt(len(allR)), 2) if sd > 0 else 0, "bar": round(bar, 3) if bar else None,
            "is": round(float(np.mean(isR)), 3) if isR else None,
            "oos": round(float(np.mean(ooR)), 3) if ooR else None}


def main():
    import MetaTrader5 as mt5
    broker = _broker_map().get(WTI, "OILCash#")
    print(f"WTI range/fade screen · {datetime.now(timezone.utc).isoformat()[:16]}Z · {broker} · "
          f"W={W} k={K} · net {SPREAD}pt · bar t~{_c_n(N_TRIALS)+1.65:.2f}\n")
    diagnostic(broker)
    print("\nB. rolling-z fade (net 3pt, non-overlapping, IS/OOS):")
    for name, tf in (("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4)):
        d = fade(broker, tf, name)
        if d["n"] == 0:
            print(f"   {name:3s} no trades"); continue
        v = "BELIEVE" if (d["bar"] and d["exp_R"] > d["bar"] and d["oos"] and d["oos"] > 0 and d["n"] >= 100) \
            else ("OOS<=0" if (d["oos"] is not None and d["oos"] <= 0) else "reject")
        print(f"   {name:3s} n={d['n']:<4d} exp_R={d['exp_R']:+.3f} sd={d['sd']} t={d['t']:+.2f} "
              f"bar={d['bar']} IS={d['is']} OOS={d['oos']}  {v}")
    sh = fade(broker, mt5.TIMEFRAME_H1, "H1", rng=np.random.default_rng(11))
    if sh.get("n"):
        print(f"   shuffle(ctrl) n={sh['n']:<4d} exp_R={sh['exp_R']:+.3f} t={sh['t']:+.2f}  (ควร ~0)")
    print("\nBELIEVE = exp_R > deflated bar AND OOS>0 AND n>=100.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    main()
