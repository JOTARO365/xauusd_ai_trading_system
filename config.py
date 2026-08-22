import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Claude API ────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── Economic-calendar actuals (optional) ──────────────────────
# actual same-day scrape จาก ForexFactory.com (ไม่ต้อง key) = primary · AV = US backfill (ตามหลัง ~1 เดือน) = fallback
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")

# ── MT5 ──────────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN") or 0)          # ว่าง/ไม่มี → 0 (กัน ValueError ตอนยังไม่กรอก; MT5 จะต่อไม่ได้จนกว่ากรอก)
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# ── X/Twitter ─────────────────────────────────────────────────
X_USERNAME = os.getenv("X_USERNAME", "")
X_PASSWORD = os.getenv("X_PASSWORD", "")
X_EMAIL    = os.getenv("X_EMAIL", "")

# ── Trading ───────────────────────────────────────────────────
SYMBOL        = os.getenv("SYMBOL", "XAUUSD")
START_BALANCE = float(os.getenv("START_BALANCE") or 5000)

# ── Lot size ──────────────────────────────────────────────────
LOT_MODE  = os.getenv("LOT_MODE",  "auto")    # "auto" | "fixed"
FIXED_LOT = float(os.getenv("FIXED_LOT") or 0.01)
MIN_LOT   = float(os.getenv("MIN_LOT")   or 0.01)
MAX_LOT   = float(os.getenv("MAX_LOT")   or 0.01)

# ── Portfolio Protection ─────────────────────────────────────
# True  = เปิดระบบป้องกัน (max trades / daily loss)
# False = ปิดระบบป้องกัน → เข้า order ได้เสรี (scalping / ทุนน้อย)
PORTFOLIO_PROTECTION = os.getenv("PORTFOLIO_PROTECTION", "true").lower() != "false"

# ── No-TP on High-Impact Event / Strong Momentum ─────────────
# เปิด order โดยไม่ตั้ง TP เมื่อมี event ใหญ่ หรือ momentum แรงมาก
# แล้วตั้ง TP ภายหลังเมื่อตลาดสงบ
NO_TP_ON_EVENT     = os.getenv("NO_TP_ON_EVENT",     "true").lower() != "false"
NO_TP_EVENT_MINS   = int(os.getenv("NO_TP_EVENT_MINS")   or 20)   # ถ้า event อยู่ใน X นาที
NO_TP_WAIT_MINUTES = int(os.getenv("NO_TP_WAIT_MINUTES") or 30)   # รอ X นาทีก่อนตั้ง TP

# ── Dynamic TP Extension ─────────────────────────────────────
# True  = ขยับ TP ออกอัตโนมัติเมื่อ momentum แรงและราคาใกล้ TP
# False = ปิด TP อยู่ที่กำหนดตอนเปิด order
DYNAMIC_TP = os.getenv("DYNAMIC_TP", "true").lower() != "false"
TP_EXT_MAX = int(os.getenv("TP_EXT_MAX") or 4)   # จำนวนครั้งสูงสุดที่ dynamic-TP ขยาย TP ต่อไม้ (เดิม 2 → 4; env-tunable)
TP_EXT_PIPS = int(os.getenv("TP_EXT_PIPS") or 400)        # ระยะ extend TP ต่อรอบ (fallback เมื่อไม่มีแนว S/R)
TP_EXT_NEAR_PIPS = int(os.getenv("TP_EXT_NEAR_PIPS") or 150)   # ราคาห่าง TP ≤ นี้ จึงพิจารณา extend
TP_EXT_MOMENTUM_MIN = int(os.getenv("TP_EXT_MOMENTUM_MIN") or 4)   # momentum score ≥ นี้ (max 5) จึง extend
TP_EXT_COOLDOWN_SECS = int(os.getenv("TP_EXT_COOLDOWN_SECS") or 900)   # cooldown ระหว่าง extend แต่ละครั้ง (วินาที)
TP_EXT_SL_LOCK_PIPS = int(os.getenv("TP_EXT_SL_LOCK_PIPS") or 200)   # trail SL ห่างราคา X pips เมื่อ extend (floor ด้วย SL_MIN_GAP)
SPEECH_SUMMARY = os.getenv("SPEECH_SUMMARY", "false").lower() == "true"   # Phase 3: dashboard สรุป speech (Haiku, on-demand, cached) — default OFF (มี cost)

# ── Losing Streak Protection ──────────────────────────────────
# True  = เมื่อแพ้ติดกันเกิน max_losing_streak → เพิ่ม confidence threshold
# False = ไม่สนใจ losing streak เลย (เข้า order ตามสัญญาณปกติ)
STREAK_PROTECTION = os.getenv("STREAK_PROTECTION", "true").lower() != "false"

# ── Money Management ──────────────────────────────────────────
MONEY_MANAGEMENT = {
    "risk_per_trade":        float(os.getenv("RISK_PER_TRADE")        or 0.02),   # B1: 2% safe default (เดิม 0.50=50% footgun)
    "max_daily_loss":        float(os.getenv("MAX_DAILY_LOSS")        or 0.10),   # B2: 10% (เดิม 1.00=100% = daily circuit breaker ปิด)
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

# B1 safety net: hard cap risk ต่อไม้ (auto lot) — risk ต่อ trade ห้ามเกิน % นี้ของ balance ไม่ว่า
# RISK_PER_TRADE เท่าไร (กัน RISK สูง เช่น 2.0=200% ระเบิดพอร์ตเมื่อสลับ LOT_MODE=auto). 0 = ปิด cap
MAX_RISK_PCT = float(os.getenv("MAX_RISK_PCT") or 0.05)

# SL-ENFORCE (08-22): floor SL ขั้นต่ำ — refuse-to-open ถ้า SL หาย/0/แคบกว่านี้ (กันไม้ un-stopped คลาส −6,248).
# 100pt=$1 = safety net เฉยๆ, ไม่กระทบ algo ทองที่ SL structural 200+; SL_BACKSTOP_PIPS = เผื่อ reconcile (ensure_sl_protection ใช้อยู่แล้ว)
SL_MIN_PIPS = float(os.getenv("SL_MIN_PIPS") or 100)
SL_BACKSTOP_PIPS = float(os.getenv("SL_BACKSTOP_PIPS") or 500)

# ── EMA_PULLBACK toxicity gate ────────────────────────────────
# Loss analysis 2026-06: EMA_PULLBACK entries with a wide SL (high ATR) or a
# marginal confidence have ~0% win rate. chart_watcher blocks those deterministically.
# Replay over 514 historical AI trades: removes 7 toxic trades, +$2,981, 0 collateral.
EMA_PULLBACK_MAX_SL   = int(os.getenv("EMA_PULLBACK_MAX_SL")   or 1500)  # SL pips ≥ this → block
EMA_PULLBACK_MIN_CONF = int(os.getenv("EMA_PULLBACK_MIN_CONF") or 70)    # confidence < this → block
# Hard-block EMA_PULLBACK ทั้ง type (2026-06-28): ไม้ที่ผ่าน gate conf≥75 ยัง WR 31%/−594 (n=13)
# → confidence filter EMA_PULLBACK ไม่ได้. ตั้ง false เพื่อกลับไปใช้แค่ sl/conf limits ด้านบน
EMA_PULLBACK_BLOCK    = (os.getenv("EMA_PULLBACK_BLOCK") or "true").lower() != "false"

# MAX_TRADES_PER_DAY: เพดานจำนวนไม้ SYSTEM ที่เปิดได้ต่อวัน (0=ปิด) — เบรกกันวันพายุ
# replay 247 ไม้ (110465856): ไม้ที่ #7+ ของวัน = −411 (n=155) ขณะไม้ 1-6 แรก = +139.88;
# ยุค gates ปัจจุบัน (มิ.ย.+) cap แทบไม่ยิง (block 1 ไม้ = ไม้แพ้) = insurance เกือบฟรี
# นับจาก MT5 entry deals จริงวันนี้ (count_trades_opened_today) — market + pending fills
MAX_TRADES_PER_DAY    = int(os.getenv("MAX_TRADES_PER_DAY") or 6)

# AUTO_SL_PROTECT: ทุก cycle ถ้าเจอ open position ที่ไม่มี SL (sl==0) → ตั้ง SL ให้อัตโนมัติ
# ที่ AUTO_SL_PIPS (0 = ใช้ DEFAULT_SL_PIPS) จากราคาปัจจุบัน (กันรู: manage_* ข้าม sl==0)
# ครอบทั้ง SYSTEM + MANUAL. ตั้ง false เพื่อปิด (ไม่ยุ่งไม้ที่ไม่มี SL)
AUTO_SL_PROTECT       = (os.getenv("AUTO_SL_PROTECT") or "true").lower() != "false"
AUTO_SL_PIPS          = int(os.getenv("AUTO_SL_PIPS") or 0)   # ความกว้าง AUTO-SL แยกจาก SL บอท

# MOMENTUM_RIDE: พอร์ต "โหมดชนะ" ของระบบยุคทอง (พ.ค. W18-19) เข้าระบบปัจจุบัน —
# เมื่อ momentum 3 ชั้นเรียงแถว (M15 STRONG + H1 ทิศเดียวกัน + H4 trend ตรงทิศไม้)
# → ยกเว้น counter-spike + HTF-direction ให้ไม้นั้น (dip-entry/reversal ตามเทรนด์เข้าได้)
# เกราะอื่นทำงานครบ: conf floor, trade cap, daily loss, streak, SL_MIN_GAP, exit mgmt
# ไม้ที่เข้าทางนี้ติด tag RIDE ใน comment → วัดผลแยกได้ (score_trend_mode/DB)
MOMENTUM_RIDE         = os.getenv("MOMENTUM_RIDE", "true").lower() != "false"

# SL_MIN_GAP_PIPS: ทุกกลไกที่ "เลื่อน" SL (breakeven/force-BE/dynamic-TP lock) ห้ามวาง SL
# ใกล้ราคาปัจจุบันกว่านี้ — user report 07-03: SL โดนดันชิด bid/ask (force-BE เหลือ gap 10p,
# dynamic-TP lock 200p, BE-cap×HTF-buffer เหลือ 500p) ขณะทองวัน event วิ่ง ~3,200p
# → โดนกวาดด้วย noise. 0 = ปิด guard (พฤติกรรมเดิม)
SL_MIN_GAP_PIPS       = int(os.getenv("SL_MIN_GAP_PIPS") or 800)

# ── Decision gates & anti-fade guards ─────────────────────────
# Replay 489 ไม้ (2026-06-10): conf 50-59 = WR 23.5% / −3,807; Asian 0-7 UTC = −115/ไม้
MIN_TECHNICAL_CONFIDENCE = int(os.getenv("MIN_TECH_CONF") or 62)      # floor ทุก entry (HTF zone ไม่ลดแล้ว)
ASIAN_MIN_CONF           = float(os.getenv("ASIAN_MIN_CONF") or 72)   # Asian 0-7 UTC ทุก entry
COUNTER_SPIKE_PIPS       = float(os.getenv("COUNTER_SPIKE_PIPS") or 500)  # ห้ามเข้าสวนสไปก์ ≥ นี้ (0=ปิด)
# ── Ecosystem Monitor (dashboard, display-only, 0 token, ไม่ป้อน entry/gate) ──
ECO_RSI_OB = float(os.getenv("ECO_RSI_OB") or 70)   # RSI(14) H1 ≥ นี้ = overbought → เตือนโอกาสกลับตัว
ECO_RSI_OS = float(os.getenv("ECO_RSI_OS") or 30)   # RSI(14) H1 ≤ นี้ = oversold → เตือนโอกาสกลับตัว
# NEWS_GATE retired 2026-08-22 (T-06): was dead under REGIME_LIVE (decision_maker early-return).
# Opposition-block intent deferred to T-17 shadow-only veto in entry_gate.
NEWS_FIRST               = os.getenv("NEWS_FIRST", "true").lower() != "false"      # บล็อกเข้าสวนทิศข่าวชัด
NEWS_BIAS_MIN_CONF       = float(os.getenv("NEWS_BIAS_MIN_CONF") or 55)
HTF_FADE_BLOCK           = os.getenv("HTF_FADE_BLOCK", "true").lower() != "false"  # ห้าม SELL@D1/W1 support ฯลฯ
NEWS_OVERRIDE_TREND      = os.getenv("NEWS_OVERRIDE_TREND", "true").lower() != "false"  # option C: ข่าว+PA ยืนยัน → เข้าสวน H4 ได้
NEWS_CONFIRM_PIPS        = float(os.getenv("NEWS_CONFIRM_PIPS") or 500)
NEWS_OVERRIDE_MIN_CONF   = float(os.getenv("NEWS_OVERRIDE_MIN_CONF") or 50)
# counter-H4 ที่ D1/W1 zone หนุนทิศไม้ (BUY@SUPPORT / SELL@RESISTANCE) = reversal → allow ถ้า conf ≥ นี้
# (gate 4 exception; HTF major zone มีน้ำหนักกว่า H4 ที่ lag; ตั้งสูงมากเช่น 999 = ปิด)
HTF_REVERSAL_MIN_CONF    = float(os.getenv("HTF_REVERSAL_MIN_CONF") or 70)
# HTF-direction block (NEXT STEP #4 ตัวจริง — anchor D1 ไม่ใช่ H4 ของ gate 4):
# ห้ามเข้าสวนเทรนด์ D1 (EMA20+slope, แท่งปิดแล้ว) แบบ hard — replay 251 ไม้ no-lookahead:
# counter-D1 = −248 (มิ.ย.: BUY สวน D1-BEARISH −242 WR21% ≈ เลือดทั้งเดือน, conf 78-82 ก็แพ้)
# ไม้ตาม D1 ≈ breakeven; exception (htf_zone+conf≥70) ทดสอบแล้วแย่ลง → ไม่มี exception
HTF_DIRECTION_BLOCK      = os.getenv("HTF_DIRECTION_BLOCK", "true").lower() != "false"
TREND_CONT_CONF          = float(os.getenv("TREND_CONT_CONF") or 65)      # conf สังเคราะห์ TREND_CONT/HTF override
TREND_CONT_MAX_DIST_PCT  = float(os.getenv("TREND_CONT_MAX_DIST_PCT") or 0.3)  # % ห่าง H1 EMA20 (pullback จริง)
NNLB_FASTPATH            = os.getenv("NNLB_FASTPATH", "true").lower() != "false"   # false = NNLB ผ่าน Claude เสมอ
MIN_AI_EQUITY            = float(os.getenv("MIN_AI_EQUITY") or 150)   # ทุนต่ำกว่านี้ → ไม่เรียก AI เลย (0=ปิด)

# ── Position-Guardian thread ──────────────────────────────────
# daemon thread เฝ้าไม้เปิดถี่ๆ (breakeven/trailing/momentum-exit) อิสระจาก AI cycle ที่ช้า
# *** DEFAULT OFF *** — เปิดบน VM หลังทดสอบกับ MT5 จริงแล้วเท่านั้น (concurrency + เงินจริง)
GUARDIAN_ENABLED      = os.getenv("GUARDIAN_ENABLED", "false").lower() == "true"
GUARDIAN_INTERVAL_SEC = int(os.getenv("GUARDIAN_INTERVAL_SEC") or 4)     # poll ทุกกี่วินาที
# B11: open_order ปล่อย _mt5_lock ระหว่าง retry-backoff sleep (fine-grained) แทนถือ lock ทั้งก้อน
#   → guardian ไม่ถูก starve ตอน retry. false = พฤติกรรมเดิม (ถือ lock ตลอด รวม sleep). เปิดคู่ guardian
OPEN_ORDER_FINE_LOCK  = os.getenv("OPEN_ORDER_FINE_LOCK", "false").lower() == "true"
# B9: เพดานเวลาต่อ cycle (วินาที). >0 = ครอบ ainvoke ด้วย asyncio.wait_for; timeout → รัน protective
#   fallback (SL/BE/trailing) แล้วจบ cycle. 0 = ปิด (พฤติกรรมเดิม: ไม่มีเพดาน แค่ log เตือน)
CYCLE_DEADLINE_SEC    = float(os.getenv("CYCLE_DEADLINE_SEC") or 0)

# ── Specialist agents (multi-TF entries, Layer-A) ─────────────
# *** DEFAULT OFF *** — ships flag-off จน replay-validator ผ่าน. ดู docs/DESIGN_specialist_agents.md
# SHADOW  = compute + append-only capture logs/spec_shadow.jsonl (เก็บ data, 0 token, 0 behavior change)
# ENABLED = advisory context ให้ decision_maker (ไม่แตะ gate/cap 6/floor 62). เปิดหลัง replay ผ่านเท่านั้น
SPECIALIST_SHADOW     = os.getenv("SPECIALIST_SHADOW", "false").lower() == "true"
SPECIALIST_ENABLED    = os.getenv("SPECIALIST_ENABLED", "false").lower() == "true"

# REGIME_SHADOW = minimal-AI regime router (deterministic entry design ใหม่) รัน SHADOW: log ว่า
# "จะเข้าไม้ไหน" ต่อ H1 bar → logs/regime_shadow.jsonl. 0 LLM, 0 order, return {} (ไม่แตะ decision).
# *** DEFAULT OFF *** — entry algos P2-พิสูจน์ −EV; เก็บ track record live-forward ก่อน validate/flip.
# ดู docs/DESIGN_regime_shadow.md. Kill switch = REGIME_SHADOW=false (live-reload).
REGIME_SHADOW         = os.getenv("REGIME_SHADOW", "false").lower() == "true"

# REGIME_LIVE = algo ตัดสินใจ entry เอง (แทน LLM) → วาง order จริง lot จิ๋ว ผ่าน open_order เดิม
# (DRY_RUN + daily-cap + SL/TP + fixed-lot 0.01 ครบในตัว). LLM → sentiment-only (decision_maker หยุดเปิดไม้).
# ⚠️ LIVE MONEY — default OFF. เปิด = พี่ควบคุมเอง (set .env REGIME_LIVE=true + restart). แนะนำ DRY_RUN verify ก่อน.
# entry algo = momentum_breakout ใน TREND เท่านั้น (P2: ยังไม่มี validated edge → lot จิ๋ว เก็บ data จริง).
# kill switch = REGIME_LIVE=false (live-reload). หมายเหตุ: pending/ZRE/swing เป็น path แยก (ปิดเองถ้าจะ algo-only ล้วน).
REGIME_LIVE           = os.getenv("REGIME_LIVE", "false").lower() == "true"

# DB_RECONCILE_SECS = ช่วงเวลา (วินาที) ที่รัน sync+reconcile MT5→DB ระหว่าง session (in-loop).
# แก้ root cause: ไม้ระบบ (magic) ไม่ persist ลง DB ตอนเปิด → DB cohort นิ่งตั้งแต่ startup.
# sync เขียนไม้ใหม่ (OPEN/CLOSED) + reconcile flip DB-OPEN ที่ปิดจริง → /api/data fresh. 0 token. 0=ปิด.
DB_RECONCILE_SECS     = int(os.getenv("DB_RECONCILE_SECS") or 600)

# SHADOW_ENGINE = Batch B multi-pair shadow — รัน algo (regime_momentum) ทุกคู่ใน SHADOW → log/resolve
# เข้า logs/shadow/<algo>__<sym>.jsonl. 0 order, 0 token. default OFF. kill = SHADOW_ENGINE=false.
# SHADOW_UNIVERSE = คู่ที่ shadow (comma-sep; ว่าง = 8 คู่ default ใน algo_registry). MAX_HOLD = timeout บาร์.
SHADOW_ENGINE         = os.getenv("SHADOW_ENGINE", "false").lower() == "true"
SHADOW_UNIVERSE       = [s.strip() for s in os.getenv("SHADOW_UNIVERSE", "").split(",") if s.strip()] or None
SHADOW_MAX_HOLD_BARS  = int(os.getenv("SHADOW_MAX_HOLD_BARS") or 48)

# SHADOW_TSMOM = forward TSMOM-D1 equity tracker (trend-follower) per symbol → logs/shadow/tsmom__<sym>.jsonl.
# 0 order. default OFF. universe (comma-sep) default = trend-family BTCUSD,XAUUSD,XAGUSD (gold = validated ref).
SHADOW_TSMOM          = os.getenv("SHADOW_TSMOM", "false").lower() == "true"
SHADOW_TSMOM_UNIVERSE = [s.strip() for s in os.getenv("SHADOW_TSMOM_UNIVERSE", "").split(",") if s.strip()] or None

# REGIME_LIVE_TICK = per-tick executor (daemon thread) — เช็ค breakout ทุก ~Ns (realtime) แทนรอ bar-close cycle.
# level คำนวณต่อ bar-close (cache), ต่อ tick แค่เทียบราคา vs level (0 LLM, 0 recompute). ต้องมี REGIME_LIVE=true ด้วย.
# ⚠️ LIVE MONEY — default OFF. kill = REGIME_LIVE_TICK=false. เปิด = per-cycle executor ปิดอัตโนมัติ (กันเข้าซ้ำ).
REGIME_LIVE_TICK      = os.getenv("REGIME_LIVE_TICK", "false").lower() == "true"
REGIME_TICK_INTERVAL_SEC = int(os.getenv("REGIME_TICK_INTERVAL_SEC") or 3)

# REGIME_PENDING = algo วาง STOP order ล่วงหน้าที่ Donchian level (straddle: BUY_STOP@high + SELL_STOP@low)
# แทน market entry — MT5 fill เองตอนราคาแตะ. refresh ต่อ H1 bar. mode ที่ 3 (market executors ปิดเมื่อเปิดตัวนี้).
# safety: มีไม้ ALGO เปิด → cancel pending ที่เหลือทุก cycle (กัน whipsaw fill 2 ทาง). ต้องมี REGIME_LIVE=true.
# ⚠️ LIVE MONEY — default OFF. kill = REGIME_PENDING=false.
REGIME_PENDING        = os.getenv("REGIME_PENDING", "false").lower() == "true"

# REGIME_SR_ENTRY = algo v2 P-B: entry_gate (fade S/R + indicator + vol/mom) → **journal shadow เท่านั้น**
# (ยัง 0 order — weights ยังไม่ fit; เก็บ counterfactual outcome ไป fit ก่อน flip live). ดู docs/DESIGN_algo_v2.md.
# ⚠️ default OFF. kill = REGIME_SR_ENTRY=false (live-reload).
REGIME_SR_ENTRY       = os.getenv("REGIME_SR_ENTRY", "false").lower() == "true"

# REGIME_PENDING_FADE = algo v2 P-C: RANGE fade LIMIT (BUY_LIMIT@support / SELL_LIMIT@resistance) วางจริง
# + vol/momentum gate (cancel เมื่อราคาใกล้ + momentum break). ⚠️ RANGE-fade ยังไม่ผ่าน validation (naive fade −EV)
# → เปิดหลัง journal (REGIME_SR_ENTRY) พิสูจน์ edge เท่านั้น. default OFF. ต้องมี REGIME_LIVE=true. kill = false.
REGIME_PENDING_FADE   = os.getenv("REGIME_PENDING_FADE", "false").lower() == "true"

# REGIME_SR_EXIT = algo v2 P-D: exit ตาม S/R — TP ตามความสำคัญแนว (pick_tp_target แทน RR2 คงที่) +
# trailing = vol + S/R buffer (SL ใต้ support/เหนือ resistance − buffer·ATR) สำหรับไม้ ALGO. default OFF.
# ต้องมี REGIME_LIVE=true. kill = REGIME_SR_EXIT=false (live-reload). ดู docs/DESIGN_algo_v2.md.
REGIME_SR_EXIT        = os.getenv("REGIME_SR_EXIT", "false").lower() == "true"

# REGIME_SR_SIZING = algo v2 P-E: lot ไม้ ALGO = risk-based ตามทุน (equity × RISK_PCT / sl_pips, cap MAX_RISK_PCT
# + clamp MIN/MAX_LOT) แทน fixed 0.01 → risk คงที่ต่อทุน (โตตามพอร์ต, floor ที่ MIN_LOT). default OFF.
# ต้องมี REGIME_LIVE=true. ⚠️ แตะ lot จริง — เปิด = พี่ควบคุมเอง. kill = REGIME_SR_SIZING=false.
REGIME_SR_SIZING      = os.getenv("REGIME_SR_SIZING", "false").lower() == "true"
REGIME_SR_RISK_PCT    = float(os.getenv("REGIME_SR_RISK_PCT") or 0.005)   # risk ต่อไม้ ALGO (0.5% ของ equity)

# REGIME_SHADOW_FILL = algo เข้า order แบบ paper/shadow (เฉพาะไม้ ALGO) — วาง order ได้แม้ไม่มีทุน/margin
# (open_order/place_pending_order จำลอง return success ไม่วางจริง). ไม้จริง legacy บริหารปกติ (DRY_RUN=false).
# journal ยังเก็บ counterfactual outcome. เปิด = เก็บ data ก่อนเติมทุน. default OFF. kill = false (live-reload).
REGIME_SHADOW_FILL    = os.getenv("REGIME_SHADOW_FILL", "false").lower() == "true"

# ALGO_MAX_STACK = จำนวนไม้ ALGO ที่ถือพร้อมกันได้ (no-stack เดิม=1). ทุน/margin cap เองว่าวางได้อีกไหม
# (ไม้ปิด/margin ว่าง → เข้าใหม่อัตโนมัติ). ยังผ่าน MAX_OPEN guard ต่อทิศ + margin check. default 1.
ALGO_MAX_STACK        = int(os.getenv("ALGO_MAX_STACK") or 1)
# ALGO_MAX_SAME_DIR = ไม้ ALGO ทิศทางเดียวกันที่ถือพร้อมกันได้ (1 = ห้าม 2 engine เข้าซ้อนทางเดียวกัน; ยังเปิดฝั่งตรงข้ามได้)
ALGO_MAX_SAME_DIR     = int(os.getenv("ALGO_MAX_SAME_DIR") or 1)
# ALGO_ENTRY_HOURS = allow-list ชั่วโมง UTC ที่ intraday algo เข้าได้ (เช่น "0-13"=Asian+London). ว่าง = ทุกชั่วโมง (default, ไม่กรอง)
ALGO_ENTRY_HOURS      = os.getenv("ALGO_ENTRY_HOURS", "")
# MULTI_SYMBOL_LIVE = master toggle: multi_symbol_executor วางออเดอร์จริงบน symbol ที่ toggle=LIVE (default OFF = 0 order; ต้องเปิด + toggle combo LIVE 2 ชั้น)
MULTI_SYMBOL_LIVE     = os.getenv("MULTI_SYMBOL_LIVE", "false").lower() == "true"
# COCKPIT_LIVE = Discretion Cockpit Phase 2: อนุญาต manual order (user กดใน dashboard → cockpit_executor). default OFF = ปฏิเสธทุก order. ⚠️ LIVE MONEY. reuse guard เดิม (LONG_ONLY_ALL/cap/structural-SL). kill = false
COCKPIT_LIVE          = os.getenv("COCKPIT_LIVE", "false").lower() == "true"
# ALGO_SL_MULT = SL multiplier ต่อ symbol "SYM:mult,..." (WTIUSD:0.7 = validated; ตัวอื่น default 1.0)
ALGO_SL_MULT          = os.getenv("ALGO_SL_MULT", "WTIUSD:0.7")
# MSE_MAX_POSITIONS = ไม้สูงสุดที่ multi_symbol_executor ถือพร้อมกันต่อ combo (stack ทีละไม้ต่อ signal-bar ใหม่)
MSE_MAX_POSITIONS     = int(os.getenv("MSE_MAX_POSITIONS") or 1)
# MSE_MAX_TOTAL = เพดานรวมไม้ MSE ทุก symbol (กัน exposure บวมเมื่อเปิดหลายคู่พร้อมกัน). 0 = ไม่จำกัดรวม (per-symbol เท่านั้น)
MSE_MAX_TOTAL         = int(os.getenv("MSE_MAX_TOTAL") or 0)
# MSE_SL_MIN_ATR / MSE_SL_MAX_ATR = clamp SL ของ MSE เป็น multiple ของ ATR (กัน ATR เพี้ยน→SL บ้าๆ; ไม่แตะ edge เคสปกติ). 0 = ปิด clamp ฝั่งนั้น
MSE_SL_MIN_ATR        = float(os.getenv("MSE_SL_MIN_ATR") or 0.5)
MSE_SL_MAX_ATR        = float(os.getenv("MSE_SL_MAX_ATR") or 4.0)
# MSE_RR_SPREAD_TOL = ผ่อน RR gate ของ MSE ต่ำกว่า validated RR เท่านี้ (กัน gate reject ไม้ที่ backtest ผ่าน
# เพราะ RR ถูกคิดใหม่จาก price จริง+spread เทียบ SL/TP จาก signal). 0 = ไม่ผ่อน. เฉพาะ MSE ไม่แตะ decision_maker
MSE_RR_SPREAD_TOL     = float(os.getenv("MSE_RR_SPREAD_TOL") or 0.05)
# Structural SL = วาง SL ที่ "ปลายไส้แท่ง D1 ปิดล่าสุด" เสมอ (BUY→D1.low−buf, SELL→D1.high+buf), ไม่ clamp
# ไม่ fallback (user directive 07-30). ทุนน้อย → lot=min เสมอ + ข้าม risk-cap. แก้ "เข้าถูกทางแต่โดน SL ก่อน".
STRUCTURAL_SL_GOLD    = os.getenv("STRUCTURAL_SL_GOLD", "false").lower() == "true"   # gold ALGO-mom (regime_executor/tick)
STRUCTURAL_SL_MSE     = os.getenv("STRUCTURAL_SL_MSE", "false").lower() == "true"    # MSE (momentum + tsmom คู่ MSE)
# STRUCTURAL_SL_BUFFER_ATR = ระยะเผื่อพ้นไส้ (× ATR) กัน wick สะอาดชน SL
STRUCTURAL_SL_BUFFER_ATR = float(os.getenv("STRUCTURAL_SL_BUFFER_ATR") or 0.3)
# ALGO_ENTRY_MIN_GAP_ATR = กัน stack เกาะจุดเดิม: skip เข้าใหม่ถ้ามีไม้ algo ทิศเดียวกันเปิดอยู่ภายใน n×ATR. 0 = ปิด guard
ALGO_ENTRY_MIN_GAP_ATR = float(os.getenv("ALGO_ENTRY_MIN_GAP_ATR") or 1.0)
# STRUCTURAL_SL_TFS = timeframe ไส้ที่พิจารณา (D1 หรือ H4). STRUCTURAL_SL_PICK = nearest(SL แคบ RR ดี)/farthest(กัน noise มากสุด)
STRUCTURAL_SL_TFS     = os.getenv("STRUCTURAL_SL_TFS", "H4,D1")
STRUCTURAL_SL_PICK    = os.getenv("STRUCTURAL_SL_PICK", "farthest")
# MIN/MAX_ATR = legacy (โหมด pivot+clamp เดิม; กฎ wick ปัจจุบันไม่ใช้ clamp) — คงไว้กัน env drift
STRUCTURAL_SL_MIN_ATR = float(os.getenv("STRUCTURAL_SL_MIN_ATR") or 0.5)
STRUCTURAL_SL_MAX_ATR = float(os.getenv("STRUCTURAL_SL_MAX_ATR") or 4.0)
# WEEKEND_RUN = รัน loop ต่อวันหยุด (เก็บ edge BTC crypto 24/7). AI ยังรัน (sentiment) แต่ loop ห่างขึ้น (ลด token). default OFF
WEEKEND_RUN           = os.getenv("WEEKEND_RUN", "false").lower() == "true"
# WEEKEND_INTERVAL_SECS = interval ต่ำสุดของ loop วันหยุด (ห่างกว่าปกติ = ลด token; default 1800 = 30 นาที)
WEEKEND_INTERVAL_SECS = int(os.getenv("WEEKEND_INTERVAL_SECS") or 1800)
# AUTO_SL_PCT_OTHER = ระยะ auto-SL ของคู่ที่ไม่ใช่ทอง (orphan sl==0) = % ของราคา (ทองใช้ AUTO_SL_PIPS/DEFAULT_SL_PIPS เดิม)
AUTO_SL_PCT_OTHER     = float(os.getenv("AUTO_SL_PCT_OTHER") or 0.01)

# ── SENTIMENT BIAS — LLM ให้คะแนน sentiment −100..+100 (ข่าว+พื้นฐาน) → soft-bias ทิศ algo ──
# สวนทิศ = ต้อง break แรงขึ้น (extra_margin) + lot เล็กลง (lot_mult). ไม่ hard-block (data ยังนำ). default OFF = kill switch.
SENTIMENT_BIAS          = os.getenv("SENTIMENT_BIAS", "false").lower() == "true"
SENTIMENT_BIAS_DEADBAND = int(os.getenv("SENTIMENT_BIAS_DEADBAND") or 20)   # |score| < นี้ = neutral (เข้า 2 ทาง)
SENTIMENT_LOT_FLOOR     = float(os.getenv("SENTIMENT_LOT_FLOOR") or 0.5)    # lot สวนทิศต่ำสุด = floor × lot ปกติ
SENTIMENT_MARGIN_MULT   = float(os.getenv("SENTIMENT_MARGIN_MULT") or 0.5)  # break สวนทิศต้องเกิน level อีก (มากสุด) นี้ × ATR
# |score| ≥ นี้ + ทิศสวน sentiment = veto (ห้ามเข้าทิศผิด, รอทิศถูก) — factor เลือกทิศ. 0 = ปิด (soft ล้วน)
SENTIMENT_BLOCK_ABOVE   = int(os.getenv("SENTIMENT_BLOCK_ABOVE") or 60)
SENTIMENT_REFRESH_MIN   = int(os.getenv("SENTIMENT_REFRESH_MIN") or 30)     # cache score กี่นาที (กัน LLM ยิงถี่)
SENTIMENT_MODEL         = os.getenv("SENTIMENT_MODEL", "claude-sonnet-4-6")

# ── REGIME NARRATIVE AUTO — LLM เขียน narrative ของ macro_regime.md ใหม่รายสัปดาห์ (จันทร์) จากข่าวสด ──
# กัน narrative ค้าง (แก้มือ). เขียนเฉพาะโซน narrative (ไม่แตะ MACRO_AUTO block/header) + backup + log. default OFF = kill switch.
REGIME_NARRATIVE_AUTO   = os.getenv("REGIME_NARRATIVE_AUTO", "false").lower() == "true"
REGIME_NARRATIVE_MODEL  = os.getenv("REGIME_NARRATIVE_MODEL", "claude-sonnet-4-6")
# รันทุกเช้า (1 ครั้ง/วัน หลังชั่วโมงนี้ local). จันทร์=baseline สัปดาห์ · วันอื่น=ติดตามสถานการณ์ใหม่ (ไม่ recap)
REGIME_NARRATIVE_HOUR   = int(os.getenv("REGIME_NARRATIVE_HOUR") or 7)

# ALGO_SIZE_STANDDOWN = safety guard บัญชีเล็ก: ก่อนเปิดไม้ ALGO เช็คว่าถ้าเปิดที่ MIN_LOT จะเสี่ยงเกิน
# ALGO_MAX_TRADE_RISK_PCT ไหม (min-lot ใหญ่เกินทุน). เกิน → ข้ามไม้ (stand down) ไม่ over-risk. ramp อัตโนมัติ
# ตามทุน (ทุนโต → ไม้ SL แคบเปิดก่อน, กว้างตามมา). แตะเฉพาะ momentum ALGO. default ON (ปลอดภัย). 0 token.
ALGO_SIZE_STANDDOWN     = os.getenv("ALGO_SIZE_STANDDOWN", "true").lower() == "true"
ALGO_MAX_TRADE_RISK_PCT = float(os.getenv("ALGO_MAX_TRADE_RISK_PCT") or 0.02)   # เพดาน risk/ไม้ ALGO (2%)

# TSMOM-D1 = time-series momentum รายวัน (DESIGN_tsmom_integration.md) — edge เดียวที่ validated (~31 กลยุทธ์).
# position-based daily overlay: signal ensemble sign(close_D1 − close_D1[L]) majority vote, vol-target lot,
# exit=flip, SL=chandelier. ⚠️ TSMOM_LIVE → ปิด momentum intraday + fade (กัน conflict). default OFF. kill=false.
TSMOM_LIVE       = os.getenv("TSMOM_LIVE", "false").lower() == "true"
TSMOM_SHADOW     = os.getenv("TSMOM_SHADOW", "false").lower() == "true"      # log target เฉยๆ ไม่วาง order
TSMOM_COEXIST    = os.getenv("TSMOM_COEXIST", "false").lower() == "true"     # true → intraday engine ทำงานคู่ TSMOM (ไม่ hand-off) = เข้า BUY+SELL ทั้ง 2 ทาง; cap ด้วย ALGO_MAX_STACK
TSMOM_LONG_ONLY  = os.getenv("TSMOM_LONG_ONLY", "true").lower() == "true"    # (legacy) default BUY-only; ถูก override โดย TSMOM_DIR_MODE ถ้าตั้ง
# TSMOM_DIR_MODE = ทิศ tsmom: long (BUY เท่านั้น) / short (SELL เท่านั้น) / both (symmetric). ถ้าว่าง → derive จาก TSMOM_LONG_ONLY
TSMOM_DIR_MODE   = (os.getenv("TSMOM_DIR_MODE") or ("long" if TSMOM_LONG_ONLY else "both")).lower()
# TSMOM_HEDGE_PENDING = โหมด long/short → วาง pending LIMIT ทิศตรงข้ามที่โซน S/R ปลอดภัย (long→SELL_LIMIT@res). default OFF
TSMOM_HEDGE_PENDING = os.getenv("TSMOM_HEDGE_PENDING", "false").lower() == "true"
TSMOM_MIN_ADX    = float(os.getenv("TSMOM_MIN_ADX") or 0)                    # เข้าเฉพาะ ADX(D1) ≥ นี้ (0 = off; overfit-risk n น้อย)
TSMOM_MIN_VOLPCT = float(os.getenv("TSMOM_MIN_VOLPCT") or 0)                 # เข้าเฉพาะ vol_percentile(D1) ≥ นี้ (0 = off)
TSMOM_LOOKBACKS  = os.getenv("TSMOM_LOOKBACKS", "21,63,126")                # ensemble lookback (วัน D1) — เพิ่ม short-horizon (08-07)
TSMOM_CONFIRM_LB = int(os.getenv("TSMOM_CONFIRM_LB") or 21)                  # short-term confirm: ไม่เข้าสวน momentum n วัน (0=off). BTC/WTI EV ดีขึ้น
# per-combo short-term override (08-07): backtest H4 = short-term ที่ +EV (H1/M15 −EV). "algo:SYM=TF" คั่น ; · lookbacks "algo:SYM=6,18,42"
ALGO_TF_OVERRIDE = os.getenv("ALGO_TF_OVERRIDE", "regime_momentum:BTCUSD=H4;tsmom_d1:XAGUSD=H4")   # BTC H4 momentum(t1.6) + XAG H4 tsmom
ALGO_LB_OVERRIDE = os.getenv("ALGO_LB_OVERRIDE", "tsmom_d1:XAGUSD=6,18,42")                        # lookbacks (บาร์ TF) ต่อ combo
# XAU-XAG pairs-trade (stat-arb, 2-leg market-neutral, 08-07). backtest rolling-β causal: WR57% OOS+2.45 t1.89
PAIRS_LIVE       = os.getenv("PAIRS_LIVE", "false").lower() == "true"        # master gate (default OFF → 0 order)
PAIRS_SHADOW     = os.getenv("PAIRS_SHADOW", "false").lower() == "true"      # paper mode (PAIRS_LIVE=false + นี่=true): log z-trade เก็บสถิติ ไม่วาง order. live-first
PAIRS_REENTRY_COOLDOWN_MIN = int(os.getenv("PAIRS_REENTRY_COOLDOWN_MIN") or 30)   # พักหลังปิดฉุกเฉิน (repair-close/leg-fail/atomic-abort) ก่อนเข้าใหม่ = กัน churn ลูป
PAIRS_SYMBOLS    = os.getenv("PAIRS_SYMBOLS", "XAUUSD:XAGUSD")               # y:x (spread = y − β·x)
PAIRS_WIN        = int(os.getenv("PAIRS_WIN") or 120)                        # rolling window (β + z), บาร์ H1
PAIRS_Z_IN       = float(os.getenv("PAIRS_Z_IN") or 2.0)                     # เข้าเมื่อ |z| ≥
PAIRS_Z_OUT      = float(os.getenv("PAIRS_Z_OUT") or 0.5)                    # ออกเมื่อ |z| ≤ (กลับ mean)
PAIRS_Z_STOP     = float(os.getenv("PAIRS_Z_STOP") or 3.5)                   # cut เมื่อ |z| ≥ (spread เบี่ยงต่อ)
PAIRS_XAU_LOT    = float(os.getenv("PAIRS_XAU_LOT") or 0.0)                  # 0 = ใช้ MIN_LOT (XAG คำนวณ β-hedge)
PAIRS_DISASTER_ATR = float(os.getenv("PAIRS_DISASTER_ATR") or 6.0)           # disaster SL/ขา (×ATR H1, backstop)
CONF15M_SESSION  = os.getenv("CONF15M_SESSION", "13-21")
# event-engine (NFP/CPI/FOMC) — SHADOW-first (log อย่างเดียว จนกว่า validate). ffcalendar+event_scenarios
EVENT_ENGINE_LIVE = os.getenv("EVENT_ENGINE_LIVE", "false").lower() == "true"   # true=bias/gate trade; false=shadow log
EVENT_PRE_MIN     = int(os.getenv("EVENT_PRE_MIN") or 30)                        # ก่อนข่าวแรง N นาที = flat/pause
EVENT_POST_MIN    = int(os.getenv("EVENT_POST_MIN") or 120)                      # หลัง release N นาที = bias window
# loss-adaptive + LLM algo-router (08-08) — SHADOW/OFF default
LOSS_ADAPTIVE_LIVE = os.getenv("LOSS_ADAPTIVE_LIVE", "false").lower() == "true"   # true=ปรับ dir/pause จริง; false=log
LOSS_STREAK_RECHECK = int(os.getenv("LOSS_STREAK_RECHECK") or 3)                  # แพ้ติดกี่ไม้ = trigger
LOSS_ADAPTIVE_COOLDOWN_MIN = int(os.getenv("LOSS_ADAPTIVE_COOLDOWN_MIN") or 240)
ALGO_ROUTER_ENABLE = os.getenv("ALGO_ROUTER_ENABLE", "false").lower() == "true"   # เปิด LLM router (ใช้ token)
ALGO_ROUTER_LIVE   = os.getenv("ALGO_ROUTER_LIVE", "false").lower() == "true"     # true=สลับ switch จริง; false=log
ALGO_ROUTER_ALLOW_PROMOTE = os.getenv("ALGO_ROUTER_ALLOW_PROMOTE", "false").lower() == "true"  # LLM ห้าม promote LIVE เอง (demote-only)
ALGO_ROUTER_EVERY_HRS = float(os.getenv("ALGO_ROUTER_EVERY_HRS") or 6)
ALGO_ROUTER_MIN_GAP_MIN = int(os.getenv("ALGO_ROUTER_MIN_GAP_MIN") or 60)
ALGO_ROUTER_MODEL = os.getenv("ALGO_ROUTER_MODEL", "claude-sonnet-4-6")
# force-close ทุกไม้เมื่อกำไร X% ของ balance (lock กำไร; roll baseline หลังปิด). default OFF
FORCE_CLOSE_PROFIT = os.getenv("FORCE_CLOSE_PROFIT", "false").lower() == "true"
FORCE_CLOSE_PROFIT_PCT = float(os.getenv("FORCE_CLOSE_PROFIT_PCT") or 100)
FORCE_CLOSE_MIN_CAPITAL = float(os.getenv("FORCE_CLOSE_MIN_CAPITAL") or 20000)   # force-close ทำงานเฉพาะ equity < ค่านี้ (โตเล็ก→เกณฑ์); ≥ = ปล่อยวิ่ง
# EOD_PROFIT_CLOSE_HOUR_BKK = ทุนน้อย(<FORCE_CLOSE_MIN_CAPITAL) ไม่ถือกำไรข้ามวัน: รอบแรกที่เลยชั่วโมงนี้ (BKK, UTC+7)
# ของแต่ละวัน → ปิดไม้ระบบที่ floating profit>0 ทั้งหมดครั้งเดียว (lock กำไร carry ข้ามคืน). ขาดทุน=ปล่อย SL. -1=ปิดฟีเจอร์
EOD_PROFIT_CLOSE_HOUR_BKK = int(os.getenv("EOD_PROFIT_CLOSE_HOUR_BKK") or 2)
# ── Capital affordability gate (small-account ruin-guard, sim-derived 08-09) ──
CAPITAL_GATE_ENABLE = (os.getenv("CAPITAL_GATE_ENABLE") or "false").lower() == "true"   # บล็อกไม้เสี่ยงเกิน %ทุน ตอนทุน<FLOOR
CAPITAL_GATE_FLOOR = float(os.getenv("CAPITAL_GATE_FLOOR") or 20000)                    # ทุน<ค่านี้ = gate ทำงาน; ≥ = ปิด
CAPITAL_GATE_MAX_RISK_PCT = float(os.getenv("CAPITAL_GATE_MAX_RISK_PCT") or 15)         # บล็อกถ้า risk/ไม้ > %นี้ ของ equity
# ── fixed-fractional sizing เฉพาะทุน < CAPITAL_GATE_FLOOR (A2 08-09; ≥ = fixed-lot เดิม) ──
FF_SIZING_ENABLE = (os.getenv("FF_SIZING_ENABLE") or "false").lower() == "true"
FF_RISK_PCT = float(os.getenv("FF_RISK_PCT") or 1.0)
ATR_SL_SMALL_CAP = (os.getenv("ATR_SL_SMALL_CAP") or "false").lower() == "true"   # ทุน<FLOOR → ATR SL แทน structural (ให้ FF คุม DD)
SEASONALITY_GATE = (os.getenv("SEASONALITY_GATE") or "false").lower() == "true"   # ทอง: ไม่สวน seasonal แรง (ม.ค/ธ.ค bull, มิ.ย/ก.ย/พ.ย weak; validated t>2)
# S/R entry gate (agents/sr_entry_gate.py): BUY ชนแนวต้านแข็งใกล้/SELL ชนแนวรับแข็งใกล้ → block. momentum-aware
# (แนวที่ทะลุแล้วผ่านเอง). เปิดเฉพาะ combo ที่ผ่าน sr_gate_backtest → data/sr_gate_combos.json (ว่าง=ทุก combo)
SR_ENTRY_GATE   = (os.getenv("SR_ENTRY_GATE") or "false").lower() == "true"
SR_BLOCK_ATR    = float(os.getenv("SR_BLOCK_ATR") or 0.5)    # block ถ้าแนวใกล้ ≤ นี้×ATR
SR_MIN_TOUCHES  = int(os.getenv("SR_MIN_TOUCHES") or 2)      # แนวต้อง touch ≥ นี้ (แข็ง) ถึง block
SR_LOOKBACK     = int(os.getenv("SR_LOOKBACK") or 60)        # หา swing pivot กี่แท่งย้อนหลัง
SR_PIVOT        = int(os.getenv("SR_PIVOT") or 3)            # pivot = local extreme ±กี่แท่ง
SR_CLUSTER_ATR  = float(os.getenv("SR_CLUSTER_ATR") or 0.3)  # merge แนวห่าง ≤ นี้×ATR เป็นแนวเดียว
SR_BREAKOUT_ALGOS = os.getenv("SR_BREAKOUT_ALGOS", "regime_momentum,regime_momentum_fvg,macro_momentum,confluence_15m,tsmom_d1")  # algo ยกเว้น gate (คิดตาม breakout); ใช้เฉพาะ legacy mode = SR_GATE_COMBOS ว่าง
# allowlist combo ที่ให้ S/R gate (comma "algo|SYMBOL"). ตั้ง = allowlist mode: gate เฉพาะที่ list (breakout-tag ไม่เกี่ยว).
# ว่าง = fallback data/sr_gate_combos.json (ตัวผ่าน validation) → ถ้าว่างอีก = legacy (gate ทุกตัวยกเว้น breakout).
SR_GATE_COMBOS  = os.getenv("SR_GATE_COMBOS", "")
# ทุก algo มองโซนก่อน action (user 08-21): true = gate ทุก combo (block-only, momentum-aware) — เหนือ allowlist
SR_GATE_ALL     = (os.getenv("SR_GATE_ALL") or "false").lower() == "true"
# ยกเว้น gate เสมอ (หลักฐานว่า gate ทำแย่) — comma "algo" หรือ "algo|SYMBOL". pullback_buy: gate บล็อก dip กำไร
SR_GATE_EXCLUDE = os.getenv("SR_GATE_EXCLUDE", "pullback_buy")
# rich-zone block (user 08-21): block เฉพาะโซนที่ 'เด้งมีนัยสถิติ' (causal bounce_pct≥min, tests≥min) ไม่ใช่แค่มี swing
SR_RICH_ZONE     = (os.getenv("SR_RICH_ZONE") or "false").lower() == "true"
SR_RICH_MIN_BOUNCE = float(os.getenv("SR_RICH_MIN_BOUNCE") or 55)   # โซนต้องเด้ง ≥ นี้% (จาก causal test) ถึง block
SR_RICH_MIN_TESTS  = int(os.getenv("SR_RICH_MIN_TESTS") or 3)       # ต้องมี test ≥ นี้ครั้ง (มีนัย)
# CDC Action Zone (อ.โฉลก) — ทิศ cdc_zone algo: long (BUY เท่านั้น, default) / short / both. SELL leg −EV → long
CDC_DIR_MODE = (os.getenv("CDC_DIR_MODE") or "long").lower()
# pullback entry (โฉลก wave-2/4: เข้าตอนย่อ ไม่ไล่ราคา) — validated: ดัน XAUUSD t1.99→2.05 (RSI filter พังของดี)
CDC_PULLBACK_MIN = float(os.getenv("CDC_PULLBACK_MIN") or 0.005)   # ต้องย่อจาก high ล่าสุด ≥ นี้ (0.5%) ถึงเข้า; 0=ปิด
CDC_PULLBACK_LB  = int(os.getenv("CDC_PULLBACK_LB") or 20)         # lookback high/low สำหรับวัด pullback
# Turtle pyramiding (big order) — เติม unit ตามเทรนด์. default OFF (money-management sensitive; เปิดเมื่อ live+พร้อม)
CDC_PYRAMID    = (os.getenv("CDC_PYRAMID") or "false").lower() == "true"
CDC_MAX_UNITS  = int(os.getenv("CDC_MAX_UNITS") or 4)             # จำนวน unit สูงสุดต่อ campaign (Turtle=4)
CDC_ADD_HALF_N = float(os.getenv("CDC_ADD_HALF_N") or 0.5)        # เติม unit ทุก +นี้×ATR(N) ที่ราคาไปในทาง
# safety: block cdc entry/pyramid ถ้า risk/unit (min-lot × 2N SL) > นี้% ของ equity (audit: ทอง micro 2N=63%/ไม้!)
CDC_MAX_UNIT_RISK_PCT = float(os.getenv("CDC_MAX_UNIT_RISK_PCT") or 3.0)   # 0=ปิด guard
# Confirmation gate (agents/confirm_gate.py): กรอง "แท่งปฏิเสธ/fakeout" ของสัญญาณ algo เอง — เข้าเฉพาะแท่งสัญญาณ
# ที่ปิดแข็งฝั่งสัญญาณ (BUY ปิดครึ่งบน / SELL ปิดครึ่งล่าง). block-only, apply ทุก algo. price-action confirm.
# เปิดเฉพาะ combo ที่ผ่าน confirm_gate_backtest → data/confirm_gate_combos.json (ว่าง=ทุก combo). default OFF
CONFIRM_GATE = (os.getenv("CONFIRM_GATE") or "false").lower() == "true"
CONFIRM_CLV  = float(os.getenv("CONFIRM_CLV") or 0.5)   # close ต้องอยู่เลย นี้ ของช่วงแท่งไปฝั่งสัญญาณ (0.5=กึ่งกลาง)
# METALS_LONG_ONLY: block ทุก SELL บนโลหะมีค่า (XAU*/XAG*/GOLD/SILVER) ทุก path (open_order choke) — โลหะขาขึ้น
# โครงสร้าง + พิสูจน์แล้วไม่มี short edge (short ทอง/เงินเสีย −9.4k). BTC/อื่น short ได้ปกติ. kill switch = false
METALS_LONG_ONLY = (os.getenv("METALS_LONG_ONLY") or "false").lower() == "true"
# LONG_ONLY_ALL: block ทุก SELL **ทุกคู่** (superset ของ metals) — หลักฐาน 3 ชั้น: DB BUY+86k/SELL−79k · บัญชี 381706956
# BUY+2417/SELL−2440 · real-edge short=ตัวเสียหลัก. ⚠️ regime-dependent (bull 24-25) → kill switch = false ถ้าตลาดพลิกหมี
LONG_ONLY_ALL = (os.getenv("LONG_ONLY_ALL") or "false").lower() == "true"
# TREND_BLOCK_NEUTRAL (gold-fit 08-22): block momentum breakout ทองตอน D1-drift NEUTRAL (choppy = slice เจ๊ง −0.199R
# t−2.62 ทุก quartile). block-only. SHADOW=true → log-only. ⚠️ drift-harvest ไม่ใช่ alpha (t0.93). kill = TREND_BLOCK_NEUTRAL=false
TREND_BLOCK_NEUTRAL = (os.getenv("TREND_BLOCK_NEUTRAL") or "false").lower() == "true"
TREND_BLOCK_NEUTRAL_SHADOW = (os.getenv("TREND_BLOCK_NEUTRAL_SHADOW") or "true").lower() == "true"
# Pullback-buy (dip-buyer SL แคบ) — เข้าย่อในเทรนด์ขึ้นด้วย SL เล็ก (~0.7% risk; ต่าง cdc 2N=15.5%). long-only. SHADOW default
PULLBACK_EMA        = int(os.getenv("PULLBACK_EMA") or 20)          # H1 EMA ที่ reclaim
PULLBACK_D1_EMA     = int(os.getenv("PULLBACK_D1_EMA") or 20)       # D1 EMA trend filter
PULLBACK_SWING_LB   = int(os.getenv("PULLBACK_SWING_LB") or 8)      # ก้นดิพ = min low กี่แท่ง
PULLBACK_SL_BUF_ATR = float(os.getenv("PULLBACK_SL_BUF_ATR") or 0.25)  # buffer ใต้ swing low
PULLBACK_SL_CAP_ATR = float(os.getenv("PULLBACK_SL_CAP_ATR") or 2.0)   # cap SL ที่ นี้×ATR_H1 (คุม risk)
PULLBACK_RR         = float(os.getenv("PULLBACK_RR") or 3.0)        # TP = RR×SL (backtest best RR3)
CUSTOM_LOT_ENABLE = (os.getenv("CUSTOM_LOT_ENABLE") or "false").lower() == "true"   # ใช้ lot ต่อคู่ (data/pair_lots.json แก้จาก dashboard)
# trailing หลวมสำหรับ momentum algo (ปล่อยวิ่งถึง TP; replay: trail แน่นตัดกำไร +119%→+12%)
TRAILING_MOM_MULT = float(os.getenv("TRAILING_MOM_MULT") or 3.0)      # trail กว้าง (×ATR)
TRAILING_MOM_MIN_R = float(os.getenv("TRAILING_MOM_MIN_R") or 1.9)    # trail หลัง R สูง (ใกล้ TP)
MOM_LET_RUN = os.getenv("MOM_LET_RUN", "true").lower() == "true"          # momentum algo = fixed SL/TP (ไม่ BE/trail) ปล่อยถึง TP (replay: +119% vs +12%)                    # gold confluence_15m: เทรดเฉพาะ ชม UTC นี้ (NY, ตัด Asian chop). ว่าง=ทุกชม
TSMOM_SL_ATR     = float(os.getenv("TSMOM_SL_ATR") or 3.0)                   # chandelier disaster SL (× ATR D1)
# TSMOM_SL_PIPS > 0 = override SL เป็นค่าคงที่ (points) แทน chandelier — สำหรับบัญชีเล็กให้เปิด order ได้.
# ⚠️ SL แคบ = edge TSMOM หาย (backtest: SL<2000p → WR 2-18% โดน noise รูด). = execution-test ไม่ใช่ edge.
TSMOM_SL_PIPS    = float(os.getenv("TSMOM_SL_PIPS") or 0)
# TSMOM_SL_CAP_FALLBACK: ทุนไม่พอ SL TSMOM (chandelier กว้าง เกินเพดาน risk) → ใช้ manual auto-SL (AUTO_SL_PIPS/
# DEFAULT_SL_PIPS แคบกว่า พอดีทุน) แทน + เตือนจนเติมทุนพอ → กลับไปใช้ SL TSMOM. default true (risk-reducing).
# ⚠️ SL แคบ = edge TSMOM หาย (WR 2-18%) → fallback = เปิดได้/เก็บ data ไม่ใช่โหมดกำไร. false = warn-only เดิม.
TSMOM_SL_CAP_FALLBACK = os.getenv("TSMOM_SL_CAP_FALLBACK", "true").lower() != "false"

# ZRE = Zone Re-Entry RR≥2 (v2 fixed-SL). วาง LIMIT ดักเด้งที่โซนเกรดสูงเชิงรุก (RR≥2, SL คงที่).
# เกราะสุด (replay 2026-07-16): trend-align-only (ตัด SIDEWAYS ที่ replay ขาดทุน −0.6R),
# grade A/B + score≥ZRE_MIN_SCORE, สด ≤ZRE_MAX_BARS_SINCE, ในระยะ ZRE_PROXIMITY_PCT%,
# cap ZRE_MAX_CONCURRENT/ทิศ + daily cap เดิม. ENABLED=วางจริง, SHADOW=log อย่างเดียว, OFF ทั้งคู่=no-op.
ZONE_REENTRY_ENABLED  = os.getenv("ZONE_REENTRY_ENABLED", "false").lower() == "true"
ZONE_REENTRY_SHADOW   = os.getenv("ZONE_REENTRY_SHADOW", "false").lower() == "true"
ZRE_MIN_SCORE         = int(os.getenv("ZRE_MIN_SCORE") or 78)
ZRE_MAX_BARS_SINCE    = int(os.getenv("ZRE_MAX_BARS_SINCE") or 3)
ZRE_PROXIMITY_PCT     = float(os.getenv("ZRE_PROXIMITY_PCT") or 0.4)
ZRE_TREND_ALIGN_ONLY  = os.getenv("ZRE_TREND_ALIGN_ONLY", "true").lower() != "false"
ZRE_MAX_CONCURRENT    = int(os.getenv("ZRE_MAX_CONCURRENT") or 2)

# P1b — decision-snapshot shadow logging (add-only, 0 behavior change) → logs/decision_snapshots.jsonl
# สะสม labeled feature vector ให้ evidence-based entry model (docs/DESIGN_evidence_based_entry.md §7.0)
DECISION_SNAPSHOT     = os.getenv("DECISION_SNAPSHOT", "true").lower() != "false"
# P1c — trade excursion (MFE/MAE) shadow sampling ต่อ cycle → logs/trade_excursions.jsonl
# สะสม in-trade timeline ให้ statistical-exit model (docs/DESIGN_statistical_exit.md §5)
TRADE_EXCURSION       = os.getenv("TRADE_EXCURSION", "true").lower() != "false"

def reload_config():
    """อ่าน .env ใหม่และอัปเดตตัวแปรทั้งหมด — เรียกทุกต้น cycle เพื่อ pick up dashboard changes"""
    global SYMBOL, START_BALANCE, LOT_MODE, FIXED_LOT, MIN_LOT, MAX_LOT
    global PORTFOLIO_PROTECTION, NO_TP_ON_EVENT, NO_TP_EVENT_MINS, NO_TP_WAIT_MINUTES
    global DYNAMIC_TP, TP_EXT_MAX, TP_EXT_PIPS, TP_EXT_NEAR_PIPS, STREAK_PROTECTION
    global TP_EXT_MOMENTUM_MIN, TP_EXT_COOLDOWN_SECS, TP_EXT_SL_LOCK_PIPS, SPEECH_SUMMARY
    global DB_RECONCILE_SECS, SHADOW_ENGINE, SHADOW_UNIVERSE, SHADOW_MAX_HOLD_BARS
    global SHADOW_TSMOM, SHADOW_TSMOM_UNIVERSE
    load_dotenv(override=True)
    SYMBOL        = os.getenv("SYMBOL", "XAUUSD")
    START_BALANCE = float(os.getenv("START_BALANCE") or 5000)
    LOT_MODE      = os.getenv("LOT_MODE",  "auto")
    FIXED_LOT     = float(os.getenv("FIXED_LOT", 0.01))
    MIN_LOT       = float(os.getenv("MIN_LOT",   0.01))
    MAX_LOT       = float(os.getenv("MAX_LOT",   0.01))
    PORTFOLIO_PROTECTION = os.getenv("PORTFOLIO_PROTECTION", "true").lower() != "false"
    NO_TP_ON_EVENT     = os.getenv("NO_TP_ON_EVENT",     "true").lower() != "false"
    NO_TP_EVENT_MINS   = int(os.getenv("NO_TP_EVENT_MINS",   "20"))
    NO_TP_WAIT_MINUTES = int(os.getenv("NO_TP_WAIT_MINUTES", "30"))
    DYNAMIC_TP        = os.getenv("DYNAMIC_TP", "true").lower() != "false"
    TP_EXT_MAX        = int(os.getenv("TP_EXT_MAX") or 4)
    TP_EXT_PIPS       = int(os.getenv("TP_EXT_PIPS") or 400)
    TP_EXT_NEAR_PIPS  = int(os.getenv("TP_EXT_NEAR_PIPS") or 150)
    TP_EXT_MOMENTUM_MIN  = int(os.getenv("TP_EXT_MOMENTUM_MIN") or 4)
    TP_EXT_COOLDOWN_SECS = int(os.getenv("TP_EXT_COOLDOWN_SECS") or 900)
    TP_EXT_SL_LOCK_PIPS  = int(os.getenv("TP_EXT_SL_LOCK_PIPS") or 200)
    SPEECH_SUMMARY       = os.getenv("SPEECH_SUMMARY", "false").lower() == "true"
    DB_RECONCILE_SECS    = int(os.getenv("DB_RECONCILE_SECS") or 600)
    SHADOW_ENGINE        = os.getenv("SHADOW_ENGINE", "false").lower() == "true"
    SHADOW_UNIVERSE      = [s.strip() for s in os.getenv("SHADOW_UNIVERSE", "").split(",") if s.strip()] or None
    SHADOW_MAX_HOLD_BARS = int(os.getenv("SHADOW_MAX_HOLD_BARS") or 48)
    SHADOW_TSMOM          = os.getenv("SHADOW_TSMOM", "false").lower() == "true"
    SHADOW_TSMOM_UNIVERSE = [s.strip() for s in os.getenv("SHADOW_TSMOM_UNIVERSE", "").split(",") if s.strip()] or None
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
    global BE_MAX_TRIGGER_PIPS
    BE_MAX_TRIGGER_PIPS = int(os.getenv("BE_MAX_TRIGGER_PIPS", "1500"))
    TRAILING_STOP        = os.getenv("TRAILING_STOP",           "false").lower() == "true"
    TRAILING_ATR_TF      = os.getenv("TRAILING_ATR_TF",         "D1")
    TRAILING_ATR_MULT    = float(os.getenv("TRAILING_ATR_MULT",  "0.3"))   # × ATR(tf) — vol-adaptive buffer
    TRAILING_MIN_PROFIT_R= float(os.getenv("TRAILING_MIN_PROFIT_R", "1.5"))
    TRAILING_LOOKBACK    = int(os.getenv("TRAILING_LOOKBACK",    "6"))
    global MIN_TECHNICAL_CONFIDENCE, ASIAN_MIN_CONF, COUNTER_SPIKE_PIPS
    global NEWS_FIRST, NEWS_BIAS_MIN_CONF, HTF_FADE_BLOCK
    global NEWS_OVERRIDE_TREND, NEWS_CONFIRM_PIPS, NEWS_OVERRIDE_MIN_CONF, HTF_REVERSAL_MIN_CONF
    global HTF_DIRECTION_BLOCK
    global TREND_CONT_CONF, TREND_CONT_MAX_DIST_PCT, NNLB_FASTPATH, MIN_AI_EQUITY
    MIN_TECHNICAL_CONFIDENCE = int(os.getenv("MIN_TECH_CONF") or 62)
    ASIAN_MIN_CONF           = float(os.getenv("ASIAN_MIN_CONF") or 72)
    COUNTER_SPIKE_PIPS       = float(os.getenv("COUNTER_SPIKE_PIPS") or 500)
    global ECO_RSI_OB, ECO_RSI_OS
    ECO_RSI_OB               = float(os.getenv("ECO_RSI_OB") or 70)
    ECO_RSI_OS               = float(os.getenv("ECO_RSI_OS") or 30)
    # NEWS_GATE retired 2026-08-22 (T-06) — no reload needed.
    NEWS_FIRST               = os.getenv("NEWS_FIRST", "true").lower() != "false"
    NEWS_BIAS_MIN_CONF       = float(os.getenv("NEWS_BIAS_MIN_CONF") or 55)
    HTF_FADE_BLOCK           = os.getenv("HTF_FADE_BLOCK", "true").lower() != "false"
    NEWS_OVERRIDE_TREND      = os.getenv("NEWS_OVERRIDE_TREND", "true").lower() != "false"
    NEWS_CONFIRM_PIPS        = float(os.getenv("NEWS_CONFIRM_PIPS") or 500)
    NEWS_OVERRIDE_MIN_CONF   = float(os.getenv("NEWS_OVERRIDE_MIN_CONF") or 50)
    HTF_REVERSAL_MIN_CONF    = float(os.getenv("HTF_REVERSAL_MIN_CONF") or 70)
    HTF_DIRECTION_BLOCK      = os.getenv("HTF_DIRECTION_BLOCK", "true").lower() != "false"
    TREND_CONT_CONF          = float(os.getenv("TREND_CONT_CONF") or 65)
    TREND_CONT_MAX_DIST_PCT  = float(os.getenv("TREND_CONT_MAX_DIST_PCT") or 0.3)
    NNLB_FASTPATH            = os.getenv("NNLB_FASTPATH", "true").lower() != "false"
    MIN_AI_EQUITY            = float(os.getenv("MIN_AI_EQUITY") or 150)
    global OPEN_ORDER_FINE_LOCK, CYCLE_DEADLINE_SEC
    OPEN_ORDER_FINE_LOCK     = os.getenv("OPEN_ORDER_FINE_LOCK", "false").lower() == "true"   # B11: ปล่อย lock ระหว่าง retry sleep
    CYCLE_DEADLINE_SEC       = float(os.getenv("CYCLE_DEADLINE_SEC") or 0)                    # B9: เพดานเวลา/cycle (0=ปิด)
    global SPECIALIST_ENABLED, SPECIALIST_SHADOW, MAX_RISK_PCT, REGIME_SHADOW
    global REGIME_LIVE, REGIME_LIVE_TICK, REGIME_TICK_INTERVAL_SEC, REGIME_PENDING, REGIME_SR_ENTRY, REGIME_PENDING_FADE, REGIME_SR_EXIT
    global REGIME_SR_SIZING, REGIME_SR_RISK_PCT, REGIME_SHADOW_FILL, ALGO_MAX_STACK, ALGO_MAX_SAME_DIR, ALGO_ENTRY_HOURS, MULTI_SYMBOL_LIVE, COCKPIT_LIVE, ALGO_SL_MULT, MSE_MAX_POSITIONS, MSE_MAX_TOTAL, MSE_SL_MIN_ATR, MSE_SL_MAX_ATR, MSE_RR_SPREAD_TOL, WEEKEND_RUN, WEEKEND_INTERVAL_SECS, AUTO_SL_PCT_OTHER
    global STRUCTURAL_SL_GOLD, STRUCTURAL_SL_MSE, STRUCTURAL_SL_BUFFER_ATR, STRUCTURAL_SL_MIN_ATR, STRUCTURAL_SL_MAX_ATR, STRUCTURAL_SL_TFS, STRUCTURAL_SL_PICK, ALGO_ENTRY_MIN_GAP_ATR
    global ALGO_SIZE_STANDDOWN, ALGO_MAX_TRADE_RISK_PCT
    global SENTIMENT_BIAS, SENTIMENT_BIAS_DEADBAND, SENTIMENT_LOT_FLOOR, SENTIMENT_MARGIN_MULT, SENTIMENT_BLOCK_ABOVE, SENTIMENT_REFRESH_MIN, SENTIMENT_MODEL
    SENTIMENT_BIAS           = os.getenv("SENTIMENT_BIAS", "false").lower() == "true"
    SENTIMENT_BIAS_DEADBAND  = int(os.getenv("SENTIMENT_BIAS_DEADBAND") or 20)
    SENTIMENT_LOT_FLOOR      = float(os.getenv("SENTIMENT_LOT_FLOOR") or 0.5)
    SENTIMENT_MARGIN_MULT    = float(os.getenv("SENTIMENT_MARGIN_MULT") or 0.5)
    SENTIMENT_BLOCK_ABOVE    = int(os.getenv("SENTIMENT_BLOCK_ABOVE") or 60)
    SENTIMENT_REFRESH_MIN    = int(os.getenv("SENTIMENT_REFRESH_MIN") or 30)
    SENTIMENT_MODEL          = os.getenv("SENTIMENT_MODEL", "claude-sonnet-4-6")
    global REGIME_NARRATIVE_AUTO, REGIME_NARRATIVE_MODEL, REGIME_NARRATIVE_HOUR
    REGIME_NARRATIVE_AUTO    = os.getenv("REGIME_NARRATIVE_AUTO", "false").lower() == "true"
    REGIME_NARRATIVE_MODEL   = os.getenv("REGIME_NARRATIVE_MODEL", "claude-sonnet-4-6")
    REGIME_NARRATIVE_HOUR    = int(os.getenv("REGIME_NARRATIVE_HOUR") or 7)
    global TSMOM_LIVE, TSMOM_SHADOW, TSMOM_COEXIST, TSMOM_LONG_ONLY, TSMOM_MIN_ADX, TSMOM_MIN_VOLPCT, TSMOM_LOOKBACKS, TSMOM_SL_ATR, TSMOM_SL_PIPS, TSMOM_SL_CAP_FALLBACK
    SPECIALIST_SHADOW        = os.getenv("SPECIALIST_SHADOW", "false").lower() == "true"
    SPECIALIST_ENABLED       = os.getenv("SPECIALIST_ENABLED", "false").lower() == "true"
    REGIME_SHADOW            = os.getenv("REGIME_SHADOW", "false").lower() == "true"
    REGIME_LIVE              = os.getenv("REGIME_LIVE", "false").lower() == "true"       # kill switch live-reload
    REGIME_LIVE_TICK         = os.getenv("REGIME_LIVE_TICK", "false").lower() == "true"
    REGIME_TICK_INTERVAL_SEC = int(os.getenv("REGIME_TICK_INTERVAL_SEC") or 3)
    REGIME_PENDING           = os.getenv("REGIME_PENDING", "false").lower() == "true"
    REGIME_SR_ENTRY          = os.getenv("REGIME_SR_ENTRY", "false").lower() == "true"  # P-B fade shadow
    REGIME_PENDING_FADE      = os.getenv("REGIME_PENDING_FADE", "false").lower() == "true"  # P-C RANGE fade LIMIT
    REGIME_SR_EXIT           = os.getenv("REGIME_SR_EXIT", "false").lower() == "true"       # P-D S/R TP + trailing
    REGIME_SR_SIZING         = os.getenv("REGIME_SR_SIZING", "false").lower() == "true"     # P-E risk-based lot
    REGIME_SR_RISK_PCT       = float(os.getenv("REGIME_SR_RISK_PCT") or 0.005)
    REGIME_SHADOW_FILL       = os.getenv("REGIME_SHADOW_FILL", "false").lower() == "true"   # algo paper-fill
    ALGO_MAX_STACK           = int(os.getenv("ALGO_MAX_STACK") or 1)                        # ไม้ ALGO พร้อมกัน
    ALGO_MAX_SAME_DIR        = int(os.getenv("ALGO_MAX_SAME_DIR") or 1)                      # ไม้ ALGO ทิศเดียวกันสูงสุด
    ALGO_ENTRY_HOURS         = os.getenv("ALGO_ENTRY_HOURS", "")                             # allow-list ชม UTC (ว่าง=ทุกชม)
    MULTI_SYMBOL_LIVE        = os.getenv("MULTI_SYMBOL_LIVE", "false").lower() == "true"     # master: executor multi-symbol วางออเดอร์จริง (default OFF)
    COCKPIT_LIVE             = os.getenv("COCKPIT_LIVE", "false").lower() == "true"          # Cockpit Phase 2: manual order (default OFF)
    ALGO_SL_MULT             = os.getenv("ALGO_SL_MULT", "WTIUSD:0.7")                        # SL mult ต่อ symbol "SYM:mult,..."
    MSE_MAX_POSITIONS        = int(os.getenv("MSE_MAX_POSITIONS") or 1)                       # ไม้สูงสุด/combo ที่ executor ถือ
    MSE_MAX_TOTAL            = int(os.getenv("MSE_MAX_TOTAL") or 0)                            # เพดานรวมไม้ MSE ทุก symbol (0=ไม่จำกัด)
    MSE_SL_MIN_ATR           = float(os.getenv("MSE_SL_MIN_ATR") or 0.5)                       # clamp SL ≥ n×ATR (0=ปิด)
    MSE_SL_MAX_ATR           = float(os.getenv("MSE_SL_MAX_ATR") or 4.0)                       # clamp SL ≤ n×ATR (0=ปิด)
    MSE_RR_SPREAD_TOL        = float(os.getenv("MSE_RR_SPREAD_TOL") or 0.05)                   # ผ่อน RR gate MSE ต่ำกว่า validated RR (กัน spread reject)
    WEEKEND_RUN              = os.getenv("WEEKEND_RUN", "false").lower() == "true"             # รัน loop วันหยุด (เก็บ BTC)
    WEEKEND_INTERVAL_SECS   = int(os.getenv("WEEKEND_INTERVAL_SECS") or 1800)                 # loop ห่างวันหยุด (ลด token)
    AUTO_SL_PCT_OTHER       = float(os.getenv("AUTO_SL_PCT_OTHER") or 0.01)                    # auto-SL คู่ non-gold = %ราคา
    STRUCTURAL_SL_GOLD       = os.getenv("STRUCTURAL_SL_GOLD", "false").lower() == "true"       # SL ปลายไส้ D1/H4 — gold
    STRUCTURAL_SL_MSE        = os.getenv("STRUCTURAL_SL_MSE", "false").lower() == "true"        # SL ปลายไส้ D1/H4 — MSE
    STRUCTURAL_SL_BUFFER_ATR = float(os.getenv("STRUCTURAL_SL_BUFFER_ATR") or 0.3)              # เผื่อพ้นไส้ × ATR
    ALGO_ENTRY_MIN_GAP_ATR   = float(os.getenv("ALGO_ENTRY_MIN_GAP_ATR") or 1.0)                # กัน stack เกาะจุดเดิม (0=ปิด)
    STRUCTURAL_SL_TFS        = os.getenv("STRUCTURAL_SL_TFS", "H4,D1")                          # timeframe ไส้ (D1/H4)
    STRUCTURAL_SL_PICK       = os.getenv("STRUCTURAL_SL_PICK", "farthest")                       # nearest/farthest
    STRUCTURAL_SL_MIN_ATR    = float(os.getenv("STRUCTURAL_SL_MIN_ATR") or 0.5)                 # legacy (ไม่ใช้)
    STRUCTURAL_SL_MAX_ATR    = float(os.getenv("STRUCTURAL_SL_MAX_ATR") or 4.0)                 # legacy (ไม่ใช้)
    ALGO_SIZE_STANDDOWN      = os.getenv("ALGO_SIZE_STANDDOWN", "true").lower() == "true"    # small-acct guard
    ALGO_MAX_TRADE_RISK_PCT  = float(os.getenv("ALGO_MAX_TRADE_RISK_PCT") or 0.02)           # เพดาน risk/ไม้
    TSMOM_LIVE               = os.getenv("TSMOM_LIVE", "false").lower() == "true"            # TSMOM directional engine
    TSMOM_SHADOW             = os.getenv("TSMOM_SHADOW", "false").lower() == "true"
    TSMOM_COEXIST            = os.getenv("TSMOM_COEXIST", "false").lower() == "true"         # intraday engine ทำงานคู่ TSMOM
    TSMOM_LONG_ONLY          = os.getenv("TSMOM_LONG_ONLY", "true").lower() == "true"        # legacy (override โดย TSMOM_DIR_MODE)
    global TSMOM_DIR_MODE, TSMOM_HEDGE_PENDING, TSMOM_CONFIRM_LB, ALGO_TF_OVERRIDE, ALGO_LB_OVERRIDE
    TSMOM_DIR_MODE           = (os.getenv("TSMOM_DIR_MODE") or ("long" if TSMOM_LONG_ONLY else "both")).lower()
    TSMOM_HEDGE_PENDING      = os.getenv("TSMOM_HEDGE_PENDING", "false").lower() == "true"
    TSMOM_CONFIRM_LB         = int(os.getenv("TSMOM_CONFIRM_LB") or 21)
    ALGO_TF_OVERRIDE         = os.getenv("ALGO_TF_OVERRIDE", "regime_momentum:BTCUSD=H4;tsmom_d1:XAGUSD=H4")
    ALGO_LB_OVERRIDE         = os.getenv("ALGO_LB_OVERRIDE", "tsmom_d1:XAGUSD=6,18,42")
    global PAIRS_LIVE, PAIRS_SHADOW, PAIRS_REENTRY_COOLDOWN_MIN, PAIRS_SYMBOLS, PAIRS_WIN, PAIRS_Z_IN, PAIRS_Z_OUT, PAIRS_Z_STOP, PAIRS_XAU_LOT, PAIRS_DISASTER_ATR
    PAIRS_LIVE               = os.getenv("PAIRS_LIVE", "false").lower() == "true"
    PAIRS_SHADOW             = os.getenv("PAIRS_SHADOW", "false").lower() == "true"
    PAIRS_REENTRY_COOLDOWN_MIN = int(os.getenv("PAIRS_REENTRY_COOLDOWN_MIN") or 30)
    PAIRS_SYMBOLS            = os.getenv("PAIRS_SYMBOLS", "XAUUSD:XAGUSD")
    PAIRS_WIN                = int(os.getenv("PAIRS_WIN") or 120)
    PAIRS_Z_IN               = float(os.getenv("PAIRS_Z_IN") or 2.0)
    PAIRS_Z_OUT              = float(os.getenv("PAIRS_Z_OUT") or 0.5)
    PAIRS_Z_STOP             = float(os.getenv("PAIRS_Z_STOP") or 3.5)
    PAIRS_XAU_LOT            = float(os.getenv("PAIRS_XAU_LOT") or 0.0)
    PAIRS_DISASTER_ATR       = float(os.getenv("PAIRS_DISASTER_ATR") or 6.0)
    global CONF15M_SESSION
    CONF15M_SESSION          = os.getenv("CONF15M_SESSION", "13-21")
    global EVENT_ENGINE_LIVE, EVENT_PRE_MIN, EVENT_POST_MIN
    EVENT_ENGINE_LIVE        = os.getenv("EVENT_ENGINE_LIVE", "false").lower() == "true"
    EVENT_PRE_MIN            = int(os.getenv("EVENT_PRE_MIN") or 30)
    EVENT_POST_MIN           = int(os.getenv("EVENT_POST_MIN") or 120)
    global LOSS_ADAPTIVE_LIVE, LOSS_STREAK_RECHECK, LOSS_ADAPTIVE_COOLDOWN_MIN, ALGO_ROUTER_ENABLE, ALGO_ROUTER_LIVE, ALGO_ROUTER_ALLOW_PROMOTE, ALGO_ROUTER_EVERY_HRS, ALGO_ROUTER_MIN_GAP_MIN, ALGO_ROUTER_MODEL
    LOSS_ADAPTIVE_LIVE       = os.getenv("LOSS_ADAPTIVE_LIVE", "false").lower() == "true"
    LOSS_STREAK_RECHECK      = int(os.getenv("LOSS_STREAK_RECHECK") or 3)
    LOSS_ADAPTIVE_COOLDOWN_MIN = int(os.getenv("LOSS_ADAPTIVE_COOLDOWN_MIN") or 240)
    ALGO_ROUTER_ENABLE       = os.getenv("ALGO_ROUTER_ENABLE", "false").lower() == "true"
    ALGO_ROUTER_LIVE         = os.getenv("ALGO_ROUTER_LIVE", "false").lower() == "true"
    ALGO_ROUTER_ALLOW_PROMOTE = os.getenv("ALGO_ROUTER_ALLOW_PROMOTE", "false").lower() == "true"
    ALGO_ROUTER_EVERY_HRS    = float(os.getenv("ALGO_ROUTER_EVERY_HRS") or 6)
    ALGO_ROUTER_MIN_GAP_MIN  = int(os.getenv("ALGO_ROUTER_MIN_GAP_MIN") or 60)
    ALGO_ROUTER_MODEL        = os.getenv("ALGO_ROUTER_MODEL", "claude-sonnet-4-6")
    global FORCE_CLOSE_PROFIT, FORCE_CLOSE_PROFIT_PCT
    FORCE_CLOSE_PROFIT       = os.getenv("FORCE_CLOSE_PROFIT", "false").lower() == "true"
    FORCE_CLOSE_PROFIT_PCT   = float(os.getenv("FORCE_CLOSE_PROFIT_PCT") or 100)
    global FORCE_CLOSE_MIN_CAPITAL, EOD_PROFIT_CLOSE_HOUR_BKK
    FORCE_CLOSE_MIN_CAPITAL  = float(os.getenv("FORCE_CLOSE_MIN_CAPITAL") or 20000)
    EOD_PROFIT_CLOSE_HOUR_BKK = int(os.getenv("EOD_PROFIT_CLOSE_HOUR_BKK") or 2)   # ทุนน้อย: flush ไม้กำไร carry หลังชั่วโมงนี้ (BKK)
    global CAPITAL_GATE_ENABLE, CAPITAL_GATE_FLOOR, CAPITAL_GATE_MAX_RISK_PCT
    CAPITAL_GATE_ENABLE = (os.getenv("CAPITAL_GATE_ENABLE") or "false").lower() == "true"
    CAPITAL_GATE_FLOOR = float(os.getenv("CAPITAL_GATE_FLOOR") or 20000)
    CAPITAL_GATE_MAX_RISK_PCT = float(os.getenv("CAPITAL_GATE_MAX_RISK_PCT") or 15)
    global FF_SIZING_ENABLE, FF_RISK_PCT
    FF_SIZING_ENABLE = (os.getenv("FF_SIZING_ENABLE") or "false").lower() == "true"
    FF_RISK_PCT = float(os.getenv("FF_RISK_PCT") or 1.0)
    global ATR_SL_SMALL_CAP
    ATR_SL_SMALL_CAP = (os.getenv("ATR_SL_SMALL_CAP") or "false").lower() == "true"
    global SEASONALITY_GATE
    SEASONALITY_GATE = (os.getenv("SEASONALITY_GATE") or "false").lower() == "true"
    global SR_ENTRY_GATE, SR_BLOCK_ATR, SR_MIN_TOUCHES, SR_LOOKBACK, SR_PIVOT, SR_CLUSTER_ATR
    SR_ENTRY_GATE   = (os.getenv("SR_ENTRY_GATE") or "false").lower() == "true"
    SR_BLOCK_ATR    = float(os.getenv("SR_BLOCK_ATR") or 0.5)
    SR_MIN_TOUCHES  = int(os.getenv("SR_MIN_TOUCHES") or 2)
    SR_LOOKBACK     = int(os.getenv("SR_LOOKBACK") or 60)
    SR_PIVOT        = int(os.getenv("SR_PIVOT") or 3)
    SR_CLUSTER_ATR  = float(os.getenv("SR_CLUSTER_ATR") or 0.3)
    global SR_BREAKOUT_ALGOS, SR_GATE_COMBOS, SR_GATE_ALL, SR_GATE_EXCLUDE, SR_RICH_ZONE, SR_RICH_MIN_BOUNCE, SR_RICH_MIN_TESTS, CDC_DIR_MODE, CDC_PULLBACK_MIN, CDC_PULLBACK_LB, CDC_PYRAMID, CDC_MAX_UNITS, CDC_ADD_HALF_N
    SR_BREAKOUT_ALGOS = os.getenv("SR_BREAKOUT_ALGOS", "regime_momentum,regime_momentum_fvg,macro_momentum,confluence_15m,tsmom_d1")
    SR_GATE_COMBOS  = os.getenv("SR_GATE_COMBOS", "")
    SR_GATE_ALL     = (os.getenv("SR_GATE_ALL") or "false").lower() == "true"
    SR_GATE_EXCLUDE = os.getenv("SR_GATE_EXCLUDE", "pullback_buy")
    SR_RICH_ZONE     = (os.getenv("SR_RICH_ZONE") or "false").lower() == "true"
    SR_RICH_MIN_BOUNCE = float(os.getenv("SR_RICH_MIN_BOUNCE") or 55)
    SR_RICH_MIN_TESTS  = int(os.getenv("SR_RICH_MIN_TESTS") or 3)
    CDC_DIR_MODE = (os.getenv("CDC_DIR_MODE") or "long").lower()
    CDC_PULLBACK_MIN = float(os.getenv("CDC_PULLBACK_MIN") or 0.005)
    CDC_PULLBACK_LB  = int(os.getenv("CDC_PULLBACK_LB") or 20)
    CDC_PYRAMID    = (os.getenv("CDC_PYRAMID") or "false").lower() == "true"
    CDC_MAX_UNITS  = int(os.getenv("CDC_MAX_UNITS") or 4)
    CDC_ADD_HALF_N = float(os.getenv("CDC_ADD_HALF_N") or 0.5)
    global CONFIRM_GATE, CONFIRM_CLV, METALS_LONG_ONLY
    CONFIRM_GATE = (os.getenv("CONFIRM_GATE") or "false").lower() == "true"
    CONFIRM_CLV  = float(os.getenv("CONFIRM_CLV") or 0.5)
    METALS_LONG_ONLY = (os.getenv("METALS_LONG_ONLY") or "false").lower() == "true"
    global LONG_ONLY_ALL
    LONG_ONLY_ALL = (os.getenv("LONG_ONLY_ALL") or "false").lower() == "true"
    global TREND_BLOCK_NEUTRAL, TREND_BLOCK_NEUTRAL_SHADOW
    TREND_BLOCK_NEUTRAL = (os.getenv("TREND_BLOCK_NEUTRAL") or "false").lower() == "true"
    TREND_BLOCK_NEUTRAL_SHADOW = (os.getenv("TREND_BLOCK_NEUTRAL_SHADOW") or "true").lower() == "true"
    global PULLBACK_EMA, PULLBACK_D1_EMA, PULLBACK_SWING_LB, PULLBACK_SL_BUF_ATR, PULLBACK_SL_CAP_ATR, PULLBACK_RR
    PULLBACK_EMA        = int(os.getenv("PULLBACK_EMA") or 20)
    PULLBACK_D1_EMA     = int(os.getenv("PULLBACK_D1_EMA") or 20)
    PULLBACK_SWING_LB   = int(os.getenv("PULLBACK_SWING_LB") or 8)
    PULLBACK_SL_BUF_ATR = float(os.getenv("PULLBACK_SL_BUF_ATR") or 0.25)
    PULLBACK_SL_CAP_ATR = float(os.getenv("PULLBACK_SL_CAP_ATR") or 2.0)
    PULLBACK_RR         = float(os.getenv("PULLBACK_RR") or 3.0)
    global CDC_MAX_UNIT_RISK_PCT
    CDC_MAX_UNIT_RISK_PCT = float(os.getenv("CDC_MAX_UNIT_RISK_PCT") or 3.0)
    global CUSTOM_LOT_ENABLE
    CUSTOM_LOT_ENABLE = (os.getenv("CUSTOM_LOT_ENABLE") or "false").lower() == "true"
    global TRAILING_MOM_MULT, TRAILING_MOM_MIN_R
    TRAILING_MOM_MULT        = float(os.getenv("TRAILING_MOM_MULT") or 3.0)
    TRAILING_MOM_MIN_R       = float(os.getenv("TRAILING_MOM_MIN_R") or 1.9)
    global MOM_LET_RUN
    MOM_LET_RUN              = os.getenv("MOM_LET_RUN", "true").lower() == "true"
    TSMOM_MIN_ADX            = float(os.getenv("TSMOM_MIN_ADX") or 0)                        # เข้าเฉพาะ ADX(D1) ≥ นี้
    TSMOM_MIN_VOLPCT         = float(os.getenv("TSMOM_MIN_VOLPCT") or 0)                     # เข้าเฉพาะ vol% ≥ นี้
    TSMOM_LOOKBACKS          = os.getenv("TSMOM_LOOKBACKS", "21,63,126")
    TSMOM_SL_ATR             = float(os.getenv("TSMOM_SL_ATR") or 3.0)
    TSMOM_SL_PIPS            = float(os.getenv("TSMOM_SL_PIPS") or 0)                        # fixed SL override (บัญชีเล็ก)
    TSMOM_SL_CAP_FALLBACK    = os.getenv("TSMOM_SL_CAP_FALLBACK", "true").lower() != "false"  # ทุนไม่พอ→manual auto-SL

    global ZONE_REENTRY_ENABLED, ZONE_REENTRY_SHADOW, ZRE_MIN_SCORE, ZRE_MAX_BARS_SINCE
    global ZRE_PROXIMITY_PCT, ZRE_TREND_ALIGN_ONLY, ZRE_MAX_CONCURRENT
    ZONE_REENTRY_ENABLED     = os.getenv("ZONE_REENTRY_ENABLED", "false").lower() == "true"
    ZONE_REENTRY_SHADOW      = os.getenv("ZONE_REENTRY_SHADOW", "false").lower() == "true"
    ZRE_MIN_SCORE            = int(os.getenv("ZRE_MIN_SCORE") or 78)
    ZRE_MAX_BARS_SINCE       = int(os.getenv("ZRE_MAX_BARS_SINCE") or 3)
    ZRE_PROXIMITY_PCT        = float(os.getenv("ZRE_PROXIMITY_PCT") or 0.4)
    ZRE_TREND_ALIGN_ONLY     = os.getenv("ZRE_TREND_ALIGN_ONLY", "true").lower() != "false"
    ZRE_MAX_CONCURRENT       = int(os.getenv("ZRE_MAX_CONCURRENT") or 2)
    MAX_RISK_PCT             = float(os.getenv("MAX_RISK_PCT") or 0.05)
    global EMA_PULLBACK_BLOCK, AUTO_SL_PROTECT, MAX_TRADES_PER_DAY, AUTO_SL_PIPS, SL_MIN_GAP_PIPS
    EMA_PULLBACK_BLOCK       = (os.getenv("EMA_PULLBACK_BLOCK") or "true").lower() != "false"
    AUTO_SL_PROTECT          = (os.getenv("AUTO_SL_PROTECT") or "true").lower() != "false"
    MAX_TRADES_PER_DAY       = int(os.getenv("MAX_TRADES_PER_DAY") or 6)
    AUTO_SL_PIPS             = int(os.getenv("AUTO_SL_PIPS") or 0)
    SL_MIN_GAP_PIPS          = int(os.getenv("SL_MIN_GAP_PIPS") or 800)
    global MOMENTUM_RIDE
    MOMENTUM_RIDE            = os.getenv("MOMENTUM_RIDE", "true").lower() != "false"
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
        "risk_per_trade":        float(os.getenv("RISK_PER_TRADE")        or 0.02),   # B1
        "max_daily_loss":        float(os.getenv("MAX_DAILY_LOSS")        or 0.10),   # B2
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
# BE_MAX_TRIGGER_PIPS: เพดาน trigger (pips) — ไม้ SL กว้าง (เช่น 3500p×2.0R=7000p) จะ
# lock กำไรไม่ทันเพราะ trigger ไกลเกิน → cap ไว้ให้ขยับ SL หน้าทุนเมื่อกำไรถึง X pips ไม่ว่า R เท่าไร
BE_MAX_TRIGGER_PIPS = int(os.getenv("BE_MAX_TRIGGER_PIPS", "1500"))

# ── Trailing Stop (Swing Low/High Higher TF) ──────────────────
TRAILING_STOP         = os.getenv("TRAILING_STOP",      "false").lower() == "true"
TRAILING_ATR_TF       = os.getenv("TRAILING_ATR_TF",    "D1")   # H4 | D1 | W1
TRAILING_ATR_MULT     = float(os.getenv("TRAILING_ATR_MULT",     "0.3"))   # × ATR(tf) buffer ใต้/เหนือ swing (vol-adaptive; เดิม flat-$ แคบไป→whipsaw, 0.8 ไกลไป, 0.3 พอดี)
TRAILING_MIN_PROFIT_R = float(os.getenv("TRAILING_MIN_PROFIT_R", "1.5"))  # start only after 1.5R profit
TRAILING_LOOKBACK     = int(os.getenv("TRAILING_LOOKBACK",       "6"))    # candles for swing calc

# ── Lesson Learning (RAG-based) ───────────────────────────────
LESSON_LEARNING = os.getenv("LESSON_LEARNING", "true").lower() != "false"

# ── DRY_RUN mode — mock MT5 execution, log "would have placed" ─
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# ── Regime-aware vol-target sizing (user-approved 2026-07-18) ─
# ลด lot ตอน RISK-OFF (vol สูง, ทองอ่อน −10%/yr) = ลด risk-of-ruin (ช่วย survival). ไม่แตะ direction/gate.
# อ่าน data/risk_regime_now.json (scripts/fetch_risk_regime.py). OFF = 0 behavior change; เปิดผ่าน .env.
# = pure risk-reduction (regime validated ทำนาย forward vol) ไม่ใช่ directional edge.
REGIME_SIZING    = os.getenv("REGIME_SIZING", "false").lower() == "true"
REGIME_OFF_SCALE = float(os.getenv("REGIME_OFF_SCALE", "0.5"))   # RISK-OFF → lot × ค่านี้

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

# ── SWING_HOLD mode (long-term/position sleeve) — DEFAULT OFF ──────────────────
# *** wire เข้า pipeline แล้ว (agents/swing_manager.py → node_position_mgmt) แต่ inert by default ***
# ดู .claude/context/SWING_HOLD_spec.md. manage_swing_campaign() return 0 ทันทีถ้าไม่ผ่าน gate:
# inert จนครบ 2 ด่าน: SWING_ENABLED=true + equity ≥ SWING_MIN_EQUITY → ไม่กระทบ behavior live ตอนนี้
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
    # สำนักข่าวต่างประเทศก่อน (สัญญาณจริง: Fed/geopolitics) — kun_purich (ไทย retail) ท้ายสุด
    # scoring cap 12 โพสต์ตามลำดับ list → ต่างประเทศได้คิวก่อน (07-05 user สั่ง)
    or ["cnnbrk", "BBCBreaking", "ZeroHedge", "markets", "kun_purich"]
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
        "Pezeshkian", "Geneva",
        # crypto (2026-07-26: WEEKEND_RUN เก็บ edge BTC — ข่าว crypto เสาร์อาทิตย์)
        "bitcoin", "BTC", "ethereum", "ETH", "crypto", "halving", "stablecoin", "ETF flows"]
)
