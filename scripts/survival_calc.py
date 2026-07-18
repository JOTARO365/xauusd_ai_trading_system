#!/usr/bin/env python
"""
survival_calc.py — Track 1 (Risk Management) teaching tool: expectancy + risk-of-ruin ของบัญชีจริง

สอนคณิตศาสตร์การรอดจาก trade จริง (logs/trades.json SYSTEM closed):
  1) Expectancy + bootstrap CI (n น้อย = ไม่แน่นอน)
  2) Breakeven WR ที่ RR ปัจจุบัน
  3) Risk of Ruin ผ่าน Monte Carlo (resample trade จริง) ที่ sizing ต่างๆ
  4) บทเรียน: negative expectancy → sizing เปลี่ยนแค่ "ความเร็วตาย" ไม่ใช่ "ตาย/ไม่ตาย"

รัน: python scripts\\survival_calc.py [equity] [ai_floor]
     python scripts\\survival_calc.py 2147.99 1000
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
EQUITY = float(sys.argv[1]) if len(sys.argv) > 1 else 2147.99
AI_FLOOR = float(sys.argv[2]) if len(sys.argv) > 2 else 1000.0   # ต่ำกว่านี้ AI หยุด = ตายเชิงระบบ
TRADES_PER_DAY = 2.0
MAX_TRADES = 1000
N_PATHS = 20000
RNG = np.random.default_rng(0)


def load_pnls():
    td = json.load(open(os.path.join(_BASE, "logs", "trades.json"), encoding="utf-8"))
    trades = td if isinstance(td, list) else td.get("trades", [])
    return [float(t["pnl"]) for t in trades
            if str(t.get("source")) == "SYSTEM" and t.get("status") == "CLOSED" and t.get("pnl") is not None]


def boot_ci(x, fn, B=5000):
    x = np.asarray(x, float)
    vals = [fn(x[RNG.integers(0, len(x), len(x))]) for _ in range(B)]
    return np.percentile(vals, 2.5), np.percentile(vals, 97.5)


def ruin_mc(pnls, scale, e0, floor, n=N_PATHS):
    """Monte Carlo: resample trade จริง (× scale) จาก e0 จนแตะ floor. คืน P(ruin), median trades."""
    p = np.asarray(pnls, float) * scale
    ruined = 0; ttr = []
    for _ in range(n):
        e = e0; t = 0
        while e > floor and t < MAX_TRADES:
            e += p[RNG.integers(0, len(p))]; t += 1
        if e <= floor:
            ruined += 1; ttr.append(t)
    return ruined / n, (np.median(ttr) if ttr else MAX_TRADES)


def main():
    pnls = load_pnls()
    n = len(pnls)
    wins = [x for x in pnls if x > 0]; losses = [x for x in pnls if x <= 0]
    wr = len(wins) / n
    aw = np.mean(wins) if wins else 0; al = np.mean(losses) if losses else 0
    exp = np.mean(pnls)
    rr = (aw / -al) if al < 0 else 0
    be_wr = 1 / (1 + rr) if rr > 0 else 0

    print("=" * 72)
    print(f"SURVIVAL CALCULATOR — Track 1 | equity {EQUITY:.0f}฿ (AI floor {AI_FLOOR:.0f}฿) | n={n} trades")
    print("=" * 72)

    print("\n① EXPECTANCY (กำไรคาดหวังต่อไม้)")
    print(f"   WR {wr*100:.0f}% | avgWin +{aw:.0f}฿ | avgLoss {al:.0f}฿ | RR {rr:.2f}")
    print(f"   E = {wr:.2f}×{aw:.0f} + {1-wr:.2f}×({al:.0f}) = **{exp:+.0f}฿/ไม้**")
    lo, hi = boot_ci(pnls, np.mean)
    print(f"   95% CI (n={n} น้อย!): [{lo:+.0f}, {hi:+.0f}]฿ → "
          f"{'บวก/ลบ ยังไม่ชัด (sample เล็ก)' if lo < 0 < hi else 'ลบชัด' if hi < 0 else 'บวกชัด'}")

    print("\n② RISK PER TRADE + CAPITALIZATION (กฎทอง: เสี่ยง ≤1-2%/ไม้)")
    avg_loss_pct = -al / EQUITY * 100
    worst = -min(pnls); worst_pct = worst / EQUITY * 100
    print(f"   avgLoss {-al:.0f}฿ = **{avg_loss_pct:.0f}% ของ equity/ไม้** | worst {worst:.0f}฿ = {worst_pct:.0f}% (ไม้เดียว!)")
    print(f"   → เสี่ยง {avg_loss_pct:.0f}%/ไม้ ควร ≤2% = **สูงไป ~{avg_loss_pct/2:.0f} เท่า** (undercapitalized)")
    need_001 = (-al * 0.5) / 0.02       # equity ที่ทำให้ avgLoss@0.01lot = 2%
    need_002 = (-al) / 0.02             # equity ที่ทำให้ avgLoss@0.02lot = 2%
    print(f"   ทุนที่ 'ปลอดภัย' (avgLoss = 2%): **~{need_001:,.0f}฿ (0.01 lot) / ~{need_002:,.0f}฿ (0.02 lot)**")
    print(f"   → ที่ {EQUITY:.0f}฿ แม้ lot ต่ำสุด (0.01) ก็เสี่ยง ~{avg_loss_pct/2:.0f}%/ไม้ = ยังสูงเกิน 2x")

    print("\n③ BREAKEVEN WR (ที่ RR นี้)")
    print(f"   ต้อง WR ≥ 1/(1+{rr:.2f}) = **{be_wr*100:.0f}%** ถึงจะไม่ขาดทุน")
    print(f"   ปัจจุบัน WR {wr*100:.0f}% {'< breakeven → EV ลบ ❌' if wr < be_wr else '≥ breakeven → EV บวก ✅'}")

    print(f"\n④ RISK OF RUIN (Monte Carlo {N_PATHS} paths, resample trade จริง)")
    print(f"   {'sizing':>16} | {'P(ruin ≤1000ไม้)':>16} | {'median ไม้ถึงตาย':>16} | {'≈ วัน':>8}")
    for label, scale in [("0.02 lot (ปัจจุบัน)", 1.0), ("0.01 lot (regime/min)", 0.5), ("0.005 (สมมติ)", 0.25)]:
        pr, med = ruin_mc(pnls, scale, EQUITY, AI_FLOOR)
        days = med / TRADES_PER_DAY
        print(f"   {label:>16} | {pr*100:>14.0f}% | {med:>13.0f} ไม้ | {days:>6.0f}")

    print("\n" + "=" * 72)
    print("④ บทเรียนโหลดแบก:")
    if wr < be_wr:
        print("   • EV ลบ → **sizing เปลี่ยนแค่ 'ความเร็วตาย' ไม่ใช่ 'ตาย/ไม่ตาย'** — ลด lot = ยืดเวลา ไม่ใช่รอด")
        print("   • **คุณ size ออกจาก negative expectancy ไม่ได้** — ต้องแก้ที่ WR/RR (หา edge) หรือหยุดเทรด")
        print(f"   • แต่ n={n} เล็ก + CI คร่อม 0 → อาจแค่ช่วงซวย (DB เก่า ~47.6% WR) → **ยัง 'ไม่รู้' EV จริง**")
        print("   • เมื่อไม่รู้ EV → **size เล็กสุด + เก็บ data** จน 'รู้' ก่อนค่อยเพิ่ม (นี่คือเหตุผล regime-sizing/DRY_RUN)")
    else:
        print("   • EV บวก → sizing จัดการ variance ได้; fractional Kelly เป็นเพดาน")
    print("   • drawdown math: −50% ต้อง +100% กลับ → หลีกเลี่ยง drawdown ลึก = สำคัญกว่าไล่กำไร")
    print("=" * 72)
    print("⚠️ pnl scale เชิงเส้นกับ lot (ประมาณ). n เล็ก = MC บอกภาพ ไม่ใช่ทำนายแม่น. เก็บ data เพิ่ม → แม่นขึ้น.")


if __name__ == "__main__":
    main()
