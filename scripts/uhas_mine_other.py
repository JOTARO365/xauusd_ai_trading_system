#!/usr/bin/env python
"""scripts/uhas_mine_other.py — port UHAS idea (#1 fair-value reversion + #2 zone-reaction) ไป symbol อื่น.

ทองไม่มี edge (fair-value ไม่ coint · zone-buy ติดลบ). เทสว่า idea เดียวกันมี edge บน symbol ที่ mean-revert
มากกว่าไหม: silver (offline), WTI (autocorr −0.008 = mean-revert, memory), BTC.
  - silver: reversion driver=XAU (gold/silver ratio) + zone-reaction
  - WTI   : reversion driver=DXY + self mean-revert (close-only → zone ไม่ได้)
  - BTC   : reversion self + zone-reaction (OHLCV เต็ม)

quant เดียวกับ #1/#2: causal · rolling OLS residual z-fade · z-stop · cost · non-overlap · OOS70/30 ·
cointegration diag · MIN_N=100 · t>2. long+short พิมพ์เทียบ (⚠️ live LONG_ONLY_ALL บล็อก short).
offline: silver=data/, WTI/BTC=scratchpad cache (ดึงผ่าน AlphaVantage MCP ไม่แตะ MT5/live). 0-token backtest.
รัน: python scripts/uhas_mine_other.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
from cointegration_scan import _adf_tstat, _half_life, _hurst          # noqa: E402
from zone_reaction_backtest import run as zone_run, _report as zone_report  # noqa: E402

DATA = os.path.join(_ROOT, "data")
SCRATCH = os.environ.get("CLAUDE_SCRATCH") or os.path.join(
    os.path.dirname(_ROOT), "_scratch")
# fallback หา cache จาก path ที่ convert ไว้
_CACHE = r"C:\Users\PORNNA~1\AppData\Local\Temp\claude\D--claude-workspace-xauusd-ai-trading-system\8753aacd-c36b-49f7-88e5-e6a3c9fac75f\scratchpad"
MIN_N = 100
DAY = 86400
ADF_CRIT = -2.86


def _rows(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _daily(rows, idx=4):
    return {int(r[0]) // DAY: float(r[idx]) for r in rows}


def _align(target_rows, driver_paths):
    """คืน dates, target_close, {name: driver_close} เรียงตามวันที่ครบทุก series."""
    tc = _daily(target_rows)
    drv = {n: _daily(_rows(p)) for n, p in driver_paths.items()}
    common = set(tc)
    for d in drv.values():
        common &= set(d)
    dates = sorted(common)
    y = np.array([tc[d] for d in dates], float)
    dv = {n: np.array([drv[n][d] for d in dates], float) for n in drv}
    return dates, y, dv


def _resid_full(y, feats):
    cols = [feats[k] for k in feats] + [np.ones_like(y)]
    X = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ coef


def _diag(y, feats, label):
    r = _resid_full(y, feats)
    adf, hurst, hl = _adf_tstat(r), _hurst(r), _half_life(r)
    h = len(r) // 2
    a1 = _adf_tstat(_resid_full(y[:h], {k: v[:h] for k, v in feats.items()}))
    a2 = _adf_tstat(_resid_full(y[h:], {k: v[h:] for k, v in feats.items()}))
    ok = adf < ADF_CRIT and hurst < 0.5 and 5 <= hl <= 500 and a1 < ADF_CRIT and a2 < ADF_CRIT
    hl_s = f"{hl:6.1f}" if np.isfinite(hl) else "  inf "
    print(f"  {label:22s} ADF {adf:+6.2f}  Hurst {hurst:.2f}  HL {hl_s}  ADF½ {a1:+5.2f}/{a2:+5.2f}  "
          f"coint={'YES' if ok else '—'}")
    return ok


def revert(y, feats, win=252, z_in=2.0, z_out=0.5, z_stop=3.5, side="long", cost=0.0, max_hold=60):
    """rolling OLS residual z-fade (causal). feats ว่าง = self mean-revert (residual = y − rolling mean)."""
    names = list(feats)
    F = np.column_stack([feats[k] for k in names]) if names else None
    n = len(y); trades = []; i = win
    def feat_row(j):
        return np.concatenate([F[j], [1.0]]) if names else np.array([1.0])
    while i < n - 1:
        yw = y[i - win:i]
        Xw = (np.column_stack([F[i - win:i], np.ones(win)]) if names
              else np.ones((win, 1)))
        coef, *_ = np.linalg.lstsq(Xw, yw, rcond=None)
        resid = yw - Xw @ coef
        sd = resid.std()
        if sd <= 0:
            i += 1; continue
        z = (y[i] - feat_row(i) @ coef) / sd
        want = (z < -z_in and side in ("long", "both")) or (z > z_in and side in ("short", "both"))
        if not want:
            i += 1; continue
        sign = 1 if z < 0 else -1
        sl_dist = (z_stop - z_in) * sd
        if sl_dist <= 0:
            i += 1; continue
        entry = y[i]; exit_i = min(i + max_hold, n - 1)
        for j in range(i + 1, min(i + max_hold, n - 1) + 1):
            zj = (y[j] - feat_row(j) @ coef) / sd
            if (zj <= -z_stop if sign > 0 else zj >= z_stop) or \
               (zj >= -z_out if sign > 0 else zj <= z_out):
                exit_i = j; break
        trades.append((sign * (y[exit_i] - entry) - cost) / sl_dist)
        i = exit_i + 1
    return trades


def _stats(tr):
    n = len(tr)
    if n == 0:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    k = int(n * 0.7); oe = np.array(tr[k:]).mean() if n - k > 0 else float("nan")
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t, oe


def _rep(label, tr):
    s = _stats(tr)
    if not s:
        print(f"  {label:26s} n=0"); return
    n, wr, ex, t, oe = s
    flag = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oe > 0) else "—"
    print(f"  {label:26s} n={n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} OOS{oe:+.4f} [{flag}]")


def revert_suite(y, feats, cost, tag):
    print(f"\n  ── #1 REVERSION [{tag}] (long primary · short=เทียบ, live บล็อก) ──")
    for side in ("long", "short"):
        for win in (252, 504):
            for z_in in (2.0, 2.5):
                _rep(f"{side} w{win} z{z_in}", revert(y, feats, win=win, z_in=z_in, side=side, cost=cost))


def zone_suite(rows, cost_pips, point, tag):
    h = np.array([r[2] for r in rows], float)
    l = np.array([r[3] for r in rows], float)
    c = np.array([r[4] for r in rows], float)
    print(f"\n  ── #2 ZONE-REACTION [{tag}] BUY-at-support (D1, long-only) ──")
    for name, kw in [("baseline rr2", dict(rr=2.0)), ("fresh≤20 strong≥6", dict(rr=2.0, fresh_max=20, strong_min=6)),
                     ("rr3 fresh≤20", dict(rr=3.0, fresh_max=20))]:
        zone_report(name, zone_run(h, l, c, cost_pips, point, **kw))


def main():
    print("\n=== UHAS-IDEA MINING บน symbol อื่น (silver/WTI/BTC · causal · cost-adj · OOS70/30 · MIN_N=100) ===")
    print("gate PASS = n≥100 + exp_R>0 + t>2 + OOS>0 · coint=YES ถึงเชื่อ reversion\n")

    # ---------- SILVER ----------
    print("███ SILVER (offline drv_xag daily · driver=XAU gold/silver) ███")
    xag = _rows(os.path.join(DATA, "drv_xag_h1.json"))
    dates, y, dv = _align(xag, {"XAU": os.path.join(DATA, "xau_d1.json")})
    print(f"  n_days={len(y)}")
    print("  ── cointegration diag ──")
    _diag(y, dv, "XAG~XAU")
    _diag(y, {}, "XAG self")
    revert_suite(y, dv, cost=0.03, tag="XAG~XAU")
    zone_suite(xag, cost_pips=3.0, point=0.01, tag="XAG")

    # ---------- WTI ----------
    print("\n███ WTI (cache daily close-only · driver=DXY) ███")
    wti = _rows(os.path.join(_CACHE, "wti_d1.json"))
    dw, yw, dvw = _align(wti, {"DXY": os.path.join(DATA, "drv_dxy_h1.json")})
    print(f"  n_days aligned={len(yw)}")
    print("  ── cointegration diag ──")
    _diag(yw, dvw, "WTI~DXY")
    _diag(np.array([r[4] for r in wti], float), {}, "WTI self(full)")
    revert_suite(yw, dvw, cost=0.03, tag="WTI~DXY")
    # self บน history เต็ม (ไม่ align DXY)
    revert_suite(np.array([r[4] for r in wti], float), {}, cost=0.03, tag="WTI self")

    # ---------- BTC ----------
    print("\n███ BTC (cache daily OHLCV · self mean-revert) ███")
    btc = _rows(os.path.join(_CACHE, "btc_d1.json"))
    yb = np.array([r[4] for r in btc], float)
    print(f"  n_days={len(yb)}")
    print("  ── cointegration diag ──")
    _diag(yb, {}, "BTC self")
    _diag(np.log(yb), {}, "BTC self(log)")
    revert_suite(yb, {}, cost=15.0, tag="BTC self")
    zone_suite(btc, cost_pips=15.0, point=1.0, tag="BTC")

    print("\n⚠️ variants เยอะ = multiple-testing. เชื่อเฉพาะ coint=YES + PASS + OOS>0. short=เทียบเฉยๆ (LONG_ONLY_ALL).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
