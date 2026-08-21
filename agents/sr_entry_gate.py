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


# breakout/momentum algo = ปล่อยผ่าน gate (edge = ทะลุแนว). ที่เหลือ (fade/reversal) = gate ทุกคู่.
# ⚠️ ใช้เฉพาะ legacy mode (allowlist ว่าง). ถ้าตั้ง allowlist (SR_GATE_COMBOS/ไฟล์) → allowlist ตัดสิน, breakout-tag ไม่เกี่ยว.
_BREAKOUT_DEFAULT = "regime_momentum,regime_momentum_fvg,macro_momentum,confluence_15m,tsmom_d1"


def _breakout_algos():
    """set ของ algo ที่ยกเว้น gate (คิดตาม breakout). config.SR_BREAKOUT_ALGOS (comma) override ได้."""
    try:
        import config as _c
        raw = getattr(_c, "SR_BREAKOUT_ALGOS", _BREAKOUT_DEFAULT)
    except Exception:
        raw = _BREAKOUT_DEFAULT
    return {a.strip() for a in str(raw).split(",") if a.strip()}


import os as _os
import time as _time
import json as _json

_ALLOW_CACHE = {"set": None, "ts": 0.0}                    # cache allowlist (config/ไฟล์) 30s กัน read ถี่ต่อ tick


def _allowlist():
    """set ของ combo "algo|SYMBOL" ที่ให้ gate. มา 2 ทาง (config ก่อน, ไฟล์รอง):
      1. config.SR_GATE_COMBOS (comma "algo|SYM") — opt-in มือ (รวม risk-shape combo ที่ backtest ไม่ผ่านนัยสำคัญ)
      2. data/sr_gate_combos.json "combos" — ตัวที่ผ่าน validation อัตโนมัติ (sr_gate_backtest)
    ว่างทั้งคู่ → คืน set() = legacy mode (blocks_live gate ทุกตัวยกเว้น breakout). cache 30s."""
    now = _time.time()
    if _ALLOW_CACHE["set"] is not None and now - _ALLOW_CACHE["ts"] < 30:
        return _ALLOW_CACHE["set"]
    out = set()
    try:
        import config as _c
        raw = getattr(_c, "SR_GATE_COMBOS", "") or ""
        out = {x.strip() for x in str(raw).split(",") if x.strip()}
    except Exception:
        out = set()
    if not out:                                            # config ว่าง → fallback ไฟล์ validation
        try:
            _base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            with open(_os.path.join(_base, "data", "sr_gate_combos.json"), encoding="utf-8") as f:
                out = {str(x).strip() for x in (_json.load(f).get("combos") or []) if str(x).strip()}
        except Exception:
            out = set()
    _ALLOW_CACHE["set"] = out; _ALLOW_CACHE["ts"] = now
    return out


def _excluded(algo_id, symbol):
    """combo/algo ที่ยกเว้น gate เสมอ (มีหลักฐานว่า gate ทำแย่ เช่น pullback_buy: บล็อก dip กำไร).
    config.SR_GATE_EXCLUDE (comma "algo" หรือ "algo|SYMBOL")."""
    try:
        import config as _c
        raw = getattr(_c, "SR_GATE_EXCLUDE", "") or ""
    except Exception:
        raw = ""
    ex = {x.strip() for x in str(raw).split(",") if x.strip()}
    return bool(algo_id and (algo_id in ex or (symbol and f"{algo_id}|{symbol}" in ex)))


def _gated(algo_id, symbol):
    """combo นี้ควรโดน gate ไหม.
    priority: exclude (หลักฐานว่าแย่) → SR_GATE_ALL (ทุก algo มองโซนก่อน action) → allowlist → legacy."""
    if _excluded(algo_id, symbol):                         # หลักฐาน gate ทำแย่ (เช่น pullback) → ไม่ gate เด็ดขาด
        return False
    try:
        import config as _c
        if getattr(_c, "SR_GATE_ALL", False):              # user 08-21: ทุก algo มองโซนก่อนเข้า (block-only, momentum-aware)
            return True
    except Exception:
        pass
    al = _allowlist()
    if al:                                                 # allowlist mode: list ตัดสินอย่างเดียว (breakout-tag ไม่เกี่ยว)
        return bool(algo_id and symbol and f"{algo_id}|{symbol}" in al)
    return not (algo_id and algo_id in _breakout_algos())  # legacy: gate all except breakout


def blocks_live(bars, direction, price, atr, algo_id=None, symbol=None):
    """live wrapper: เรียกจาก executor. คืน (block: bool, reason: str).
    เคารพ flag SR_ENTRY_GATE + allowlist (SR_GATE_COMBOS/sr_gate_combos.json)."""
    try:
        import config as _c
        if not getattr(_c, "SR_ENTRY_GATE", False):
            return False, ""
    except Exception:
        return False, ""
    if not _gated(algo_id, symbol):                        # ไม่อยู่ allowlist (หรือ breakout ใน legacy) → ปล่อยผ่าน
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


def blocks_live_gold(algo_id, direction, price, atr, tf="H1", symbol="XAUUSD"):
    """entry-path wrapper สำหรับ path ทองที่**ไม่มี h/l/c array อยู่แล้ว** (regime_tick, tsmom_manager).
    fetch บาร์ broker บน tf เอง → เรียก blocks_live. fail-open (error = ไม่ block, live-money ปลอดภัยฝั่งไม่ค้าง).
    เช็ค flag+allowlist ก่อน fetch (ไม่อยู่ allowlist → ไม่เสีย MT5 call)."""
    try:
        import config as _c
        if not getattr(_c, "SR_ENTRY_GATE", False):
            return False, ""
        if not _gated(algo_id, symbol):                    # ข้าม fetch ถ้า combo นี้ไม่ถูก gate
            return False, ""
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        p = params_from_config()
        n = int(p[0]) + int(p[1]) + 5                      # lookback+pivot+buffer พอสำหรับ swing
        tfmap = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
        broker = getattr(_c, "SYMBOL", symbol)
        r = get_ohlcv(broker, tfmap.get(str(tf).upper(), mt5.TIMEFRAME_H1), n)
        if not r or len(r) < 10:
            return False, ""
        h = [float(x["high"]) for x in r]
        l = [float(x["low"]) for x in r]
        c = [float(x["close"]) for x in r]
        return blocks_live((h, l, c), direction, price, atr, algo_id, symbol)
    except Exception:
        return False, ""
