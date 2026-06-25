import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Claude API ────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── MT5 ──────────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 0))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# ── X/Twitter ─────────────────────────────────────────────────
X_USERNAME = os.getenv("X_USERNAME", "")
X_PASSWORD = os.getenv("X_PASSWORD", "")
X_EMAIL    = os.getenv("X_EMAIL", "")

# ── Trading ───────────────────────────────────────────────────
SYMBOL        = os.getenv("SYMBOL", "XAUUSD")
START_BALANCE = float(os.getenv("START_BALANCE", 5000))

# ── Lot size ──────────────────────────────────────────────────
LOT_MODE  = os.getenv("LOT_MODE",  "auto")    # "auto" | "fixed"
FIXED_LOT = float(os.getenv("FIXED_LOT", 0.01))
MIN_LOT   = float(os.getenv("MIN_LOT",   0.01))
MAX_LOT   = float(os.getenv("MAX_LOT",   0.01))

# ── Portfolio Protection ─────────────────────────────────────
# True  = เปิดระบบป้องกัน (max trades / daily loss)
# False = ปิดระบบป้องกัน → เข้า order ได้เสรี (scalping / ทุนน้อย)
PORTFOLIO_PROTECTION = os.getenv("PORTFOLIO_PROTECTION", "true").lower() != "false"

# ── No-TP on High-Impact Event / Strong Momentum ─────────────
# เปิด order โดยไม่ตั้ง TP เมื่อมี event ใหญ่ หรือ momentum แรงมาก
# แล้วตั้ง TP ภายหลังเมื่อตลาดสงบ
NO_TP_ON_EVENT     = os.getenv("NO_TP_ON_EVENT",     "true").lower() != "false"
NO_TP_EVENT_MINS   = int(os.getenv("NO_TP_EVENT_MINS",   "20"))   # ถ้า event อยู่ใน X นาที
NO_TP_WAIT_MINUTES = int(os.getenv("NO_TP_WAIT_MINUTES", "30"))   # รอ X นาทีก่อนตั้ง TP

# ── Dynamic TP Extension ─────────────────────────────────────
# True  = ขยับ TP ออกอัตโนมัติเมื่อ momentum แรงและราคาใกล้ TP
# False = ปิด TP อยู่ที่กำหนดตอนเปิด order
DYNAMIC_TP = os.getenv("DYNAMIC_TP", "true").lower() != "false"

# ── Losing Streak Protection ──────────────────────────────────
# True  = เมื่อแพ้ติดกันเกิน max_losing_streak → เพิ่ม confidence threshold
# False = ไม่สนใจ losing streak เลย (เข้า order ตามสัญญาณปกติ)
STREAK_PROTECTION = os.getenv("STREAK_PROTECTION", "true").lower() != "false"

# ── Money Management ──────────────────────────────────────────
MONEY_MANAGEMENT = {
    "risk_per_trade":        float(os.getenv("RISK_PER_TRADE")        or 0.50),
    "max_daily_loss":        float(os.getenv("MAX_DAILY_LOSS")        or 1.00),
    "max_open_trades":       int(os.getenv("MAX_OPEN_TRADES")         or 4),
    "default_sl_pips":       int(os.getenv("DEFAULT_SL_PIPS")         or 2000),
    "default_tp_pips":       int(os.getenv("DEFAULT_TP_PIPS")         or 5000),
    "min_rr_ratio":          float(os.getenv("MIN_RR_RATIO")          or 2.0),
    "max_pending_buy":        int(os.getenv("MAX_PENDING_BUY")         or 4),
    "max_pending_sell":       int(os.getenv("MAX_PENDING_SELL")        or 4),
    "pending_expiry_hours":  int(os.getenv("PENDING_EXPIRY_HOURS")    or 24),
    "max_losing_streak":     int(os.getenv("MAX_LOSING_STREAK")       or 5),
    "streak_min_confidence": int(os.getenv("STREAK_MIN_CONFIDENCE")   or 62),
    "hedge_buffer_pips":     int(os.getenv("HEDGE_BUFFER_PIPS")       or 2500),
    "conf_full_size_at":     int(os.getenv("CONF_FULL_SIZE_AT")       or 80),
    "conf_min_scale":        float(os.getenv("CONF_MIN_SCALE")        or 0.5),
}

# ── EMA_PULLBACK toxicity gate ────────────────────────────────
# Loss analysis 2026-06: EMA_PULLBACK entries with a wide SL (high ATR) or a
# marginal confidence have ~0% win rate. chart_watcher blocks those deterministically.
# Replay over 514 historical AI trades: removes 7 toxic trades, +$2,981, 0 collateral.
EMA_PULLBACK_MAX_SL   = int(os.getenv("EMA_PULLBACK_MAX_SL")   or 1500)  # SL pips ≥ this → block
EMA_PULLBACK_MIN_CONF = int(os.getenv("EMA_PULLBACK_MIN_CONF") or 70)    # confidence < this → block

# ── Decision gates & anti-fade guards ─────────────────────────
# Replay 489 ไม้ (2026-06-10): conf 50-59 = WR 23.5% / −3,807; Asian 0-7 UTC = −115/ไม้
MIN_TECHNICAL_CONFIDENCE = int(os.getenv("MIN_TECH_CONF") or 62)      # floor ทุก entry (HTF zone ไม่ลดแล้ว)
ASIAN_MIN_CONF           = float(os.getenv("ASIAN_MIN_CONF") or 72)   # Asian 0-7 UTC ทุก entry
COUNTER_SPIKE_PIPS       = float(os.getenv("COUNTER_SPIKE_PIPS") or 500)  # ห้ามเข้าสวนสไปก์ ≥ นี้ (0=ปิด)
NEWS_FIRST               = os.getenv("NEWS_FIRST", "true").lower() != "false"      # บล็อกเข้าสวนทิศข่าวชัด
NEWS_BIAS_MIN_CONF       = float(os.getenv("NEWS_BIAS_MIN_CONF") or 55)
HTF_FADE_BLOCK           = os.getenv("HTF_FADE_BLOCK", "true").lower() != "false"  # ห้าม SELL@D1/W1 support ฯลฯ
NEWS_OVERRIDE_TREND      = os.getenv("NEWS_OVERRIDE_TREND", "true").lower() != "false"  # option C: ข่าว+PA ยืนยัน → เข้าสวน H4 ได้
NEWS_CONFIRM_PIPS        = float(os.getenv("NEWS_CONFIRM_PIPS") or 500)
NEWS_OVERRIDE_MIN_CONF   = float(os.getenv("NEWS_OVERRIDE_MIN_CONF") or 50)
TREND_CONT_CONF          = float(os.getenv("TREND_CONT_CONF") or 65)      # conf สังเคราะห์ TREND_CONT/HTF override
TREND_CONT_MAX_DIST_PCT  = float(os.getenv("TREND_CONT_MAX_DIST_PCT") or 0.3)  # % ห่าง H1 EMA20 (pullback จริง)
NNLB_FASTPATH            = os.getenv("NNLB_FASTPATH", "true").lower() != "false"   # false = NNLB ผ่าน Claude เสมอ
MIN_AI_EQUITY            = float(os.getenv("MIN_AI_EQUITY") or 150)   # ทุนต่ำกว่านี้ → ไม่เรียก AI เลย (0=ปิด)

# ── Position-Guardian thread ──────────────────────────────────
# daemon thread เฝ้าไม้เปิดถี่ๆ (breakeven/trailing/momentum-exit) อิสระจาก AI cycle ที่ช้า
# *** DEFAULT OFF *** — เปิดบน VM หลังทดสอบกับ MT5 จริงแล้วเท่านั้น (concurrency + เงินจริง)
GUARDIAN_ENABLED      = os.getenv("GUARDIAN_ENABLED", "false").lower() == "true"
GUARDIAN_INTERVAL_SEC = int(os.getenv("GUARDIAN_INTERVAL_SEC") or 4)     # poll ทุกกี่วินาที

def reload_config():
    """อ่าน .env ใหม่และอัปเดตตัวแปรทั้งหมด — เรียกทุกต้น cycle เพื่อ pick up dashboard changes"""
    global SYMBOL, START_BALANCE, LOT_MODE, FIXED_LOT, MIN_LOT, MAX_LOT
    global PORTFOLIO_PROTECTION, NO_TP_ON_EVENT, NO_TP_EVENT_MINS, NO_TP_WAIT_MINUTES
    global DYNAMIC_TP, STREAK_PROTECTION
    load_dotenv(override=True)
    SYMBOL        = os.getenv("SYMBOL", "XAUUSD")
    START_BALANCE = float(os.getenv("START_BALANCE", 5000))
    LOT_MODE      = os.getenv("LOT_MODE",  "auto")
    FIXED_LOT     = float(os.getenv("FIXED_LOT", 0.01))
    MIN_LOT       = float(os.getenv("MIN_LOT",   0.01))
    MAX_LOT       = float(os.getenv("MAX_LOT",   0.01))
    PORTFOLIO_PROTECTION = os.getenv("PORTFOLIO_PROTECTION", "true").lower() != "false"
    NO_TP_ON_EVENT     = os.getenv("NO_TP_ON_EVENT",     "true").lower() != "false"
    NO_TP_EVENT_MINS   = int(os.getenv("NO_TP_EVENT_MINS",   "20"))
    NO_TP_WAIT_MINUTES = int(os.getenv("NO_TP_WAIT_MINUTES", "30"))
    DYNAMIC_TP        = os.getenv("DYNAMIC_TP", "true").lower() != "false"
    STREAK_PROTECTION = os.getenv("STREAK_PROTECTION", "true").lower() != "false"
    global TRAILING_STOP, TRAILING_ATR_TF, TRAILING_ATR_MULT
    global TRAILING_MIN_PROFIT_R, TRAILING_LOOKBACK
    global BE_TRIGGER_R, BE_BUFFER_PIPS, BE_CONFIRM_CYCLES
    global HTF_BE_TRIGGER_R, HTF_BE_BUFFER_PIPS
    BE_TRIGGER_R       = float(os.getenv("BE_TRIGGER_R",       "1.2"))
    BE_BUFFER_PIPS     = int(os.getenv("BE_BUFFER_PIPS",     "300"))
    BE_CONFIRM_CYCLES  = int(os.getenv("BE_CONFIRM_CYCLES",  "2"))
    HTF_BE_TRIGGER_R   = float(os.getenv("HTF_BE_TRIGGER_R",  "2.0"))
    HTF_BE_BUFFER_PIPS = int(os.getenv("HTF_BE_BUFFER_PIPS", "1000"))
    TRAILING_STOP        = os.getenv("TRAILING_STOP",           "false").lower() == "true"
    TRAILING_ATR_TF      = os.getenv("TRAILING_ATR_TF",         "D1")
    TRAILING_ATR_MULT    = float(os.getenv("TRAILING_ATR_MULT",  "1.5"))
    TRAILING_MIN_PROFIT_R= float(os.getenv("TRAILING_MIN_PROFIT_R", "1.5"))
    TRAILING_LOOKBACK    = int(os.getenv("TRAILING_LOOKBACK",    "6"))
    global MIN_TECHNICAL_CONFIDENCE, ASIAN_MIN_CONF, COUNTER_SPIKE_PIPS
    global NEWS_FIRST, NEWS_BIAS_MIN_CONF, HTF_FADE_BLOCK
    global NEWS_OVERRIDE_TREND, NEWS_CONFIRM_PIPS, NEWS_OVERRIDE_MIN_CONF
    global TREND_CONT_CONF, TREND_CONT_MAX_DIST_PCT, NNLB_FASTPATH, MIN_AI_EQUITY
    MIN_TECHNICAL_CONFIDENCE = int(os.getenv("MIN_TECH_CONF") or 62)
    ASIAN_MIN_CONF           = float(os.getenv("ASIAN_MIN_CONF") or 72)
    COUNTER_SPIKE_PIPS       = float(os.getenv("COUNTER_SPIKE_PIPS") or 500)
    NEWS_FIRST               = os.getenv("NEWS_FIRST", "true").lower() != "false"
    NEWS_BIAS_MIN_CONF       = float(os.getenv("NEWS_BIAS_MIN_CONF") or 55)
    HTF_FADE_BLOCK           = os.getenv("HTF_FADE_BLOCK", "true").lower() != "false"
    NEWS_OVERRIDE_TREND      = os.getenv("NEWS_OVERRIDE_TREND", "true").lower() != "false"
    NEWS_CONFIRM_PIPS        = float(os.getenv("NEWS_CONFIRM_PIPS") or 500)
    NEWS_OVERRIDE_MIN_CONF   = float(os.getenv("NEWS_OVERRIDE_MIN_CONF") or 50)
    TREND_CONT_CONF          = float(os.getenv("TREND_CONT_CONF") or 65)
    TREND_CONT_MAX_DIST_PCT  = float(os.getenv("TREND_CONT_MAX_DIST_PCT") or 0.3)
    NNLB_FASTPATH            = os.getenv("NNLB_FASTPATH", "true").lower() != "false"
    MIN_AI_EQUITY            = float(os.getenv("MIN_AI_EQUITY") or 150)
    global LESSON_LEARNING, DRY_RUN, NNLB_MODE, NNLB_BASE_EQUITY, NNLB_EQUITY_PER_LOT, NNLB_MAX_LOSS_PCT
    LESSON_LEARNING      = os.getenv("LESSON_LEARNING", "true").lower() != "false"
    DRY_RUN              = os.getenv("DRY_RUN", "false").lower() == "true"
    NNLB_MODE            = os.getenv("NNLB_MODE", "false").lower() == "true"
    NNLB_BASE_EQUITY     = float(os.getenv("NNLB_BASE_EQUITY", "100"))
    NNLB_EQUITY_PER_LOT  = float(os.getenv("NNLB_EQUITY_PER_LOT", "100"))
    NNLB_MAX_LOSS_PCT    = float(os.getenv("NNLB_MAX_LOSS_PCT", "25"))
    global SWING_ENABLED, SWING_MIN_CONF, SWING_MAX_LEGS, SWING_TOTAL_RISK_PCT
    global SWING_LEG_SPLIT, SWING_TF, SWING_BE_TRIGGER_R, SWING_MAX_HOLD_DAYS, SWING_MIN_EQUITY
    SWING_ENABLED        = os.getenv("SWING_ENABLED", "false").lower() == "true"
    SWING_MIN_CONF       = float(os.getenv("SWING_MIN_CONF") or 70)
    SWING_MAX_LEGS       = int(os.getenv("SWING_MAX_LEGS") or 3)
    SWING_TOTAL_RISK_PCT = float(os.getenv("SWING_TOTAL_RISK_PCT") or 20.0)
    SWING_LEG_SPLIT      = [int(x) for x in (os.getenv("SWING_LEG_SPLIT") or "40,30,30").split(",") if x.strip()]
    SWING_TF             = [t.strip().upper() for t in (os.getenv("SWING_TF") or "D1,W1").split(",") if t.strip()]
    SWING_BE_TRIGGER_R   = float(os.getenv("SWING_BE_TRIGGER_R") or 3.0)
    SWING_MAX_HOLD_DAYS  = int(os.getenv("SWING_MAX_HOLD_DAYS") or 30)
    SWING_MIN_EQUITY     = float(os.getenv("SWING_MIN_EQUITY") or 3600)
    MONEY_MANAGEMENT.update({
        "risk_per_trade":        float(os.getenv("RISK_PER_TRADE")        or 0.50),
        "max_daily_loss":        float(os.getenv("MAX_DAILY_LOSS")        or 1.00),
        "max_open_trades":       int(os.getenv("MAX_OPEN_TRADES")         or 4),
        "default_sl_pips":       int(os.getenv("DEFAULT_SL_PIPS")         or 2000),
        "default_tp_pips":       int(os.getenv("DEFAULT_TP_PIPS")         or 5000),
        "min_rr_ratio":          float(os.getenv("MIN_RR_RATIO")          or 2.0),
        "max_pending_buy":        int(os.getenv("MAX_PENDING_BUY")         or 4),
        "max_pending_sell":       int(os.getenv("MAX_PENDING_SELL")        or 4),
        "pending_expiry_hours":  int(os.getenv("PENDING_EXPIRY_HOURS")    or 24),
        "max_losing_streak":     int(os.getenv("MAX_LOSING_STREAK")       or 5),
        "streak_min_confidence": int(os.getenv("STREAK_MIN_CONFIDENCE")   or 62),
        "hedge_buffer_pips":     int(os.getenv("HEDGE_BUFFER_PIPS")       or 2500),
        "conf_full_size_at":     int(os.getenv("CONF_FULL_SIZE_AT")       or 80),
        "conf_min_scale":        float(os.getenv("CONF_MIN_SCALE")        or 0.5),
    })


# ── Breakeven ────────────────────────────────────────────────
# BE_TRIGGER_R  : trigger BE เมื่อ profit ≥ X × SL distance (1.2 = profit > SL)
BE_TRIGGER_R       = float(os.getenv("BE_TRIGGER_R",       "1.2"))
# BE_BUFFER_PIPS: lock กำไรขั้นต่ำ (code ใช้ max(buffer, profit×30%) อัตโนมัติ)
BE_BUFFER_PIPS     = int(os.getenv("BE_BUFFER_PIPS",     "300"))
# BE_CONFIRM_CYCLES: ราคาต้องค้างเหนือ trigger กี่ cycle ก่อน SL ย้าย
BE_CONFIRM_CYCLES  = int(os.getenv("BE_CONFIRM_CYCLES",  "2"))
# HTF zone (D1/W1/MN): ให้วิ่งได้ไกลกว่าก่อน BE
HTF_BE_TRIGGER_R   = float(os.getenv("HTF_BE_TRIGGER_R",  "2.0"))
HTF_BE_BUFFER_PIPS = int(os.getenv("HTF_BE_BUFFER_PIPS", "1000"))

# ── Trailing Stop (Swing Low/High Higher TF) ──────────────────
TRAILING_STOP         = os.getenv("TRAILING_STOP",      "false").lower() == "true"
TRAILING_ATR_TF       = os.getenv("TRAILING_ATR_TF",    "D1")   # H4 | D1 | W1
TRAILING_ATR_MULT     = float(os.getenv("TRAILING_ATR_MULT",     "1.5"))
TRAILING_MIN_PROFIT_R = float(os.getenv("TRAILING_MIN_PROFIT_R", "1.5"))  # start only after 1.5R profit
TRAILING_LOOKBACK     = int(os.getenv("TRAILING_LOOKBACK",       "6"))    # candles for swing calc

# ── Lesson Learning (RAG-based) ───────────────────────────────
LESSON_LEARNING = os.getenv("LESSON_LEARNING", "true").lower() != "false"

# ── DRY_RUN mode — mock MT5 execution, log "would have placed" ─
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# ── NNLB mode (No-Risk-No-Lamborghini) ───────────────────────
# true  = ข้าม money management / gates ทั้งหมด — lot scale ตาม equity tier
# false = ปกติ (แนะนำ)
# *** ค่า BASE_EQUITY / EQUITY_PER_LOT เป็น USD แล้วแปลงเป็นสกุลบัญชีอัตโนมัติ ***
# (rate = pip value ของทอง = $1/pip → USD=1.0, THB~36) → ค่าชุดเดียวใช้ได้ทุกสกุล
NNLB_MODE = os.getenv("NNLB_MODE", "false").lower() == "true"

# equity ขั้นต่ำ (USD) ก่อนอนุญาตให้เข้า order แรก — แปลงเป็นสกุลบัญชีอัตโนมัติ
# ถ้า equity < base(แปลงแล้ว) → skip (ทุนน้อยเกินไป ไม่คุ้มกับ SL)
NNLB_BASE_EQUITY = float(os.getenv("NNLB_BASE_EQUITY", "100"))

# กำไร (USD) ต่อการเพิ่ม 0.01 lot — แปลงเป็นสกุลบัญชีอัตโนมัติ
# steps = floor((equity − base) / per_lot) → lot = MIN_LOT + steps×0.01
# ตัวอย่าง USD: base=25, per_lot=25 → equity $75 (กำไร $50) → steps=2 → lot=0.03
NNLB_EQUITY_PER_LOT = float(os.getenv("NNLB_EQUITY_PER_LOT", "100"))

# max loss ต่อ trade (% ของ equity) — cap lot ให้ loss ไม่เกิน X% (ไม่ขึ้นกับสกุล)
# ค่า 25 หมายถึง ยอมรับ loss ได้ 25% ของ equity ต่อ trade
NNLB_MAX_LOSS_PCT = float(os.getenv("NNLB_MAX_LOSS_PCT", "25"))

# ── SWING_HOLD mode (long-term/position sleeve) — SCAFFOLDING, DEFAULT OFF ─────
# *** ยังไม่ wire เข้า pipeline — ดู .claude/context/SWING_HOLD_spec.md ***
# inert จนครบ 3 ด่าน: equity ≥ SWING_MIN_EQUITY + SWING_ENABLED=true + ผ่าน backtest/DRY_RUN
# ไม่มีโค้ดไหนอ่านค่าพวกนี้ตอนนี้ → เพิ่มไว้เฉยๆ ไม่กระทบ behavior live
SWING_ENABLED        = os.getenv("SWING_ENABLED", "false").lower() == "true"  # master switch
SWING_MIN_CONF       = float(os.getenv("SWING_MIN_CONF") or 70)               # conf floor (สูงกว่า scalp 62)
SWING_MAX_LEGS       = int(os.getenv("SWING_MAX_LEGS") or 3)                  # scale-in สูงสุดกี่ leg
SWING_TOTAL_RISK_PCT = float(os.getenv("SWING_TOTAL_RISK_PCT") or 20.0)       # % equity ต่อ campaign (รวมทุก leg)
SWING_LEG_SPLIT      = [int(x) for x in (os.getenv("SWING_LEG_SPLIT") or "40,30,30").split(",") if x.strip()]
SWING_TF             = [t.strip().upper() for t in (os.getenv("SWING_TF") or "D1,W1").split(",") if t.strip()]
SWING_BE_TRIGGER_R   = float(os.getenv("SWING_BE_TRIGGER_R") or 3.0)          # ช้ากว่า scalp มาก (ถือยาว)
SWING_MAX_HOLD_DAYS  = int(os.getenv("SWING_MAX_HOLD_DAYS") or 30)            # 0 = ไม่จำกัด
SWING_MIN_EQUITY     = float(os.getenv("SWING_MIN_EQUITY") or 3600)           # THB — ต่ำกว่านี้ไม่เปิด campaign (@20%)

# ── X accounts to follow ──────────────────────────────────────
_accounts_raw = os.getenv("X_ACCOUNTS_TO_FOLLOW", "")
X_ACCOUNTS_TO_FOLLOW = (
    [a.strip() for a in _accounts_raw.split(",") if a.strip()]
    or ["kun_purich", "cnnbrk", "BBCBreaking", "ZeroHedge", "markets"]
)

# ── Keywords ──────────────────────────────────────────────────
_keywords_raw = os.getenv("X_KEYWORDS", "")
X_KEYWORDS = (
    [k.strip() for k in _keywords_raw.split(",") if k.strip()]
    or ["XAUUSD", "gold", "XAU", "bullion", "Fed", "inflation",
        # geopolitics (safe-haven driver) + cross-asset — เพิ่มจาก HFM live 06-08 (ceasefire→ทองเด้ง)
        "Iran", "Israel", "ceasefire", "geopolitical", "war", "oil", "crude",
        # macro prints — HFM live 06-10: CPI ต่ำ = driver หลักของวัน แต่ tweet มักพิมพ์แค่ "CPI"
        "CPI", "rate cut",
        # oil-as-hostage escalation theme (HFM live ดึก 06-10: ยิงกัน=ทองลง, น้ำมันคือตัวประกัน)
        "Hormuz", "CENTCOM",
        # HFM live 06-11: เป้ายึดเกาะ Kharg (oil terminal); PPI ร้อนชี้ CPI/เฟด; FOMC พุธหน้า = event ใหญ่
        "Kharg", "PPI", "FOMC",
        # HFM live 06-12: ทีมเจรจาอิหร่านบินไปปากีสถานวันอาทิตย์ 06-14 (multi-party talks)
        "Pakistan",
        # HFM live 06-15: กรอบ MOU ตกลง 06-14, เซ็นทางการศุกร์ 06-19 ที่ Geneva; Pezeshkian ประกาศจะเซ็น
        "Pezeshkian", "Geneva"]
)
