"""agents/structural_sl.py — วาง SL ที่ "ปลายไส้แท่ง D1/H4 ปิดล่าสุด" เสมอ. pure/testable, 0 token, 0 order.

แก้ "เข้าถูกทางแต่โดน SL ก่อน": SL แบบ fixed/ATR วางในที่ว่าง → noise เขี่ยออกก่อนราคาไปต่อ.
กฎ (user directive 07-30): SL **ต้องอยู่ปลายไส้ D1 หรือ H4 เสมอ** ไม่ว่าทุนน้อยแค่ไหน —
  BUY  → SL = low ของแท่งปิดล่าสุด − buffer·ATR   (เลือก TF ตาม mode)
  SELL → SL = high ของแท่งปิดล่าสุด + buffer·ATR
เลือกจากหลาย TF: mode "nearest" = ไส้ใกล้ entry สุด (SL แคบ RR ดี) · "farthest" = ไกลสุด (กัน noise มากสุด).
ไม่ clamp, ไม่ fallback เป็น pip เดิม (ยกเว้น geometry ผิดข้างทุก TF). lot ชดเชยด้วย min-lot.

CORE INVARIANT: level = ไส้แท่งจริง (closed bar) ไม่ prediction, ไม่มี AI.
"""


def near_existing(entry, atr, same_dir_prices, gap_atr):
    """True = มีไม้ทิศเดียวกันเปิดอยู่ภายใน gap_atr·ATR ของ entry → ควร skip (กัน stack เกาะจุดเดิม).
    gap_atr≤0 หรือ atr≤0 → False (ปิด guard). same_dir_prices = ราคาเปิดของไม้ทิศเดียวกัน."""
    if gap_atr <= 0 or atr <= 0 or not same_dir_prices:
        return False
    gap = float(gap_atr) * float(atr)
    return any(abs(float(entry) - float(p)) <= gap for p in same_dir_prices)


def wick_sl(direction, entry, atr, point, wicks, buffer_atr=0.3, mode="nearest"):
    """เลือก SL จากปลายไส้หลาย TF. คืน {sl_pips, sl_price, tf} หรือ None (ทุก TF ผิดข้าง/data ไม่พอ).
    wicks = {"H4": (high, low), "D1": (high, low), ...}. buffer = buffer_atr·ATR."""
    entry = float(entry)
    if entry <= 0 or point <= 0 or not wicks:
        return None
    buf = float(buffer_atr) * float(atr) if atr and atr > 0 else 0.0
    cands = []                                             # (sl_price, tf, dist)
    for tf, hl in wicks.items():
        if not hl:
            continue
        hi, lo = hl
        if not hi or not lo:
            continue
        if direction == "BUY":
            sp = float(lo) - buf
            if sp < entry:                                 # ไส้ล่างต้องต่ำกว่า entry
                cands.append((sp, tf, entry - sp))
        else:
            sp = float(hi) + buf
            if sp > entry:                                 # ไส้บนต้องสูงกว่า entry
                cands.append((sp, tf, sp - entry))
    if not cands:
        return None
    sp, tf, dist = (min(cands, key=lambda c: c[2]) if mode == "nearest"
                    else max(cands, key=lambda c: c[2]))
    return {"sl_pips": dist / point, "sl_price": round(sp, 5), "tf": tf}


def live_adjust(direction, entry, atr, point, symbol, base_sl_pips, base_tp_pips, cfg, enabled):
    """flag-gated end-to-end (impure): ดึงแท่ง D1 ปิดล่าสุด → SL ปลายไส้ เสมอ (ไม่ clamp). คง RR (TP recompute).
    `enabled` = flag ของ path (gold/MSE). ใช้ไม่ได้/ปิด/fail → (base_sl, base_tp, None) = พฤติกรรมเดิม.
    คืน (sl_pips, tp_pips, meta|None). meta.force_min_lot=True → caller ต้องใช้ min lot + ข้าม risk-cap."""
    if not enabled:
        return base_sl_pips, base_tp_pips, None
    if entry <= 0 or point <= 0:
        return base_sl_pips, base_tp_pips, None
    try:
        from agents import htf_levels
        tfs = [t.strip() for t in str(getattr(cfg, "STRUCTURAL_SL_TFS", "H4,D1")).split(",") if t.strip()]
        wicks = {}
        for tf in tfs:
            hl = htf_levels.last_closed_wick(symbol, tf)    # (high, low) แท่ง TF ปิดล่าสุด
            if hl:
                wicks[tf] = hl
        if not wicks:
            return base_sl_pips, base_tp_pips, None
        r = wick_sl(direction, entry, atr, point, wicks,
                    buffer_atr=float(getattr(cfg, "STRUCTURAL_SL_BUFFER_ATR", 0.3)),
                    mode=str(getattr(cfg, "STRUCTURAL_SL_PICK", "nearest")))
        if not r:
            return base_sl_pips, base_tp_pips, None
        sl_pips = r["sl_pips"]
        # เปลี่ยน SL อย่างเดียว, **คง TP เดิม** (ไม่ scale RR): backtest = SL-hit ลดฮวบ + expR ดีสุด
        # (คง RR → TP ไกลเกิน SL กว้าง → ไม้ค้าง timeout → expR แย่). TP เดิม = WR สูง exit เร็ว
        meta = {"tf": r["tf"], "sl_price": r["sl_price"],
                "base_pips": round(base_sl_pips), "struct_pips": round(sl_pips), "force_min_lot": True}
        return sl_pips, base_tp_pips, meta
    except Exception:
        return base_sl_pips, base_tp_pips, None
