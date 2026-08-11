"""agents/sr_entry_gate.py — S/R proximity entry gate (momentum-aware, bars-only, causal).

แนวคิด (user 2026-08-11): ทุก algo ควรเช็คแนวรับ/แนวต้านก่อนเข้า —
  BUY  → ถ้าใกล้ "แนวต้านแข็ง" ที่ยังไม่ทะลุ ≤ block_atr×ATR  → block
  SELL → ถ้าใกล้ "แนวรับแข็ง" ที่ยังไม่ทะลุ  ≤ block_atr×ATR  → block

momentum-aware: มองเฉพาะแนว "ฝั่งตรงข้ามที่ขวางอยู่" (resistance เหนือราคา / support ใต้ราคา).
breakout ที่ทะลุแนวไปแล้ว → แนวนั้นไม่อยู่ข้างหน้าอีก → ผ่านเอง (ไม่ฆ่า edge momentum).
บล็อกเฉพาะเมื่อราคา "ชนกำแพงแข็งที่ยังไม่ผ่าน" (touches ≥ min_touches) = ที่ว่างวิ่งน้อย.

**pure + causal:** ใช้แค่ swing pivot จาก bar ก่อนหน้า (คอนเฟิร์มด้วย ±pivot แท่ง, ทุกแท่ง < i)
→ ไม่มี look-ahead → backtest กับ live เรียก `blocks_at` ตัวเดียวกัน = parity เป๊ะ.
0 token (คำนวณใน code). data นอกไม่เกี่ยว — แนวจาก OHLC เอง.
"""

# params tuple: (lookback, pivot, block_atr, min_touches, cluster_atr)
DEFAULTS = (60, 3, 0.5, 2, 0.3)


def _swing_levels(h, l, i, lookback, pivot):
    """swing highs (resistance) / lows (support) จาก [i-lookback, i-pivot] — causal (คอนเฟิร์มก่อน i)."""
    lo = max(pivot, i - lookback)
    res = []
    sup = []
    for k in range(lo, i - pivot + 1):                 # k+pivot ≤ i → คอนเฟิร์มด้วยแท่งที่ปิดก่อน i แล้ว
        seg_h = h[k - pivot:k + pivot + 1]
        seg_l = l[k - pivot:k + pivot + 1]
        if float(h[k]) >= float(max(seg_h)):
            res.append(float(h[k]))
        if float(l[k]) <= float(min(seg_l)):
            sup.append(float(l[k]))
    return res, sup


def _cluster(levels, tol):
    """merge แนวใกล้กัน (≤ tol) → [(level_mean, touches)]. touches = จำนวน pivot ในกลุ่ม = ความแข็ง."""
    if not levels:
        return []
    levels = sorted(levels)
    merged = [[levels[0], 1]]
    for lv in levels[1:]:
        if abs(lv - merged[-1][0]) <= tol:
            cnt = merged[-1][1] + 1
            merged[-1][0] = (merged[-1][0] * merged[-1][1] + lv) / cnt
            merged[-1][1] = cnt
        else:
            merged.append([lv, 1])
    return merged


def blocks_at(h, l, i, px, d, atr, params=DEFAULTS):
    """True = block entry. h,l = high/low arrays (newest last). i = signal-bar index. px = entry price.
    d = +1 BUY / -1 SELL. atr = ATR ที่ bar นั้น. params = DEFAULTS หรือ params_from_config()."""
    if atr is None or atr <= 0:
        return False
    lookback, pivot, block_atr, min_touches, cluster_atr = params
    if i < pivot + 2:
        return False
    res, sup = _swing_levels(h, l, i, lookback, pivot)
    tol = cluster_atr * atr
    thresh = block_atr * atr
    if d > 0:                                          # BUY: แนวต้านแข็งที่ขวางเหนือราคา + ยังไม่ทะลุ
        cand = [(lv, ct) for lv, ct in _cluster(res, tol) if lv > px]
        if cand:
            lv, ct = min(cand, key=lambda t: t[0])     # ต้านใกล้สุดเหนือราคา
            if (lv - px) < thresh and ct >= min_touches:
                return True
    else:                                              # SELL: แนวรับแข็งที่รองใต้ราคา + ยังไม่ทะลุ
        cand = [(lv, ct) for lv, ct in _cluster(sup, tol) if lv < px]
        if cand:
            lv, ct = max(cand, key=lambda t: t[0])     # รับใกล้สุดใต้ราคา
            if (px - lv) < thresh and ct >= min_touches:
                return True
    return False


def params_from_config():
    """อ่าน params จาก config (hot ผ่าน reload). fallback DEFAULTS ถ้าไม่มี."""
    try:
        import config as _c
        return (
            int(getattr(_c, "SR_LOOKBACK", DEFAULTS[0])),
            int(getattr(_c, "SR_PIVOT", DEFAULTS[1])),
            float(getattr(_c, "SR_BLOCK_ATR", DEFAULTS[2])),
            int(getattr(_c, "SR_MIN_TOUCHES", DEFAULTS[3])),
            float(getattr(_c, "SR_CLUSTER_ATR", DEFAULTS[4])),
        )
    except Exception:
        return DEFAULTS


def _combos_allow():
    """set ของ combo ที่ผ่าน validation (ให้ gate ทำงานเฉพาะตัวที่ backtest พิสูจน์ว่าช่วย).
    data/sr_gate_combos.json = {"combos": ["algo|SYMBOL", ...]}. ว่าง/ไม่มี = ไม่มีตัวไหน gate."""
    import json
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sr_gate_combos.json")
    try:
        return set(json.load(open(p, encoding="utf-8")).get("combos", []))
    except Exception:
        return set()


def blocks_live(bars, direction, price, atr, algo_id=None, symbol=None):
    """live wrapper: เรียกจาก executor. คืน (block: bool, reason: str).
    เคารพ flag SR_ENTRY_GATE + allowlist ต่อ combo (เปิดเฉพาะที่ validation ผ่าน)."""
    try:
        import config as _c
        if not getattr(_c, "SR_ENTRY_GATE", False):
            return False, ""
    except Exception:
        return False, ""
    # allowlist: ถ้ามีไฟล์ combos → gate เฉพาะ combo นั้น; ถ้าไม่มีไฟล์ (ว่าง) → gate ทุกตัว (global mode)
    if algo_id and symbol:
        allow = _combos_allow()
        if allow and f"{algo_id}|{symbol}" not in allow:
            return False, ""
    try:
        h, l, c = bars[0], bars[1], bars[2]
        if c is None or len(c) < 10:
            return False, ""
        d = 1 if str(direction).upper() == "BUY" else -1
        i = len(c) - 1
        if blocks_at(h, l, i, float(price), d, float(atr or 0), params_from_config()):
            side = "แนวต้าน" if d > 0 else "แนวรับ"
            return True, f"S/R gate: {direction} ชน{side}แข็งใกล้ (≤{params_from_config()[2]}×ATR ยังไม่ทะลุ)"
    except Exception:
        return False, ""
    return False, ""
