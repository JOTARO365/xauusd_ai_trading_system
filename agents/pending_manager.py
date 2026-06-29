"""
Pending Order Manager — วาง pending orders อัตโนมัติที่ key S/R levels
ไม่พึ่ง AI signal: ตั้งไว้รอเผื่อ Sentiment เปลี่ยน คำนวณ lot ตามเงินทุน
"""
import json
import os
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta, timezone
from loguru import logger
from connectors.price_feed import get_account_info, get_ohlcv
from connectors.mt5_connector import place_pending_order, get_pending_orders, calculate_lot_size, cancel_pending_order
from agents.reporter import log_pending_order, count_pending_by_direction
from config import SYMBOL, MONEY_MANAGEMENT
import config as _cfg

_MANUAL_RANGE_FILE = os.path.join(os.path.dirname(__file__), "../logs/manual_range.json")


def _get_manual_range() -> tuple[float, float] | tuple[None, None]:
    """อ่าน manual range จาก logs/manual_range.json — คืน (high, low) หรือ (None, None)"""
    try:
        with open(_MANUAL_RANGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        high = float(data.get("high", 0))
        low  = float(data.get("low",  0))
        if high > 0 and low > 0 and high > low:
            return high, low
    except (FileNotFoundError, Exception):
        pass
    return None, None

DUPLICATE_ZONE_PCT = 0.003   # 0.3% — ถือว่า level เดียวกัน, ไม่วางซ้ำ
MIN_DIST_FROM_PRICE = 0.003  # 0.3% — ห่างจากราคาปัจจุบันขั้นต่ำ (ไม่วาง pending ติดราคาเกินไป)
COUNTER_TREND_DIST  = 0.015  # 1.5% — ระยะขั้นต่ำสำหรับ counter-trend pending (extreme S/R เท่านั้น)


# ─────────────────────────────────────────────────────────────
#  LEVEL DETECTION
# ─────────────────────────────────────────────────────────────

def _find_swing_levels_from_rates(rates, window: int = 3, max_levels: int = 6,
                                   dedup_pct: float = 0.004) -> dict:
    """หา swing high/low จาก rates array (ใช้ได้กับ H4 หรือ D1)"""
    df    = pd.DataFrame(rates)
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values

    swing_highs, swing_lows = [], []
    for i in range(window, len(high) - window):
        if all(high[i] >= high[i-j] for j in range(1, window+1)) and \
           all(high[i] >= high[i+j] for j in range(1, window+1)):
            swing_highs.append(round(float(high[i]), 2))
        if all(low[i] <= low[i-j] for j in range(1, window+1)) and \
           all(low[i] <= low[i+j] for j in range(1, window+1)):
            swing_lows.append(round(float(low[i]), 2))

    def dedup(levels):
        levels = sorted(set(levels), reverse=True)
        result = []
        for lv in levels:
            if not result or result[-1] == 0 or abs(lv - result[-1]) / result[-1] > dedup_pct:
                result.append(lv)
        return result

    current = float(close[-1])
    res = sorted([h for h in dedup(swing_highs) if h > current])[:max_levels]
    sup = sorted([l for l in dedup(swing_lows)  if l < current], reverse=True)[:max_levels]
    return {"resistance": res, "support": sup}


def _get_daily_sr() -> dict:
    """ดึง swing S/R จาก D1 — แนวรับแนวต้านระดับใหญ่"""
    rates = get_ohlcv(timeframe=mt5.TIMEFRAME_D1, count=60)
    if rates is None:
        logger.warning("ดึง D1 data ไม่ได้ — ข้าม Daily S/R")
        return {"resistance": [], "support": []}
    return _find_swing_levels_from_rates(rates, window=3, max_levels=5)


def _merge_levels(lists: list[list], current: float, side: str, max_out: int = 4) -> list:
    """
    รวม level จากหลาย timeframe เข้าด้วยกัน
    - dedup ระดับที่ใกล้กัน (< 0.5%) โดยเก็บค่าเฉลี่ย
    - score ตามจำนวน timeframe ที่ยืนยัน
    - คืน level ที่ดีที่สุดเรียงจากใกล้ราคาไปไกล
    """
    all_lvs: dict[float, int] = {}  # level → score
    for lvs in lists:
        for lv in lvs:
            # หา representative level ที่ใกล้ที่สุด
            found = False
            for existing in list(all_lvs.keys()):
                if abs(lv - existing) / existing < 0.005:
                    # merge: เก็บค่าเฉลี่ย, เพิ่ม score
                    merged = round((existing + lv) / 2, 2)
                    score  = all_lvs.pop(existing) + 1
                    all_lvs[merged] = score
                    found = True
                    break
            if not found:
                all_lvs[lv] = 1

    if side == "resistance":
        result = sorted((lv for lv in all_lvs if lv > current),
                        key=lambda lv: (-all_lvs[lv], lv))
    else:
        result = sorted((lv for lv in all_lvs if lv < current),
                        key=lambda lv: (-all_lvs[lv], -lv))

    return result[:max_out]


# ─────────────────────────────────────────────────────────────
#  SENTIMENT PARSER
# ─────────────────────────────────────────────────────────────

def _parse_sentiment(sentiment_data: dict) -> tuple[str, int]:
    """
    คืน (direction, confidence) จาก sentiment_data
    direction: "BUY" | "SELL" | "NEUTRAL"
    """
    raw  = (sentiment_data.get("sentiment") or "NEUTRAL").upper()
    conf = int(sentiment_data.get("confidence") or 0)

    if "BULL" in raw:
        return "BUY", conf
    if "BEAR" in raw:
        return "SELL", conf
    return "NEUTRAL", conf


# ─────────────────────────────────────────────────────────────
#  AUTO PENDING PLACEMENT
# ─────────────────────────────────────────────────────────────

_SL_FLOOR_PENDING     = 600     # SL ขั้นต่ำของ pending (pips)
_PENDING_SL_ZONE_PCT  = 0.003   # 0.3% beyond zone = breakdown ยืนยัน → cut (แทน default 2000 คงที่)


def _structural_sl_pips(entry: float, same_side_levels: list, is_sell: bool,
                        point: float, fallback_pips: int) -> int:
    """A (2026-06-30): SL structural — วาง beyond zone ที่ pending วาง (ทะลุ = setup ผิด → cut เร็ว)
    แทน default 2000 คงที่ (ทำให้ไม้แพ้แพ้เต็ม = R:R พัง ทั้งที่ WR สูง).
    BUY@support → SL ใต้ zone; SELL@resistance → SL เหนือ zone; ถ้ามี S/R ถัดไปใกล้กว่า ใช้ตัวนั้น.
    clamp [_SL_FLOOR_PENDING, fallback_pips]."""
    if not point:
        return fallback_pips
    buf = entry * _PENDING_SL_ZONE_PCT
    if is_sell:                                   # SELL@resistance: SL เหนือ entry
        sl_price = entry + buf
        higher = [l for l in same_side_levels if entry < l < sl_price]
        if higher:
            sl_price = min(higher) + entry * 0.0008
        dist = sl_price - entry
    else:                                         # BUY@support: SL ใต้ entry
        sl_price = entry - buf
        lower = [l for l in same_side_levels if sl_price < l < entry]
        if lower:
            sl_price = max(lower) - entry * 0.0008
        dist = entry - sl_price
    sl = round(dist / point)
    return max(_SL_FLOOR_PENDING, min(sl, fallback_pips))


def auto_place_pending_orders(chart_data: dict, sentiment_data: dict | None = None) -> int:
    """
    วาง pending orders อัตโนมัติที่ key S/R (H4 + Daily) ตาม Sentiment

    Sentiment กำหนดลำดับความสำคัญ:
    - BULLISH  → BUY_LIMIT ที่ support ก่อน (align)  + SELL_LIMIT ที่ resistance (hedge)
    - BEARISH  → SELL_LIMIT ที่ resistance ก่อน (align) + BUY_LIMIT ที่ support (hedge)
    - NEUTRAL  → วางสลับกัน BUY และ SELL เท่ากัน

    ถ้า confidence สูง (≥ 70%): วางเฉพาะทิศทาง align เท่านั้น (ไม่ hedge)
    คำนวณ lot จากเงินทุนและระยะ SL อัตโนมัติ

    Returns: จำนวน pending orders ที่วางใหม่
    """
    # ── C (2026-06-30): parser-alive guard — ไม่วาง pending ถ้า chart วิเคราะห์ไม่ได้ ──
    # conf<=0 = parser fail/data invalid (เคยวาง pending มั่ว conf=0/zone=NONE → fill → โดน SL)
    _chart_conf = chart_data.get("confidence", 0) or 0
    if _chart_conf <= 0:
        logger.info(f"Auto-pending: chart confidence={_chart_conf} (parser ไม่ให้ค่า/data invalid) — skip")
        return 0

    # ── นับ pending ที่มีอยู่แล้วแยก BUY/SELL ─────────────────
    pending_counts = count_pending_by_direction()
    max_buy  = MONEY_MANAGEMENT["max_pending_buy"]
    max_sell = MONEY_MANAGEMENT["max_pending_sell"]
    buy_slots  = max(0, max_buy  - pending_counts["BUY"])
    sell_slots = max(0, max_sell - pending_counts["SELL"])

    if buy_slots <= 0 and sell_slots <= 0:
        logger.info(f"Pending slots เต็มแล้ว (BUY {pending_counts['BUY']}/{max_buy}, SELL {pending_counts['SELL']}/{max_sell})")
        return 0

    logger.info(f"Pending slots remaining — BUY: {buy_slots}/{max_buy}, SELL: {sell_slots}/{max_sell}")

    # ── Sentiment direction ────────────────────────────────────
    sent_dir, sent_conf = _parse_sentiment(sentiment_data or {})
    strong_sentiment    = sent_conf >= 70

    logger.info(
        f"Pending sentiment: {sent_dir} ({sent_conf}%) "
        f"{'— strong, no hedge' if strong_sentiment else '— weak/neutral, will hedge'}"
    )

    # ── Trend alignment ───────────────────────────────────────
    # BULLISH: SELL_LIMIT ได้สูงสุด 1 slot แต่ต้องอยู่ที่ extreme resistance (≥1.5%)
    # BEARISH: BUY_LIMIT ได้สูงสุด 1 slot แต่ต้องอยู่ที่ extreme support (≥1.5%)
    _trend           = chart_data.get("trend", "SIDEWAYS")
    _counter_buy     = False   # BUY วางสวนเทรนด์ BEARISH
    _counter_sell    = False   # SELL วางสวนเทรนด์ BULLISH

    if _trend == "BEARISH" and buy_slots > 0:
        buy_slots    = min(buy_slots, 1)
        _counter_buy = True
        logger.info("Auto-pending: BEARISH trend — BUY_LIMIT จำกัด 1 slot ที่ extreme support (≥1.5%) เท่านั้น")
    elif _trend == "BULLISH" and sell_slots > 0:
        sell_slots    = min(sell_slots, 1)
        _counter_sell = True
        logger.info("Auto-pending: BULLISH trend — SELL_LIMIT จำกัด 1 slot ที่ extreme resistance (≥1.5%) เท่านั้น")

    if buy_slots <= 0 and sell_slots <= 0:
        logger.info("Auto-pending: ไม่มี slots ที่เปิดได้ (หลัง trend filter) — ข้าม")
        return 0

    # ── รวม S/R levels จาก H4 + Daily ────────────────────────
    h4_sr   = chart_data.get("sr_zones", {})
    key_lvl = chart_data.get("key_levels", {}) or {}
    d1_sr   = _get_daily_sr()

    current = chart_data.get("indicators", {}).get("h4", {}).get("close", 0)
    if not current:
        tick = mt5.symbol_info_tick(SYMBOL)
        current = tick.bid if tick else 0
    if not current:
        logger.warning("ไม่มีราคาปัจจุบัน — ข้าม auto-pending")
        return 0

    pdh = key_lvl.get("pdh")
    pdl = key_lvl.get("pdl")
    res_levels = _merge_levels(
        [h4_sr.get("resistance", []),
         d1_sr.get("resistance", []),
         [pdh] if pdh and pdh > current else []],
        current, "resistance", max_out=3,
    )
    sup_levels = _merge_levels(
        [h4_sr.get("support", []),
         d1_sr.get("support", []),
         [pdl] if pdl and pdl < current else []],
        current, "support", max_out=3,
    )

    min_dist      = current * MIN_DIST_FROM_PRICE
    counter_dist  = current * COUNTER_TREND_DIST

    res_min = counter_dist if _counter_sell else min_dist
    sup_min = counter_dist if _counter_buy  else min_dist

    res_levels = [r for r in res_levels if r > current + res_min]
    sup_levels = [s for s in sup_levels if s < current - sup_min]

    if not res_levels and not sup_levels:
        logger.info("ไม่พบ key S/R level ที่เหมาะสำหรับ pending")
        return 0

    info  = mt5.symbol_info(SYMBOL)
    point = info.point if info else 0.01
    _default_sl = MONEY_MANAGEMENT["default_sl_pips"]   # fallback/clamp; SL จริง = structural ต่อ level (A)

    # ── จัดลำดับ tasks ตาม sentiment ─────────────────────────
    buy_task  = ("BUY_LIMIT",  sup_levels, res_levels)
    sell_task = ("SELL_LIMIT", res_levels, sup_levels)

    if sent_dir == "BUY":
        tasks = [buy_task] + ([] if strong_sentiment else [sell_task])
    elif sent_dir == "SELL":
        tasks = [sell_task] + ([] if strong_sentiment else [buy_task])
    else:
        tasks = [buy_task, sell_task]

    # ── วาง orders — แยก slot ตาม BUY/SELL ──────────────────
    existing_prices = [p["price"] for p in get_pending_orders()]
    placed = 0
    used_buy = used_sell = 0

    for pending_type, levels, opposing in tasks:
        is_sell = "SELL" in pending_type
        for level in levels:
            # ตรวจ slot ตาม direction
            if is_sell and used_sell >= sell_slots:
                break
            if not is_sell and used_buy >= buy_slots:
                break

            if _is_covered(level, existing_prices):
                logger.info(f"{pending_type} @ {level:.2f} มี pending อยู่แล้ว — ข้าม")
                continue

            # A: structural SL ต่อ level (beyond zone) แทน 2000 คงที่
            sl_pips = _structural_sl_pips(level, levels, is_sell, point, _default_sl)
            tp_pips = _calc_tp_pips(level, opposing, point,
                                    MONEY_MANAGEMENT["default_tp_pips"], is_sell=is_sell)
            rr = (tp_pips / sl_pips if sl_pips > 0 else 0) if sl_pips > 0 else 0
            if rr < MONEY_MANAGEMENT["min_rr_ratio"]:
                logger.info(f"{pending_type} @ {level:.2f}: RR {rr:.2f} ต่ำ — ข้าม")
                continue

            result = place_pending_order(
                pending_type=pending_type,
                price=level,
                sl_pips=sl_pips,
                tp_pips=tp_pips,
                comment=f"AP {pending_type} {sent_dir[:3]} {level:.0f}",
                expiry_hours=MONEY_MANAGEMENT["pending_expiry_hours"],
            )
            if result.get("success"):
                _log(result, chart_data, sentiment_data)
                existing_prices.append(level)
                placed += 1
                if is_sell:
                    used_sell += 1
                else:
                    used_buy += 1
                logger.info(
                    f"Auto pending: {pending_type} @ {level:.2f} "
                    f"SL={sl_pips}p TP={tp_pips}p RR={rr:.2f}"
                )
            else:
                logger.warning(f"{pending_type} @ {level:.2f} failed: {result.get('error')}")

    return placed


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
#  WEEKLY CALENDAR PENDING (จันทร์เช้า)
# ─────────────────────────────────────────────────────────────

_WEEKLY_TAG = "WK-"


def cancel_pending_on_breakdown(chart_data: dict) -> int:
    """B (2026-06-30): ยกเลิก AP pending fade ที่กำลังจะ fill 'สวน' fast move (zone กำลังแตก).
    ดิ่งลงแรง (fast<0) → ยก BUY_LIMIT (รอ fill ตอนราคาดิ่งต่อ = สวน momentum → ติดลบ);
    พุ่งขึ้นแรง (fast>0) → ยก SELL_LIMIT. ใช้ fast_move_pips + COUNTER_SPIKE_PIPS (เกณฑ์เดียวกับ counter-spike).
    เฉพาะ AP pending (ไม่แตะ RNG-/WK-/manual). คืนจำนวนที่ยกเลิก."""
    thr = _cfg.COUNTER_SPIKE_PIPS
    if thr <= 0:
        return 0
    fast = float(chart_data.get("fast_move_pips", 0) or 0)
    if abs(fast) < thr:
        return 0
    target = "BUY_LIMIT" if fast < 0 else "SELL_LIMIT"
    cancelled = 0
    for o in get_pending_orders():
        if o.get("source") != "SYSTEM":
            continue
        if not str(o.get("comment", "")).startswith("AP "):   # เฉพาะ auto-pending
            continue
        if o.get("pending_type") == target:
            if cancel_pending_order(o["ticket"]):
                cancelled += 1
    if cancelled:
        logger.warning(
            f"[BREAKDOWN] fast_move {fast:+.0f}p ≥ {thr} — ยกเลิก {cancelled} {target} AP pending "
            f"(กัน fill สวน momentum / zone แตก)"
        )
    return cancelled


def _has_weekly_pending() -> bool:
    """ตรวจว่ามี WEEKLY pending orders อยู่แล้วหรือไม่"""
    orders = get_pending_orders()
    return any(str(o.get("comment", "")).startswith(_WEEKLY_TAG) for o in orders)


def place_weekly_calendar_pending(chart_data: dict) -> int:
    """
    วาง BUY_STOP + SELL_STOP ทุกวันจันทร์เช้า ตาม high-impact events สัปดาห์นี้

    Strategy (straddle breakout):
    - BUY_STOP  ที่ resistance ใกล้สุด — จับ breakout ขาขึ้นช่วง news
    - SELL_STOP ที่ support ใกล้สุด    — จับ breakdown ขาลงช่วง news
    - Expiry 7 วัน (ครอบคลุมทั้งสัปดาห์)
    - ข้ามถ้ามี WEEKLY orders อยู่แล้ว หรือไม่มี High-impact events

    Returns: จำนวน weekly pending ที่วางใหม่
    """
    from connectors.web_news import fetch_forexfactory_calendar

    if _has_weekly_pending():
        logger.info("Weekly pending: มี orders อยู่แล้วสัปดาห์นี้ — ข้าม")
        return 0

    # ── ดึง calendar ทั้งสัปดาห์ (7 วัน) ─────────────────────────
    week_events = fetch_forexfactory_calendar(hours_ahead=168)
    high_events = [e for e in week_events if e.get("impact") == "High"]
    if not high_events:
        logger.info("Weekly pending: ไม่มี High-impact events สัปดาห์นี้ — ข้าม")
        return 0

    # ชื่อ events สำคัญ (USD ก่อน)
    usd_first   = sorted(high_events, key=lambda e: e.get("currency") != "USD")
    event_names = "/".join(e["title"][:12] for e in usd_first[:2])
    logger.info(
        f"Weekly pending: {len(high_events)} High-impact events | "
        f"สำคัญ: {event_names}"
    )

    # ── ราคาปัจจุบันและ S/R levels ───────────────────────────────
    current = chart_data.get("indicators", {}).get("h4", {}).get("close", 0)
    if not current:
        tick = mt5.symbol_info_tick(SYMBOL)
        current = tick.bid if tick else 0
    if not current:
        logger.warning("Weekly pending: ไม่มีราคาปัจจุบัน — ข้าม")
        return 0

    h4_sr  = chart_data.get("sr_zones", {})
    d1_sr  = _get_daily_sr()

    res_levels = _merge_levels(
        [h4_sr.get("resistance", []), d1_sr.get("resistance", [])],
        current, "resistance", max_out=3,
    )
    sup_levels = _merge_levels(
        [h4_sr.get("support", []), d1_sr.get("support", [])],
        current, "support", max_out=3,
    )

    min_dist   = current * MIN_DIST_FROM_PRICE
    res_levels = [r for r in res_levels if r > current + min_dist]
    sup_levels = [s for s in sup_levels if s < current - min_dist]

    if not res_levels or not sup_levels:
        logger.warning("Weekly pending: ไม่พบ S/R levels ที่เหมาะสม — ข้าม")
        return 0

    info    = mt5.symbol_info(SYMBOL)
    point   = info.point if info else 0.01
    sl_pips = MONEY_MANAGEMENT["default_sl_pips"]
    max_buy = MONEY_MANAGEMENT["max_pending_buy"]
    max_sell= MONEY_MANAGEMENT["max_pending_sell"]
    min_rr  = MONEY_MANAGEMENT["min_rr_ratio"] * 0.8  # ผ่อนปรน 20% สำหรับ weekly
    short_tag = event_names[:10]

    existing_prices = [p["price"] for p in get_pending_orders()]
    pending_counts  = count_pending_by_direction()
    placed = 0

    # ── BUY_STOP ที่ resistance ───────────────────────────────────
    if pending_counts["BUY"] < max_buy:
        buy_lv = res_levels[0]
        if not _is_covered(buy_lv, existing_prices):
            tp_pips = _calc_tp_pips(buy_lv, res_levels[1:], point,
                                    MONEY_MANAGEMENT["default_tp_pips"], is_sell=False)
            if (tp_pips / sl_pips if sl_pips > 0 else 0) >= min_rr:
                res = place_pending_order(
                    pending_type="BUY_STOP",
                    price=buy_lv,
                    sl_pips=sl_pips,
                    tp_pips=tp_pips,
                    comment=f"{_WEEKLY_TAG}BUY {short_tag}",
                    expiry_hours=168,
                )
                if res.get("success"):
                    existing_prices.append(buy_lv)
                    placed += 1
                    logger.info(f"Weekly BUY_STOP @ {buy_lv:.2f} | {event_names}")
                else:
                    logger.warning(f"Weekly BUY_STOP failed: {res.get('error')}")

    # ── SELL_STOP ที่ support ─────────────────────────────────────
    if pending_counts["SELL"] < max_sell:
        sell_lv = sup_levels[0]
        if not _is_covered(sell_lv, existing_prices):
            tp_pips = _calc_tp_pips(sell_lv, sup_levels[1:], point,
                                    MONEY_MANAGEMENT["default_tp_pips"], is_sell=True)
            if (tp_pips / sl_pips if sl_pips > 0 else 0) >= min_rr:
                res = place_pending_order(
                    pending_type="SELL_STOP",
                    price=sell_lv,
                    sl_pips=sl_pips,
                    tp_pips=tp_pips,
                    comment=f"{_WEEKLY_TAG}SELL {short_tag}",
                    expiry_hours=168,
                )
                if res.get("success"):
                    placed += 1
                    logger.info(f"Weekly SELL_STOP @ {sell_lv:.2f} | {event_names}")
                else:
                    logger.warning(f"Weekly SELL_STOP failed: {res.get('error')}")

    return placed


def _is_covered(level: float, existing_prices: list) -> bool:
    if level == 0:
        return False
    return any(abs(p - level) / level < DUPLICATE_ZONE_PCT for p in existing_prices)


def _calc_tp_pips(entry: float, opposing_levels: list, point: float,
                  default_tp: int, is_sell: bool) -> int:
    """คำนวณ TP pips จาก entry ไปยัง opposing S/R level ที่ใกล้ที่สุด"""
    if opposing_levels:
        if is_sell:
            # SELL_LIMIT: TP = support ที่ต่ำกว่า entry
            targets = [s for s in opposing_levels if s < entry]
        else:
            # BUY_LIMIT: TP = resistance ที่สูงกว่า entry
            targets = [r for r in opposing_levels if r > entry]
        if targets:
            best = targets[0]  # ใกล้สุด
            tp_pips = round(abs(entry - best) / point)
            if tp_pips > 0:
                return tp_pips
    return default_tp


def _log(order_result: dict, chart_data: dict, sentiment_data: dict | None = None):
    """บันทึก auto-pending ลง trades.json ผ่าน log_pending_order"""
    log_pending_order({
        "action":        "PENDING",
        "pending_type":  order_result.get("pending_type"),
        "pending_price": order_result.get("price"),
        "order":         order_result,
        "technical":     chart_data,
        "sentiment":     sentiment_data or {},
    })


# ─────────────────────────────────────────────────────────────
#  SIDEWAYS RANGE PENDING SYSTEM (แยกจาก Weekly + Auto Pending)
# ─────────────────────────────────────────────────────────────

_RANGE_TAG = "RNG-"   # prefix comment สำหรับ range pending orders


def _has_range_pending(direction: str) -> bool:
    """ตรวจว่ามี Range pending orders ฝั่งนี้อยู่แล้วหรือไม่"""
    tag = f"{_RANGE_TAG}{direction[:4].upper()}"   # RNG-BUY / RNG-SELL
    return any(str(o.get("comment", "")).startswith(tag) for o in get_pending_orders())


def cancel_stale_range_pending(current_trend: str) -> int:
    """
    ยกเลิก Range pending orders เมื่อ trend เปลี่ยนจาก SIDEWAYS → BULLISH/BEARISH
    Returns: จำนวน orders ที่ยกเลิก
    """
    if current_trend == "SIDEWAYS":
        return 0
    cancelled = 0
    for o in get_pending_orders():
        if str(o.get("comment", "")).startswith(_RANGE_TAG):
            if cancel_pending_order(o["ticket"]):
                cancelled += 1
                logger.info(
                    f"Range pending cancelled (trend={current_trend}): "
                    f"ticket={o['ticket']} {o.get('pending_type')} @ {o.get('price')}"
                )
    if cancelled:
        logger.info(f"cancel_stale_range_pending: ยกเลิก {cancelled} range orders")
    return cancelled


def _cancel_range_pending_side(direction: str) -> int:
    """Cancel range pending orders on one side after the opposing side has triggered.
    Returns count cancelled."""
    tag = f"{_RANGE_TAG}{direction[:4].upper()}"
    cancelled = 0
    for o in get_pending_orders():
        if str(o.get("comment", "")).startswith(tag):
            if cancel_pending_order(o["ticket"]):
                cancelled += 1
                logger.info(
                    f"Range {direction} pending cancelled (opposing side already triggered): "
                    f"ticket={o['ticket']} @ {o.get('price')}"
                )
    return cancelled


def manage_range_pending(chart_data: dict) -> int:
    """
    Sideways Range Pending — วาง BUY_LIMIT/SELL_LIMIT ที่กรอบอัตโนมัติ

    Logic:
    - ถ้า TREND == SIDEWAYS: คำนวณ Range บน/ล่าง จาก H4 S/R + PDH/PDL
    - BUY_LIMIT  @ range_lower (TP near upper, SL below lower)
    - SELL_LIMIT @ range_upper (TP near lower, SL above upper)
    - ถ้า TREND != SIDEWAYS: ยกเลิก range pending ที่ค้างอยู่

    Guards:
    - Range Width < 2000 pips → skip (กรอบแคบเกิน)
    - H4 ATR > Range Width × 60% → skip (volatile เกิน)
    - มี range pending ฝั่งนั้นอยู่แล้ว → skip

    Returns: จำนวน range pending ที่วางใหม่
    """
    trend = chart_data.get("trend", "SIDEWAYS")

    # ── ยกเลิก stale orders ถ้า trend เปลี่ยน ──────────────────────
    cancel_stale_range_pending(trend)

    # ── Cancel opposing pending เมื่อ 1 ฝั่ง trigger แล้ว ──────────
    # รวบรวม directions ทั้งหมดก่อน แล้ว cancel ฝั่งตรงข้ามครบทุกตัว
    _rng_positions = mt5.positions_get(symbol=SYMBOL) or []
    _has_rng_buy  = any(str(getattr(_p, "comment", "") or "").startswith(f"{_RANGE_TAG}BUY")  for _p in _rng_positions)
    _has_rng_sell = any(str(getattr(_p, "comment", "") or "").startswith(f"{_RANGE_TAG}SELL") for _p in _rng_positions)
    if _has_rng_buy:
        _cancel_range_pending_side("SELL")
    if _has_rng_sell:
        _cancel_range_pending_side("BUY")

    if trend != "SIDEWAYS":
        return 0

    # ── ราคาปัจจุบัน ──────────────────────────────────────────────
    current = chart_data.get("indicators", {}).get("h4", {}).get("close", 0)
    if not current:
        tick = mt5.symbol_info_tick(SYMBOL)
        current = float(tick.bid) if tick else 0.0
    if not current:
        logger.warning("Range pending: ไม่มีราคาปัจจุบัน — ข้าม")
        return 0

    info  = mt5.symbol_info(SYMBOL)
    point = info.point if info else 0.01
    h4_atr = chart_data.get("indicators", {}).get("h4", {}).get("atr", 0)

    # ── Manual Range Override — ถ้ามีค่าจาก Dashboard ใช้เลย ────
    _manual_high, _manual_low = _get_manual_range()
    if _manual_high and _manual_low:
        upper = _manual_high
        lower = _manual_low
        logger.info(f"Range pending: ใช้ Manual Range [{lower:.2f} ─ {upper:.2f}]")
    else:
        # ── Auto-detect จาก H4 S/R + PDH/PDL ─────────────────────
        sr_zones = chart_data.get("sr_zones", {})
        key_lvl  = chart_data.get("key_levels", {}) or {}

        res_list = sorted([r for r in sr_zones.get("resistance", []) if r > current])
        sup_list = sorted([s for s in sr_zones.get("support",    []) if s < current], reverse=True)

        pdh = key_lvl.get("pdh")
        pdl = key_lvl.get("pdl")
        if pdh and pdh > current:
            res_list = sorted(set(res_list + [round(pdh, 2)]))
        if pdl and pdl < current:
            sup_list = sorted(set(sup_list + [round(pdl, 2)]), reverse=True)

        if not res_list or not sup_list:
            logger.info("Range pending: ไม่พบ Range bounds ครบทั้งสองฝั่ง — ข้าม")
            return 0

        upper = res_list[0]
        lower = sup_list[0]

    range_width      = upper - lower
    range_width_pips = round(range_width / point)

    # ── Guards ────────────────────────────────────────────────────
    MIN_WIDTH_PIPS = 2000
    if range_width_pips < MIN_WIDTH_PIPS:
        logger.info(
            f"Range pending: width={range_width_pips}p < {MIN_WIDTH_PIPS}p — กรอบแคบเกิน ข้าม"
        )
        return 0

    if h4_atr > 0 and h4_atr > range_width * 0.60:
        logger.info(
            f"Range pending: ATR={h4_atr:.1f} > width×60%={range_width*0.60:.1f} — volatile ข้าม"
        )
        return 0

    logger.info(
        f"Range [{lower:.2f} ─ {upper:.2f}] width={range_width_pips}p | "
        f"price={current:.2f} | ATR={h4_atr:.1f}"
    )

    # ── SL / TP ───────────────────────────────────────────────────
    # SL = 15% ของ range width (แต่ไม่น้อยกว่า default_sl_pips)
    # TP = 85% ของ range width (จาก entry ถึงอีกฝั่ง − buffer 15%)
    sl_pips = max(round(range_width_pips * 0.15), MONEY_MANAGEMENT["default_sl_pips"])
    tp_pips = round(range_width_pips * 0.85)
    min_rr  = MONEY_MANAGEMENT["min_rr_ratio"]

    if (tp_pips / sl_pips if sl_pips > 0 else 0) < min_rr:
        logger.info(
            f"Range pending: RR={tp_pips/sl_pips:.2f} < {min_rr} — ข้าม"
        )
        return 0

    min_dist = current * MIN_DIST_FROM_PRICE
    placed   = 0

    # ── BUY_LIMIT @ lower ─────────────────────────────────────────
    if lower < current - min_dist:
        if _has_range_pending("BUY"):
            logger.info(f"Range BUY_LIMIT @ {lower:.2f} — มีอยู่แล้ว ข้าม")
        else:
            res = place_pending_order(
                pending_type="BUY_LIMIT",
                price=lower,
                sl_pips=sl_pips,
                tp_pips=tp_pips,
                comment=f"{_RANGE_TAG}BUY {lower:.0f}",
                expiry_hours=72,
            )
            if res.get("success"):
                placed += 1
                logger.info(
                    f"Range BUY_LIMIT @ {lower:.2f} | "
                    f"SL={sl_pips}p TP={tp_pips}p RR={tp_pips/sl_pips:.2f}"
                )
                _log(res, chart_data)
            else:
                logger.warning(f"Range BUY_LIMIT failed: {res.get('error')}")

    # ── SELL_LIMIT @ upper ────────────────────────────────────────
    if upper > current + min_dist:
        if _has_range_pending("SELL"):
            logger.info(f"Range SELL_LIMIT @ {upper:.2f} — มีอยู่แล้ว ข้าม")
        else:
            res = place_pending_order(
                pending_type="SELL_LIMIT",
                price=upper,
                sl_pips=sl_pips,
                tp_pips=tp_pips,
                comment=f"{_RANGE_TAG}SELL {upper:.0f}",
                expiry_hours=72,
            )
            if res.get("success"):
                placed += 1
                logger.info(
                    f"Range SELL_LIMIT @ {upper:.2f} | "
                    f"SL={sl_pips}p TP={tp_pips}p RR={tp_pips/sl_pips:.2f}"
                )
                _log(res, chart_data)
            else:
                logger.warning(f"Range SELL_LIMIT failed: {res.get('error')}")

    return placed


# ─────────────────────────────────────────────────────────────
#  POST-SL RE-ENTRY SYSTEM
# ─────────────────────────────────────────────────────────────

_SLRE_TAG        = "SL-RE-"
_SLRE_WINDOW_MIN = 30   # ตรวจ SL closes ย้อนหลัง N นาที


def _get_recent_sl_closes(minutes: int = _SLRE_WINDOW_MIN) -> list[dict]:
    """
    ดึง deals ที่ปิดด้วย SL ใน N นาทีที่ผ่านมาจาก MT5 deal history
    deal.entry==1 = OUT (closing), deal.reason==4 = SL
    SELL deal (type=1) ปิด BUY position → orig_dir=BUY และในทางกลับกัน
    """
    now     = datetime.now(timezone.utc)
    from_dt = now - timedelta(minutes=minutes)
    deals   = mt5.history_deals_get(from_dt, now)
    if deals is None or len(deals) == 0:
        return []
    result = []
    for d in deals:
        if d.entry == 1 and d.reason == 4 and d.symbol == SYMBOL:
            orig_dir = "BUY" if d.type == 1 else "SELL"
            result.append({"ticket": d.order, "direction": orig_dir, "profit": d.profit})
    return result


def _has_slre_pending(direction: str) -> bool:
    """ตรวจว่ามี SL-RE pending ฝั่งนั้นอยู่แล้วหรือไม่"""
    tag = f"{_SLRE_TAG}{direction[:4].upper()}"   # SL-RE-BUY / SL-RE-SELL
    return any(str(o.get("comment", "")).startswith(tag) for o in get_pending_orders())


def manage_sl_reentry(chart_data: dict) -> int:
    """
    Post-SL Re-entry — หลัง SL hit ให้วาง pending ที่ safe zone ถัดไป

    BUY โดน SL → ราคาร่วง → หา Support ถัดไป → BUY_LIMIT ที่นั่น
    SELL โดน SL → ราคาพุ่ง → หา Resistance ถัดไป → SELL_LIMIT ที่นั่น

    Guards:
    - Trend alignment (BUY re-entry ห้ามใน BEARISH, SELL ห้ามใน BULLISH)
    - มี SL-RE pending ฝั่งนั้นอยู่แล้ว → skip
    - RR < min_rr → skip
    - Overlap กับ pending เดิม → skip

    Returns: จำนวน pending orders ที่วางใหม่
    """
    sl_closes = _get_recent_sl_closes()
    if not sl_closes:
        return 0

    logger.info(f"Post-SL: พบ {len(sl_closes)} SL close(s) ใน {_SLRE_WINDOW_MIN} นาที")

    # ── ราคาปัจจุบัน ──────────────────────────────────────────────
    current = chart_data.get("indicators", {}).get("h4", {}).get("close", 0)
    if not current:
        tick    = mt5.symbol_info_tick(SYMBOL)
        current = float(tick.bid) if tick else 0.0
    if not current:
        logger.warning("Post-SL: ไม่มีราคาปัจจุบัน — ข้าม")
        return 0

    trend    = chart_data.get("trend", "SIDEWAYS")
    sr_zones = chart_data.get("sr_zones", {})
    key_lvl  = chart_data.get("key_levels", {}) or {}
    d1_sr    = _get_daily_sr()

    pdh = key_lvl.get("pdh")
    pdl = key_lvl.get("pdl")

    res_levels = _merge_levels(
        [sr_zones.get("resistance", []), d1_sr.get("resistance", []),
         [pdh] if pdh and pdh > current else []],
        current, "resistance", max_out=4,
    )
    sup_levels = _merge_levels(
        [sr_zones.get("support", []), d1_sr.get("support", []),
         [pdl] if pdl and pdl < current else []],
        current, "support", max_out=4,
    )

    info     = mt5.symbol_info(SYMBOL)
    point    = info.point if info else 0.01
    min_dist = current * MIN_DIST_FROM_PRICE
    sl_pips  = MONEY_MANAGEMENT["default_sl_pips"]
    min_rr   = MONEY_MANAGEMENT["min_rr_ratio"]

    existing_prices = [p["price"] for p in get_pending_orders()]
    placed    = 0
    seen_dirs: set[str] = set()   # ป้องกันวาง SL-RE ซ้ำทิศทางใน loop เดียว

    for trade in sl_closes:
        orig_dir = trade["direction"]
        if orig_dir in seen_dirs:
            continue

        if orig_dir == "BUY":
            if trend == "BEARISH":
                logger.info("Post-SL BUY: ข้ามเพราะ trend=BEARISH (counter-trend)")
                continue
            if _has_slre_pending("BUY"):
                logger.info("Post-SL BUY: มี SL-RE-BUY อยู่แล้ว — ข้าม")
                continue
            # Support ที่ปลอดภัย = สูงสุดที่ยังต่ำกว่าราคา
            safe_lvs = [s for s in sup_levels if s < current - min_dist]
            if not safe_lvs:
                logger.info("Post-SL BUY: ไม่พบ Support level ที่ปลอดภัย — ข้าม")
                continue
            safe_lv = safe_lvs[0]
            if _is_covered(safe_lv, existing_prices):
                logger.info(f"Post-SL BUY_LIMIT @ {safe_lv:.2f} — มี pending อยู่แล้ว ข้าม")
                continue
            tp_pips = _calc_tp_pips(safe_lv, res_levels, point,
                                    MONEY_MANAGEMENT["default_tp_pips"], is_sell=False)
            if (tp_pips / sl_pips if sl_pips > 0 else 0) < min_rr:
                logger.info(f"Post-SL BUY_LIMIT @ {safe_lv:.2f}: RR {tp_pips/sl_pips:.2f} ต่ำ — ข้าม")
                continue
            res = place_pending_order(
                pending_type="BUY_LIMIT",
                price=safe_lv,
                sl_pips=sl_pips,
                tp_pips=tp_pips,
                comment=f"SL-RE-BUY {safe_lv:.0f}",
                expiry_hours=24,
            )
            if res.get("success"):
                placed += 1
                seen_dirs.add("BUY")
                existing_prices.append(safe_lv)
                logger.info(
                    f"Post-SL: BUY_LIMIT @ {safe_lv:.2f} | "
                    f"SL={sl_pips}p TP={tp_pips}p RR={tp_pips/sl_pips:.2f}"
                )
                _log(res, chart_data)
            else:
                logger.warning(f"Post-SL BUY_LIMIT failed: {res.get('error')}")

        else:   # SELL
            if trend == "BULLISH":
                logger.info("Post-SL SELL: ข้ามเพราะ trend=BULLISH (counter-trend)")
                continue
            if _has_slre_pending("SELL"):
                logger.info("Post-SL SELL: มี SL-RE-SELL อยู่แล้ว — ข้าม")
                continue
            # Resistance ที่ปลอดภัย = ต่ำสุดที่ยังสูงกว่าราคา
            safe_lvs = [r for r in res_levels if r > current + min_dist]
            if not safe_lvs:
                logger.info("Post-SL SELL: ไม่พบ Resistance level ที่ปลอดภัย — ข้าม")
                continue
            safe_lv = safe_lvs[0]
            if _is_covered(safe_lv, existing_prices):
                logger.info(f"Post-SL SELL_LIMIT @ {safe_lv:.2f} — มี pending อยู่แล้ว ข้าม")
                continue
            tp_pips = _calc_tp_pips(safe_lv, sup_levels, point,
                                    MONEY_MANAGEMENT["default_tp_pips"], is_sell=True)
            if (tp_pips / sl_pips if sl_pips > 0 else 0) < min_rr:
                logger.info(f"Post-SL SELL_LIMIT @ {safe_lv:.2f}: RR {tp_pips/sl_pips:.2f} ต่ำ — ข้าม")
                continue
            res = place_pending_order(
                pending_type="SELL_LIMIT",
                price=safe_lv,
                sl_pips=sl_pips,
                tp_pips=tp_pips,
                comment=f"SL-RE-SELL {safe_lv:.0f}",
                expiry_hours=24,
            )
            if res.get("success"):
                placed += 1
                seen_dirs.add("SELL")
                existing_prices.append(safe_lv)
                logger.info(
                    f"Post-SL: SELL_LIMIT @ {safe_lv:.2f} | "
                    f"SL={sl_pips}p TP={tp_pips}p RR={tp_pips/sl_pips:.2f}"
                )
                _log(res, chart_data)
            else:
                logger.warning(f"Post-SL SELL_LIMIT failed: {res.get('error')}")

    return placed
