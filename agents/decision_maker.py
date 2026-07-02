import json
from datetime import datetime, timezone as _tz
from pathlib import Path
from langchain_anthropic import ChatAnthropic
from connectors.mt5_connector import open_order, get_open_positions, count_protected_slots, check_open_slot, _is_momentum_strong, daily_trade_cap_reached
from connectors.price_feed import get_account_info
from agents.reporter import get_trade_history_summary
from agents.schemas import DecisionMakerOutput
import config as _cfg
from config import ANTHROPIC_API_KEY, MONEY_MANAGEMENT
from loguru import logger

_llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    api_key=ANTHROPIC_API_KEY,
    max_tokens=256,   # 120 เดิมคับ — reason ฟิลด์ free-text ถูก truncate → structured parse fail → SKIP เงียบ
    temperature=0,
).with_structured_output(DecisionMakerOutput, include_raw=True)

# ── Order fail streak tracker ─────────────────────────────────────────────────
_order_fail_streak: dict[str, int] = {"BUY": 0, "SELL": 0}
_FAIL_STREAK_WARN = 3   # warning เมื่อ fail ≥ N ครั้งติดกัน

# ── Gate-block observability (audit 2026-06-28) ───────────────────────────────
# log ทุก gate ที่ block ลง logs/gate_blocks.jsonl (append). จำเป็นเพราะไม้ที่ถูก
# block ไม่มี row ใน trades → guard หลายตัว (news-first/HTF-fade/counter-spike)
# วัดผลไม่ได้เลย. สะสม log 1-2 สัปดาห์เพื่อพิสูจน์ว่า guard ตัวไหน block ไม้ดีทิ้ง.
_GATE_LOG = Path("logs") / "gate_blocks.jsonl"

_GATE_CATEGORIES = [
    ("news-first", "news_first"), ("news_first", "news_first"),
    ("htf-direction", "htf_direction"),   # ต้องมาก่อน "htf" (first match wins)
    ("htf", "htf_fade"), ("spike", "counter_spike"), ("counter-trend", "counter_trend"),
    ("ema_pullback", "ema_pullback"), ("engulfing", "engulfing"), ("sideways", "sideways"),
    ("asian", "session"), ("quiet", "session"), ("ny close", "session"),
    ("unknown trend", "unknown_trend"), ("daily loss", "daily_loss"), ("trade cap", "trade_cap"),
    ("streak", "streak"),
    ("resistance", "sell_resistance"), ("sr zone", "no_zone"), ("atr", "atr"),
    ("confidence", "min_conf"), ("conf ", "min_conf"), ("slot", "slot"),
    ("sl ", "sl_range"), ("no_trade", "no_trade"), ("no trade", "no_trade"),
    ("ทิศทางไม่ชัด", "no_direction"),
]


def _gate_category(reason: str) -> str:
    r = reason.lower()
    for k, v in _GATE_CATEGORIES:
        if k in r:
            return v
    return "other"


def _log_gate_block(reason: str, chart_data: dict, sentiment_data: dict | None = None) -> None:
    """append 1 บรรทัด JSONL ต่อ 1 block — best-effort, ไม่ขวาง decision flow"""
    try:
        h1 = (chart_data.get("indicators") or {}).get("h1") or {}
        rec = {
            "at": datetime.now(_tz.utc).isoformat(),
            "gate": _gate_category(reason),
            "reason": reason,
            "signal": chart_data.get("signal"),
            "trend": chart_data.get("trend"),
            "sr_zone": chart_data.get("sr_zone"),
            "sr_strength": chart_data.get("sr_strength"),
            "conf": chart_data.get("confidence"),
            "entry_type": chart_data.get("entry_type"),
            "price": h1.get("close"),
            "sentiment_bias": (sentiment_data or {}).get("bias"),
            # TREND-MODE shadow experiment (07-03): เก็บสภาพ momentum/D1 ตอน block
            # เพื่อ score ย้อนหลังด้วย scripts/score_trend_mode.py (เงื่อนไขจริง ไม่ใช่ H4 proxy)
            "fast_move": chart_data.get("fast_move_pips"),
            "d1_trend": chart_data.get("d1_trend"),
            "mom_h1": ((chart_data.get("momentum_tf") or {}).get("h1") or {}).get("direction"),
            "mom_m15": ((chart_data.get("momentum_tf") or {}).get("m15") or {}).get("direction"),
        }
        _GATE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _GATE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"gate_block log failed: {e}")

SYSTEM_PROMPT = json.dumps(
    json.loads(Path("agents/prompts/decision_maker.json").read_text(encoding="utf-8")),
    separators=(",", ":"),  # minified — saves ~15% tokens vs pretty-printed
)

# Gate/guard knobs ทั้งหมดอยู่ใน config.py (อ่านผ่าน _cfg.* ตอนเรียกใช้ → reload_config()
# จาก dashboard เห็นผลทันที ไม่ต้อง restart) — replay 489 ไม้หนุนค่า default ดู config.py


def _momentum_ride_active(direction: str, chart_data: dict) -> bool:
    """MOMENTUM_RIDE — เงื่อนไข "โหมดชนะ" ของระบบยุคทอง (04-06 พ.ค. +24.9k):
    momentum 3 ชั้นเรียงแถวตรงทิศไม้: M15 STRONG + H1 ทิศเดียวกัน + H4 trend ตรง.
    active → ยกเว้น counter-spike + HTF-direction ให้ไม้นั้น (dip/reversal ตามเทรนด์เข้าได้
    เหมือนยุคเดิม) แต่เกราะยุคใหม่ทำงานครบ (conf floor/trade cap/daily loss/streak/SL gap).
    SIDEWAYS ไม่มีวัน ride (h4 ต้อง BULLISH/BEARISH ตรงทิศ). fail-open = False (ตึงตามปกติ)"""
    if not getattr(_cfg, "MOMENTUM_RIDE", True):
        return False
    trend = (chart_data.get("trend") or "").upper()
    h4_ok = (direction == "BUY" and trend == "BULLISH") or \
            (direction == "SELL" and trend == "BEARISH")
    if not h4_ok:
        return False
    mom  = chart_data.get("momentum_tf") or {}
    m15  = mom.get("m15") or {}
    h1   = mom.get("h1") or {}
    want = "UP" if direction == "BUY" else "DOWN"
    return (m15.get("direction") == want and m15.get("strength") == "STRONG"
            and h1.get("direction") == want)


def _counter_spike_reason(direction: str, chart_data: dict) -> str | None:
    """News-first guard: ราคาที่สไปก์แรงคือผลของข่าวทันที → ห้ามเข้าสวนทาง.
    fast_move_pips (จาก chart_watcher, net M15 ~45min, + = ขึ้น):
      พุ่งขึ้นแรง → ห้าม SELL (สวนการเด้ง);  ดิ่งลงแรง → ห้าม BUY (สวนการร่วง).
    ยกเว้น: MOMENTUM_RIDE active — dip ระหว่างเทรนด์ที่ momentum กลับตัวแล้ว = จุดเข้า ไม่ใช่ข่าวร้าย
    """
    if _cfg.COUNTER_SPIKE_PIPS <= 0:
        return None
    if _momentum_ride_active(direction, chart_data):
        _f = chart_data.get("fast_move_pips", 0)
        logger.info(f"[RIDE] counter-spike waived: {direction} fast={_f:+.0f}p แต่ M15-STRONG+H1+H4 เรียงแถว")
        return None
    fast = float(chart_data.get("fast_move_pips", 0) or 0)
    if abs(fast) < _cfg.COUNTER_SPIKE_PIPS:
        return None
    if fast > 0 and direction == "SELL":
        return f"Counter-spike: ราคาพุ่งขึ้น {fast:.0f}p (น่าจะข่าว) — ห้าม SELL สวนการเด้ง"
    if fast < 0 and direction == "BUY":
        return f"Counter-spike: ราคาดิ่งลง {abs(fast):.0f}p (น่าจะข่าว) — ห้าม BUY สวนการร่วง"
    return None


def _news_bias_dir(sentiment_data: dict, advisor_data: dict | None) -> tuple[str | None, str]:
    """คืน (news_dir, why). news_dir='BUY'/'SELL' เมื่อข่าวชี้ทิศชัด, ไม่งั้น None.
    ยึด analyst.bias (รวม macro_regime.md แล้ว) เป็นหลักเมื่อ conf ถึงเกณฑ์;
    ถ้า regime (advisor) ชี้ตรงข้ามชัด → ถือว่าไม่ชัด (ไม่บังคับทิศ ปล่อยเทคนิคตัดสิน)."""
    if not _cfg.NEWS_FIRST:
        return None, ""
    a_bias = (sentiment_data or {}).get("bias", "NEUTRAL")
    a_conf = float((sentiment_data or {}).get("confidence", 0) or 0)
    if a_bias not in ("BUY", "SELL") or a_conf < _cfg.NEWS_BIAS_MIN_CONF:
        return None, ""
    adv_dir = {"BULLISH": "BUY", "BEARISH": "SELL"}.get(
        (advisor_data or {}).get("bias", "NEUTRAL"), "NEUTRAL")
    if adv_dir in ("BUY", "SELL") and adv_dir != a_bias:
        return None, f"analyst={a_bias} ขัด regime={adv_dir} — ไม่บังคับทิศ"
    return a_bias, f"analyst conf {a_conf:.0f}%≥{_cfg.NEWS_BIAS_MIN_CONF:.0f}"


def _htf_fade_reason(direction: str, chart_data: dict) -> str | None:
    """ห้ามเข้าสวนแนว HTF (D1/W1): ที่ SUPPORT ราคามักเด้ง → ห้าม SELL;
    ที่ RESISTANCE มักย่อ → ห้าม BUY. (htf_zone ถูกตั้งเฉพาะ D1/W1 เท่านั้น)"""
    if not _cfg.HTF_FADE_BLOCK:
        return None
    z = chart_data.get("htf_zone")
    if not z:
        return None
    zt, tf, lvl = z.get("zone_type"), z.get("tf"), z.get("level")
    trend = (chart_data.get("trend") or "").upper()
    # block เฉพาะ 'fade' (เด้ง) ไม่ block 'breakdown' (ทะลุตามเทรนด์):
    # SUPPORT+BEARISH = แนวรับใน downtrend มักแตก → SELL breakdown valid → ไม่ block
    # RESISTANCE+BULLISH = แนวต้านใน uptrend มักทะลุ → BUY breakout valid → ไม่ block
    if zt == "SUPPORT" and direction == "SELL" and trend != "BEARISH":
        return f"HTF-fade: SELL ที่ {tf} SUPPORT ({lvl}) ใน trend {trend or '?'} — แนวรับมักเด้ง (ไม่ใช่ breakdown) โอกาสพลาดสูง"
    if zt == "RESISTANCE" and direction == "BUY" and trend != "BULLISH":
        return f"HTF-fade: BUY ที่ {tf} RESISTANCE ({lvl}) ใน trend {trend or '?'} — แนวต้านมักย่อ (ไม่ใช่ breakout) โอกาสพลาดสูง"
    return None


def _htf_direction_reason(direction: str, chart_data: dict) -> str | None:
    """HTF-direction block (NEXT STEP #4 — anchor D1, ไม่ซ้ำ gate 4 ที่ดู H4):
    ห้ามเข้าสวนเทรนด์ D1 (calc_d1_trend: EMA20+slope จากแท่งปิดแล้ว) แบบ hard.
    replay 251 ไม้ no-lookahead: counter-D1 = −248/134ไม้; มิ.ย. BUY สวน D1-BEARISH
    = −242 WR21% ≈ การเลือดทั้งเดือน (market conf 78-82 ก็แพ้ยกชุด → ไม่มี conf exception;
    ทดสอบ exception htf_zone+conf≥70 แล้ว 'แย่ลง' −84). d1_trend ไม่มี/NEUTRAL = ไม่ block"""
    if not getattr(_cfg, "HTF_DIRECTION_BLOCK", True):
        return None
    if _momentum_ride_active(direction, chart_data):
        logger.info(f"[RIDE] HTF-direction waived: {direction} (D1 lag) — M15-STRONG+H1+H4 เรียงแถว")
        return None
    d1 = (chart_data.get("d1_trend") or "NEUTRAL").upper()
    if d1 == "BEARISH" and direction == "BUY":
        return "HTF-direction: BUY สวน D1 BEARISH — counter-D1 replay −248 (มิ.ย. −242, conf สูงก็แพ้)"
    if d1 == "BULLISH" and direction == "SELL":
        return "HTF-direction: SELL สวน D1 BULLISH — counter-D1 replay −248"
    return None


# Option C — news ลากเข้าได้แม้สวนเทรนด์ H4 (ต้องตรงข่าว + price action ยืนยัน)
def _news_override_ok(direction: str, chart_data: dict, news_dir: str | None,
                      conf: int) -> tuple[bool, str]:
    """อนุญาตเข้าสวนเทรนด์ H4 เมื่อ 'ตรงข่าว + price action ยืนยัน' (role: ดูข่าว→price action→เข้า).
    เงื่อนไข: NEWS_OVERRIDE_TREND on, direction==news_dir, conf≥floor, และยืนยัน 1 ใน 2:
      (a) สไปก์ไปทางเดียวกับไม้ ≥ NEWS_CONFIRM_PIPS (ข่าวดันราคาจริง), หรือ
      (b) อยู่ที่ HTF zone ที่หนุนไม้ (BUY ที่ SUPPORT / SELL ที่ RESISTANCE)."""
    if not _cfg.NEWS_OVERRIDE_TREND:
        return False, ""
    if not news_dir or direction != news_dir:
        return False, ""
    if float(conf or 0) < _cfg.NEWS_OVERRIDE_MIN_CONF:
        return False, f"conf {conf}<{_cfg.NEWS_OVERRIDE_MIN_CONF:.0f}"
    fast = float(chart_data.get("fast_move_pips", 0) or 0)
    if (direction == "BUY" and fast >= _cfg.NEWS_CONFIRM_PIPS) or \
       (direction == "SELL" and fast <= -_cfg.NEWS_CONFIRM_PIPS):
        return True, f"ข่าว {news_dir} + สไปก์ยืนยัน {fast:+.0f}p"
    z = chart_data.get("htf_zone") or {}
    if (direction == "BUY" and z.get("zone_type") == "SUPPORT") or \
       (direction == "SELL" and z.get("zone_type") == "RESISTANCE"):
        return True, f"ข่าว {news_dir} + อยู่ที่ {z.get('tf')} {z.get('zone_type')}"
    return False, "ไม่มี price action ยืนยัน (ต้องสไปก์ตามทิศ หรืออยู่ที่ HTF zone หนุน)"

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
        _log_gate_block(reason, chart_data, sentiment_data)
        return {"pass": False, "reason": reason}

    _utc_hour = datetime.now(_tz.utc).hour   # คำนวณครั้งเดียว — ใช้ใน NNLB Asian / gate 5b / LN-NY overlap

    # 0. Daily trade cap — เบรกกันวันพายุ ครอบทั้ง NNLB/ปกติ (ตัดก่อนเรียก Claude = ประหยัด token)
    #    replay 247 ไม้: ไม้ #7+ ของวัน = −411 (n=155) vs ไม้ 1-6 = +139.88; มิ.ย.+ block แต่ไม้แพ้
    _capped, _cap_reason = daily_trade_cap_reached()
    if _capped:
        return _fail(_cap_reason)

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
                # conf สังเคราะห์แบบเดียวกับ TREND_CONT — เดิมเปิดไม้ได้ทั้งที่ conf=0
                # (chart บอก NO_TRADE) ซึ่งข้อมูลจริง band conf 0-9 = 21 ไม้ −633
                conf = max(conf, int(_cfg.TREND_CONT_CONF))
                chart_data["confidence"] = conf
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

                # #2 — ต้องเป็น pullback จริง: ราคาใกล้ H1 EMA20 ไม่ใช่ entry กลางเทรนด์ที่ยืดแล้ว
                #      (conf 55 เป็นค่าสังเคราะห์ ไม่มี zone/PA ยืนยัน → อย่างน้อยขอ proximity เป็นหลักฐาน)
                if _tc_dir and _px and abs(_px - _e20) / _px * 100 > _cfg.TREND_CONT_MAX_DIST_PCT:
                    logger.info(
                        f"[TREND_CONT] skip {_tc_dir} — ราคาห่าง H1 EMA20 "
                        f"{abs(_px - _e20) / _px * 100:.2f}% > {_cfg.TREND_CONT_MAX_DIST_PCT}% (extended ไม่ใช่ pullback)"
                    )
                    _tc_dir = None

                if _tc_dir:
                    tech_signal = f"TREND_CONT_{_tc_dir}"
                    chart_data["signal"]     = _tc_dir
                    chart_data["confidence"] = int(_cfg.TREND_CONT_CONF)   # tunable; ยังไม่มี zone anchor
                    chart_data["entry_type"] = "EMA_PULLBACK"
                    conf = int(_cfg.TREND_CONT_CONF)
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

        # Quality gates ที่ replay พิสูจน์ (489 ไม้) — NNLB ข้ามเฉพาะ money-management
        # ไม่ใช่ quality: conf 50-59 = WR 23.5%, Asian conf ต่ำ = −115/ไม้ → ใช้กับ NNLB ด้วย
        _conf_now = int(chart_data.get("confidence", conf) or 0)
        if _conf_now < _cfg.MIN_TECHNICAL_CONFIDENCE:
            return _fail(f"NNLB: conf {_conf_now}% < floor {_cfg.MIN_TECHNICAL_CONFIDENCE}%")
        if _utc_hour < 7 and _conf_now < _cfg.ASIAN_MIN_CONF:
            return _fail(f"NNLB Asian (0-7 UTC): conf {_conf_now}% < {_cfg.ASIAN_MIN_CONF:.0f}%")

        # Anti-fade guards — แม้ NNLB ข้าม gates ก็ยังห้ามเข้าสวน: สไปก์ข่าว / ทิศข่าว / แนว HTF
        _cs = _counter_spike_reason(direction, chart_data)
        if _cs:
            return _fail(f"NNLB: {_cs}")
        _ndir, _nwhy = _news_bias_dir(sentiment_data, advisor_data)
        if _ndir and direction != _ndir:
            return _fail(f"NNLB: News-first ข่าวชี้ {_ndir} — บล็อก {direction} สวนข่าว ({_nwhy})")
        _hf = _htf_fade_reason(direction, chart_data)
        if _hf:
            return _fail(f"NNLB: {_hf}")
        _hd = _htf_direction_reason(direction, chart_data)
        if _hd:
            return _fail(f"NNLB: {_hd}")

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
        conf = max(conf, _cfg.MIN_TECHNICAL_CONFIDENCE)   # ตาม floor — ค่าตายตัวต่ำกว่า floor จะโดน gate 6 ฆ่าเงียบ
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

    # 2b. News-spike guard — ห้ามเข้าสวนการสไปก์แรง (ข่าว): ไม่ขายสวนการเด้ง/ไม่ซื้อสวนการร่วง
    _cs = _counter_spike_reason(direction, chart_data)
    if _cs:
        return _fail(_cs)

    # 2c. News-first — ข่าว macro เป็นหลัก: บล็อกการเข้าสวนทิศข่าวที่ชัด
    _ndir, _nwhy = _news_bias_dir(sentiment_data, advisor_data)
    if _ndir and direction != _ndir:
        return _fail(f"News-first: ข่าวชี้ {_ndir} — บล็อก {direction} สวนข่าว ({_nwhy})")

    # 2d. HTF-fade — ห้าม SELL ที่แนวรับ D1/W1 / ห้าม BUY ที่แนวต้าน (โอกาสพลาดสูง)
    _hf = _htf_fade_reason(direction, chart_data)
    if _hf:
        return _fail(_hf)

    # 2e. HTF-direction — ห้ามเข้าสวนเทรนด์ D1 (hard, ไม่มี exception — วางก่อน gate 4
    #     เพื่อไม่ให้ news-override/HTF-reversal ปล่อยไม้สวน D1 ผ่าน: replay พิสูจน์แล้วว่าแพ้)
    _hd = _htf_direction_reason(direction, chart_data)
    if _hd:
        return _fail(_hd)

    # 3. UNKNOWN trend — ไม่เทรดเมื่อ trend ไม่ชัดเจน (WR 32% ใน historical data)
    if not trend or trend.upper() in ("UNKNOWN", "?", ""):
        return _fail(f"UNKNOWN trend — ไม่เทรดเมื่อทิศทาง H4 ไม่ชัดเจน")

    # 4. Counter-trend block
    is_counter = (trend == "BULLISH" and direction == "SELL") or \
                 (trend == "BEARISH" and direction == "BUY")
    if is_counter:
        # Option C — news ลากเข้า: ตรงข่าว + price action ยืนยัน → ข่าวมีอำนาจเหนือเทรนด์ H4
        _ovr_ok, _ovr_why = _news_override_ok(direction, chart_data, _ndir, conf)
        # HTF-reversal override (2026-06-30): ราคาที่ D1/W1 zone หนุนทิศไม้ = reversal มีน้ำหนักกว่า H4 ที่ lag
        # counter-spike (gate 2b) กรอง breakdown-spike ออกก่อนแล้ว → ที่ถึงตรงนี้ = ไม่ดิ่งแรง = reversal-ish
        _htf = chart_data.get("htf_zone")
        _htf_reversal = bool(_htf) and conf >= getattr(_cfg, "HTF_REVERSAL_MIN_CONF", 70) and (
            (direction == "BUY"  and _htf.get("zone_type") == "SUPPORT") or
            (direction == "SELL" and _htf.get("zone_type") == "RESISTANCE")
        )
        if _ovr_ok:
            logger.warning(f"[News-override] {direction} สวนเทรนด์ H4={trend} แต่ {_ovr_why} → อนุญาต")
        elif _htf_reversal:
            logger.warning(f"[HTF-reversal] {direction} สวนเทรนด์ H4={trend} ที่ {_htf.get('tf')} "
                           f"{_htf.get('zone_type')} ({_htf.get('level')}) conf={conf} → อนุญาต (HTF zone > H4 lag)")
        else:
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
        # SR_ZONE bounce: เกณฑ์เดิม 52/60 ถูกครอบด้วย floor รวม (gate 6) ที่สูงกว่าแล้ว — ตัดทิ้ง
        if not _at_sr_zone and _is_breakout and conf < 65:
            return _fail(f"SIDEWAYS MOMENTUM_BREAKOUT requires conf ≥65% (got {conf}%)")

    # 5b. Session gate — Asian/dead-zone sessions block weak entries (data shows Asian = noise)
    _in_quiet_session = not (7 <= _utc_hour < 21)   # Asian 0-7 UTC or dead zone 21-24 UTC
    if _in_quiet_session:
        _sess_lbl = "Asian (quiet)" if _utc_hour < 7 else "NY Close (quiet)"
        _q_min = _cfg.ASIAN_MIN_CONF
        # Asian 0-7 UTC: ทุก entry ต้อง conf ≥ ASIAN_MIN_CONF — replay 489 ไม้:
        # Asian = −4,380 (avg −115/ไม้); บล็อก conf<72 ตัด −4,506 เสียกำไรดีแค่ +57
        if _utc_hour < 7 and conf < _q_min:
            return _fail(f"{_sess_lbl}: ALL entries require conf ≥{_q_min:.0f}% (got {conf}%)")
        if entry_type in ("EMA_PULLBACK", "STRUCTURE_PULLBACK") and conf < _q_min:
            return _fail(f"{_sess_lbl}: EMA/structure entries require conf ≥{_q_min:.0f}% (got {conf}%)")
        if sr_zone == "NONE" and conf < _q_min:
            return _fail(f"{_sess_lbl}: no-zone entries blocked — conf {conf}% < {_q_min:.0f}%")

    # 5c. SELL at RESISTANCE in BEARISH trend — momentum-aware (แก้ 2026-06-30 รอบ 2)
    # SELL@resistance = fade โดยธรรมชาติ = ราคาเด้งขึ้นแตะ resistance (fast_move > 0) เสมอ
    # → เงื่อนไขเดิม (_fast<=0) ไม่เคยจริงที่ resistance → block fade ปกติทั้งหมด (รวม 8 WIN counterfactual 06-30)
    # แก้: allow ถ้าเด้งขึ้น 'ไม่แรง' (< COUNTER_SPIKE_PIPS = pullback/fade ตามเทรนด์ลง) + conf>=floor
    #  - counter-spike (gate 2b) block SELL สวน up-spike แรง (>=500) ออกก่อนแล้ว → ที่ถึงนี่ = fade ปกติ
    #  - block เฉพาะ breakout แรงจริง (fast>=COUNTER_SPIKE, ปกติ counter-spike จับ) หรือ conf<floor
    if direction == "SELL" and trend == "BEARISH" and sr_zone == "RESISTANCE":
        _fast = float(chart_data.get("fast_move_pips", 0) or 0)
        _ok = _fast < _cfg.COUNTER_SPIKE_PIPS and conf >= _cfg.MIN_TECHNICAL_CONFIDENCE
        if not _ok and not (sr_str == "STRONG" and conf >= 80):
            return _fail(f"SELL+RESISTANCE in BEARISH (breakout fast={_fast:+.0f}p / conf {conf}): requires STRONG + conf>=80 (got {sr_str}/{conf}%)")

    # 6. Min confidence — floor เดียวทุกกรณี (replay 489 ไม้: การลด floor ที่ HTF zone
    #    เหลือ 42/45 คือประตูให้ไม้ conf 50-59 ที่ WR 23.5% / −3,807 เข้ามา — เลิกลด)
    htf_zone = chart_data.get("htf_zone")
    _min_conf = _cfg.MIN_TECHNICAL_CONFIDENCE
    if conf < _min_conf:
        return _fail(f"Confidence {conf}% < {_min_conf}% (HTF={htf_zone['tf'] if htf_zone else 'none'})")

    # 6. Entry-type gates
    if entry_type == "EMA_PULLBACK":
        if getattr(_cfg, "EMA_PULLBACK_BLOCK", True):
            return _fail("EMA_PULLBACK hard-blocked — conf≥75 ยัง WR31%/−594 (n=13)  [EMA_PULLBACK_BLOCK]")
        if conf < 75:
            return _fail(f"EMA_PULLBACK requires conf ≥75% (got {conf}%)  [WR 26% historical]")
    if entry_type == "ENGULFING" and conf < 75:
        return _fail(f"ENGULFING requires conf ≥75% (got {conf}%)")

    # MOMENTUM_BREAKOUT: require higher conf threshold at gate 7+8
    # Other entries: conf ≥ 62 is enough
    _ln_ny_overlap = 12 <= _utc_hour < 16   # London/NY overlap (12-16 UTC)
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

    # 9. Regime alignment — เกณฑ์เดิม (TRANSITION<52, counter-regime<55) เป็น dead code
    #    หลัง gate 6 การันตี conf ≥ 62 แล้ว — ตัดทิ้ง (จะคืนชีพได้ก็ต่อเมื่อตั้งเกณฑ์ > floor)

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

    # reset ก่อน early-return ทุกทาง (gate block = ส่วนใหญ่ของ cycles) — ไม่งั้น usage ของ
    # Claude call ครั้งก่อนค้างให้ accounting นับซ้ำทุกรอบ → cost decision_maker เฟ้อใน DB
    # (บัคชนิดเดียวกับที่แก้แล้วใน reporter.analyze_performance)
    global _last_usage
    _last_usage = None

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
    # (NNLB_FASTPATH=false → ตกไปใช้ Claude decision ปกติ = ปลอดภัยขึ้นแลกกับช้า/เสีย token)
    if _cfg.NNLB_FASTPATH and _cfg.NNLB_MODE and ("TREND_CONT" in tech_signal or tech_signal.startswith("HTF_")):
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

    messages = [
        {"role": "system", "content": [
            {"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}
        ]},
        {"role": "user", "content": user_message},
    ]
    try:
        raw_out = _llm.invoke(messages)
        _raw    = raw_out.get("raw")
        _last_usage = (getattr(_raw, "response_metadata", None) or {}).get("usage")
        result: DecisionMakerOutput = raw_out.get("parsed")
        if result is None:
            raise ValueError(raw_out.get("parsing_error") or "structured parse returned None")
        decision         = result.decision
        out_direction    = result.direction
        trade_quality    = result.trade_quality
        confidence_score = result.confidence_score
        decision_text    = result.reason
        logger.info(f"Decision: {decision} {out_direction}")
    except Exception as e:
        logger.error(f"[DM] structured output failed: {e} — defaulting SKIP")
        decision, out_direction, trade_quality, confidence_score = "SKIP", "NONE", "C", 0
        decision_text = f"decision unavailable ({e})"

    logger.info(f"Quality:{trade_quality} ConfScore:{confidence_score}")

    if decision == "EXECUTE" and out_direction in ("BUY", "SELL"):
        # ── เลือก SL ตามทิศทาง (ยืนยันอีกครั้ง) ─────────────────
        sl_key = "buy_sl_pips" if out_direction == "BUY" else "sell_sl_pips"
        sl_pips = chart_data.get(sl_key, sl_pips)

        # ── Position sizing: streak protection only ──────────────
        # ตัด confidence-based lot scaling ออก (2026-06-28): replay พิสูจน์ว่าการ scale lot
        # ตาม confidence ทำลาย ~7,500฿ บน acct 381706956 เพราะ conf ไม่ correlate WR
        # (conf 80-89 แพ้ / 50-59 ชนะ) → scale ตาม conf = อัดเงินหนักในไม้ที่ดันแพ้.
        # คง streak_scale ไว้ (ลด size ตอนแพ้ติดกัน = ป้องกันที่พิสูจน์ได้).
        streak_scale = gate.get("streak_scale", 1.0)
        conf_scale   = round(max(0.10, streak_scale), 2)   # floor 10% ไม่ให้ size เป็น 0
        logger.info(
            f"Position sizing: conf={conf}% (conf-scaling OFF) → scale={conf_scale:.2f}"
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
        # RIDE นำหน้า — comment โดนตัด 31 ตัว tag ต้องรอด เพื่อ segment ผล ride แยกใน MT5/DB
        _ride_tag   = "RIDE " if _momentum_ride_active(out_direction, chart_data) else ""
        comment_tag = f"{_ride_tag}AI:{tech_signal}|PA:{pa_tag}|{sentiment}"
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
