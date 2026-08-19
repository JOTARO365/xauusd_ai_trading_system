#!/usr/bin/env python
"""scripts/uhas_ablation_macromom.py — ablation #2: UHAS feature (1-4) เป็น filter บน macro_momentum (ทอง H4).

reproduce core ของ MacroMomAlgo offline: Donchian breakout (BRK=20) + EURUSD macro-confirm (MLB=24, msign
จาก R.macro_for) → BUY/SELL; SL_ATR=1.5, RR=2.0. (sentiment/seasonal gate = live-only → ตัดออก; orthogonal
กับ UHAS feature). long-only focus (LONG_ONLY_ALL). แต่ละ breakout = 1 ไม้ SL/TP non-overlap → filter กด entry ตรงๆ.

feature เดียวกับ ablation cdc: (1) fair-value z (daily XAU~DXY/XAG ffill→H4) (2) zone-strength (3) vol sizing
(4) conditional-reject. window = xau_h4 ∩ EURUSD (2022+, EURUSD data เริ่ม 2022 → บางกว่า cdc). causal · cost-adj · OOS70/30.
research offline (ไม่แตะ MT5/live/agent). wire = ขออนุมัติ. 0 order. รัน: python scripts/uhas_ablation_macromom.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                    # noqa: E402
from agents.cluster_map import compute_cluster_map        # noqa: E402

DATA = os.path.join(_ROOT, "data")
DAY = 86400
BRK, MLB, SL_ATR, RR = 20, 24, 1.5, 2.0
FV_WIN = 252
ZONE_WIN = 600
MAX_HOLD = 120


def _rows(fn):
    with open(os.path.join(DATA, fn), "r", encoding="utf-8") as f:
        return json.load(f)


def _close_daily(rows):
    return {int(r[0]) // DAY: float(r[4]) for r in rows}


def _daily_xau_close():
    return {int(r[0]) // DAY: float(r[4]) for r in _rows("xau_d1.json")}


def fair_value_z_daily():
    """z รายวันของ residual XAU~[DXY,XAG] (causal rolling OLS). คืน {day_bucket: z}."""
    xau = _daily_xau_close(); dxy = _close_daily(_rows("drv_dxy_h1.json")); xag = _close_daily(_rows("drv_xag_h1.json"))
    ks = sorted(set(xau) & set(dxy) & set(xag))
    c = np.array([xau[k] for k in ks], float)
    F = np.column_stack([[dxy[k] for k in ks], [xag[k] for k in ks]]).astype(float)
    out = {}
    for i in range(FV_WIN, len(ks)):
        Xw = np.column_stack([F[i - FV_WIN:i], np.ones(FV_WIN)])
        coef, *_ = np.linalg.lstsq(Xw, c[i - FV_WIN:i], rcond=None)
        resid = c[i - FV_WIN:i] - Xw @ coef; sd = resid.std()
        if sd > 0:
            out[ks[i]] = (c[i] - np.concatenate([F[i], [1.0]]) @ coef) / sd
    return out


def load_h4():
    """xau H4 arrays + EURUSD close aligned + fair-value z ต่อ H4 bar (prior-day, causal)."""
    xr = _rows("xau_h4.json")
    t = np.array([int(x[0]) for x in xr]); o = np.array([x[1] for x in xr], float)
    h = np.array([x[2] for x in xr], float); l = np.array([x[3] for x in xr], float)
    c = np.array([x[4] for x in xr], float)
    # EURUSD hourly → close at/ก่อน H4 ts
    er = _rows("drv_eurusd_h1.json")
    et = np.array([int(x[0]) for x in er]); ec = np.array([x[4] for x in er], float)
    idx = np.clip(np.searchsorted(et, t, side="right") - 1, 0, len(ec) - 1)
    eur = np.where(t >= et[0], ec[idx], np.nan)
    # fair-value z ต่อ H4 = z ของวันก่อนหน้า (causal)
    zd = fair_value_z_daily()
    zt = np.array([zd.get((int(ts) // DAY) - 1, np.nan) for ts in t])   # prior-day z
    return t, o, h, l, c, eur, zt


def bt_macromom(t, o, h, l, c, eur, cost_price, point=0.01, entry_ok=None, size_fn=None, long_only=True):
    """Donchian breakout + EURUSD confirm (msign=+1 XAUUSD: EURUSD↑=DXY↓→BUY). SL/TP RR non-overlap.
    entry_ok(i)->bool กรอง; size_fn(i)->w. คืน (R,w) list."""
    atr = R.atr(h, l, c)
    n = len(c); trades = []; i = max(BRK, MLB) + 1
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or eur[i] != eur[i] or eur[i - MLB] != eur[i - MLB]:
            i += 1; continue
        px = c[i]; hh = h[i - BRK:i].max(); ll = l[i - BRK:i].min()
        d = "BUY" if px > hh else ("SELL" if px < ll else None)
        if d is None:
            i += 1; continue
        md = "BUY" if (eur[i] - eur[i - MLB]) > 0 else "SELL"      # msign=+1 (XAUUSD~EURUSD)
        if d != md:
            i += 1; continue
        if long_only and d == "SELL":
            i += 1; continue
        if entry_ok is not None and not entry_ok(i):
            i += 1; continue
        sign = 1 if d == "BUY" else -1
        risk = SL_ATR * av; sl = px - sign * risk; tp = px + sign * risk * RR
        w = float(size_fn(i)) if size_fn is not None else 1.0
        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            if (l[j] <= sl if sign > 0 else h[j] >= sl):
                r_out, exit_i = -1.0 - cost_price / risk, j; break
            if (h[j] >= tp if sign > 0 else l[j] <= tp):
                r_out, exit_i = RR - cost_price / risk, j; break
        if r_out is None:
            r_out = sign * (c[end] - px) / risk - cost_price / risk
        trades.append((r_out, w)); i = exit_i + 1
    return trades


def _stats(tr):
    if len(tr) < 20:
        return None
    Rv = np.array([x for x, _ in tr], float); w = np.array([x for _, x in tr], float)
    n = len(Rv); wm = float(np.sum(w * Rv) / np.sum(w))
    wsd = math.sqrt(float(np.sum(w * (Rv - wm) ** 2) / np.sum(w)))
    t = wm / (wsd / math.sqrt(n)) if wsd > 0 else 0.0
    k = int(n * 0.7); oos = float(np.sum(w[k:] * Rv[k:]) / np.sum(w[k:])) if np.sum(w[k:]) > 0 else float("nan")
    return {"n": n, "exp_R": wm, "t": t, "oos": oos, "wr": round(float((Rv > 0).mean()) * 100, 1)}


def _rep(label, tr, base=None):
    s = _stats(tr)
    if not s:
        print(f"  {label:28s} n<20"); return None
    d = f"  Δexp_R {s['exp_R'] - base['exp_R']:+.3f}" if base else ""
    rob = "ROBUST" if (s["exp_R"] > 0 and s["oos"] >= 0 and s["n"] >= 100 and abs(s["t"]) >= 2) else \
          ("+EV" if s["exp_R"] > 0 and s["oos"] >= 0 else "—")
    print(f"  {label:28s} n{s['n']:4d} exp_R{s['exp_R']:+.3f} t{s['t']:+5.2f} OOS{s['oos']:+.3f} WR{s['wr']:5.1f} [{rob}]{d}")
    return s


def main():
    t, o, h, l, c, eur, z = load_h4()
    atr = R.atr(h, l, c); cost = 0.30
    nvalid = int(np.sum(eur == eur))
    print(f"\n=== UHAS FEATURE ABLATION บน macro_momentum (ทอง H4) · Donchian20+EURUSD24 · window EURUSD-overlap ~{nvalid} H4 bars (2022+) ===")
    print("baseline = macro_mom long-only (ตัด sentiment gate) · ROBUST=exp_R>0+OOS≥0+n≥100+|t|≥2\n")
    base = _rep("baseline macro_mom", bt_macromom(t, o, h, l, c, eur, cost))

    print("\n── (1) fair-value filter: long เฉพาะทองไม่แพงเกิน (z<thr) ──")
    for thr in (1.5, 1.0, 0.5):
        _rep(f"+ FV z<{thr}", bt_macromom(t, o, h, l, c, eur, cost,
             entry_ok=lambda i, tt=thr: not (z[i] == z[i]) or z[i] < tt), base)

    print("\n── (2) zone strength: long เฉพาะมี support (touches≥k) ใกล้ใต้ราคา ──")
    def sup_ok(i, mt, tol):
        w0 = max(0, i - (ZONE_WIN - 1))
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        if not cm.get("ok"):
            return False
        sup = cm.get("support"); av = float(atr[i]) if atr[i] == atr[i] else 0.0
        return bool(sup and sup["touches"] >= mt and av > 0 and sup["dist_atr"] <= tol)
    for mt, tol in [(6, 2.0), (8, 2.0)]:
        _rep(f"+ sup≥{mt} tol{tol}", bt_macromom(t, o, h, l, c, eur, cost,
             entry_ok=lambda i, m=mt, tl=tol: sup_ok(i, m, tl)), base)

    print("\n── (3) vol-clock sizing: weight = inverse trailing-vol ──")
    ret = np.concatenate([[0.0], np.diff(np.log(c))]); vw = 30
    sig = np.array([ret[max(0, i - vw):i].std() if i >= vw else np.nan for i in range(len(c))])
    smed = np.nanmedian(sig)
    _rep("+ inv-vol sizing", bt_macromom(t, o, h, l, c, eur, cost,
         size_fn=lambda i: float(np.clip(smed / sig[i], 0.33, 3.0)) if (sig[i] == sig[i] and sig[i] > 0) else 1.0), base)

    print("\n── (4) conditional reject: skip ถ้ามี resistance แข็ง (≥6) เหนือ ≤k·ATR ──")
    def no_res(i, k):
        w0 = max(0, i - (ZONE_WIN - 1))
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        if not cm.get("ok"):
            return True
        res = cm.get("resistance"); av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if not (res and res["touches"] >= 6 and av > 0):
            return True
        return (res["level"] - c[i]) > k * av
    for k in (1.0, 1.5):
        _rep(f"+ no-res≤{k}ATR", bt_macromom(t, o, h, l, c, eur, cost, entry_ok=lambda i, kk=k: no_res(i, kk)), base)

    print("\n⚠️ window บาง (2022+) + ตัด sentiment gate → robust น้อยกว่า cdc. เก็บเฉพาะ Δ+ ROBUST OOS≥0.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
