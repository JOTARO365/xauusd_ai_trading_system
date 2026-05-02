import anthropic
from datetime import datetime, timezone as _tz
from pathlib import Path
from connectors.mt5_connector import open_order, get_open_positions, count_protected_slots, check_open_slot, _is_momentum_strong
from connectors.price_feed import get_account_info
from agents.reporter import get_trade_history_summary
from config import ANTHROPIC_API_KEY, MONEY_MANAGEMENT, PORTFOLIO_PROTECTION, STREAK_PROTECTION, NO_TP_ON_EVENT, NO_TP_EVENT_MINS
from loguru import logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = Path("agents/prompts/decision_maker.md").read_text(encoding="utf-8")

MIN_TECHNICAL_CONFIDENCE = 45   # threshold เดียว — ไม่แยก มีข่าว/ไม่มีข่าว

_last_usage = None   # set after each API call — read by accountant

_MAX_TP_SCALE = 2.0   # TP ขยายได้สูงสุด 2× default_tp_pips


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

    if hot >= 5: return 1.0
    if hot >= 3: return 1.2
    if hot >= 1: return 1.3
    return base


def make_decision(chart_data: dict, sentiment_data: dict, advisor_data: dict | None = None) -> dict:
    logger.info("Agent 4 (ผู้ตัดสินใจ): กำลังอ่านประวัติและตัดสินใจ...")

    tech_signal = chart_data.get("signal", "NO_TRADE")

    # ── Early exit ①: NO_TRADE + momentum override ไม่ผ่าน → ไม่เรียก Claude ──
    if tech_signal == "NO_TRADE":
        _mt  = chart_data.get("momentum_tf", {})
        _m15 = _mt.get("m15", {})
        _h1  = _mt.get("h1", {})
        _can_mo = (
            _m15.get("strength") == "STRONG" and
            _m15.get("direction") == _h1.get("direction") and
            _m15.get("direction") in ("UP", "DOWN") and
            chart_data.get("trend", "SIDEWAYS") != "SIDEWAYS"
        )
        if not _can_mo:
            logger.debug("Early exit: NO_TRADE + no momentum override — skip Claude")
            return {"action": "SKIP", "reason": "NO_TRADE signal",
                    "trade_quality": "C", "confidence_score": 0}

    account = get_account_info()
    open_positions = get_open_positions()
    history = get_trade_history_summary()

    tech_signal     = chart_data.get("signal", "NO_TRADE")
    tech_confidence = chart_data.get("confidence", 0)
    sentiment       = sentiment_data.get("sentiment", "NEUTRAL")
    sent_confidence = sentiment_data.get("confidence", 0)
    has_news        = sentiment_data.get("tweet_count", 0) > 0
    # ใช้ SL จาก wick ของแท่งก่อนหน้า M15 ตามทิศทางที่จะเข้า
    _buy_sl  = chart_data.get("buy_sl_pips",  MONEY_MANAGEMENT["default_sl_pips"])
    _sell_sl = chart_data.get("sell_sl_pips", MONEY_MANAGEMENT["default_sl_pips"])
    # sl_pips จะเลือกให้ถูกต้องหลัง direction รู้ค่า (ใช้ fallback ก่อน)
    sl_pips         = chart_data.get("sl_pips", MONEY_MANAGEMENT["default_sl_pips"])
    tp_pips         = chart_data.get("tp_pips", MONEY_MANAGEMENT["default_tp_pips"])
    min_tech_conf   = MIN_TECHNICAL_CONFIDENCE

    # หยุดเทรดทันทีถ้าขาดทุนวันนี้เกิน max daily loss (ถ้า portfolio protection เปิด)
    if PORTFOLIO_PROTECTION and account.get("balance", 0) > 0:
        daily_loss_pct = abs(min(history["today_pnl"], 0)) / account["balance"]
        if daily_loss_pct >= MONEY_MANAGEMENT["max_daily_loss"]:
            logger.warning(f"Daily loss เกิน {MONEY_MANAGEMENT['max_daily_loss']*100}% — หยุดเทรดวันนี้")
            return {"action": "SKIP", "reason": "Max daily loss reached"}

    # ── Price action จาก Agent 1 ──────────────────────────────────────
    sr_actions = chart_data.get("sr_actions", [])
    candle_pat = chart_data.get("candle_pat", {})

    if sr_actions:
        pa_lines = "\n".join(
            f"  [{a['action']}] Level={a['level']} | Zone={a['zone']} | Dir={a['direction']}\n"
            f"  Pattern={a['pattern']} | {a['note']}"
            for a in sr_actions
        )
    else:
        pa_lines = "  ไม่พบสัญญาณ Rejection/Breakout ที่ S/R zone ตอนนี้"

    candle_str = (
        f"Pattern={candle_pat.get('patterns',['—'])} | "
        f"Bias={candle_pat.get('bias','—')} | "
        f"Body={candle_pat.get('body_pct',0)}%"
    )

    adv = advisor_data or {}
    advisor_section = f"""
=== Market Advisor (Agent 2.5) ===
Regime    : {adv.get('regime', '—')} ({adv.get('regime_confidence', 0)}%) | Bias: {adv.get('bias', '—')}
Volatility: {adv.get('volatility', '—')} | TP Style: {adv.get('tp_style', '—')}
Structure : H4={adv.get('intraday_h4','—')} | H1={adv.get('intraday_h1','—')} | M15={adv.get('intraday_m15','—')}
Best (log): {adv.get('top_setup', 'NO_DATA')}
Indicators: {', '.join(adv.get('best_indicators', [])) or '—'}
Advice    : {adv.get('advisor_note', '—')}
""" if adv else ""

    user_message = f"""ข้อมูลสำหรับการตัดสินใจ:

=== สถานะบัญชี ===
Balance : {account.get('balance', 0):.2f} {account.get('currency', 'USD')}
Equity  : {account.get('equity', 0):.2f}
Open Pos: {len(open_positions)} / {MONEY_MANAGEMENT['max_open_trades']}

=== ประวัติการเทรด (อ่านก่อนตัดสินใจ) ===
วันนี้          : {history['today_trades']} trades | P&L = {history['today_pnl']:+.2f} USD
Win Rate ล่าสุด : {history['last_10_winrate']}% ({history['last_10_win']}W / {history['last_10_loss']}L จาก 10 trade ล่าสุด)
Losing Streak   : {history['losing_streak']} trade ติดต่อกัน

Strategy Performance (entry type ที่ผ่านมา — ใช้เลือก entry ที่น่าเชื่อถือ):
{history['entry_perf_text']}
5 Trade ล่าสุด (Entry | PA | SR | Trend → P&L):
{history['recent_trades_text']}

=== สัญญาณ Technical (Agent 1) ===
Signal: {tech_signal} | Confidence: {tech_confidence}%
Trend: {chart_data.get('trend','—')} | SR Zone: {chart_data.get('sr_zone','—')} | SR Strength: {chart_data.get('sr_strength','—')}
SL: {sl_pips} pips | TP: {tp_pips} pips

=== Price Action (สำคัญ — ใช้ยืนยัน signal) ===
Candle M15: {candle_str}

Rejection / Breakout ที่ S/R:
{pa_lines}

=== Sentiment จากข่าว (Agent 3) ===
มีข้อมูลข่าว: {"YES" if has_news else "NO — ไม่มี tweet วันนี้ ให้ใช้ Technical + Price Action เท่านั้น"}
Sentiment: {sentiment} | Confidence: {sent_confidence}% | Bias: {sentiment_data.get('bias', 'NEUTRAL')}
Summary: {sentiment_data.get('summary', '') or "—"}
Threshold ที่ใช้: Technical ≥ {min_tech_conf}%

=== กฎ Money Management ===
- Risk per trade : {MONEY_MANAGEMENT['risk_per_trade']*100}%
- Max daily loss : {MONEY_MANAGEMENT['max_daily_loss']*100}%
- Min RR ratio   : {MONEY_MANAGEMENT['min_rr_ratio']}

{advisor_section}
ตัดสินใจตามกฎที่กำหนดและตอบในรูปแบบที่ระบุไว้"""

    global _last_usage
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=350,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    _last_usage = response.usage

    decision_text = response.content[0].text
    logger.info(f"Decision:\n{decision_text}")

    decision         = "SKIP"
    direction        = "NONE"
    trade_quality    = "C"
    confidence_score = 0

    for line in decision_text.splitlines():
        if line.startswith("DECISION:"):
            decision = line.split(":", 1)[1].strip()
        elif line.startswith("DIRECTION:"):
            direction = line.split(":", 1)[1].strip()
        elif line.startswith("TRADE_QUALITY:"):
            trade_quality = line.split(":", 1)[1].strip()
        elif line.startswith("CONFIDENCE_SCORE:"):
            try:
                confidence_score = int(line.split(":", 1)[1].strip().replace("%", ""))
            except Exception:
                pass

    logger.info(f"Quality:{trade_quality} ConfScore:{confidence_score}")

    # ── Momentum Override ─────────────────────────────────────────
    # Claude อาจ SKIP เพราะ SR_ZONE = NONE แต่ถ้า momentum แรงจริงๆ
    # ให้ override เป็น EXECUTE (M15 STRONG + H1 aligned + H4 trend ตรงกัน)
    if decision == "SKIP":
        mom_tf  = chart_data.get("momentum_tf", {})
        mom_m15 = mom_tf.get("m15", {})
        mom_h1  = mom_tf.get("h1", {})
        h4_bias = chart_data.get("trend", "SIDEWAYS")
        m15_str = mom_m15.get("strength")
        m15_dir = mom_m15.get("direction")   # "UP" / "DOWN" / "FLAT"
        h1_dir  = mom_h1.get("direction")

        if (m15_str == "STRONG" and m15_dir == h1_dir and
                m15_dir in ("UP", "DOWN") and h4_bias != "SIDEWAYS"):

            override_dir = "BUY" if m15_dir == "UP" else "SELL"
            h4_match     = (h4_bias == "BULLISH" and override_dir == "BUY") or \
                           (h4_bias == "BEARISH" and override_dir == "SELL")
            sent_bias    = sentiment_data.get("bias", "NEUTRAL")
            sent_ok      = sent_bias == "NEUTRAL" or \
                           (sent_bias == "BUY"  and override_dir == "BUY") or \
                           (sent_bias == "SELL" and override_dir == "SELL")

            if h4_match and sent_ok:
                direction       = override_dir
                decision        = "EXECUTE"
                trade_quality   = "B"
                tech_confidence = max(tech_confidence, 55)
                logger.info(
                    f"[Momentum Override] SKIP→EXECUTE {override_dir} | "
                    f"M15={m15_dir}_STRONG H1={h1_dir} H4={h4_bias}"
                )

    # ใช้ SL ตามทิศทางที่ตัดสินใจได้แล้ว
    if direction == "BUY":
        sl_pips = _buy_sl
    elif direction == "SELL":
        sl_pips = _sell_sl

    if decision == "EXECUTE" and direction in ["BUY", "SELL"]:
        if tech_confidence < min_tech_conf:
            logger.warning(f"Technical confidence {tech_confidence}% < {min_tech_conf}% — ยกเลิก")
            return {"action": "SKIP", "reason": f"Technical confidence too low ({tech_confidence}% < {min_tech_conf}%)"}

        # ── Regime alignment check ─────────────────────────────────────
        regime_bias = (adv.get("bias", "NEUTRAL") if adv else "NEUTRAL")
        regime      = (adv.get("regime", "")       if adv else "")
        is_counter  = (regime_bias == "BULLISH" and direction == "SELL") or \
                      (regime_bias == "BEARISH" and direction == "BUY")
        is_transition = "TRANSITION" in regime

        if is_transition and tech_confidence < 52:
            logger.warning(f"Regime TRANSITION — confidence {tech_confidence}% < 52% — ยกเลิก")
            return {"action": "SKIP", "reason": f"TRANSITION regime requires confidence ≥ 52% (got {tech_confidence}%)"}

        if is_counter and tech_confidence < 55:
            logger.warning(
                f"Counter-trend {direction} vs regime {regime_bias} — "
                f"confidence {tech_confidence}% < 55% — ยกเลิก"
            )
            return {"action": "SKIP", "reason": f"Counter-trend vs {regime_bias} regime requires confidence ≥ 55% (got {tech_confidence}%)"}

        can_open, slot_reason = check_open_slot(direction)
        if not can_open:
            logger.warning(slot_reason)
            return {"action": "SKIP", "reason": slot_reason}

        max_streak  = MONEY_MANAGEMENT["max_losing_streak"]
        streak_conf = MONEY_MANAGEMENT["streak_min_confidence"]
        if STREAK_PROTECTION and history["losing_streak"] >= max_streak:
            logger.warning(f"Losing streak {history['losing_streak']} — ต้อง confidence ≥ {streak_conf}%")
            if tech_confidence < streak_conf:
                return {"action": "SKIP", "reason": f"Losing streak {history['losing_streak']} — confidence ต้องสูงกว่า {streak_conf}%"}

        # ── Dynamic R:R ───────────────────────────────────────────────
        eff_rr = _effective_min_rr(chart_data, sentiment_data)
        if eff_rr != MONEY_MANAGEMENT["min_rr_ratio"]:
            logger.info(f"Dynamic R:R: {MONEY_MANAGEMENT['min_rr_ratio']} → {eff_rr:.1f} (market hot)")

        # ── No-TP mode: event ใกล้ หรือ momentum แรงมาก ─────────────
        effective_tp = tp_pips
        notp_tag     = ""
        if NO_TP_ON_EVENT:
            nearest_mins = sentiment_data.get("nearest_event_minutes", 9999)
            strong_mom   = _is_momentum_strong(direction)
            if nearest_mins <= NO_TP_EVENT_MINS:
                effective_tp = 0
                notp_tag     = f"EVT{nearest_mins}m"
                logger.info(f"No-TP mode: high-impact event ใน {nearest_mins}min — เปิด order ไม่ตั้ง TP")
            elif strong_mom:
                effective_tp = 0
                notp_tag     = "MOMT"
                logger.info("No-TP mode: momentum แรงมาก — เปิด order ไม่ตั้ง TP")

        # ── TP scaling: ปรับ TP ขึ้นถ้าไม่พอตาม effective R:R ────────
        if effective_tp > 0:
            min_tp_needed = sl_pips * eff_rr
            if effective_tp < min_tp_needed:
                max_tp = int(MONEY_MANAGEMENT["default_tp_pips"] * _MAX_TP_SCALE)
                adjusted_tp = min(int(min_tp_needed) + 100, max_tp)
                logger.info(
                    f"TP scaling: {effective_tp} → {adjusted_tp} pips "
                    f"(SL={sl_pips} × R:R {eff_rr:.1f} = {min_tp_needed:.0f} ต้องการ)"
                )
                effective_tp = adjusted_tp

        pa_tag = sr_actions[0]["action"] if sr_actions else "NOPA"
        comment_tag = f"AI:{tech_signal}|PA:{pa_tag}|{sentiment}"
        if notp_tag:
            comment_tag += f"|NOTP:{notp_tag}"
        order_result = open_order(
            direction=direction,
            sl_pips=sl_pips,
            tp_pips=effective_tp,
            comment=comment_tag,
            min_rr=eff_rr,
        )

        if not order_result.get("success"):
            err = order_result.get("error", "unknown")
            logger.error(f"Order rejected by MT5: {err}")
            return {"action": "SKIP", "reason": f"Order failed: {err}"}

        return {
            "action":           "EXECUTE",
            "direction":        direction,
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
