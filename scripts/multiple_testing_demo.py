#!/usr/bin/env python
"""
multiple_testing_demo.py — Track 2 บทที่ 1: ทำไม backtest โกหก (multiple testing / selection bias)

สาธิตให้เห็นกับตา: ลองกลยุทธ์ N อันที่ **ไม่มี edge เลย (สุ่มล้วน)** แล้วเลือกอันดีสุด →
Sharpe ตัวชนะดู "เทพ" ทั้งที่เป็น noise 100%. E[max Sharpe] โตตาม √(2·ln N).

→ บทเรียน: **"ลองกี่ครั้ง (N)" คือข้อมูลสำคัญสุดที่มักหายไป** — backtest ที่ไม่บอก N = อ่านไม่ได้.
   นี่คือเหตุผลที่ต้อง Deflated Sharpe (บทถัดไป) หัก N ออกก่อนเชื่อ.

รัน: python scripts\\multiple_testing_demo.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

RNG = np.random.default_rng(0)
T = 252        # 1 ปี daily
TRIALS = 1000  # MC เพื่อหา E[max]


def best_of_n_sharpe(N):
    """E[max Sharpe ของ N กลยุทธ์ zero-edge 1 ปี] + สัดส่วนที่ 'ดูดี' (Sharpe>1)."""
    maxes = np.empty(TRIALS)
    good = 0
    for i in range(TRIALS):
        R = RNG.normal(0.0, 0.01, (N, T))          # zero-edge: mean=0
        sh = R.mean(1) / R.std(1) * np.sqrt(T)     # annualized Sharpe แต่ละกลยุทธ์
        maxes[i] = sh.max()
        if sh.max() > 1.0:
            good += 1
    return maxes.mean(), good / TRIALS


def main():
    print("=" * 72)
    print("MULTIPLE TESTING — ลองกลยุทธ์ 'สุ่มล้วน (0 edge)' N อัน แล้วเลือกตัวชนะ")
    print("=" * 72)
    print(f"(แต่ละกลยุทธ์ = {T} วัน daily return mean=0 = ไม่มี edge จริงเลย)\n")
    print(f"  {'N (จำนวนที่ลอง)':>16} | {'E[max Sharpe]':>13} | {'√(2·lnN) ทฤษฎี':>15} | {'% ที่ Sharpe>1':>14}")
    print("  " + "-" * 66)
    for N in (1, 5, 20, 100, 500, 2000):
        emax, pgood = best_of_n_sharpe(N)
        theo = np.sqrt(2 * np.log(N)) if N > 1 else 0.0
        print(f"  {N:>16} | {emax:>13.2f} | {theo:>15.2f} | {pgood*100:>12.0f}%")

    print("\n" + "=" * 72)
    print("บทเรียนโหลดแบก:")
    print("  • ลอง 100 กลยุทธ์ที่ไม่มี edge → ตัวชนะ Sharpe ~2.5-3 = **ดูเทพ แต่ noise 100%**")
    print("  • E[max Sharpe] โตตาม **√(2·ln N)** — ยิ่งลองเยอะ ยิ่งเจอ 'ตัวสวย' จากโชค")
    print("  • **'ลองกี่ครั้ง' = fact สำคัญสุดที่มักหายไป** — รวมทุก param/variant/ไอเดียที่ทิ้ง")
    print("  • backtest ที่ไม่บอก N (หรือคุณจำไม่ได้ว่าลองไปกี่อัน) = **อ่านไม่ได้/เชื่อไม่ได้**")
    print("  • นี่คือ selection bias / data-snooping = ตัวฆ่าอันดับ 1 → ต้อง Deflated Sharpe (บทถัดไป) หัก N")
    print("=" * 72)
    print("เชื่อมโยง session: ที่เราทำ btc_validate/gold — นับ N config แล้ว 'หัก' ด้วย DSR ก่อนเชื่อ = เพราะเหตุนี้")


if __name__ == "__main__":
    main()
