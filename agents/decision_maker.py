import anthropic
from datetime import datetime, timezone as _tz
from pathlib import Path
from connectors.mt5_connector import open_order, get_open_positions, count_protected_slots, check_open_slot, _is_momentum_strong
from connectors.price_feed import get_account_info
from agents.reporter import get_trade_history_summary
import config as _cfg
from config import ANTHROPIC_API_KEY, MONEY_MANAGEMENT
from loguru import logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Order fail streak tracker ─────────────────────────────────────────────────
_order_fail_streak: dict[str, int] = {"BUY": 0, "SELL": 0}
_FAIL_STREAK_WARN = 3   # warning เมื่อ fail ≥ N ครั้งติดกัน

SYSTEM_PROMPT = Path("agents/prompts/decision_maker.md").read_text(encoding="utf-8")

MIN_TECHNICAL_CONFIDENCE = 50

_last_usage = None   # set after each API call — read by accountant

_MAX_TP_SCALE = 2.0   # TP ขยายได้สูงสุด 2× default_tp_pips (= 10,000 pips)


def _effective_min_rr(chart_data: dict, sentiment_data: dict) -> float:
    """
    คำนวณ minimum R:R ที่ยอมรับได้ตามสภาพตลาด
    ตลาดร้อนแรง (US session, ATR สูง, momentum แรง) → ลด R:R threshold
    ตลาดเงียบ → คืน default จาก config
    """
    base     = MONEY_MANAGEMENT["min_rr_ratio"]
    hour_utc = datetime.now(_tz.utc).hour
    h4_atr   = chart_data.get("indicators", {}).get("h4", {}).get("atr", 0)
    mom_tf   = chart_data.get("momentum_tf", {})
    mom_m15  = mom_tf.get("m15", {})
    mom_h1   = mom_tf.get("h1", {})
    nearest  = sentiment_data.get("nearest_event_minutes", 9999)

    hot = 0
    if 13 <= hour_utc < 17:    hot += 2   # London/NY overlap
    elif 7 <= hour_utc < 20:   hot += 1   # London / NY

    if h4_atr > 30:   hot += 2
    elif h4_atr > 20: hot += 1

    if mom_m15.get("strength") == "STRONG":
        hot += 2 if mom_h1.get("direction") == mom_m15.get("direction") else 1

    if nearest <= 30: hot += 1   # event ใกล้ → ยืดหยุ่น TP

    # floor 1.5 เสมอ — ต่ำกว่านี้แพ้ทุกครั้งที่ WR < 40%
    if hot >= 5: return 1.5
    if hot >= 3: return 1.7
    if hot >= 1: return 1.8
    return base


def _session_name(hour_utc: int) -> str:
    if 13 <= hour_utc < 17: return "London/NY Overlap"
    if 7  <= hour_utc < 13: return "London"
    if 17 <= hour_utc < 22: return "NY"
    return "Asian"


def _get_entry_wr(entry_type: str, entry_perf_text: str) -> str:
    """ดึง WR/count ของ entry_type ที่ระบุจาก entry_perf_text (1 บรรทัด)"""
    for line in entry_perf_text.splitlines():
        if entry_type in line:
            return line.strip()
    return f"{entry_type}: no history"


def _last_trade_in_dir_lost(direction: str, recent_trades: list) -> bool:
    """True ถ้า trade v2 ล่าสุดในทิศทางนี้ขาดทุน
    ใช้ตัดสินใจว่าจะให้ bonus slot หรือไม่"""
    same_dir = [
        t for t in recent_trades
        if t.get("direction", "").upper() == direction.upper()
        and t.get("pnl") is not None
    ]
    if not same_dir:
        return False
    return (same_dir[-1].get("pnl") or 0) < 0


# ─────────────────────────────────────────────────────────────
#  GATE LAYER — Python-only quantitative filters
# ─────────────────────────────────────────────────────────────

def _run_gates(chart_data: dict, sentiment_data: dict, advisor_data: dict | None,
               history: dict, account: dict) -> dict:
    """
    รัน quantitative gate ทั้งหมด ไม่ใช้ Claude
    คืน: {"pass": bool, "reason": str, "direction": str,
           "sl_pips": float, "tp_pips": float, "confidence": int,
           "tech_signal": str}
    """
    tech_signal = chart_data.get("signal", "NO_TRADE")
    trend       = chart_data.get("trend", "SIDEWAYS")
    sr_zone     = chart_data.get("sr_zone", "NONE")
    sr_str      = chart_data.get("sr_strength", "NORMAL")
    conf        = chart_data.get("confidence", 0)
    entry_type  = chart_data.get("entry_type", "NONE")

    def _fail(reason: str) -> dict:
        return {"pass": False, "reason": reason}

    # ── NNLB mode: ข้าม gates ทั้งหมดยกเว้นทิศทาง ────────────────
    if _cfg.NNLB_MODE:
        if tech_signal == "NO_TRADE":
            # HTF zone override: ถ้าราคาอยู่ที่ D1/W1 zone ให้ใช้ zone_type เป็น direction
            # แต่ต้อง trend-aligned เท่านั้น — ป้องกัน counter-trend entry ที่ zone กำลังถูกทะลุ
            _htf = chart_data.get("htf_zone")
            if _htf:
                _htf_dir  = "BUY" if _htf["zone_type"] == "SUPPORT" else "SELL"
                _trend    = (trend or "").upper()
                # SUPPORT + BEARISH → zone likely to break → skip
                # RESISTANCE + BULLISH → zone likely to break → skip
                _counter  = (_htf["zone_type"] == "SUPPORT"    and _trend == "BEARISH") or \
                             (_htf["zone_type"] == "RESISTANCE" and _trend == "BULLISH")
                if _counter:
                    return _fail(
                        f"NNLB HTF override blocked: {_htf['zone_type']} ใน trend {_trend} "
                        f"— counter-trend zone มักถูกทะลุ ({_htf['tf']} @ {_htf['level']})"
                    )
                tech_signal = f"HTF_{_htf_dir}"
                chart_data["signal"] = _htf_dir
                logger.warning(
                    f"[NNLB] HTF zone override: NO_TRADE → {_htf_dir} "
                    f"({_htf['tf']} {_htf['zone_type']} @ {_htf['level']} dist={_htf['dist_pct']}%)"
                )
            else:
                # Trend Continuation: EMA pullback ใน trending market — ไม่ต้องการ zone
                # เงื่อนไข: H1+H4 EMA stack aligned + ราคาอยู่ใกล้ H1 EMA20 ≤ 0.3% (pullback zone)
                _trend_upper = (trend or "").upper()
                _h1    = chart_data.get("indicators", {}).get("h1", {})
                _h4    = chart_data.get("indicators", {}).get("h4", {})
                _px    = float(_h1.get("close") or 0)
                _e20   = float(_h1.get("ema20") or 0)
                _e50   = float(_h1.get("ema50") or 0)
                _h4e20 = float(_h4.get("ema20") or 0)
                _h4e50 = float(_h4.get("ema50") or 0)

                _tc_dir = None
                if _px and _e20 and _e50 and _h4e20 and _h4e50:
                    # H1 + H4 EMA stack ยืนยันแนวโน้ม — ไม่ต้องตรวจ proximity (EMA stack คือ filter)
                    if (_trend_upper == "BEARISH"
                            and _e20 < _e50                  # H1 EMA bearish order
                            and _h4e20 < _h4e50):            # H4 ยืนยัน
                        _tc_dir = "SELL"
                    elif (_trend_upper == "BULLISH"
                            and _e20 > _e50                  # H1 EMA bullish order
                            and _h4e20 > _h4e50):
                        _tc_dir = "BUY"

                if _tc_dir:
                    tech_signal = f"TREND_CONT_{_tc_dir}"
                    chart_data["signal"]     = _tc_dir
                    chart_data["confidence"] = 55            # moderate — no zone anchor
                    chart_data["entry_type"] = "EMA_PULLBACK"
                    conf = 55
                    # SL = H4 ATR (clamped), TP = SL × 2  → R:R = 2.0
                    _h4_atr = float(chart_data.get("indicators", {}).get("h4", {}).get("atr") or 0)
                    _tc_sl  = int(min(max(round(_h4_atr / 0.01), 500), 3500)) if _h4_atr else 1500
                    _tc_tp  = _tc_sl * 2
                    chart_data["sell_sl_pips"] = _tc_sl
                    chart_data["buy_sl_pips"]  = _tc_sl
                    chart_data["tp_pips"]      = _tc_tp
                    logger.warning(
                        f"[TREND_CONT] {_trend_upper} EMA pullback → {_tc_dir} | "
                        f"H1 EMA20={_e20:.2f} price={_px:.2f} "
                        f"SL={_tc_sl}p TP={_tc_tp}p (ATR={_h4_atr:.1f})"
                    )
                else:
                    return _fail("NNLB: NO_TRADE signal (ไม่มีทิศทาง)")
        if "BUY" in tech_signal:
            direction = "BUY"
        elif "SELL" in tech_signal:
            direction = "SELL"
        else:
            return _fail(f"NNLB: ทิศทางไม่ชัดเจน: {tech_signal}")
        sl_pips = float(chart_data.get("buy_sl_pips" if direction == "BUY" else "sell_sl_pips")
                        or MONEY_MANAGEMENT["default_sl_pips"])
        tp_pips = float(chart_data.get("tp_pips") or MONEY_MANAGEMENT["default_tp_pips"])
        # NNLB streak protection — ถึงแม้ NNLB จะข้าม gates แต่ยังต้องหยุดเมื่อ streak สูง
        if _cfg.STREAK_PROTECTION:
            _nnlb_streak = history.get("losing_streak", 0)
            _max_s       = getattr(_cfg, "MAX_LOSING_STREAK", 5)
            if _nnlb_streak >= _max_s:
                return _fail(f"NNLB: losing streak {_nnlb_streak}L ≥ {_max_s} — หยุดชั่วคราว")

        # NNLB slot/BE check — opposing positions ต้อง protected หรือกำไรก่อนเปิดฝั่งตรงข้าม
        # ข้าม quality gates ทั้งหมด แต่ยังป้องกันการเปิด order ที่ทำให้ขาดทุนซ้อนกัน
        _last_lost = _last_trade_in_dir_lost(direction, history.get("recent_trades", []))
        _can_open, _slot_reason = check_open_slot(direction, last_dir_lost=_last_lost)
        if not _can_open:
            return _fail(f"NNLB: {_slot_reason}")

        logger.warning(f"[NNLB] ข้าม gates ทั้งหมด — {direction} SL={sl_pips:.0f}p TP={tp_pips:.0f}p conf={conf}%")
        return {
            "pass":         True,
            "reason":       "NNLB_MODE",
            "direction":    direction,
            "tech_signal":  tech_signal,
            "sl_pips":      sl_pips,
            "tp_pips":      tp_pips,
            "confidence":   conf,
            "streak_scale": 1.0,
        }

    # 1. Daily loss limit
    if _cfg.PORTFOLIO_PROTECTION and account.get("balance", 0) > 0:
        daily_loss_pct = abs(min(history["today_pnl"], 0)) / account["balance"]
        if daily_loss_pct >= MONEY_MANAGEMENT["max_daily_loss"]:
            return _fail(f"Max daily loss {MONEY_MANAGEMENT['max_daily_loss']*100:.0f}% reached")

    # 2. NO_TRADE — ตรวจ momentum override
    if tech_signal == "NO_TRADE":
        mom_tf = chart_data.get("momentum_tf", {})
        m15    = mom_tf.get("m15", {})
        h1     = mom_tf.get("h1", {})
        m15_dir = m15.get("direction")
        can_mo  = (
            m15.get("strength") == "STRONG" and
            m15_dir == h1.get("direction") and
            m15_dir in ("UP", "DOWN") and
            trend != "SIDEWAYS"
        )
        if not can_mo:
            return _fail("NO_TRADE signal")

        mo_dir   = "BUY" if m15_dir == "UP" else "SELL"
        h4_match = (trend == "BULLISH" and mo_dir == "BUY") or (trend == "BEARISH" and mo_dir == "SELL")
        sent_ok  = sentiment_data.get("bias", "NEUTRAL") in ("NEUTRAL", mo_dir)
        if not (h4_match and sent_ok):
            return _fail("NO_TRADE — momentum override ไม่ตรง H4/sentiment")

        tech_signal = f"MOM_{mo_dir}"
        conf = max(conf, 55)
        chart_data["signal"]     = tech_signal
        chart_data["confidence"] = conf
        logger.info(f"Momentum override: NO_TRADE → {tech_signal} (conf={conf})")

    # หา effective direction
    if "BUY" in tech_signal:
        direction = "BUY"
    elif "SELL" in tech_signal:
        direction = "SELL"
    else:
        return _fail(f"ทิศทางไม่ชัดเจน: {tech_signal}")

    # 3. UNKNOWN trend — ไม่เทรดเมื่อ trend ไม่ชัดเจน (WR 32% ใน historical data)
    if not trend or trend.upper() in ("UNKNOWN", "?", ""):
        return _fail(f"UNKNOWN trend — ไม่เทรดเมื่อทิศทาง H4 ไม่ชัดเจน")

    # 4. Counter-trend block
    is_counter = (trend == "BULLISH" and direction == "SELL") or \
                 (trend == "BEARISH" and direction == "BUY")
    if is_counter:
        at_strong = sr_str == "STRONG" and sr_zone in ("RESISTANCE", "SUPPORT")
        if not (at_strong and conf >= 80):
            return _fail(f"Counter-trend {direction} blocked (trend={trend}, conf={conf}, need 80%)")

    # 5. SIDEWAYS — range bounce strategy
    # อนุญาต: SR_ZONE bounce ที่ขอบ range, MOMENTUM_BREAKOUT (breakout จาก range)
    # ไม่อนุญาต: trend-following (EMA_PULLBACK, TREND_CONT) — ไม่มี trend ใน range
    if trend == "SIDEWAYS":
        # Fix 1 — High ATR means range is expanding (breakout forming), not tradeable
        _sw_h4_atr = chart_data.get("indicators", {}).get("h4", {}).get("atr", 0)
        if _sw_h4_atr > 35:
            return _fail(f"SIDEWAYS + high ATR ({_sw_h4_atr:.1f}) — market too volatile for range trade, likely breaking out")
        # Fix 3 — Ensure range is wide enough to fit TP inside
        _sw_sr   = chart_data.get("sr_zones", {})
        _sw_px   = float(chart_data.get("indicators", {}).get("h1", {}).get("close") or 0)
        if _sw_px and _sw_sr:
            _res_above = sorted([r for r in _sw_sr.get("resistance", []) if r > _sw_px])
            _sup_below = sorted([s for s in _sw_sr.get("support", []) if s < _sw_px], reverse=True)
            if _res_above and _sup_below:
                _range_pips = (_res_above[0] - _sup_below[0]) / 0.01
                if _range_pips < 1500:
                    return _fail(f"SIDEWAYS range too narrow ({_range_pips:.0f}p < 1500p) — SL would exceed range")
        _is_trend_follow = entry_type == "EMA_PULLBACK" or "TREND_CONT" in tech_signal
        _at_sr_zone      = sr_zone in ("RESISTANCE", "SUPPORT")
        _is_breakout     = entry_type == "MOMENTUM_BREAKOUT"

        if _is_trend_follow:
            return _fail("SIDEWAYS — trend-following blocked, ใช้ range bounce ที่ SR zone เท่านั้น")
        if not _at_sr_zone and not _is_breakout:
            return _fail("SIDEWAYS — ต้องอยู่ที่ SR zone หรือ MOMENTUM_BREAKOUT")
        if _at_sr_zone:
            _sw_min = 52 if sr_str == "STRONG" else 60
            if conf < _sw_min:
                return _fail(f"SIDEWAYS SR_ZONE ({sr_str}) requires conf ≥{_sw_min}% (got {conf}%)")
        elif _is_breakout and conf < 65:
            return _fail(f"SIDEWAYS MOMENTUM_BREAKOUT requires conf ≥65% (got {conf}%)")

    # 5b. Session gate — Asian/dead-zone sessions block weak entries (data shows Asian = noise)
    _sess_hour        = datetime.now(_tz.utc).hour
    _in_quiet_session = not (7 <= _sess_hour < 21)   # Asian 0-7 UTC or dead zone 21-24 UTC
    if _in_quiet_session:
        _sess_lbl = "Asian (quiet)" if _sess_hour < 7 else "NY Close (quiet)"
        if entry_type in ("EMA_PULLBACK", "STRUCTURE_PULLBACK") and conf < 72:
            return _fail(f"{_sess_lbl}: EMA/structure entries require conf ≥72% (got {conf}%)")
        if sr_zone == "NONE" and conf < 72:
            return _fail(f"{_sess_lbl}: no-zone entries blocked — conf {conf}% < 72%")

    # 5c. SELL at RESISTANCE in BEARISH trend — WR=39% historically, require STRONG zone + high conf
    if direction == "SELL" and trend == "BEARISH" and sr_zone == "RESISTANCE":
        if not (sr_str == "STRONG" and conf >= 80):
            return _fail(f"SELL+RESISTANCE in BEARISH: WR=39% — requires STRONG zone + conf >=80% (got {sr_str}/{conf}%)")

    # 6. Min confidence — ลด threshold ถ้าอยู่ที่ D1/W1 major zone
    htf_zone = chart_data.get("htf_zone")
    _min_conf = MIN_TECHNICAL_CONFIDENCE
    if htf_zone:
        if htf_zone["tf"] == "W1":
            _min_conf = 42   # W1 zone: โอกาสพลิกกลับสูง — ยอมรับ conf ต่ำกว่า
        elif htf_zone["tf"] == "D1":
            _min_conf = 45   # D1 zone: structural level
        logger.info(
            f"[HTF] {htf_zone['tf']} zone detected — gate 5 threshold: {_min_conf}% "
            f"(ปกติ {MIN_TECHNICAL_CONFIDENCE}%)"
        )
    if conf < _min_conf:
        return _fail(f"Confidence {conf}% < {_min_conf}% (HTF={htf_zone['tf'] if htf_zone else 'none'})")

    # 6. Entry-type gates
    if entry_type == "EMA_PULLBACK" and conf < 75:
        return _fail(f"EMA_PULLBACK requires conf ≥75% (got {conf}%)  [WR 26% historical]")
    if entry_type == "ENGULFING" and conf < 75:
        return _fail(f"ENGULFING requires conf ≥75% (got {conf}%)")

    # MOMENTUM_BREAKOUT: require higher conf threshold at gate 7+8
    # Other entries: conf ≥ 62 is enough
    _hour_utc      = datetime.now(_tz.utc).hour
    _ln_ny_overlap = 12 <= _hour_utc < 16   # London/NY overlap (12-16 UTC)
    _mo_threshold  = 65 if _ln_ny_overlap else 70
    _gate_min_conf = _mo_threshold if entry_type == "MOMENTUM_BREAKOUT" else 62

    # 7. No SR zone
    if sr_zone == "NONE" and conf < _gate_min_conf:
        _tag = " [LN/NY overlap]" if _ln_ny_overlap else ""
        return _fail(f"No SR zone requires conf ≥{_gate_min_conf}%{_tag} (got {conf}%)")

    # 8. ATR gate — ตลาดผันผวน
    h4_atr = chart_data.get("indicators", {}).get("h4", {}).get("atr", 0)
    if h4_atr > 20 and conf < _gate_min_conf:
        return _fail(f"High ATR ({h4_atr:.1f}) requires conf ≥{_gate_min_conf}% (got {conf}%)")

    # 9. Regime alignment
    adv         = advisor_data or {}
    regime_bias = adv.get("bias", "NEUTRAL")
    regime      = adv.get("regime", "")
    is_cnt_reg  = (regime_bias == "BULLISH" and direction == "SELL") or \
                  (regime_bias == "BEARISH" and direction == "BUY")
    if "TRANSITION" in regime and conf < 52:
        return _fail(f"TRANSITION regime requires conf ≥52% (got {conf}%)")
    if is_cnt_reg and conf < 55:
        return _fail(f"Counter-trend vs {regime_bias} regime requires conf ≥55% (got {conf}%)")

    # 10. Max open trades + hedge slot
    # ถ้า trade ล่าสุดทิศนี้แพ้ → ตัด bonus slot (ป้องกัน pyramid ทิศเดียวหลัง trend เปลี่ยน)
    _last_lost = _last_trade_in_dir_lost(direction, history.get("recent_trades", []))
    can_open, slot_reason = check_open_slot(direction, last_dir_lost=_last_lost)
    if not can_open:
        return _fail(slot_reason)

    # 11. Losing streak — hard block + gradual position reduction
    streak_scale = 1.0
    if _cfg.STREAK_PROTECTION:
        streak      = history["losing_streak"]
        max_streak  = getattr(_cfg, "MAX_LOSING_STREAK", 5)
        min_conf_st = getattr(_cfg, "STREAK_MIN_CONFIDENCE", 62)

        if streak >= max_streak:
            return _fail(f"Losing streak {streak}L ≥ MAX_LOSING_STREAK={max_streak} — หยุดเทรดชั่วคราว")

        if streak >= 2 and conf < min_conf_st:
            return _fail(f"Streak {streak}L requires conf ≥{min_conf_st}% (got {conf}%)")

        if streak >= 4:
            streak_scale = 0.40
        elif streak == 3:
            streak_scale = 0.60
        elif streak == 2:
            streak_scale = 0.80
        if streak >= 2:
            logger.info(f"Streak protection: streak={streak}L → size ×{streak_scale:.2f}")

    # 12. SL validation
    sl_key  = "buy_sl_pips" if direction == "BUY" else "sell_sl_pips"
    wick_sl = chart_data.get(sl_key)
    if wick_sl is None or not (500 <= wick_sl <= 3500):
        return _fail(f"SL {wick_sl} out of valid range 500–3500 pips")

    return {
        "pass":         True,
        "reason":       "",
        "direction":    direction,
        "tech_signal":  tech_signal,
        "sl_pips":      float(wick_sl),
        "tp_pips":      float(chart_data.get("tp_pips", MONEY_MANAGEMENT["default_tp_pips"])),
        "confidence":   conf,
        "streak_scale": streak_scale,
    }


# ─────────────────────────────────────────────────────────────
#  MAIN DECISION FUNCTION
# ─────────────────────────────────────────────────────────────

def make_decision(chart_data: dict, sentiment_data: dict, advisor_data: dict | None = None) -> dict:
    logger.info("Agent 4 (ผู้ตัดสินใจ): รัน gates และตัดสินใจ...")

    account = get_account_info()
    history = get_trade_history_summary()

    # ── Gate layer — Python-only, ไม่เรียก Claude ────────────────
    gate = _run_gates(chart_data, sentiment_data, advisor_data, history, account)
    if not gate["pass"]:
        logger.debug(f"Gate failed: {gate['reason']}")
        return {"action": "SKIP", "reason": gate["reason"],
                "trade_quality": "C", "confidence_score": 0}

    direction   = gate["direction"]
    sl_pips     = gate["sl_pips"]
    tp_pips     = gate["tp_pips"]
    tech_signal = gate["tech_signal"]
    conf        = gate["confidence"]
    trend       = chart_data.get("trend", "SIDEWAYS")

    # NNLB fast-path: HTF zone override หรือ TREND_CONT — ข้าม Claude เข้า order ทันที
    if _cfg.NNLB_MODE and ("TREND_CONT" in tech_signal or tech_signal.startswith("HTF_")):
        tag = "HTF_ZONE" if tech_signal.startswith("HTF_") else "TREND_CONT"
        logger.warning(
            f"[{tag}] Fast-path → {direction} SL={sl_pips:.0f}p TP={tp_pips:.0f}p "
            f"(skipping Claude — NNLB)"
        )
        order_result = open_order(
            direction=direction,
            sl_pips=sl_pips,
            tp_pips=tp_pips,
            comment=f"{tag}_{direction}|NNLB",
        )
        if not order_result.get("success"):
            err = order_result.get("error", "unknown")
            logger.error(f"[TREND_CONT] Order rejected by MT5: {err}")
            return {"action": "SKIP", "reason": f"TREND_CONT order failed: {err}",
                    "trade_quality": "C", "confidence_score": 0}
        return {
            "action":           "EXECUTE",
            "direction":        direction,
            "trade_quality":    "B",
            "confidence_score": conf,
            "order":            order_result,
            "technical":        chart_data,
            "sentiment":        sentiment_data,
        }

    # SIDEWAYS TP: target ขอบ range ฝั่งตรงข้าม แทน fixed 2×SL
    if trend == "SIDEWAYS":
        _sr_zones = chart_data.get("sr_zones", {})
        _px = float(chart_data.get("indicators", {}).get("h1", {}).get("close") or 0)
        if _px:
            if direction == "BUY" and _sr_zones.get("resistance"):
                _res = sorted([r for r in _sr_zones["resistance"] if r > _px])
                if _res:
                    _rng_tp = round((_res[0] - _px) / 0.01 * 0.85)   # 85% ไปฝั่ง resistance
                    if _rng_tp >= sl_pips * 1.5:
                        logger.info(f"[SIDEWAYS] TP {tp_pips:.0f}p → {_rng_tp}p (range boundary {_res[0]:.2f})")
                        tp_pips = float(_rng_tp)
            elif direction == "SELL" and _sr_zones.get("support"):
                _sup = sorted([s for s in _sr_zones["support"] if s < _px], reverse=True)
                if _sup:
                    _rng_tp = round((_px - _sup[0]) / 0.01 * 0.85)   # 85% ไปฝั่ง support
                    if _rng_tp >= sl_pips * 1.5:
                        logger.info(f"[SIDEWAYS] TP {tp_pips:.0f}p → {_rng_tp}p (range boundary {_sup[0]:.2f})")
                        tp_pips = float(_rng_tp)

    # ── Clean summary สำหรับ Claude (~15 บรรทัด) ─────────────────
    hour_utc    = datetime.now(_tz.utc).hour
    session     = _session_name(hour_utc)
    entry_type  = chart_data.get("entry_type", "NONE")
    sr_zone     = chart_data.get("sr_zone", "NONE")
    sr_str      = chart_data.get("sr_strength", "NORMAL")

    candle_pat  = chart_data.get("candle_pat", {})
    sr_actions  = chart_data.get("sr_actions", [])
    pa_str      = (f"{sr_actions[0]['action']} @ {sr_actions[0]['level']}"
                   if sr_actions else "no PA signal")
    candle_str  = (f"{candle_pat.get('patterns',['—'])[0]} body={candle_pat.get('body_pct',0)}%"
                   if candle_pat else "—")

    mom_tf      = chart_data.get("momentum_tf", {})
    mom_h4      = mom_tf.get("h4", {})
    mom_h1      = mom_tf.get("h1", {})
    mom_m15     = mom_tf.get("m15", {})
    mom_str     = (f"H4:{mom_h4.get('direction','?')}_{mom_h4.get('strength','?')} "
                   f"H1:{mom_h1.get('direction','?')}_{mom_h1.get('strength','?')} "
                   f"M15:{mom_m15.get('direction','?')}_{mom_m15.get('strength','?')}")

    adv         = advisor_data or {}
    regime_line = (f"Regime: {adv.get('regime','—')} ({adv.get('regime_confidence',0)}%) "
                   f"Bias={adv.get('bias','—')} | {adv.get('advisor_note','')}"
                   if adv else "Regime: N/A")

    sentiment   = sentiment_data.get("sentiment", "NEUTRAL")
    sent_conf   = sentiment_data.get("confidence", 0)
    sent_line   = (f"Sentiment: {sentiment} ({sent_conf}%) — {sentiment_data.get('summary','')[:60]}"
                   if sentiment_data.get("tweet_count", 0) > 0
                   else "Sentiment: NEUTRAL (no news)")

    entry_wr    = _get_entry_wr(entry_type, history["entry_perf_text"])
    eff_rr_preview = _effective_min_rr(chart_data, sentiment_data)

    # ── RAG Lesson Retrieval — hybrid search (pre-filter + vector + weighted score) ──
    lesson_block = ""
    if getattr(_cfg, "LESSON_LEARNING", True):
        try:
            from db.lesson_store import search_lessons, format_lessons_for_prompt
            lesson_ctx = f"{direction} {entry_type} H4:{trend} SR:{sr_zone} conf:{conf}"
            lessons = search_lessons(lesson_ctx, direction=direction, trend=trend, top_k=3)
            lesson_block = format_lessons_for_prompt(lessons)
        except Exception as _le:
            logger.debug(f"Lesson search skipped: {_le}")

    htf_zone    = chart_data.get("htf_zone")
    htf_line    = (f"⚡ HTF Zone: {htf_zone['tf']} {htf_zone['zone_type']} @ {htf_zone['level']} "
                   f"(ห่าง {htf_zone['dist_pct']}%)"
                   if htf_zone else "HTF Zone: none")

    # TREND_CONT context — แทนที่ zone/PA signal ด้วย EMA structure
    tc_line = ""
    if "TREND_CONT" in tech_signal:
        _h1_ind = chart_data.get("indicators", {}).get("h1", {})
        _h4_ind = chart_data.get("indicators", {}).get("h4", {})
        tc_line = (f"\n⚡ TREND_CONT: H1 EMA20={_h1_ind.get('ema20',0):.0f} "
                   f"< EMA50={_h1_ind.get('ema50',0):.0f} | "
                   f"H4 EMA20={_h4_ind.get('ema20',0):.0f} < EMA50={_h4_ind.get('ema50',0):.0f} "
                   f"— EMA stack is the S/R, no zone required")

    user_message = f"""Signal: {direction} | Conf: {conf}% | Entry: {entry_type}
Zone: {sr_zone} {sr_str} | PA: {pa_str} | Candle: {candle_str}
{htf_line}{tc_line}
Trend H4: {trend} | Session: {session} ({hour_utc:02d}:xx UTC)
Momentum: {mom_str}
SL: {sl_pips:.0f}p | TP: {tp_pips:.0f}p | R:R: {tp_pips/sl_pips:.1f} (min {eff_rr_preview:.1f})
{sent_line}
{regime_line}
History — {entry_wr}
Account — Today: {history['today_pnl']:+.2f} USD ({history['today_trades']} trades) | WR10: {history['last_10_winrate']}% | Streak: {history['losing_streak']}L{chr(10) + lesson_block if lesson_block else ""}"""

    global _last_usage
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    _last_usage = response.usage

    decision_text = response.content[0].text
    logger.info(f"Decision:\n{decision_text}")

    decision         = "SKIP"
    out_direction    = "NONE"
    trade_quality    = "C"
    confidence_score = 0

    for line in decision_text.splitlines():
        if line.startswith("DECISION:"):
            decision = line.split(":", 1)[1].strip()
        elif line.startswith("DIRECTION:"):
            out_direction = line.split(":", 1)[1].strip()
        elif line.startswith("TRADE_QUALITY:"):
            trade_quality = line.split(":", 1)[1].strip()
        elif line.startswith("CONFIDENCE_SCORE:"):
            try:
                confidence_score = int(line.split(":", 1)[1].strip().replace("%", ""))
            except Exception:
                pass

    logger.info(f"Quality:{trade_quality} ConfScore:{confidence_score}")

    if decision == "EXECUTE" and out_direction in ("BUY", "SELL"):
        # ── เลือก SL ตามทิศทาง (ยืนยันอีกครั้ง) ─────────────────
        sl_key = "buy_sl_pips" if out_direction == "BUY" else "sell_sl_pips"
        sl_pips = chart_data.get(sl_key, sl_pips)

        # ── Confidence-based position sizing ─────────────────────
        _conf_full   = MONEY_MANAGEMENT["conf_full_size_at"]
        _conf_min_s  = MONEY_MANAGEMENT["conf_min_scale"]
        streak_scale = gate.get("streak_scale", 1.0)
        conf_scale   = max(_conf_min_s, min(1.0, conf / _conf_full)) * streak_scale
        conf_scale   = round(max(0.10, conf_scale), 2)   # floor 10% ไม่ให้ size เป็น 0
        logger.info(
            f"Position sizing: conf={conf}% → scale={conf_scale:.2f}"
            + (f" (streak×{streak_scale})" if streak_scale < 1.0 else "")
        )

        # ── Dynamic R:R ───────────────────────────────────────────
        eff_rr = _effective_min_rr(chart_data, sentiment_data)
        if eff_rr != MONEY_MANAGEMENT["min_rr_ratio"]:
            logger.info(f"Dynamic R:R: {MONEY_MANAGEMENT['min_rr_ratio']} → {eff_rr:.1f}")

        # ── No-TP mode: event ใกล้ หรือ momentum แรงมาก ─────────
        effective_tp = tp_pips
        notp_tag     = ""
        if _cfg.NO_TP_ON_EVENT:
            nearest_mins = sentiment_data.get("nearest_event_minutes", 9999)
            strong_mom   = _is_momentum_strong(out_direction)
            if nearest_mins <= _cfg.NO_TP_EVENT_MINS:
                effective_tp = 0
                notp_tag     = f"EVT{nearest_mins}m"
                logger.info(f"No-TP mode: event ใน {nearest_mins}min")
            elif strong_mom:
                effective_tp = 0
                notp_tag     = "MOMT"
                logger.info("No-TP mode: momentum แรงมาก")

        # ── TP scaling: ปรับขึ้นถ้า TP ไม่พอตาม effective R:R ────
        if effective_tp > 0:
            min_tp_needed = sl_pips * eff_rr
            if effective_tp < min_tp_needed:
                max_tp      = int(MONEY_MANAGEMENT["default_tp_pips"] * _MAX_TP_SCALE)
                effective_tp = min(int(min_tp_needed) + 100, max_tp)
                logger.info(f"TP scaling: → {effective_tp} pips (SL={sl_pips} × R:R {eff_rr:.1f})")

        sr_actions  = chart_data.get("sr_actions", [])
        pa_tag      = sr_actions[0]["action"] if sr_actions else "NOPA"
        sentiment   = sentiment_data.get("sentiment", "NEUTRAL")
        comment_tag = f"AI:{tech_signal}|PA:{pa_tag}|{sentiment}"
        if notp_tag:
            comment_tag += f"|NOTP:{notp_tag}"

        order_result = open_order(
            direction=out_direction,
            sl_pips=sl_pips,
            tp_pips=effective_tp,
            comment=comment_tag,
            min_rr=eff_rr,
            confidence_scale=conf_scale,
        )

        if not order_result.get("success"):
            err = order_result.get("error", "unknown")
            _order_fail_streak[out_direction] = _order_fail_streak.get(out_direction, 0) + 1
            streak = _order_fail_streak[out_direction]
            if streak >= _FAIL_STREAK_WARN:
                retcode = order_result.get("retcode", 0)
                hint = ""
                if retcode in (10026, 10027):
                    hint = " → เปิดปุ่ม Algo Trading ใน MT5 toolbar"
                elif retcode == 10019:
                    hint = " → margin ไม่พอ ตรวจสอบ equity"
                elif retcode in (10004, 10021):
                    hint = " → requote ถี่ ตรวจสอบ connection หรือ spread"
                logger.warning(
                    f"Order fail streak [{out_direction}]: {streak} ครั้งติดกัน "
                    f"(retcode={retcode}){hint}"
                )
            logger.error(f"Order rejected by MT5: {err}")
            return {"action": "SKIP", "reason": f"Order failed: {err}"}

        _order_fail_streak[out_direction] = 0   # reset streak เมื่อ order สำเร็จ
        return {
            "action":           "EXECUTE",
            "direction":        out_direction,
            "trade_quality":    trade_quality,
            "confidence_score": confidence_score,
            "order":            order_result,
            "technical":        chart_data,
            "sentiment":        sentiment_data,
            "analysis":         decision_text,
        }

    return {
        "action":           "SKIP",
        "reason":           decision_text,
        "trade_quality":    trade_quality,
        "confidence_score": confidence_score,
    }
