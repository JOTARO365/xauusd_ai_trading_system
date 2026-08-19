#!/usr/bin/env python
"""scripts/fairvalue_reversion_backtest.py — Candidate #1: XAU macro fair-value reversion.

ไอเดีย (จาก UHAS "เส้นมูลค่ายุติธรรม / ถูกกว่ามูลค่าจริง $X"): ทองมี "มูลค่ายุติธรรม" ที่อธิบายได้ด้วย
macro drivers (DXY, silver). เมื่อราคาหลุดต่ำกว่าโมเดล ≥ Nσ = "ถูก" → long, ถือจนกลับเข้าโมเดล.
เป็น outright long-only (ไม่ใช่ 2-leg hedged แบบ xau_xag_pairs) → เข้ากับ LONG_ONLY_ALL, computed ไม่ predict.

Quant discipline (เหมือน sr_fade/pairs_rigorous):
  causal (rolling OLS window trailing เท่านั้น, resolve จากแท่งถัดไป), z-stop, cost หัก (R-norm),
  non-overlap, OOS 70/30, t-stat, MIN_N=100. + cointegration diagnostics (ADF/Hurst/half-life/split-half)
  ว่า residual mean-revert จริงไหม (ไม่งั้น = spurious trend proxy). variants = multiple-testing (ต้อง deflate).

⚠️ short side พิมพ์ไว้เทียบเฉยๆ — ปัจจุบัน LONG_ONLY_ALL บล็อก SELL ทุกคู่.
read-only · offline (อ่าน data/*.json ไม่แตะ MT5/live) · 0 token.
รัน: python scripts/fairvalue_reversion_backtest.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
from cointegration_scan import _adf_tstat, _half_life, _hurst   # noqa: E402

DATA = os.path.join(_ROOT, "data")
MIN_N = 100
DAY = 86400


def _load(fn):
    with open(os.path.join(DATA, fn), "r", encoding="utf-8") as f:
        return json.load(f)


def _daily_close(rows):
    """{date_bucket: close} — bucket = epoch//86400 (กัน session-close ต่างเวลาเล็กน้อย)."""
    out = {}
    for r in rows:
        out[int(r[0]) // DAY] = float(r[4])
    return out


def _daily_hlc(rows):
    """{bucket: (high,low,close)} สำหรับ ATR ของ XAU."""
    out = {}
    for r in rows:
        out[int(r[0]) // DAY] = (float(r[2]), float(r[3]), float(r[4]))
    return out


def _atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.concatenate([[h[0] - l[0]], tr])
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        out[n - 1] = tr[:n].mean()
        for i in range(n, len(c)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _align(driver_files):
    """คืน (dates, xau_close, xau_h, xau_l, {name: driver_close}) เรียงตามวันที่ที่มีครบทุก series."""
    xau = _daily_hlc(_load("xau_d1.json"))
    drv = {name: _daily_close(_load(fn)) for name, fn in driver_files.items()}
    common = set(xau.keys())
    for d in drv.values():
        common &= set(d.keys())
    dates = sorted(common)
    xh = np.array([xau[d][0] for d in dates], float)
    xl = np.array([xau[d][1] for d in dates], float)
    xc = np.array([xau[d][2] for d in dates], float)
    dv = {name: np.array([drv[name][d] for d in dates], float) for name in drv}
    return dates, xc, xh, xl, dv


def _fit_resid_full(y, feats):
    """full-sample OLS residual (diagnostic เท่านั้น — มี lookahead จงใจ, ใช้เทส stationarity)."""
    X = np.column_stack([feats[k] for k in feats] + [np.ones_like(y)])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ coef


def _diag(y, feats, label):
    resid = _fit_resid_full(y, feats)
    adf = _adf_tstat(resid); hurst = _hurst(resid); hl = _half_life(resid)
    h = len(resid) // 2
    a1 = _adf_tstat(_fit_resid_full(y[:h], {k: v[:h] for k, v in feats.items()}))
    a2 = _adf_tstat(_fit_resid_full(y[h:], {k: v[h:] for k, v in feats.items()}))
    crit = -2.86  # ADF 5% crit (constant)
    ok = adf < crit and hurst < 0.5 and 5 <= hl <= 500 and a1 < crit and a2 < crit
    hl_s = f"{hl:6.1f}" if np.isfinite(hl) else "  inf "
    print(f"  {label:18s} ADF {adf:+6.2f}  Hurst {hurst:.2f}  HL {hl_s}  "
          f"ADF½ {a1:+5.2f}/{a2:+5.2f}  coint={'YES' if ok else '—'}  (crit5% {crit})")
    return ok


def backtest(y, xh, xl, feats, atr, win=252, z_in=2.0, z_out=0.5, z_stop=3.5,
             side="long", cost=0.30, max_hold=60):
    """rolling multi-OLS (causal). z<-z_in→long(ทองถูก), z>+z_in→short. resolve บน close รายวัน.
    R = pos*(exit-entry) หัก cost หารด้วย SL_dist=(z_stop-z_in)*resid_sd (price units)."""
    names = list(feats)
    F = np.column_stack([feats[k] for k in names])
    n = len(y); trades = []; i = win
    while i < n - 1:
        yw = y[i - win:i]; Xw = np.column_stack([F[i - win:i], np.ones(win)])
        coef, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
        resid_w = yw - Xw @ coef
        sd = resid_w.std()
        if sd <= 0:
            i += 1; continue
        hat_i = np.dot(np.concatenate([F[i], [1.0]]), coef)
        z = (y[i] - hat_i) / sd
        want = (z < -z_in and side in ("long", "both")) or (z > z_in and side in ("short", "both"))
        if not want:
            i += 1; continue
        sign = 1 if z < 0 else -1
        sl_dist = (z_stop - z_in) * sd
        if sl_dist <= 0:
            i += 1; continue
        entry = y[i]; r_out = None; exit_i = min(i + max_hold, n - 1)
        for j in range(i + 1, min(i + max_hold, n - 1) + 1):
            # recompute z at j ด้วย coef เดิม (โมเดล ณ เวลาเข้า) — causal, ไม่ refit อนาคต
            zj = (y[j] - np.dot(np.concatenate([F[j], [1.0]]), coef)) / sd
            hit_stop = (zj <= -z_stop) if sign > 0 else (zj >= z_stop)
            hit_exit = (zj >= -z_out) if sign > 0 else (zj <= z_out)
            if hit_stop or hit_exit:
                exit_i = j; break
        pnl = sign * (y[exit_i] - entry) - cost
        trades.append(pnl / sl_dist)
        i = exit_i + 1
    return trades


def _stats(tr):
    n = len(tr)
    if n == 0:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t, round(float(a.sum()), 1)


def _report(label, tr):
    s = _stats(tr)
    if not s:
        print(f"  {label:30s} n=0"); return
    n, wr, ex, t, sm = s
    k = int(n * 0.7); oos = _stats(tr[k:]); oe = oos[2] if oos else float("nan")
    flag = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oe > 0) else "—"
    print(f"  {label:30s} n={n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} sumR{sm:+7.1f} OOS{oe:+.4f} [{flag}]")


def main():
    print("\n=== FAIR-VALUE REVERSION backtest (XAU D1 · rolling multi-OLS · causal · z-stop · "
          "cost-adj · OOS70/30 · MIN_N=100) ===")
    print("gate PASS = n≥100 + exp_R>0 + t>2 + OOS exp_R>0 · long-only (SELL บล็อกโดย LONG_ONLY_ALL)\n")

    driversets = {
        "DXY+XAG": {"DXY": "drv_dxy_h1.json", "XAG": "drv_xag_h1.json"},
        "XAG only": {"XAG": "drv_xag_h1.json"},
        "DXY only": {"DXY": "drv_dxy_h1.json"},
    }

    print("── COINTEGRATION DIAGNOSTIC (residual mean-revert จริงไหม — กัน spurious trend proxy) ──")
    diag_ok = {}
    for name, files in driversets.items():
        dates, xc, xh, xl, dv = _align(files)
        diag_ok[name] = _diag(xc, dv, name)
    print(f"  (n_days aligned ~{len(dates)} · ถ้า coint=— → reversion edge น่าจะปลอม/เปราะ)\n")

    print("── BACKTEST (long-only · variants = multiple-testing, ต้อง deflate) ──")
    for name, files in driversets.items():
        dates, xc, xh, xl, dv = _align(files)
        atr = _atr(xh, xl, xc)
        print(f"\n  drivers={name}  (n_days={len(xc)}, {'coint OK' if diag_ok[name] else 'NOT coint ⚠️'})")
        for win in (252, 504):
            for z_in in (1.5, 2.0, 2.5):
                lbl = f"w{win} z{z_in} long"
                _report(lbl, backtest(xc, xh, xl, dv, atr, win=win, z_in=z_in, side="long"))
        # cost sensitivity ×2 (baseline variant)
        _report("w252 z2.0 long cost×2",
                backtest(xc, xh, xl, dv, atr, win=252, z_in=2.0, side="long", cost=0.60))
    print("\n⚠️ variants เยอะ = multiple-testing. เชื่อเฉพาะตัวที่ coint=YES + PASS + ทน cost×2 + OOS>0.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
