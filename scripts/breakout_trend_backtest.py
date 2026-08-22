#!/usr/bin/env python
"""scripts/breakout_trend_backtest.py — Breakout / trend-continuation บนทอง (user idea 08-22).

ต่างจาก reversion (fv_zone_macd ที่ตาย): เข้าตอนราคา **ทะลุ** กรอบ (momentum ต่อเนื่อง) ไม่ใช่เด้งในกรอบ.
premise: ทองทะลุ S/R แล้วไปต่อ (เห็นชัดใน fv_zone: TP=mid ติดลบ = ราคาไม่เด้งกลับ มันวิ่งต่อ).

Donchian(N) breakout: close ทะลุ N-bar high → BUY · ทะลุ N-bar low → SELL (turtle). ถูก+เร็ว (ไม่ต้อง
cluster_map). filter TREND regime (ER/ADX สูง = ตลาดมีทิศ) เพราะ breakout ตายใน range (false break).
exit: fixed RR หรือ donchian-exit(M) trailing (turtle-style ปล่อยกำไรวิ่ง).

⚠️ gold entry momentum เคยพัง full-history (−0.137) · cdc trend-follow D1 borderline n<80. เทสว่า breakout
+TREND-filter ยก edge เหนือ baseline ไหม. quant: causal · SL-first · non-overlap · cost/sl_pips · cost×2 ·
OOS70/30 · MIN_N=100 · full-history · both dir · variants=multiple-testing.
read-only · offline · 0 token · ไม่แตะ MT5/live.
รัน: python scripts/breakout_trend_backtest.py [--tf h4|d1|h1]
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
MAX_HOLD = 300
MIN_N = 100


def _load_hlc(tf):
    with open(os.path.join(DATA, f"xau_{tf}.json"), "r", encoding="utf-8") as f:
        d = json.load(f)
    h = np.array([x[2] for x in d], float)
    l = np.array([x[3] for x in d], float)
    c = np.array([x[4] for x in d], float)
    return h, l, c


def _roll_max(x, n):
    """max ของ n แท่งก่อนหน้า (ไม่รวม i) — causal. out[i] = max(x[i-n:i])."""
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n:i].max()
    return out


def _roll_min(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n:i].min()
    return out


def run(h, l, c, cost, point, N=20, exit_mode="rr", rr=2.0, exit_M=None,
        sl_atr=1.5, trend_only=True, direction="both"):
    """Donchian(N) breakout. exit_mode: 'rr' fixed | 'donchian' trail (exit เมื่อ close หลุด M-bar band).
    trend_only: เข้าเฉพาะ regime TREND. direction: buy|sell|both. causal, SL-first, non-overlap."""
    atr = R.atr(h, l, c); er = R.efficiency_ratio(c); adx = R.adx(h, l, c); vp = R.vol_percentile(c)
    hi_n = _roll_max(h, N); lo_n = _roll_min(l, N)
    M = exit_M or max(2, N // 2)
    hi_m = _roll_max(h, M); lo_m = _roll_min(l, M)
    n = len(c); trades = []
    i = max(R.VOL_LOOKBACK + 40, N + 5)
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or hi_n[i] != hi_n[i]:
            i += 1; continue
        if trend_only and R.detect_regime(er[i], adx[i], vp[i]) != "TREND":
            i += 1; continue
        px = float(c[i]); side = 0
        # breakout: close ทะลุ band N-bar (causal — band คำนวณจาก bar<i)
        if direction in ("buy", "both") and px > hi_n[i]:
            side = +1
        elif direction in ("sell", "both") and px < lo_n[i]:
            side = -1
        if side == 0:
            i += 1; continue

        sl_dist = sl_atr * av
        sl_pips = sl_dist / point
        if sl_pips <= 0:
            i += 1; continue
        sl = px - side * sl_dist
        tp = px + side * rr * sl_dist if exit_mode == "rr" else None

        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            hit_sl = (l[j] <= sl) if side > 0 else (h[j] >= sl)
            if hit_sl:                                        # SL-first
                r_out, exit_i = -1.0 - cost / sl_pips, j; break
            if exit_mode == "rr":
                hit_tp = (h[j] >= tp) if side > 0 else (l[j] <= tp)
                if hit_tp:
                    r_out, exit_i = rr - cost / sl_pips, j; break
            else:                                             # donchian trail: close หลุด M-band ฝั่งตรงข้าม
                band = lo_m[j] if side > 0 else hi_m[j]
                if band == band:
                    out = (c[j] < band) if side > 0 else (c[j] > band)
                    if out:
                        r = side * (c[j] - px) / sl_dist
                        r_out, exit_i = r - cost / sl_pips, j; break
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
        print(f"  {label:36s} n=0"); return
    n, wr, ex, t, sm = s
    k = int(n * 0.7); oos = _stats(tr[k:]); oe = oos[2] if oos else float("nan")
    c2 = ""
    if tr2 is not None:
        s2 = _stats(tr2); c2 = f" cost2{s2[2]:+.4f}" if s2 else ""
    flag = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oe > 0) else "—"
    print(f"  {label:36s} n={n:4d} WR{wr:5.1f}% exp_R{ex:+.4f} t{t:+.2f} sumR{sm:+7.1f} OOS{oe:+.4f}{c2} [{flag}]")


def main():
    tf = "h4"
    if "--tf" in sys.argv:
        tf = sys.argv[sys.argv.index("--tf") + 1].lower()
    h, l, c = _load_hlc(tf)
    point = 0.01; cost = 30.0
    print(f"\n=== BREAKOUT / trend-continuation (XAU {tf.upper()} · Donchian · causal · SL-first · "
          f"cost-adj · OOS70/30 · MIN_N={MIN_N}) ===")
    print("gate PASS = n≥100 + exp_R>0 + t>2 + OOS exp_R>0 · cost2 = ทน cost×2 · TREND-filter สำคัญ")
    print(f"bars={len(c)} · เทส: breakout ไปต่อจริงไหม + TREND-filter เพิ่ม edge เหนือ no-filter ไหม\n")
    VARIANTS = [
        ("N20 rr2 no-filter (baseline)", dict(N=20, exit_mode="rr", rr=2.0, trend_only=False)),
        ("N20 rr2 TREND", dict(N=20, exit_mode="rr", rr=2.0, trend_only=True)),
        ("N40 rr2 TREND", dict(N=40, exit_mode="rr", rr=2.0, trend_only=True)),
        ("N55 rr2 TREND", dict(N=55, exit_mode="rr", rr=2.0, trend_only=True)),
        ("N20 rr3 TREND", dict(N=20, exit_mode="rr", rr=3.0, trend_only=True)),
        ("N20 donchian-trail no-filter", dict(N=20, exit_mode="donchian", trend_only=False)),
        ("N20 donchian-trail TREND", dict(N=20, exit_mode="donchian", trend_only=True)),
        ("N40 donchian-trail TREND", dict(N=40, exit_mode="donchian", trend_only=True)),
        ("N55 donchian-trail TREND", dict(N=55, exit_mode="donchian", trend_only=True)),
        ("N20 donch buy-only TREND", dict(N=20, exit_mode="donchian", trend_only=True, direction="buy")),
        ("N20 donch sell-only TREND", dict(N=20, exit_mode="donchian", trend_only=True, direction="sell")),
    ]
    for name, kw in VARIANTS:
        tr = run(h, l, c, cost, point, **kw)
        tr2 = run(h, l, c, cost * 2, point, **kw)
        _report(name, tr, tr2)
    print("\n⚠️ ถ้าไม่มีตัว PASS (t>2 + OOS>0 + ทน cost×2) = breakout ไม่มี edge จริงบนทอง — ไม่ live.")
    print("⚠️ ระวัง multiple-testing: PASS ตัวเดียวโดดๆ ใน 11 variant อาจ false positive (ต้อง OOS+cost2 หนุน).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
