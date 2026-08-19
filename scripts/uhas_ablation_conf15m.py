#!/usr/bin/env python
"""scripts/uhas_ablation_conf15m.py — ablation #3: UHAS feature (1-4) เป็น filter บน confluence_15m (ทอง M15).

reproduce core ConfluenceVol15m offline: M15 Donchian breakout (BRK=12) + H1 slope + H4 slope + EURUSD(M15) macro
+ tick-volume surge (VK=1.5) ตรงทิศทั้งหมด + session 13-21 UTC. SL_ATR=1.0 RR=2.0. long-only (LONG_ONLY_ALL).

⚠️ window บางสุด: EURUSD M15 data เริ่ม 2024-02 → ~2.5 ปี regime เดียว = reliability ต่ำกว่า cdc/macro_mom มาก.
feature 1-4 เดียวกับ ablation อื่น. causal · cost-adj · OOS70/30. offline (ไม่แตะ MT5/live). 0 order.
รัน: python scripts/uhas_ablation_conf15m.py
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
from datetime import datetime, timezone                   # noqa: E402

DATA = os.path.join(_ROOT, "data")
DAY = 86400
BRK, SL_ATR, RR, VK = 12, 1.0, 2.0, 1.5
FV_WIN, ZONE_WIN, MAX_HOLD = 252, 600, 96
SESS = (13, 21)


def _rows(fn):
    with open(os.path.join(DATA, fn), "r", encoding="utf-8") as f:
        return json.load(f)


def _ema_slope_map(src_t, src_c, tgt_t, span=50, lag=3):
    """EMA(span) slope (1/-1) ของ series src ต่อ tgt timestamp (prior completed bar, causal)."""
    k = 2.0 / (span + 1.0); e = np.empty_like(src_c); e[0] = src_c[0]
    for i in range(1, len(src_c)):
        e[i] = src_c[i] * k + e[i - 1] * (1 - k)
    idx = np.clip(np.searchsorted(src_t, tgt_t, side="right") - 1, 0, len(e) - 1)
    out = np.zeros(len(tgt_t), int)
    for j, ix in enumerate(idx):
        if ix - lag >= 0:
            out[j] = 1 if e[ix] > e[ix - lag] else (-1 if e[ix] < e[ix - lag] else 0)
    return out


def _fv_z_daily():
    xau = {int(r[0]) // DAY: float(r[4]) for r in _rows("xau_d1.json")}
    dxy = {int(r[0]) // DAY: float(r[4]) for r in _rows("drv_dxy_h1.json")}
    xag = {int(r[0]) // DAY: float(r[4]) for r in _rows("drv_xag_h1.json")}
    ks = sorted(set(xau) & set(dxy) & set(xag))
    c = np.array([xau[k] for k in ks], float)
    F = np.column_stack([[dxy[k] for k in ks], [xag[k] for k in ks]]).astype(float)
    out = {}
    for i in range(FV_WIN, len(ks)):
        Xw = np.column_stack([F[i - FV_WIN:i], np.ones(FV_WIN)])
        coef, *_ = np.linalg.lstsq(Xw, c[i - FV_WIN:i], rcond=None)
        sd = (c[i - FV_WIN:i] - Xw @ coef).std()
        if sd > 0:
            out[ks[i]] = (c[i] - np.concatenate([F[i], [1.0]]) @ coef) / sd
    return out


def load():
    m = _rows("xau_m15.json")
    t = np.array([int(x[0]) for x in m]); o = np.array([x[1] for x in m], float)
    h = np.array([x[2] for x in m], float); l = np.array([x[3] for x in m], float)
    c = np.array([x[4] for x in m], float); v = np.array([x[5] for x in m], float)
    h1 = _rows("xau_h1.json"); h4 = _rows("xau_h4.json"); eu = _rows("drv_eurusd_m15.json")
    h1t = np.array([int(x[0]) for x in h1]); h1c = np.array([x[4] for x in h1], float)
    h4t = np.array([int(x[0]) for x in h4]); h4c = np.array([x[4] for x in h4], float)
    eut = np.array([int(x[0]) for x in eu]); euc = np.array([x[4] for x in eu], float)
    slope_h1 = _ema_slope_map(h1t, h1c, t); slope_h4 = _ema_slope_map(h4t, h4c, t)
    # macro (EURUSD M15): mac = sign(ec[i]-ec[i-26]) mapped to xau M15 ts
    eidx = np.clip(np.searchsorted(eut, t, side="right") - 1, 0, len(euc) - 1)
    eur = np.where(t >= eut[0], euc[eidx], np.nan)
    eur_lag = np.where(t >= eut[0], euc[np.clip(eidx - 26, 0, len(euc) - 1)], np.nan)
    mac = np.where(np.isnan(eur), 0, np.where(eur > eur_lag, 1, -1))
    zd = _fv_z_daily()
    z = np.array([zd.get((int(ts) // DAY) - 1, np.nan) for ts in t])
    hr = np.array([datetime.fromtimestamp(int(ts), timezone.utc).hour for ts in t])
    return t, o, h, l, c, v, slope_h1, slope_h4, mac, eur, z, hr


def bt_conf(t, o, h, l, c, v, sh1, sh4, mac, eur, hr, cost, entry_ok=None, size_fn=None):
    atr = R.atr(h, l, c); n = len(c); trades = []; i = max(BRK, 210) + 1
    while i < n - 1:
        if not (SESS[0] <= hr[i] < SESS[1]) or eur[i] != eur[i]:
            i += 1; continue
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            i += 1; continue
        px = c[i]; hh = h[i - BRK:i].max()
        if not (px > hh):                                  # long-only breakout
            i += 1; continue
        med = float(np.median(v[i - 200:i])) or 1.0
        vsurge = v[i] >= VK * med and v[i] <= 2.0 * med
        if not (sh1[i] == 1 and sh4[i] == 1 and mac[i] == 1 and vsurge):   # confluence 4-align
            i += 1; continue
        if entry_ok is not None and not entry_ok(i):
            i += 1; continue
        risk = SL_ATR * av; sl = px - risk; tp = px + risk * RR
        w = float(size_fn(i)) if size_fn is not None else 1.0
        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            if l[j] <= sl:
                r_out, exit_i = -1.0 - cost / risk, j; break
            if h[j] >= tp:
                r_out, exit_i = RR - cost / risk, j; break
        if r_out is None:
            r_out = (c[end] - px) / risk - cost / risk
        trades.append((r_out, w)); i = exit_i + 1
    return trades


def _stats(tr):
    if len(tr) < 20:
        return None
    Rv = np.array([x for x, _ in tr], float); w = np.array([x for _, x in tr], float)
    n = len(Rv); wm = float(np.sum(w * Rv) / np.sum(w))
    wsd = math.sqrt(float(np.sum(w * (Rv - wm) ** 2) / np.sum(w)))
    tval = wm / (wsd / math.sqrt(n)) if wsd > 0 else 0.0
    k = int(n * 0.7); oos = float(np.sum(w[k:] * Rv[k:]) / np.sum(w[k:])) if np.sum(w[k:]) > 0 else float("nan")
    return {"n": n, "exp_R": wm, "t": tval, "oos": oos, "wr": round(float((Rv > 0).mean()) * 100, 1)}


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
    t, o, h, l, c, v, sh1, sh4, mac, eur, z, hr = load()
    atr = R.atr(h, l, c); cost = 0.30
    nvalid = int(np.sum(eur == eur))
    print(f"\n=== UHAS FEATURE ABLATION บน confluence_15m (ทอง M15) · breakout+H1+H4+EURUSD+volsurge+sess13-21 · "
          f"EURUSD-M15 overlap ~{nvalid} bars (2024+) ===")
    print("⚠️ window บางสุด (2024+ regime เดียว) → reliability ต่ำกว่า cdc/macro_mom. baseline = confluence long-only\n")
    base = _rep("baseline conf15m", bt_conf(t, o, h, l, c, v, sh1, sh4, mac, eur, hr, cost))
    if not base:
        print("  n<20 — window บางเกินสรุป (EURUSD M15 สั้น). ข้าม confluence."); return

    print("\n── (1) fair-value filter (z<thr) ──")
    for thr in (1.5, 1.0, 0.5):
        _rep(f"+ FV z<{thr}", bt_conf(t, o, h, l, c, v, sh1, sh4, mac, eur, hr, cost,
             entry_ok=lambda i, tt=thr: not (z[i] == z[i]) or z[i] < tt), base)

    print("\n── (2) zone strength (sup≥k ≤tol·ATR ใต้ราคา) ──")
    def sup_ok(i, mt, tol):
        w0 = max(0, i - (ZONE_WIN - 1))
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        sup = cm.get("support"); av = float(atr[i]) if atr[i] == atr[i] else 0.0
        return bool(cm.get("ok") and sup and sup["touches"] >= mt and av > 0 and sup["dist_atr"] <= tol)
    for mt, tol in [(6, 2.0), (6, 3.0)]:
        _rep(f"+ sup≥{mt} tol{tol}", bt_conf(t, o, h, l, c, v, sh1, sh4, mac, eur, hr, cost,
             entry_ok=lambda i, m=mt, tl=tol: sup_ok(i, m, tl)), base)

    print("\n── (3) vol-clock sizing (inverse trailing-vol) ──")
    ret = np.concatenate([[0.0], np.diff(np.log(c))]); vw = 96
    sig = np.array([ret[max(0, i - vw):i].std() if i >= vw else np.nan for i in range(len(c))])
    smed = np.nanmedian(sig)
    _rep("+ inv-vol sizing", bt_conf(t, o, h, l, c, v, sh1, sh4, mac, eur, hr, cost,
         size_fn=lambda i: float(np.clip(smed / sig[i], 0.33, 3.0)) if (sig[i] == sig[i] and sig[i] > 0) else 1.0), base)

    print("\n⚠️ window 2024+ regime เดียว = สรุปได้อ่อน. ดูว่า pattern (feature 1+2 ยก) ยังไปทางเดียวกับ cdc/macro_mom ไหม.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
