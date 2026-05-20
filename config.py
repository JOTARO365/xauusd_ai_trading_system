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
    global BE_TRIGGER_R, BE_BUFFER_PIPS
    BE_TRIGGER_R   = float(os.getenv("BE_TRIGGER_R",   "0.8"))
    BE_BUFFER_PIPS = int(os.getenv("BE_BUFFER_PIPS", "200"))
    TRAILING_STOP     = os.getenv("TRAILING_STOP",     "false").lower() == "true"
    TRAILING_ATR_TF   = os.getenv("TRAILING_ATR_TF",   "D1")
    TRAILING_ATR_MULT = float(os.getenv("TRAILING_ATR_MULT", "1.5"))
    global LESSON_LEARNING, DRY_RUN, NNLB_MODE, NNLB_BASE_EQUITY, NNLB_EQUITY_PER_LOT, NNLB_MAX_LOSS_PCT
    LESSON_LEARNING      = os.getenv("LESSON_LEARNING", "true").lower() != "false"
    DRY_RUN              = os.getenv("DRY_RUN", "false").lower() == "true"
    NNLB_MODE            = os.getenv("NNLB_MODE", "false").lower() == "true"
    NNLB_BASE_EQUITY     = float(os.getenv("NNLB_BASE_EQUITY", "100"))
    NNLB_EQUITY_PER_LOT  = float(os.getenv("NNLB_EQUITY_PER_LOT", "100"))
    NNLB_MAX_LOSS_PCT    = float(os.getenv("NNLB_MAX_LOSS_PCT", "25"))
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
# BE_TRIGGER_R  : trigger BE เมื่อ profit ≥ X × SL distance จริงของ position
#                 0.8 = 80% ของ SL (เกือบถึง 1R) — ป้องกันโดนหน้าทุนตอนกำไรน้อย
BE_TRIGGER_R   = float(os.getenv("BE_TRIGGER_R",   "0.8"))
# BE_BUFFER_PIPS: SL วางที่ entry + buffer (BUY) เพื่อรับ spread เล็กน้อย
BE_BUFFER_PIPS = int(os.getenv("BE_BUFFER_PIPS", "200"))

# ── Trailing Stop (Swing Low/High Higher TF) ──────────────────
TRAILING_STOP     = os.getenv("TRAILING_STOP",     "false").lower() == "true"
TRAILING_ATR_TF   = os.getenv("TRAILING_ATR_TF",   "D1")    # H4 | D1 | W1
TRAILING_ATR_MULT = float(os.getenv("TRAILING_ATR_MULT", "1.5"))

# ── Lesson Learning (RAG-based) ───────────────────────────────
LESSON_LEARNING = os.getenv("LESSON_LEARNING", "true").lower() != "false"

# ── DRY_RUN mode — mock MT5 execution, log "would have placed" ─
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# ── NNLB mode (No-Risk-No-Lamborghini) ───────────────────────
# true  = ข้าม money management / gates ทั้งหมด — lot คำนวณจาก equity tier
# false = ปกติ (แนะนำ)
NNLB_MODE = os.getenv("NNLB_MODE", "false").lower() == "true"

# equity ขั้นต่ำ (USD) ก่อนอนุญาตให้เข้า order แรก
# ถ้า equity < NNLB_BASE_EQUITY → skip (ทุนน้อยเกินไป ไม่คุ้มกับ SL)
NNLB_BASE_EQUITY = float(os.getenv("NNLB_BASE_EQUITY", "100"))

# equity ที่ต้องการต่อ 1 MIN_LOT
# tier = floor(equity / NNLB_EQUITY_PER_LOT) → lot = MIN_LOT × tier
# ตัวอย่าง: equity=300, NNLB_EQUITY_PER_LOT=100, MIN_LOT=0.01
#   → tier=3 → lot=0.03
NNLB_EQUITY_PER_LOT = float(os.getenv("NNLB_EQUITY_PER_LOT", "100"))

# max loss ต่อ trade (% ของ equity) — ถ้า SL กว้างเกินไปสำหรับทุนที่มี → skip
# ค่า 25 หมายถึง ยอมรับ loss ได้ 25% ของ equity ต่อ trade
NNLB_MAX_LOSS_PCT = float(os.getenv("NNLB_MAX_LOSS_PCT", "25"))

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
    or ["XAUUSD", "gold", "XAU", "bullion", "Fed", "inflation"]
)
