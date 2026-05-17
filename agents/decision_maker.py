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

    # 3. Counter-trend block
    is_counter = (trend == "BULLISH" and direction == "SELL") or \
                 (trend == "BEARISH" and direction == "BUY")
    if is_counter:
        at_strong = sr_str == "STRONG" and sr_zone in ("RESISTANCE", "SUPPORT")
        if not (at_strong and conf >= 70):
            return _fail(f"Counter-trend {direction} blocked (trend={trend}, conf={conf})")

    # 4. SIDEWAYS — เฉพาะ Momentum Breakout
    if trend == "SIDEWAYS":
        scan_best = chart_data.get("scan", {}).get("best_score", 0)
        if entry_type != "MOMENTUM_BREAKOUT" and scan_best < 65 and conf < 65:
            return _fail("SIDEWAYS — only MOMENTUM_BREAKOUT ≥65 allowed")

    # 5. Min confidence
    if conf < MIN_TECHNICAL_CONFIDENCE:
        return _fail(f"Confidence {conf}% < {MIN_TECHNICAL_CONFIDENCE}%")

    # 6. Entry-type gates
    if entry_type == "EMA_PULLBACK" and conf < 60:
        return _fail(f"EMA_PULLBACK requires conf ≥60% (got {conf}%)")
    if entry_type == "ENGULFING" and conf < 75:
        return _fail(f"ENGULFING requires conf ≥75% (got {conf}%)")

    # MOMENTUM_BREAKOUT: require higher conf threshold at gate 7+8
    # Other entries: conf ≥ 62 is enough
    _hour_utc      = datetime.utcnow().hour
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

    # 11. Losing streak — gradual position reduction (ไม่ hard block)
    streak_scale = 1.0
    if _cfg.STREAK_PROTECTION:
        streak = history["losing_streak"]
        if streak >= 5:
            streak_scale = 0.25
        elif streak == 4:
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

    # ── Clean summary สำหรับ Claude (~15 บรรทัด) ─────────────────
    hour_utc    = datetime.now(_tz.utc).hour
    session     = _session_name(hour_utc)
    entry_type  = chart_data.get("entry_type", "NONE")
    sr_zone     = chart_data.get("sr_zone", "NONE")
    sr_str      = chart_data.get("sr_strength", "NORMAL")
    trend       = chart_data.get("trend", "SIDEWAYS")

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

    user_message = f"""Signal: {direction} | Conf: {conf}% | Entry: {entry_type}
Zone: {sr_zone} {sr_str} | PA: {pa_str} | Candle: {candle_str}
Trend H4: {trend} | Session: {session} ({hour_utc:02d}:xx UTC)
Momentum: {mom_str}
SL: {sl_pips:.0f}p | TP: {tp_pips:.0f}p | R:R: {tp_pips/sl_pips:.1f} (min {eff_rr_preview:.1f})
{sent_line}
{regime_line}
History — {entry_wr}
Account — Today: {history['today_pnl']:+.2f} USD ({history['today_trades']} trades) | WR10: {history['last_10_winrate']}% | Streak: {history['losing_streak']}L"""

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
            logger.error(f"Order rejected by MT5: {err}")
            return {"action": "SKIP", "reason": f"Order failed: {err}"}

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
