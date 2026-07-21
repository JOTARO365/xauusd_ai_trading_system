#!/usr/bin/env python
"""strat_stats.py — statistical primitives สำหรับ strategy_search (numpy-only, reusable).

hurst, adf_tstat, variance_ratio_z (Lo-MacKinlay), perm_entropy (Bandt-Pompe), ou_fit, fracdiff, ema, vwap.
⚠️ estimator เหล่านี้มี noise (skill เตือน Hurst intraday ไม่เสถียร) — ใช้เป็น gate หนึ่ง ไม่ใช่ oracle.
"""
import numpy as np


def ema(x, n):
    a = 2.0 / (n + 1.0); out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def hurst(x):
    """H จาก structure-function: std(x[lag:]-x[:-lag]) ~ lag^H. H<0.5=mean-revert, >0.5=trend."""
    x = np.asarray(x, float); N = len(x)
    lags = np.arange(2, min(48, N // 3))
    if len(lags) < 4:
        return 0.5
    tau = [np.std(x[lag:] - x[:-lag]) for lag in lags]
    tau = np.maximum(tau, 1e-12)
    return float(np.polyfit(np.log(lags), np.log(tau), 1)[0])


def adf_tstat(x):
    """Dickey-Fuller t-stat (with constant): regress Δp on p_{t-1}. < −2.9 ≈ stationary (5%)."""
    x = np.asarray(x, float); dx = np.diff(x); xl = x[:-1]
    if len(dx) < 10 or np.std(xl) == 0:
        return 0.0
    X = np.column_stack([np.ones(len(xl)), xl])
    beta, *_ = np.linalg.lstsq(X, dx, rcond=None)
    resid = dx - X @ beta; dof = len(dx) - 2
    if dof <= 0:
        return 0.0
    s2 = (resid @ resid) / dof
    try:
        se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    except np.linalg.LinAlgError:
        return 0.0
    return float(beta[1] / se) if se > 0 else 0.0


def variance_ratio_z(ret, q):
    """Lo-MacKinlay heteroskedasticity-robust VR z-stat. z<−1.96 = negative autocorr (mean-revert)."""
    ret = np.asarray(ret, float); n = len(ret)
    if n < q * 4:
        return 0.0
    mu = ret.mean()
    var1 = np.sum((ret - mu) ** 2) / (n - 1)
    if var1 <= 0:
        return 0.0
    # q-period overlapping returns
    qsum = np.convolve(ret, np.ones(q), "valid")
    varq = np.sum((qsum - q * mu) ** 2) / (q * (n - q + 1) * (1 - q / n))
    vr = varq / var1
    # robust variance (heteroskedastic) ตาม LM
    phi = 0.0
    for j in range(1, q):
        dj = ret[j:] - mu
        d0 = ret[:n - j] - mu
        delta = np.sum(d0 ** 2 * dj ** 2) / (np.sum((ret - mu) ** 2)) ** 2 * n
        phi += (2.0 * (q - j) / q) ** 2 * delta
    if phi <= 0:
        return 0.0
    return float((vr - 1.0) / np.sqrt(phi))


def perm_entropy(x, m=4, tau=1):
    """Bandt-Pompe permutation entropy ∈ [0,1]. ต่ำ = dynamics มีโครงสร้าง/predictable."""
    x = np.asarray(x, float); N = len(x)
    if N < m * tau + 1:
        return 1.0
    from math import factorial, log
    perms = {}
    for i in range(N - (m - 1) * tau):
        pattern = tuple(np.argsort(x[i:i + m * tau:tau]))
        perms[pattern] = perms.get(pattern, 0) + 1
    total = sum(perms.values())
    p = np.array(list(perms.values()), float) / total
    H = -np.sum(p * np.log(p))
    return float(H / log(factorial(m)))


def ou_fit(logp):
    """fit AR(1) บน log-price. คืน (mu, half_life, sigma_eq, z_last) หรือ None ถ้า fit ไม่ได้."""
    logp = np.asarray(logp, float); x0 = logp[:-1]; x1 = logp[1:]
    if len(x0) < 20 or np.std(x0) == 0:
        return None
    b, a = np.polyfit(x0, x1, 1)          # x1 = b*x0 + a
    if b <= 0 or b >= 1:
        return None
    mu = a / (1 - b)
    half_life = -np.log(2) / np.log(b)
    resid = x1 - (b * x0 + a)
    sig_eq = np.std(resid) / np.sqrt(1 - b * b)
    if sig_eq <= 0:
        return None
    z = (logp[-1] - mu) / sig_eq
    return mu, float(half_life), float(sig_eq), float(z), float(b)


def fracdiff_weights(d, thresh=1e-4, max_k=200):
    """fixed-width fracdiff weights (López de Prado)."""
    w = [1.0]; k = 1
    while k < max_k:
        wk = -w[-1] * (d - k + 1) / k
        if abs(wk) < thresh:
            break
        w.append(wk); k += 1
    return np.array(w[::-1])


def fracdiff(series, d, thresh=1e-4):
    """apply fracdiff. คืน array align กับ series (NaN ช่วง warmup)."""
    w = fracdiff_weights(d, thresh); width = len(w)
    out = np.full(len(series), np.nan)
    for i in range(width - 1, len(series)):
        out[i] = np.dot(w, series[i - width + 1:i + 1])
    return out


def vwap(close, vol, n):
    """rolling VWAP (typical=close proxy). คืน array."""
    out = np.full(len(close), np.nan)
    pv = close * vol
    for i in range(n, len(close)):
        vs = vol[i - n:i].sum()
        out[i] = pv[i - n:i].sum() / vs if vs > 0 else close[i]
    return out
