#!/usr/bin/env python
"""
sizing_calc.py — Track 1 บทที่ 2: Position Sizing + Kelly (สอนจากบัญชีจริง)

  1) Fixed-fractional — lot ที่ทำให้เสี่ยง X% ของ equity (รากฐานที่ควรใช้)
  2) Kelly criterion — f* = WR − (1−WR)/RR = สัดส่วนที่โตเร็วสุด (แต่เป็นเพดาน ไม่ใช่เป้า)
  3) Fractional Kelly (½, ¼) — ทำไม full Kelly over-bet
  4) 2 scenario WR (sample 20% vs DB 47.6%) → Kelly แกว่งแรง = ทำไมต้อง p ที่ calibrated + conservative

รัน: python scripts\\sizing_calc.py [equity] [avgloss_at_002lot] [RR]
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

EQUITY = float(sys.argv[1]) if len(sys.argv) > 1 else 2147.99
AVGLOSS_002 = float(sys.argv[2]) if len(sys.argv) > 2 else 309.0   # ฿ ที่เสียเฉลี่ย/ไม้ ที่ 0.02 lot (SL proxy)
RR = float(sys.argv[3]) if len(sys.argv) > 3 else 2.34
MIN_LOT, MAX_LOT = 0.01, 0.03
WR_SAMPLE, WR_DB = 0.20, 0.476   # 35-trade sample vs full DB


def lot_for_risk(risk_pct):
    """lot ที่ทำให้ risk = risk_pct ของ equity (scale เชิงเส้นจาก 0.02 lot = AVGLOSS_002 ฿)."""
    risk_baht = EQUITY * risk_pct
    return 0.02 * risk_baht / AVGLOSS_002


def kelly(wr, rr):
    return wr - (1 - wr) / rr


def main():
    print("=" * 70)
    print(f"POSITION SIZING + KELLY — equity {EQUITY:.0f}฿ | SL≈{AVGLOSS_002:.0f}฿@0.02lot | RR {RR:.2f}")
    print("=" * 70)

    print("\n① FIXED-FRACTIONAL (เสี่ยง X% ของ equity/ไม้) — รากฐาน")
    print("   สูตร: lot = (equity × risk%) ÷ (SL เป็น฿ต่อ lot)")
    print(f"   {'target risk':>12} | {'risk ฿':>7} | {'lot ที่ต้องใช้':>14} | หมายเหตุ")
    for rp in (0.005, 0.01, 0.02):
        lot = lot_for_risk(rp)
        note = ("✅ ทำได้" if lot >= MIN_LOT else f"❌ < min {MIN_LOT} (ทุนน้อยไป)")
        print(f"   {rp*100:>10.1f}% | {EQUITY*rp:>6.0f}฿ | {lot:>13.4f} | {note}")
    real_pct = AVGLOSS_002 / EQUITY * 100
    minlot_pct = (AVGLOSS_002 * MIN_LOT / 0.02) / EQUITY * 100
    print(f"   → ปัจจุบัน 0.02 lot = เสี่ยง {real_pct:.0f}% | แม้ min {MIN_LOT} = เสี่ยง {minlot_pct:.0f}% (กฎ ≤2%)")

    print("\n② KELLY CRITERION — f* = WR − (1−WR)/RR (สัดส่วนโตเร็วสุด, = เพดาน)")
    for tag, wr in [("sample (WR 20%)", WR_SAMPLE), ("DB เก่า (WR 47.6%)", WR_DB)]:
        f = kelly(wr, RR)
        if f <= 0:
            print(f"   {tag:>18}: f* = {f:+.2%} → **ติดลบ = Kelly บอก 'อย่าเดิมพัน'** (WR < breakeven)")
        else:
            print(f"   {tag:>18}: f* = {f:+.2%} (full) | ½K {f/2:.1%} | ¼K {f/4:.1%}")

    print("\n③ บทเรียนโหลดแบก:")
    print(f"   • Kelly แกว่ง {kelly(WR_SAMPLE,RR):+.0%} ↔ {kelly(WR_DB,RR):+.0%} แค่เปลี่ยน WR estimate")
    print("     → **Kelly ไวต่อ p มาก** → ต้องใช้ p ที่ calibrated + วัดจาก n ใหญ่ (คุณมี n=35 = เดา)")
    print("   • **full Kelly over-bet** (est error → ~50% chance เจอ 50% drawdown) → ใช้ ¼–½ Kelly เสมอ")
    print("   • Kelly เป็น **เพดาน** — cap ด้วย fixed-fractional 2% เสมอ (อันไหนเล็กกว่าใช้อันนั้น)")
    print("   • **ไม่รู้ p → ใช้ปลายอนุรักษ์** (สมมติ WR ต่ำ). ที่ WR 20% Kelly=ลบ → เดิมพัน 0 = เก็บ data ก่อน")
    print("=" * 70)
    print("⚠️ scale เชิงเส้น (ประมาณ). Kelly ต้อง p จริง — ใช้เป็นกรอบคิด ไม่ใช่สูตรตายตัวบน n เล็ก.")


if __name__ == "__main__":
    main()
