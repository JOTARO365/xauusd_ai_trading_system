"""agents/structural_sl.py — วาง SL พิงแนว D1/W1 S/R + ATR buffer. pure, testable, 0 token, 0 order.

แก้ "เข้าถูกทางแต่โดน SL ก่อน": SL แบบ fixed/ATR วางในที่ว่าง → noise เขี่ยออกก่อนราคาไปต่อ.
วาง SL "พ้นแนวโครงสร้าง" (แนวที่ราคาต้อง break ถึงจะ invalidate ไม้) + buffer → stop พิงของจริง.

opt-in ต่อไม้: ใช้เฉพาะเมื่อแนวโครงสร้างอยู่ในช่วง [MIN,MAX]×ATR; นอกช่วง/ไม่มีแนว → คืน SL เดิม
(base_sl_pips) ไม่เปลี่ยนพฤติกรรม. ตรง CORE INVARIANT: level = swing จริง ไม่ใช่ prediction.
"""


def adjust_sl_pips(direction, entry, atr, point, levels, base_sl_pips,
                   buffer_atr=0.3, min_atr=0.5, max_atr=4.0):
    """คืน (sl_pips, reason, meta).

    direction  : "BUY" | "SELL"
    entry      : ราคาเข้า (float)
    atr        : ATR ปัจจุบัน (ราคา, ไม่ใช่ pip)
    point      : point ของ symbol (ราคา/pip)
    levels     : จาก htf_levels.nearest_levels → {"support":{level,tf}, "resistance":{...}}
    base_sl_pips : SL เดิม (fallback เมื่อโครงสร้างใช้ไม่ได้)

    BUY  → SL ใต้ support ที่ต่ำกว่า entry ลงมา buffer·ATR
    SELL → SL เหนือ resistance ที่สูงกว่า entry ขึ้นไป buffer·ATR
    """
    base = float(base_sl_pips)
    if entry <= 0 or atr <= 0 or point <= 0 or not levels:
        return base, "no-data", None
    lvl = (levels.get("support") if direction == "BUY" else levels.get("resistance"))
    if not lvl or lvl.get("level") is None:
        return base, "no-htf-level", None
    level = float(lvl["level"])
    buf = float(buffer_atr) * atr

    if direction == "BUY":
        sl_price = level - buf
        if sl_price >= entry:                              # แนวไม่ได้อยู่ใต้ entry จริง → ใช้ไม่ได้
            return base, "level-not-below", None
        dist = entry - sl_price
    else:
        sl_price = level + buf
        if sl_price <= entry:
            return base, "level-not-above", None
        dist = sl_price - entry

    sl_pips = dist / point
    atr_pips = atr / point
    lo = float(min_atr) * atr_pips if min_atr > 0 else 0.0
    hi = float(max_atr) * atr_pips if max_atr > 0 else float("inf")
    if sl_pips < lo:
        return base, f"too-close({sl_pips:.0f}p<{lo:.0f}p)", None
    if sl_pips > hi:
        return base, f"too-far({sl_pips:.0f}p>{hi:.0f}p)", None

    meta = {"level": round(level, 5), "tf": lvl.get("tf"), "sl_price": round(sl_price, 5),
            "base_pips": round(base), "struct_pips": round(sl_pips)}
    return sl_pips, "structural", meta


def live_adjust(direction, entry, atr, point, symbol, base_sl_pips, base_tp_pips, cfg, enabled):
    """flag-gated end-to-end (impure): ดึงแนว HTF จาก MT5 + adjust SL + คง RR (TP recompute).
    ใช้ร่วมกัน MSE + gold. `enabled` = flag ของ path นั้น (gold/MSE แยกกัน — backtest ต่างผล).
    default OFF / fail / ใช้ไม่ได้ → (base_sl, base_tp, None). คืน (sl_pips, tp_pips, meta|None)."""
    if not enabled:
        return base_sl_pips, base_tp_pips, None
    if atr <= 0 or point <= 0 or entry <= 0:
        return base_sl_pips, base_tp_pips, None
    try:
        from agents import htf_levels
        tfs = tuple(t.strip() for t in getattr(cfg, "STRUCTURAL_SL_TFS", "D1,W1").split(",") if t.strip())
        levels = htf_levels.from_mt5(symbol, entry, tfs=tfs, atr=atr)
        sl_pips, reason, meta = adjust_sl_pips(
            direction, entry, atr, point, levels, base_sl_pips,
            buffer_atr=float(getattr(cfg, "STRUCTURAL_SL_BUFFER_ATR", 0.3)),
            min_atr=float(getattr(cfg, "STRUCTURAL_SL_MIN_ATR", 0.5)),
            max_atr=float(getattr(cfg, "STRUCTURAL_SL_MAX_ATR", 4.0)))
        if reason != "structural" or meta is None:
            return base_sl_pips, base_tp_pips, None
        tp_pips = base_tp_pips
        if base_tp_pips > 0 and base_sl_pips > 0:
            tp_pips = (base_tp_pips / base_sl_pips) * sl_pips     # คง RR เดิม
        return sl_pips, tp_pips, meta
    except Exception:
        return base_sl_pips, base_tp_pips, None
