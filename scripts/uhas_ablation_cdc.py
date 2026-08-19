#!/usr/bin/env python
"""scripts/uhas_ablation_cdc.py — ablation: เอา UHAS feature (1-4) ใส่เป็น filter/sizing บน cdc_zone (ทอง D1)
แล้ววัด "ส่วนเพิ่ม" เหนือ baseline. = ตอบโจทย์ "เอา uhas มา tune algo เรา" (ไม่ใช่ algo ใหม่).

reuse entry จริงของ cdc: scripts/cdc_backtest.bt_cdc/cdc_zone (parity live↔backtest). แตะแค่ "รับ/ไม่รับ entry"
(filter) หรือ "น้ำหนัก lot" (sizing) — ไม่เปลี่ยน signal เดิม. feature จาก UHAS:
  (1) fair-value gap  : long เฉพาะตอนทองไม่แพงเกิน (z ของ residual XAU~DXY/XAG < thr)
  (2) zone strength   : long เฉพาะตอน "มี support แข็งหนุน" (compute_cluster_map)
  (3) vol-clock sizing: weight lot = inverse trailing-vol (generic vol-target)
  (4) conditional reject: ไม่ long ถ้ามี "แนวต้านแข็ง" คร่อมเหนือ entry ≤ k·ATR

เทียบทุก variant บน window เดียวกัน (2013+ ที่ DXY/XAG ครบ) = apples-to-apples. causal · cost-adj · OOS70/30.
research offline (ไม่แตะ MT5/live/agent). wire เข้า algo จริง = ต้องขออนุมัติ (iron rule). 0 order.
รัน: python scripts/uhas_ablation_cdc.py
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                    # noqa: E402
from cdc_backtest import cdc_zone                         # noqa: E402
from agents.cluster_map import compute_cluster_map        # noqa: E402

DATA = os.path.join(_ROOT, "data")
DAY = 86400
FV_WIN = 252
ZONE_WIN = 600


def _rows(fn):
    with open(os.path.join(DATA, fn), "r", encoding="utf-8") as f:
        return json.load(f)


def _agg_daily(rows):
    b = {}
    for r in rows:
        k = int(r[0]) // DAY
        o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
        if k not in b:
            b[k] = [o, h, l, c]
        else:
            a = b[k]; a[1] = max(a[1], h); a[2] = min(a[2], l); a[3] = c
    return b


def _close_daily(rows):
    return {int(r[0]) // DAY: float(r[4]) for r in rows}


def load_aligned():
    """xau D1 (o,h,l,c) + DXY/XAG close, เฉพาะวันที่มีครบทุก series (2013+)."""
    xau = _agg_daily(_rows("xau_d1.json"))
    dxy = _close_daily(_rows("drv_dxy_h1.json"))
    xag = _close_daily(_rows("drv_xag_h1.json"))
    ks = sorted(set(xau) & set(dxy) & set(xag))
    o = np.array([xau[k][0] for k in ks], float); h = np.array([xau[k][1] for k in ks], float)
    l = np.array([xau[k][2] for k in ks], float); c = np.array([xau[k][3] for k in ks], float)
    dv = {"DXY": np.array([dxy[k] for k in ks], float), "XAG": np.array([xag[k] for k in ks], float)}
    return o, h, l, c, dv


def fair_value_z(c, feats, win=FV_WIN):
    """z ของ residual (causal rolling OLS c~[drivers,1]). >0 = แพงกว่าโมเดล."""
    F = np.column_stack([feats[k] for k in feats])
    n = len(c); z = np.full(n, np.nan)
    for i in range(win, n):
        Xw = np.column_stack([F[i - win:i], np.ones(win)])
        coef, *_ = np.linalg.lstsq(Xw, c[i - win:i], rcond=None)
        resid = c[i - win:i] - Xw @ coef
        sd = resid.std()
        if sd > 0:
            z[i] = (c[i] - np.concatenate([F[i], [1.0]]) @ coef) / sd
    return z


def bt_cdc_abl(o, h, l, c, cost_price, sl_atr=2.0, entry_ok=None, size_fn=None):
    """mirror cdc_backtest.bt_cdc (long-only) + hook — SKIP-RUN semantics:
    entry_ok(i) ประเมินแค่ตอน fresh bull-flip; ถ้าบล็อก = ข้ามทั้ง bull run (ไม่ churn ซื้อสูงกลางเทรนด์).
    หลัง disaster-stop ภายใน run ที่ 'รับแล้ว' → เข้าใหม่ได้ (เหมือน baseline). size_fn(i)->w น้ำหนัก lot.
    คืน list ของ (R, w)."""
    fast, slow = cdc_zone(o, h, l, c)
    atr = R.atr(h, l, c)
    tr = []; pos = 0; entry = 0.0; risk = 0.0; w_at = 1.0
    bull_prev = False; run_taken = False                   # run_taken = bull run นี้ผ่าน filter แล้ว
    for i in range(30, len(c)):
        if pos != 0 and risk > 0 and pos * (c[i] - entry) <= -risk:
            tr.append((-1.0 - cost_price / risk, w_at)); pos = 0
        bull = fast[i] > slow[i]
        if bull and not bull_prev:                         # fresh bull-flip → ตัดสิน filter ครั้งเดียว/run
            run_taken = (entry_ok is None) or bool(entry_ok(i))
        if not bull:
            run_taken = False
        bull_prev = bull
        want = 1 if (bull and run_taken) else 0
        if want != pos:
            if pos != 0 and risk > 0:
                tr.append(((pos * (c[i] - entry) - cost_price) / risk, w_at))
            pos = want; entry = c[i]
            av = float(atr[i]) if atr[i] == atr[i] else 0.0
            risk = sl_atr * av if av > 0 else 0.0
            w_at = float(size_fn(i)) if (want > 0 and size_fn is not None) else 1.0
    return tr


def _stats(tr):
    if len(tr) < 20:
        return None
    Rv = np.array([x for x, _ in tr], float); w = np.array([x for _, x in tr], float)
    n = len(Rv)
    # weighted (sizing) — ถ้า w คงที่ = unweighted ปกติ
    wm = float(np.sum(w * Rv) / np.sum(w))
    wsd = math.sqrt(float(np.sum(w * (Rv - wm) ** 2) / np.sum(w)))
    t = wm / (wsd / math.sqrt(n)) if wsd > 0 else 0.0
    k = int(n * 0.7)
    oos = float(np.sum(w[k:] * Rv[k:]) / np.sum(w[k:])) if np.sum(w[k:]) > 0 else float("nan")
    return {"n": n, "exp_R": wm, "t": t, "oos": oos, "sum_R": float(Rv.sum()),
            "wr": round(float((Rv > 0).mean()) * 100, 1)}


def _rep(label, tr, base=None):
    s = _stats(tr)
    if not s:
        print(f"  {label:28s} n<20"); return None
    d = ""
    if base:
        d = f"  Δexp_R {s['exp_R'] - base['exp_R']:+.3f}"
    rob = "ROBUST" if (s["exp_R"] > 0 and s["oos"] >= 0 and s["n"] >= 100 and abs(s["t"]) >= 2) else \
          ("+EV" if s["exp_R"] > 0 and s["oos"] >= 0 else "—")
    print(f"  {label:28s} n{s['n']:4d} exp_R{s['exp_R']:+.3f} t{s['t']:+5.2f} OOS{s['oos']:+.3f} "
          f"WR{s['wr']:5.1f} [{rob}]{d}")
    return s


def main():
    o, h, l, c, dv = load_aligned()
    atr = R.atr(h, l, c)
    cost = 0.30                                            # ทอง ~30pip×0.01
    print(f"\n=== UHAS FEATURE ABLATION บน cdc_zone (ทอง D1) · window aligned n={len(c)} วัน (2013+) ===")
    print("baseline = cdc long-only เดิม · แต่ละ feature = +filter/sizing · ROBUST=exp_R>0+OOS≥0+n≥100+|t|≥2\n")

    base = _rep("baseline cdc long", bt_cdc_abl(o, h, l, c, cost))

    # ---- (1) fair-value gap ----
    z = fair_value_z(c, dv)
    print("\n── (1) fair-value filter: long เฉพาะตอนทองไม่แพงเกิน (z<thr) ──")
    for thr in (1.5, 1.0, 0.5, 0.0):
        _rep(f"cdc + FV z<{thr}", bt_cdc_abl(o, h, l, c, cost,
             entry_ok=lambda i, t=thr: not (z[i] == z[i]) or z[i] < t), base)

    # ---- (2) zone strength: long เฉพาะมี support แข็งหนุนใต้ราคา ----
    print("\n── (2) zone filter: long เฉพาะมี support (touches≥k) ใกล้ใต้ราคา ──")
    def sup_ok(i, min_touch, tol_atr):
        w0 = max(0, i - (ZONE_WIN - 1))
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        if not cm.get("ok"):
            return False
        sup = cm.get("support"); av = float(atr[i]) if atr[i] == atr[i] else 0.0
        return bool(sup and sup["touches"] >= min_touch and av > 0 and sup["dist_atr"] <= tol_atr)
    for mt, tol in [(6, 1.0), (6, 2.0), (8, 2.0)]:
        _rep(f"cdc + sup≥{mt} tol{tol}", bt_cdc_abl(o, h, l, c, cost,
             entry_ok=lambda i, m=mt, tl=tol: sup_ok(i, m, tl)), base)

    # ---- (3) vol-clock sizing ----
    print("\n── (3) vol-clock sizing: weight lot = inverse trailing-vol (generic vol-target) ──")
    ret = np.concatenate([[0.0], np.diff(np.log(c))])
    vwin = 20
    sig = np.array([ret[max(0, i - vwin):i].std() if i >= vwin else np.nan for i in range(len(c))])
    smed = np.nanmedian(sig)
    def size_iv(i):
        s = sig[i]
        return float(np.clip(smed / s, 0.33, 3.0)) if (s == s and s > 0) else 1.0
    _rep("cdc + inv-vol sizing", bt_cdc_abl(o, h, l, c, cost, size_fn=size_iv), base)

    # ---- (4) conditional reject: ไม่ long ถ้ามีต้านแข็งคร่อมเหนือ entry ≤ k·ATR ----
    print("\n── (4) conditional reject: skip long ถ้ามี resistance แข็ง (touches≥6) เหนือ ≤k·ATR ──")
    def no_res_overhead(i, k_atr):
        w0 = max(0, i - (ZONE_WIN - 1))
        cm = compute_cluster_map(h[w0:i + 1], l[w0:i + 1], c[w0:i + 1])
        if not cm.get("ok"):
            return True
        res = cm.get("resistance"); av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if not (res and res["touches"] >= 6 and av > 0):
            return True
        return (res["level"] - c[i]) > k_atr * av           # ต้านไกลกว่า k·ATR = โล่ง = เข้าได้
    for k in (1.0, 1.5, 2.0):
        _rep(f"cdc + no-res≤{k}ATR", bt_cdc_abl(o, h, l, c, cost,
             entry_ok=lambda i, kk=k: no_res_overhead(i, kk)), base)

    print("\n⚠️ variants เยอะ = multiple-testing. เก็บเฉพาะ Δexp_R บวก + ROBUST + OOS≥0. wire = ต้องขออนุมัติ.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
