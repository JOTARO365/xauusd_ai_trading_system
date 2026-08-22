#!/usr/bin/env python
"""scripts/breakout_long_v3.py — Long-only breakout confirm + period-stability (user 08-22).

v2 ablation เปิด: gold breakout = **long-only edge** (buy ทะลุขึ้นไปต่อ / sell ทะลุลงเด้งกลับ = safe-haven bull).
H4 wideN100 buy-only t2.16 OOS+2.26 cost2+1.20 แต่ n87<100 (พลาดแค่ n).

v3 หา 2 อย่าง:
  1. N sweep buy-only หาจุด n≥100 + t>2 (ลด N นิดเพื่อได้ signal มากขึ้น แต่คง long+wide+trail+atrSL)
  2. **per-quartile stability** = ตัวตัดสินจริง: long-breakout บวกทุกยุคไหม หรือแค่ recent bull (window-bias).
     ถ้าบวก ≥3/4 quartile = edge โครงสร้าง (shadow candidate). ถ้าบวกแค่ Q4 = fake จาก bull ล่าสุด = reject.

config ตายตัว (จาก v2): direction=buy, exit=donchian-trail, sl=1.5ATR (SL กว้าง — bandSL ฆ่า trend), no-regime, no-margin.
quant: causal · SL-first · non-overlap · cost×2 · OOS70/30 · MIN_N=100 · full-history.
read-only · offline · 0 token · ไม่แตะ live.
รัน: python scripts/breakout_long_v3.py [--tf h4|d1]
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


def run(h, l, c, cost, point, N=100, sl_atr=1.5):
    """long-only Donchian(N) breakout, trail exit (M=N//2), atrSL. คืน list ของ (entry_bar_index, R)."""
    atr = R.atr(h, l, c)
    hi_n = _roll_max(h, N)
    M = max(2, N // 2); lo_m = _roll_min(l, M)
    n = len(c); trades = []
    i = max(R.VOL_LOOKBACK + 40, N + 5)
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or hi_n[i] != hi_n[i]:
            i += 1; continue
        px = float(c[i])
        if not (px > hi_n[i]):                                # long-only breakout
            i += 1; continue
        sl_dist = sl_atr * av; sl_pips = sl_dist / point
        if sl_pips <= 0:
            i += 1; continue
        sl = px - sl_dist
        end = min(i + MAX_HOLD, n - 1); r_out = None; exit_i = end
        for j in range(i + 1, end + 1):
            if l[j] <= sl:
                r_out, exit_i = -1.0 - cost / sl_pips, j; break
            band = lo_m[j]
            if band == band and c[j] < band:
                r_out, exit_i = (c[j] - px) / sl_dist - cost / sl_pips, j; break
        if r_out is None:
            r_out = (c[end] - px) / sl_dist - cost / sl_pips
        trades.append((i, r_out)); i = exit_i + 1
    return trades


def _stat(rs):
    n = len(rs)
    if n == 0:
        return None
    a = np.array(rs, float); sd = a.std(ddof=1) if n > 1 else 0.0
    t = a.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return n, round(float((a > 0).mean()) * 100, 1), float(a.mean()), t


def main():
    tf = "h4"
    if "--tf" in sys.argv:
        tf = sys.argv[sys.argv.index("--tf") + 1].lower()
    h, l, c = _load_hlc(tf)
    point = 0.01; cost = 30.0
    nb = len(c)
    print(f"\n=== LONG-ONLY BREAKOUT v3 (XAU {tf.upper()} · N-sweep + period-stability · causal · SL-first · "
          f"cost×2 · MIN_N={MIN_N}) ===")
    print("PASS = n≥100 + exp_R>0 + t>2 + OOS>0 + cost2>0 · STABLE = exp_R>0 ใน ≥3/4 quartile (กัน bull-bias)")
    print(f"bars={nb} · quartile แบ่งตาม entry-bar index (Q1=เก่าสุด .. Q4=ล่าสุด)\n")
    for N in (40, 60, 80, 100, 120):
        tr = run(h, l, c, cost, point, N=N)
        tr2 = run(h, l, c, cost * 2, point, N=N)
        rs = [r for _, r in tr]
        s = _stat(rs)
        if not s:
            print(f"  N{N:3d} n=0"); continue
        n, wr, ex, t = s
        k = int(n * 0.7); oe = _stat(rs[k:])[2] if n - k > 1 else float("nan")
        c2 = _stat([r for _, r in tr2])[2]
        # per-quartile ตาม entry-bar index (แบ่ง history เป็น 4 ยุคเท่ากัน)
        q = [[], [], [], []]
        for bi, r in tr:
            qi = min(3, int(bi / nb * 4)); q[qi].append(r)
        qres = []
        for qq in q:
            ss = _stat(qq); qres.append(f"{ss[2]:+.2f}({ss[0]})" if ss else "—(0)")
        npos = sum(1 for qq in q if qq and np.mean(qq) > 0)
        pass_flag = "PASS" if (n >= MIN_N and ex > 0 and t > 2 and oe > 0 and c2 > 0) else "—"
        stable = "STABLE" if npos >= 3 else f"unstable({npos}/4)"
        print(f"  N{N:3d} n={n:4d} WR{wr:5.1f}% exp_R{ex:+.3f} t{t:+.2f} OOS{oe:+.3f} cost2{c2:+.3f} "
              f"[{pass_flag}] · Q1-4 {qres[0]} {qres[1]} {qres[2]} {qres[3]} [{stable}]")
    print("\n⚠️ STABLE (≥3/4 quartile บวก) สำคัญกว่า PASS: ถ้า t>2 แต่บวกแค่ Q4 = bull-bias ไม่ใช่ edge จริง.")
    print("⚠️ ถ้า n<100 ทุก N ที่ STABLE = edge จริงแต่ underpowered → shadow-forward (ยังไม่ live).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
