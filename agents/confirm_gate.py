"""agents/confirm_gate.py — close-strength (price-action) confirmation gate. bars-only, causal, block-only.

แนวคิด (user 2026-08-13): algo ยิง signal จาก momentum/OHLC ล้วน → เข้าได้แม้แท่งสัญญาณเป็น "แท่งปฏิเสธ"
(ทะลุแนว/แตะ level แล้วโดนตีกลับ ปิดใกล้ปลายตรงข้าม = fakeout/noise). gate นี้กรอง noise ของ algo เอง:
  BUY  → เข้าเฉพาะแท่งสัญญาณ "ปิดแข็งฝั่งบน" (close อยู่ครึ่งบนของแท่ง; ไม่มีไส้บนยาว = ไม่โดนขายกลับ)
  SELL → เข้าเฉพาะแท่งสัญญาณ "ปิดแข็งฝั่งล่าง"

ตัววัด = CLV (close location value) = (close − low) / (high − low), 0..1.
  BUY  block ถ้า clv < thr        (ปิดครึ่งล่าง = ไส้บนยาว = ราคาถูกตีกลับ = สัญญาณอ่อน)
  SELL block ถ้า clv > (1 − thr)  (ปิดครึ่งบน = ไส้ล่างยาว = สัญญาณอ่อน)
thr default 0.5 = ต้องปิดเลยกึ่งกลางแท่งไปฝั่งสัญญาณ (param เดียว, overfit ยาก = price-action confirm แท้).

**pure + causal:** ใช้แค่ high/low/close ของ "แท่งสัญญาณที่ปิดแล้ว" (แท่ง i) → 0 look-ahead → backtest กับ live
เรียก logic เดียวกัน = parity. 0 token (คำนวณใน code). ต่างจาก S/R gate: gate นี้ apply "ทุก algo รวม breakout"
(fakeout ของ breakout = เป้าหลักที่จะกรอง) — ไม่ยกเว้น breakout.
"""

# params tuple: (clv_thr, mode). mode: "cont" = continuation, "rev" = reversal-pin, "off" = ไม่ block
DEFAULTS = (0.5, "cont")
PIN_LB = 4                             # rev: แท่งต้องเจาะ extreme ของ PIN_LB แท่งล่าสุด (pin ที่ปลายจริง)

# per-algo mode: momentum/trend/breakout = cont (ตาม move) · fade/reversal = rev (แท่งกลับตัว)
MODE_BY_ALGO = {
    "regime_momentum": "cont", "regime_momentum_fvg": "cont", "macro_momentum": "cont",
    "confluence_15m": "cont", "cdc_zone": "cont", "tsmom_d1": "cont",
    "mean_reversion": "rev", "sweep_reversal": "rev",
}


def _clv(h, l, i, px):
    rng = float(h[i]) - float(l[i])
    if rng <= 0:
        return None
    return (float(px) - float(l[i])) / rng   # 0 = ปิดที่ low, 1 = ปิดที่ high


def blocks_at(h, l, i, px, d, atr=None, params=DEFAULTS):
    """True = block entry. h,l = high/low arrays (newest last). i = signal-bar index.
    px = close ของแท่งสัญญาณ (= c[i] ใน backtest). d = +1 BUY / -1 SELL.
    mode cont: block แท่งปิดอ่อนฝั่งสัญญาณ (fakeout). mode rev: block ทุกแท่งที่ไม่ใช่ pin กลับตัวที่ปลาย.
    atr = ไม่ใช้ (คงไว้ให้ signature ตรง sr_entry_gate.blocks_at = compose ได้)."""
    clv_thr = params[0]
    mode = params[1] if len(params) > 1 else "cont"
    if mode == "off":
        return False
    clv = _clv(h, l, i, px)
    if clv is None:                    # แท่งไม่มีช่วง (doji/แบน) → ตัดสินไม่ได้ ไม่ block
        return False
    if mode == "rev":                  # fade: ต้องเป็น pin กลับตัวที่ปลาย (เจาะ extreme + ปิดดีดกลับ)
        k = PIN_LB
        if d > 0:                      # hammer: เจาะ low ล่าสุด + ปิดแข็งขึ้น (ไส้ล่างยาว)
            lo = min(float(x) for x in l[max(0, i - k):i + 1])
            pin = (float(l[i]) <= lo) and (clv >= clv_thr)
        else:                          # shooting star: เจาะ high ล่าสุด + ปิดร่วงลง (ไส้บนยาว)
            hi = max(float(x) for x in h[max(0, i - k):i + 1])
            pin = (float(h[i]) >= hi) and (clv <= 1.0 - clv_thr)
        return not pin                 # ไม่ใช่ pin → block
    # mode cont
    if d > 0:
        return clv < clv_thr           # BUY: ปิดครึ่งล่าง = ปฏิเสธ → block
    return clv > (1.0 - clv_thr)       # SELL: ปิดครึ่งบน = ปฏิเสธ → block


def mode_for(algo_id):
    """โหมด confirm ต่อ algo (config CONFIRM_MODE_<ALGO> override ได้). default จาก MODE_BY_ALGO."""
    base = MODE_BY_ALGO.get(algo_id, "cont")
    try:
        import config as _c
        ov = getattr(_c, "CONFIRM_MODE_OVERRIDES", None)
        if isinstance(ov, dict) and algo_id in ov:
            return str(ov[algo_id]).lower()
    except Exception:
        pass
    return base


def params_from_config(algo_id=None):
    """อ่าน params (clv_thr, mode) จาก config (hot ผ่าน reload). mode จาก algo_id."""
    thr = DEFAULTS[0]
    try:
        import config as _c
        thr = float(getattr(_c, "CONFIRM_CLV", DEFAULTS[0]))
    except Exception:
        pass
    return (thr, mode_for(algo_id) if algo_id else DEFAULTS[1])


def blocks_live(bars, direction, price=None, algo_id=None, symbol=None):
    """live wrapper: เรียกจาก executor ก่อน open_order. คืน (block: bool, reason: str).
    เคารพ flag CONFIRM_GATE. ใช้ close ของแท่งล่าสุดที่ปิดแล้ว (ไม่ใช่ tick สด) วัด CLV = confirm จริง
    ไม่ขึ้นกับ slippage. apply ทุก algo (รวม breakout)."""
    try:
        import config as _c
        if not getattr(_c, "CONFIRM_GATE", False):
            return False, ""
    except Exception:
        return False, ""
    try:
        h, l, c = bars[0], bars[1], bars[2]
        if c is None or len(c) < 3:
            return False, ""
        d = 1 if str(direction).upper() == "BUY" else -1
        i = len(c) - 1
        p = params_from_config(algo_id)
        if blocks_at(h, l, i, float(c[i]), d, None, p):
            if p[1] == "rev":
                return True, f"confirm gate (rev): แท่งสัญญาณไม่ใช่ pin กลับตัวที่ปลาย"
            side = "บน" if d > 0 else "ล่าง"
            return True, f"confirm gate (cont): แท่งสัญญาณปิดอ่อน (CLV ไม่ถึง {p[0]} ฝั่ง{side}) = แท่งปฏิเสธ"
    except Exception:
        return False, ""
    return False, ""
