#!/usr/bin/env python
"""scripts/breakout_trend_v2.py — Breakout v2: diagnose+fix ตัวเด่นจาก v1 (user 08-22).

candidate เด่น v1: H4 N20 donch-trail no-filter (n482 +0.21 t1.83) · D1 N20 rr2 (n253 +0.17 t1.89)
— ทั้งคู่ t~1.85 พลาด >2 นิดเดียว, OOS แข็ง. edge จริงแต่ยังไม่ขาด.

จุดบกพร่อง → fix ที่เทส (ablation เพิ่มทีละตัว, ดูว่าอะไรยก t จริง):
  #1 exit trail แทน rr2 (เก็บ fat-tail ของ trend-follow)
  #2 breakout-margin: เข้าเฉพาะ close > band + k·ATR (กรอง false break/whipsaw)
  #3 structural SL = กรอบฝั่งตรงข้าม (กลับเข้ากรอบ=ผิด) แทน 1.5ATR fixed
  #4 น n: H4 wide-N (60/100/120) เลียนแบบ channel D1 แต่ได้ n มากกว่า
regime TREND-filter ถอดออกถาวร (v1 พิสูจน์ว่าทำร้าย breakout).

quant: causal · SL-first · non-overlap · cost/sl_pips · cost×2 · OOS70/30 · MIN_N=100 · full-history.
read-only · offline · 0 token · ไม่แตะ MT5/live.
รัน: python scripts/breakout_trend_v2.py [--tf h4|d1]
"""
import json
import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT); sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import regime_lib as R                                        # noqa: E402

DATA = os.path.join(_ROOT, "data")
MAX_HOLD = 400
MIN_N = 100


def _load_hlc(tf):
    with open(os.path.join(DATA, f"xau_{tf}.json"), "r", encoding="utf-8") as f:
        d = json.load(f)
    return (np.array([x[2] for x in d], float), np.array([x[3] for x in d], float),
            np.array([x[4] for x in d], float))


def _roll_max(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n:i].max()
    return out


def _roll_min(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n:i].min()
    return out


def run(h, l, c, cost, point, N=20, exit_mode="donchian", rr=2.0, exit_M=None,
        margin_atr=0.0, sl_type="atr", sl_atr=1.5, sl_buf=0.25, direction="both"):
    """Donchian(N) breakout, no regime filter. exit_mode rr|donchian. margin_atr = ต้อง close เกิน band
    เพิ่ม k·ATR (กรอง false break). sl_type: 'atr'=sl_atr·ATR | 'band'=กรอบตรงข้าม±sl_buf·ATR."""
    atr = R.atr(h, l, c)
    hi_n = _roll_max(h, N); lo_n = _roll_min(l, N)
    M = exit_M or max(2, N // 2)
    hi_m = _roll_max(h, M); lo_m = _roll_min(l, M)
    n = len(c); trades = []
    i = max(R.VOL_LOOKBACK + 40, N + 5)
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or hi_n[i] != hi_n[i]:
            i += 1; continue
        px = float(c[i]); side = 0
        mg = margin_atr * av
        if direction in ("buy", "both") and px > hi_n[i] + mg:
            side = +1
        elif direction in ("sell", "both") and px < lo_n[i] - mg:
            side = -1
        if side == 0:
            i += 1; continue

        # SL: structural (กรอบตรงข้าม) หรือ ATR fixed
        if sl_type == "band":
            sl_price = (lo_n[i] - sl_buf * av) if side > 0 else (hi_n[i] + sl_buf * av)
            sl_dist = abs(px - sl_price)
        else:
            sl_dist = sl_atr * av
            sl_price = px - side * sl_dist
        sl_pips = sl_dist / point
        if sl_pips <= 0:
            i += 1; continue
        sl = sl_price if sl_type == "band" else px - side * sl_dist
        tp = px + side * rr * sl_dist if exit_mode == "rr" else None

        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            hit_sl = (l[j] <= sl) if side > 0 else (h[j] >= sl)
            if hit_sl:
                r_out, exit_i = -1.0 - cost / sl_pips, j; break
            if exit_mode == "rr":
                hit_tp = (h[j] >= tp) if side > 0 else (l[j] <= tp)
                if hit_tp:
                    r_out, exit_i = rr - cost / sl_pips, j; break
            else:
                band = lo_m[j] if side > 0 else hi_m[j]
                if band == band:
                    out = (c[j] < band) if side > 0 else (c[j] > band)
                    if out:
                        r_out, exit_i = side * (c[j] - px) / sl_dist - cost / sl_pips, j; break
        if r_out is None:
            r_out = side * (c[end] - px) / sl_dist - cost / sl_pips
        trades.append(r_out)
        i = exit_i + 1
    return trades


def _stats(tr):
    n = len(tr)
    if n == 0:
        return None
    a = np.array(tr, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t, round(float(a.sum()), 1)


def _report(label, tr, tr2=None):
    s = _stats(tr)
    if not s:
        print(f"  {label:40s} n=0"); return
    n, wr, ex, t, sm = s
    k = int(n * 0.7); oos = _stats(tr[k:]); oe = oos[2] if oos else float("nan")
    c2 = _stats(tr2)[2] if tr2 is not None and _stats(tr2) else float("nan")
    flag = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oe > 0 and c2 > 0) else "—"
    print(f"  {label:40s} n={n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} sumR{sm:+7.1f} "
          f"OOS{oe:+.4f} cost2{c2:+.4f} [{flag}]")


def main():
    tf = "h4"
    if "--tf" in sys.argv:
        tf = sys.argv[sys.argv.index("--tf") + 1].lower()
    h, l, c = _load_hlc(tf)
    point = 0.01; cost = 30.0
    print(f"\n=== BREAKOUT v2 ablation (XAU {tf.upper()} · no-regime · causal · SL-first · cost-adj · "
          f"OOS70/30 · MIN_N={MIN_N}) ===")
    print("PASS = n≥100 + exp_R>0 + t>2 + OOS>0 + cost2>0 · ablation: เพิ่ม fix ทีละตัว ดูว่าอะไรยก t")
    print(f"bars={len(c)}\n")
    # baseline คือ candidate เด่น v1 (donch-trail no-filter). แล้วเพิ่ม fix ทีละชั้น.
    base = dict(N=20, exit_mode="donchian", sl_type="atr", sl_atr=1.5, margin_atr=0.0)
    VARIANTS = [
        ("BASE N20 trail atrSL", dict(base)),
        ("+margin0.25", {**base, "margin_atr": 0.25}),
        ("+margin0.5", {**base, "margin_atr": 0.5}),
        ("+bandSL", {**base, "sl_type": "band"}),
        ("+margin0.5+bandSL", {**base, "margin_atr": 0.5, "sl_type": "band"}),
        ("wideN60 trail", {**base, "N": 60}),
        ("wideN100 trail", {**base, "N": 100}),
        ("wideN120 trail", {**base, "N": 120}),
        ("wideN100 +margin0.5", {**base, "N": 100, "margin_atr": 0.5}),
        ("wideN100 +bandSL", {**base, "N": 100, "sl_type": "band"}),
        ("wideN100 +m0.5+bandSL", {**base, "N": 100, "margin_atr": 0.5, "sl_type": "band"}),
        ("wideN100 buy-only", {**base, "N": 100, "direction": "buy"}),
        ("wideN100 sell-only", {**base, "N": 100, "direction": "sell"}),
    ]
    for name, kw in VARIANTS:
        tr = run(h, l, c, cost, point, **kw)
        tr2 = run(h, l, c, cost * 2, point, **kw)
        _report(name, tr, tr2)
    print("\n⚠️ ดูว่า fix ตัวไหนดัน BASE ให้ t>2 + PASS. ถ้าไม่มี = edge บาง underpowered ต่อ (shadow-forward เท่านั้น).")
    print("⚠️ 13 variant = multiple-testing → PASS โดดเดี่ยวต้อง OOS+cost2 หนุนแน่น ไม่งั้น false positive.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
