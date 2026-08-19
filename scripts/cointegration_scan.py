"""scripts/cointegration_scan.py — cointegration scanner ทุกคู่ (user 08-09, จาก SAT ch10 CADF).

หา alpha stat-arb: คู่ไหน "cointegrated จริง" (spread mean-reverts) = เทรด pairs ได้. คู่ไหนไม่ = อย่าแตะ.
เทคนิคจาก Successful Algorithmic Trading (Halls-Moore) ch10/ch15 — แต่ implement numpy ล้วน (ไม่พึ่ง statsmodels):
  - hedge ratio β = OLS (causal rolling ใน executor; full-sample ที่นี่ = คัด candidate)
  - spread = A − β·B → ADF test (stationary?) → t-stat vs critical value
  - Hurst exponent (<0.5 = mean-reverting)
  - half-life ของ mean-reversion (OU: Δs=λ·s_lag → HL=−ln2/λ)
  - split-half robustness: cointegrated ทั้งครึ่งแรก+ครึ่งหลัง? (กัน lookahead/regime-luck)

ตัดสิน tradeable ⇔ ADF ต่ำกว่า 5% crit AND Hurst<0.5 AND half-life สมเหตุผล (5-500 bar) AND split-half ทั้งคู่ผ่าน.
read-only (ไม่แตะ live). 0 token. standalone: python scripts/cointegration_scan.py [--tf H1|D1]
"""
import itertools
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

try:                                     # universe เต็ม (รวมคู่ที่เก็บ data แต่ไม่ได้ live) — user 08-09
    from agents import algo_registry as _reg
    SYMBOLS = list(_reg.UNIVERSE)
except Exception:
    SYMBOLS = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "AUDUSD", "EURUSD",
               "GBPUSD", "USDCHF", "USDJPY", "BTCUSD", "WTIUSD"]
# ADF critical values (constant, no trend, large-n; MacKinnon approx)
ADF_CRIT = {"1%": -3.43, "5%": -2.86, "10%": -2.57}
HL_MIN, HL_MAX = 5, 500          # half-life สมเหตุผล (bar): เร็วพอเทรด, ไม่ช้าจนไม่กลับ


def _ols_beta(y, x):
    """β,α ของ y = α + β x (OLS, causal เมื่อใช้ window ปัจจุบัน)."""
    A = np.vstack([x, np.ones_like(x)]).T
    beta, alpha = np.linalg.lstsq(A, y, rcond=None)[0]
    return beta, alpha


def _adf_tstat(y, maxlag=1):
    """ADF t-stat (constant, no trend). Δy_t = α + γ·y_{t-1} + Σδ·Δy_{t-i} + ε; t = γ/se(γ).
    ยิ่งลบมาก = ยิ่ง stationary. numpy ล้วน."""
    y = np.asarray(y, float)
    dy = np.diff(y)
    n = len(dy)
    if n <= maxlag + 5:
        return 0.0
    lag = maxlag
    Y = dy[lag:]                              # target Δy_t
    cols = [y[lag:-1]]                        # y_{t-1} (level, lagged)
    for i in range(1, lag + 1):
        cols.append(dy[lag - i:-i])          # Δy_{t-i}
    cols.append(np.ones(len(Y)))             # const
    X = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ coef
    dof = len(Y) - X.shape[1]
    if dof <= 0:
        return 0.0
    s2 = (resid @ resid) / dof
    xtx_inv = np.linalg.pinv(X.T @ X)
    se_gamma = np.sqrt(s2 * xtx_inv[0, 0])
    return float(coef[0] / se_gamma) if se_gamma > 0 else 0.0


def _hurst(ts, max_lag=40):
    """Hurst exponent: variance ของ lagged diff scale ตาม lag^(2H). <0.5 mean-revert."""
    ts = np.asarray(ts, float)
    lags = range(2, min(max_lag, len(ts) // 2))
    tau = [np.sqrt(np.std(ts[lag:] - ts[:-lag])) for lag in lags]
    if len(tau) < 2 or any(t <= 0 for t in tau):
        return 0.5
    poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
    return float(poly[0] * 2.0)


def _half_life(spread):
    """OU half-life (bar): Δs_t = λ·s_{t-1} + c → HL = −ln2/λ (λ<0)."""
    s = np.asarray(spread, float)
    ds = np.diff(s)
    slag = s[:-1]
    beta, _ = _ols_beta(ds, slag)
    return float(-np.log(2) / beta) if beta < 0 else np.inf


def _aligned(mt5, a, b, count, tf):
    ra = mt5.copy_rates_from_pos(a, tf, 0, count)
    rb = mt5.copy_rates_from_pos(b, tf, 0, count)
    if ra is None or rb is None:
        return None, None
    mb = {int(t): float(c) for t, c in zip(rb["time"], rb["close"])}
    xa = []; xb = []
    for t, c in zip(ra["time"], ra["close"]):
        if int(t) in mb:
            xa.append(float(c)); xb.append(mb[int(t)])
    if len(xa) < 200:
        return None, None
    return np.array(xa), np.array(xb)


def _test_pair(y, x):
    """คืน dict: β, ADF t, Hurst, half-life, split-half ADF, tradeable?"""
    beta, _ = _ols_beta(y, x)
    spread = y - beta * x
    adf = _adf_tstat(spread)
    hurst = _hurst(spread)
    hl = _half_life(spread)
    corr = float(np.corrcoef(np.diff(np.log(y)), np.diff(np.log(x)))[0, 1])
    # split-half robustness (คนละ β ต่อครึ่ง — กัน regime-luck)
    h = len(y) // 2
    b1, _ = _ols_beta(y[:h], x[:h]); adf1 = _adf_tstat(y[:h] - b1 * x[:h])
    b2, _ = _ols_beta(y[h:], x[h:]); adf2 = _adf_tstat(y[h:] - b2 * x[h:])
    crit = ADF_CRIT["5%"]
    tradeable = (adf < crit and hurst < 0.5 and HL_MIN <= hl <= HL_MAX
                 and adf1 < crit and adf2 < crit)
    return {"beta": beta, "adf": adf, "hurst": hurst, "hl": hl, "corr": corr,
            "adf_h1": adf1, "adf_h2": adf2, "tradeable": tradeable}


def run(tf_name="H1", count=8000, manage_mt5=True):
    """manage_mt5=False → ไม่ init/shutdown (เรียกจาก dashboard ที่มี MT5 อยู่แล้ว + ถือ lock; กัน shutdown connection ร่วม)."""
    import MetaTrader5 as mt5
    from connectors.pair_collector import _broker_map
    if manage_mt5 and not mt5.initialize():
        print("MT5 init fail"); return
    bm = _broker_map() or {}
    tf = mt5.TIMEFRAME_H1 if tf_name == "H1" else mt5.TIMEFRAME_D1
    print("=" * 92)
    print("COINTEGRATION SCAN · %s · ทุกคู่ · SAT ch10 CADF (numpy) · ADF 5%%crit=%.2f · Hurst<0.5 · HL %d-%d"
          % (tf_name, ADF_CRIT["5%"], HL_MIN, HL_MAX))
    print("=" * 92)
    print("%-16s %6s %8s %7s %9s %7s %7s %7s  %s" % (
        "pair", "β", "ADF t", "Hurst", "half-life", "corr", "ADF½1", "ADF½2", "tradeable"))
    rows = []
    for a_lg, b_lg in itertools.combinations(SYMBOLS, 2):
        a = bm.get(a_lg, a_lg); b = bm.get(b_lg, b_lg)
        mt5.symbol_select(a, True); mt5.symbol_select(b, True)
        y, x = _aligned(mt5, a, b, count, tf)
        if y is None:
            print("%-16s  (data ไม่พอ/ไม่ align)" % f"{a_lg}-{b_lg}")
            continue
        y, x = np.log(y), np.log(x)          # log-price: scale-invariant (กัน artifact สเกลราคา เช่น XAUJPY)
        r = _test_pair(y, x)
        r["pair"] = f"{a_lg}-{b_lg}"
        rows.append(r)
        hl = "%.0f" % r["hl"] if np.isfinite(r["hl"]) else "inf"
        print("%-16s %6.1f %8.2f %7.2f %9s %7.2f %7.2f %7.2f  %s" % (
            r["pair"], r["beta"], r["adf"], r["hurst"], hl, r["corr"],
            r["adf_h1"], r["adf_h2"], "✅ YES" if r["tradeable"] else "—"))
    if manage_mt5:
        mt5.shutdown()                                    # ปิดเฉพาะ standalone; dashboard คุม connection เอง
    try:                                                  # persist ผลล่าสุด (dashboard อ่านไฟล์นี้)
        import json as _json
        import math as _math
        def _clean(v):                                    # NaN/inf → None: browser JSON.parse reject NaN → fetch พัง "ต่อไม่ได้"
            return None if (isinstance(v, float) and (_math.isnan(v) or _math.isinf(v))) else v
        _rows = [{k: _clean(v) for k, v in r.items()} for r in rows]
        _out = os.path.join(_ROOT, "data", "cointegration.json")
        with open(_out, "w", encoding="utf-8") as _f:
            _json.dump({"rows": _rows, "tf": tf_name, "n": len(_rows)}, _f, ensure_ascii=False, allow_nan=False)
    except Exception:
        pass
    print("=" * 92)
    good = [r for r in rows if r["tradeable"]]
    n_tested = len(rows)
    exp_fp = round(n_tested * 0.05, 1)       # multiple-testing: จำนวน false-positive คาดหวังที่ 5%
    print("multiple-testing: เทส %d คู่ → คาด false-positive ~%.1f คู่ ที่ 5%% โดยบังเอิญ" % (n_tested, exp_fp))
    if good:
        print("คู่ที่ cointegrated จริง (stat-arb ได้):")
        for r in sorted(good, key=lambda z: z["adf"]):
            print("  %-16s ADF %.2f · Hurst %.2f · half-life %.0f bar · β %.1f" % (
                r["pair"], r["adf"], r["hurst"], r["hl"], r["beta"]))
    else:
        print("⚠️ ไม่มีคู่ไหน cointegrated ผ่านเกณฑ์ (ADF<5% + Hurst<0.5 + half-life ok + split-half) → stat-arb ไม่มี edge จริง")
    print("\nตีความ: tradeable = spread กลับ mean จริง (ทั้ง 2 ครึ่ง) → pairs +EV. ไม่ผ่าน = อย่าเทรด pairs คู่นั้น.")
    return rows


if __name__ == "__main__":
    tfn = "H1"
    if "--tf" in sys.argv:
        tfn = sys.argv[sys.argv.index("--tf") + 1]
    run(tf_name=tfn)
