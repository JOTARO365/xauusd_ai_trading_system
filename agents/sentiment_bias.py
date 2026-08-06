"""agents/sentiment_bias.py — turn the −100..+100 sentiment score into a SOFT directional bias.

CORE INVARIANT stays intact: price/data still decides the entry. Sentiment only *nudges* —
it never flips a signal or forces a trade. When a signal is AGAINST the sentiment score it must
(a) break the level by a bit more (extra_margin_atr) and (b) size down (lot_mult toward a floor);
when it AGREES (or sentiment is within the neutral deadband) nothing changes.

Pure compute, 0 token, import-safe. Gated by config.SENTIMENT_BIAS (default OFF = kill switch).
"""


def compute(direction, score):
    """direction = 'BUY'/'SELL', score = −100..+100. Returns:
        {aligned, block, lot_mult (≤1), extra_margin_atr (≥0), score}
    - aligned/neutral (|score|<deadband หรือทิศตรง sentiment) → ไม่แตะ.
    - counter + |score| ≥ SENTIMENT_BLOCK_ABOVE → block=True (conviction สูง → ห้ามเข้าทิศผิด, รอทิศที่ถูก).
    - counter อ่อนกว่านั้น → soft: lot เล็กลง + ต้อง break แรงขึ้น (data ยังนำ)."""
    import config as _cfg
    s = int(score or 0)
    T = int(getattr(_cfg, "SENTIMENT_BIAS_DEADBAND", 20))
    floor = float(getattr(_cfg, "SENTIMENT_LOT_FLOOR", 0.5))
    marg = float(getattr(_cfg, "SENTIMENT_MARGIN_MULT", 0.5))
    block_above = int(getattr(_cfg, "SENTIMENT_BLOCK_ABOVE", 0) or 0)

    counter = (s <= -T and direction == "BUY") or (s >= T and direction == "SELL")
    if not counter:                                   # aligned หรืออยู่ใน deadband → ไม่แตะ
        return {"aligned": True, "block": False, "lot_mult": 1.0, "extra_margin_atr": 0.0, "score": s}

    block = block_above > 0 and abs(s) >= block_above  # สวน sentiment แรง → veto ทิศผิด (เลือกทิศถูก)
    frac = min(1.0, (abs(s) - T) / max(1, 100 - T))    # 0..1 = สวนแรงแค่ไหน (พ้น deadband)
    lot_mult = max(floor, 1.0 - frac * (1.0 - floor))
    return {"aligned": False, "block": block, "lot_mult": round(lot_mult, 3),
            "extra_margin_atr": round(marg * frac, 3), "score": s}
