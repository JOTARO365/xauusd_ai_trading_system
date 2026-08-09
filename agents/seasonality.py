"""agents/seasonality.py — gold monthly seasonal bias (structural, validated 08-09).

validated บน XAUUSD D1 2014-2026: ม.ค +3.53%(t2.73,pos75%) · ธ.ค +1.52%(t2.35,pos64%) = bull ชัด (t>2);
มิ.ย/ก.ย/พ.ย avg ลบ pos<40% = bear. fundamental: อินเดีย festival/wedding + year-end demand.
ใช้เป็น structural gate: "ไม่สวน seasonality แรง" (เหมือน macro/sentiment gate) — XAU เท่านั้น. flag-gated.
CORE INVARIANT คง: seasonality = filter ทิศ (data-driven) ไม่ prediction, ไม่ตัดสิน entry เอง.
"""
STRONG_BULL = {1, 12}      # t>2, pos≥64% — ไม่ short ทอง
WEAK = {6, 9, 11}          # avg ลบ, pos<40% — ไม่ long ทอง


def gold_bias(month):
    """+1 bull / −1 bear / 0 neutral ตามเดือน (1-12)."""
    if month in STRONG_BULL:
        return 1
    if month in WEAK:
        return -1
    return 0


def blocks(symbol, direction, month):
    """True = entry นี้สวน seasonality แรง → ควร block (XAU เท่านั้น).
    block SHORT ในเดือน bull แรง · block LONG ในเดือน weak. เดือน neutral = ไม่ block."""
    if not symbol or not str(symbol).upper().startswith("XAU"):
        return False
    b = gold_bias(int(month))
    d = 1 if str(direction).upper() == "BUY" else -1
    return (b == 1 and d == -1) or (b == -1 and d == 1)
