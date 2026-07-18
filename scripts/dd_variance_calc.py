#!/usr/bin/env python
"""
dd_variance_calc.py — Track 1 บทที่ 3: Drawdown & Variance Math (สอนจาก trade จริง)

  1) Drawdown asymmetry — ขาดทุน X% ต้องกำไร X/(1−X)% ถึงจะกลับ (−50%→+100%)
  2) Losing-streak / variance — WR ต่ำ = ติดลบยาวบ่อย; MC วัด maxDD จริงที่ variance พาไป (แม้ทุนหนา)
  3) Volatility drag — geometric return < arithmetic ด้วย σ²/2 (ทำไมเรียบ+เล็ก ชนะ แกว่ง+ใหญ่)

รัน: python scripts\\dd_variance_calc.py
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEALTHY = 20000.0    # ทุน "หนา" — แยกบทเรียน DD/variance ออกจากบทเรียน ruin (ทุนบาง)
HORIZON = 100        # ไม้
N_PATHS = 20000
RNG = np.random.default_rng(0)


def load_pnls():
    td = json.load(open(os.path.join(_BASE, "logs", "trades.json"), encoding="utf-8"))
    tr = td if isinstance(td, list) else td.get("trades", [])
    return [float(t["pnl"]) for t in tr
            if str(t.get("source")) == "SYSTEM" and t.get("status") == "CLOSED" and t.get("pnl") is not None]


def mc_drawdown(pnls, e0, horizon, n=N_PATHS):
    p = np.asarray(pnls, float)
    max_dds, max_streaks = [], []
    for _ in range(n):
        draws = p[RNG.integers(0, len(p), horizon)]
        eq = e0 + np.cumsum(draws)
        peak = np.maximum.accumulate(np.concatenate([[e0], eq]))
        dd = (peak[1:] - eq) / peak[1:]
        max_dds.append(dd.max() * 100)
        st = mx = 0
        for d in draws:
            st = st + 1 if d <= 0 else 0
            mx = max(mx, st)
        max_streaks.append(mx)
    return np.array(max_dds), np.array(max_streaks)


def main():
    pnls = load_pnls()
    wr = np.mean([x > 0 for x in pnls])
    print("=" * 70)
    print(f"DRAWDOWN & VARIANCE — n={len(pnls)} trades, WR {wr*100:.0f}%")
    print("=" * 70)

    print("\n① DRAWDOWN ASYMMETRY (ขาดทุน X% ต้องกำไรเท่าไรถึงกลับ)")
    print(f"   {'drawdown':>10} | {'ต้องกำไรกลับ':>14}")
    for dd in (0.10, 0.20, 0.30, 0.50, 0.70, 0.90):
        print(f"   {dd*100:>8.0f}% | {dd/(1-dd)*100:>13.0f}%")
    print("   → ยิ่งลึกยิ่งกลับยากทวีคูณ → **เลี่ยง DD ลึก สำคัญกว่าไล่กำไร**")

    print(f"\n② VARIANCE / LOSING-STREAK (MC {N_PATHS} paths, ทุนหนา {HEALTHY:.0f}฿, {HORIZON} ไม้)")
    print("   *ใช้ทุนหนาเพื่อแยก 'variance' ออกจาก 'ruin ทุนบาง'*")
    dds, streaks = mc_drawdown(pnls, HEALTHY, HORIZON)
    print(f"   max drawdown ที่จะเจอใน {HORIZON} ไม้:  median {np.median(dds):.0f}%  |  "
          f"p90 {np.percentile(dds,90):.0f}%  |  worst {dds.max():.0f}%")
    print(f"   ไม้ติดลบติดกันยาวสุด:            median {np.median(streaks):.0f}  |  "
          f"p90 {np.percentile(streaks,90):.0f}  |  worst {streaks.max():.0f} ไม้")
    lr = 1 - wr
    print(f"   P(ติดลบ 5 ไม้รวด) = {lr**5*100:.0f}%  |  P(10 รวด) = {lr**10*100:.0f}%  (LR={lr:.0%})")
    print("   → **แม้ EV บวก variance ก็พา DD ลึกได้** → ต้องมี buffer + size เล็กพอทน streak")

    print("\n③ VOLATILITY DRAG (geometric < arithmetic)")
    r = np.asarray(pnls) / HEALTHY
    a = r.mean(); s = r.std()
    g = a - s**2 / 2
    print(f"   arithmetic mean return/ไม้ = {a*100:+.2f}%  |  σ = {s*100:.2f}%")
    print(f"   geometric (ทบต้นจริง) ≈ a − σ²/2 = {a*100:+.2f}% − {s**2/2*100:.2f}% = **{g*100:+.2f}%/ไม้**")
    print("   → **variance กิน compound growth** (σ²/2 drag) → เรียบ+เล็ก ชนะ แกว่ง+ใหญ่ ระยะยาว")
    print("=" * 70)
    print("⚠️ resample real trades (n เล็ก, WR ช่วงซวย). ใช้เข้าใจกลไก DD/variance — เก็บ data เพิ่ม → แม่นขึ้น.")


if __name__ == "__main__":
    main()
