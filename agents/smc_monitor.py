"""agents/smc_monitor.py — SMC context monitor (compute-in-code, 0 token, DISPLAY-ONLY).

จาก research (skill smc-ict-quant-evidence): SMC ไม่มี directional edge หลัง cost →
ใช้เป็น "บริบท/เฝ้าดู" เท่านั้น ไม่ป้อน entry/gate (คง CORE INVARIANT). โชว์:
  • unfilled FVG (H1/H4) — imbalance ที่ราคายังไม่กลับมาเติม (ตัวสะอาดสุดที่ backtestได้)
  • liquidity map — prior-day/week H/L + round number (Osler kernel จริง: order กระจุกที่เลขกลม)
  • sweep flag — ราคาแตะเลย level แล้วปิดกลับเข้าใน + เตือน "sweep→มัก continuation อย่า fade"

pure functions บน bars (ไม่แตะ MT5) → unit-test ได้. caller (dashboard) ป้อน bars มาเอง.
bars = dict {"o":[],"h":[],"l":[],"c":[],"t":[]} oldest-first (float/int). ใช้แท่งปิด (ตัดแท่งกำลังก่อ = index -1).
"""
from __future__ import annotations


def _round_levels(price: float, step: float, n: int = 2):
    """คืน [(level, dist_pips)] ของเลขกลม step รอบ price (n ชั้นบน+ล่าง). gold pip=$0.01."""
    if price <= 0 or step <= 0:
        return []
    base = round(price / step) * step
    out = []
    for k in range(-n, n + 1):
        lv = round(base + k * step, 2)
        if lv <= 0:
            continue
        out.append({"level": lv, "dist_pips": round(abs(price - lv) / 0.01)})
    return sorted(out, key=lambda x: x["dist_pips"])


def unfilled_fvgs(bars: dict, tf: str, max_age: int = 60, max_out: int = 4):
    """FVG 3 แท่ง (bull: low[i] > high[i-2]; bear: high[i] < low[i-2]) ที่ 'ยังไม่ถูกเติม'.
    filled = ราคาหลังจากนั้นวิ่งกลับเข้า gap. คืนล่าสุดที่ยังไม่เติม (สดสุดก่อน). causal (ใช้แท่งปิด)."""
    h, l, o, c = bars["h"], bars["l"], bars["o"], bars["c"]
    n = len(c)
    end = n - 1                      # ตัดแท่งกำลังก่อตัว (index n-1 = ล่าสุดปิด ถ้า caller ส่งเฉพาะปิด; เผื่อไว้ใช้ n-1)
    out = []
    # สแกนย้อนจากใหม่ไปเก่า ในกรอบ max_age
    lo = max(2, end - max_age)
    for i in range(end, lo - 1, -1):
        if i < 2:
            break
        gap_dir = None
        if l[i] > h[i - 2] and c[i - 1] > o[i - 1]:
            gap_dir, top, bot = "bull", l[i], h[i - 2]      # gap = [bot, top]
        elif h[i] < l[i - 2] and c[i - 1] < o[i - 1]:
            gap_dir, top, bot = "bear", l[i - 2], h[i]
        if gap_dir is None:
            continue
        # เติมยัง? ราคาแท่งหลัง i วิ่งเข้าช่วง [bot,top] หรือยัง
        filled = False
        for j in range(i + 1, end + 1):
            if l[j] <= top and h[j] >= bot:
                filled = True
                break
        if not filled:
            out.append({"tf": tf, "dir": gap_dir, "top": round(top, 2), "bot": round(bot, 2),
                        "mid": round((top + bot) / 2, 2), "size_pips": round((top - bot) / 0.01),
                        "age_bars": end - i})
        if len(out) >= max_out:
            break
    return out


def liquidity_map(price: float, pdh, pdl, pwh, pwl):
    """prior-day/week H/L + round number ($5/$10/$50) รอบราคา + ระยะ (pips)."""
    lv = []
    def _add(name, p):
        if p and p > 0:
            lv.append({"name": name, "level": round(float(p), 2),
                       "dist_pips": round(abs(price - float(p)) / 0.01),
                       "side": "above" if p > price else "below"})
    _add("PDH", pdh); _add("PDL", pdl); _add("PWH", pwh); _add("PWL", pwl)
    rounds = _round_levels(price, 10.0, 2) + _round_levels(price, 50.0, 1)
    seen = set()
    for r in rounds:
        if r["level"] in seen:
            continue
        seen.add(r["level"])
        lv.append({"name": f"R{int(r['level'])}", "level": r["level"], "dist_pips": r["dist_pips"],
                   "side": "above" if r["level"] > price else "below"})
    return sorted(lv, key=lambda x: x["dist_pips"])[:10]


def sweep_status(bars: dict, pdh, pdl):
    """แท่งปิดล่าสุดแตะเลย PDH/PDL แล้วปิดกลับเข้าใน = sweep. คืน dict หรือ None.
    NOTE (research): sweep→มัก CONTINUATION ไม่ใช่ reversal — เตือน 'อย่า fade'."""
    h, l, c = bars["h"], bars["l"], bars["c"]
    if len(c) < 1 or not pdh or not pdl:
        return None
    i = len(c) - 1
    if h[i] > pdh and c[i] < pdh:
        return {"level": "PDH", "price": round(float(pdh), 2), "dir": "swept_high",
                "note": "แตะเหนือ PDH แล้วปิดกลับ — sweep บน. research: มัก continuation อย่า fade"}
    if l[i] < pdl and c[i] > pdl:
        return {"level": "PDL", "price": round(float(pdl), 2), "dir": "swept_low",
                "note": "แตะใต้ PDL แล้วปิดกลับ — sweep ล่าง. research: มัก continuation อย่า fade"}
    return None


def build(price: float, h1: dict, h4: dict, pdh=None, pdl=None, pwh=None, pwl=None, regime=None):
    """รวมทุกอย่างเป็น payload เดียวสำหรับ dashboard. display-only."""
    return {
        "ok": True,
        "price": round(float(price), 2) if price else None,
        "regime": regime,
        "fvg": (unfilled_fvgs(h4, "H4") + unfilled_fvgs(h1, "H1")) if (h1 and h4) else [],
        "liquidity": liquidity_map(price, pdh, pdl, pwh, pwl) if price else [],
        "sweep": sweep_status(h1, pdh, pdl) if h1 else None,
        "note": "SMC = บริบท/เฝ้าดูเท่านั้น ไม่ป้อน entry (backtest: ไม่มี edge หลัง cost)",
    }
