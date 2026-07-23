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
TP_EXT_MAX = int(os.getenv("TP_EXT_MAX") or 4)   # จำนวนครั้งสูงสุดที่ dynamic-TP ขยาย TP ต่อไม้ (เดิม 2 → 4; env-tunable)
TP_EXT_PIPS = int(os.getenv("TP_EXT_PIPS") or 400)        # ระยะ extend TP ต่อรอบ (fallback เมื่อไม่มีแนว S/R)
TP_EXT_NEAR_PIPS = int(os.getenv("TP_EXT_NEAR_PIPS") or 150)   # ราคาห่าง TP ≤ นี้ จึงพิจารณา extend

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
# ── NEWS_GATE (flag, default OFF) — News Impact score ปรับ "conf floor" เท่านั้น ──
# ยังไม่ validate → เปิดด้วยความระวัง. ไม่แตะ money mgmt / HTF-direction / counter-spike.
NEWS_GATE             = os.getenv("NEWS_GATE", "false").lower() == "true"
NEWS_GATE_OPPOSE      = float(os.getenv("NEWS_GATE_OPPOSE") or 40)    # |score| ที่ถือว่า "แรง"
NEWS_OPPOSE_PENALTY   = int(os.getenv("NEWS_OPPOSE_PENALTY") or 8)    # ข่าวสวน → floor +เท่านี้ (เข้มขึ้น)
NEWS_AGREE_RELAX      = int(os.getenv("NEWS_AGREE_RELAX") or 5)       # ข่าวหนุน → floor −เท่านี้ (ผ่อน)
NEWS_GATE_HARD_FLOOR  = int(os.getenv("NEWS_GATE_HARD_FLOOR") or 58)  # ผ่อนแล้วห้ามต่ำกว่านี้เด็ดขาด
NEWS_GATE_MIN_N       = int(os.getenv("NEWS_GATE_MIN_N") or 3)        # ต้อง scored ≥ นี้ ไม่งั้น no-op
NEWS_GATE_MAX_AGE_MIN = int(os.getenv("NEWS_GATE_MAX_AGE_MIN") or 60) # snapshot เก่ากว่านี้ = no-op

# ── (ก) NEWS contradiction dampener (flag, default OFF) — ผ่อน oppose-penalty เมื่อ price/flow สวนข่าว ──
# นับเสียงยืนยันทิศไม้ (momentum m15 STRONG + h1 + fast_move + volume tilt): STRONG เสียง→penalty 0, SOME→ครึ่ง
NEWS_CONTRA_ENABLED   = os.getenv("NEWS_CONTRA_ENABLED", "false").lower() == "true"
NEWS_CONTRA_STRONG    = int(os.getenv("NEWS_CONTRA_STRONG") or 3)     # ≥ เสียงนี้ → penalty 0 (ราคาสวนข่าวท่วมท้น)
NEWS_CONTRA_SOME      = int(os.getenv("NEWS_CONTRA_SOME") or 2)       # ≥ เสียงนี้ → penalty ครึ่ง
NEWS_CONTRA_FAST_PIPS = float(os.getenv("NEWS_CONTRA_FAST_PIPS") or 300)  # fast_move ต้องเกินนี้จึงนับ 1 เสียง
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
TSMOM_LOOKBACKS  = os.getenv("TSMOM_LOOKBACKS", "63,126,252")                # ensemble lookback (วัน D1)
TSMOM_SL_ATR     = float(os.getenv("TSMOM_SL_ATR") or 3.0)                   # chandelier disaster SL (× ATR D1)
# TSMOM_SL_PIPS > 0 = override SL เป็นค่าคงที่ (points) แทน chandelier — สำหรับบัญชีเล็กให้เปิด order ได้.
# ⚠️ SL แคบ = edge TSMOM หาย (backtest: SL<2000p → WR 2-18% โดน noise รูด). = execution-test ไม่ใช่ edge.
TSMOM_SL_PIPS    = float(os.getenv("TSMOM_SL_PIPS") or 0)

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
    TP_EXT_MAX        = int(os.getenv("TP_EXT_MAX") or 4)
    TP_EXT_PIPS       = int(os.getenv("TP_EXT_PIPS") or 400)
    TP_EXT_NEAR_PIPS  = int(os.getenv("TP_EXT_NEAR_PIPS") or 150)
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
    global NEWS_GATE, NEWS_GATE_OPPOSE, NEWS_OPPOSE_PENALTY, NEWS_AGREE_RELAX
    global NEWS_GATE_HARD_FLOOR, NEWS_GATE_MIN_N, NEWS_GATE_MAX_AGE_MIN
    NEWS_GATE             = os.getenv("NEWS_GATE", "false").lower() == "true"
    NEWS_GATE_OPPOSE      = float(os.getenv("NEWS_GATE_OPPOSE") or 40)
    NEWS_OPPOSE_PENALTY   = int(os.getenv("NEWS_OPPOSE_PENALTY") or 8)
    NEWS_AGREE_RELAX      = int(os.getenv("NEWS_AGREE_RELAX") or 5)
    NEWS_GATE_HARD_FLOOR  = int(os.getenv("NEWS_GATE_HARD_FLOOR") or 58)
    NEWS_GATE_MIN_N       = int(os.getenv("NEWS_GATE_MIN_N") or 3)
    NEWS_GATE_MAX_AGE_MIN = int(os.getenv("NEWS_GATE_MAX_AGE_MIN") or 60)

    global NEWS_CONTRA_ENABLED, NEWS_CONTRA_STRONG, NEWS_CONTRA_SOME, NEWS_CONTRA_FAST_PIPS
    NEWS_CONTRA_ENABLED   = os.getenv("NEWS_CONTRA_ENABLED", "false").lower() == "true"
    NEWS_CONTRA_STRONG    = int(os.getenv("NEWS_CONTRA_STRONG") or 3)
    NEWS_CONTRA_SOME      = int(os.getenv("NEWS_CONTRA_SOME") or 2)
    NEWS_CONTRA_FAST_PIPS = float(os.getenv("NEWS_CONTRA_FAST_PIPS") or 300)
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
    global SPECIALIST_ENABLED, SPECIALIST_SHADOW, MAX_RISK_PCT, REGIME_SHADOW
    global REGIME_LIVE, REGIME_LIVE_TICK, REGIME_TICK_INTERVAL_SEC, REGIME_PENDING, REGIME_SR_ENTRY, REGIME_PENDING_FADE, REGIME_SR_EXIT
    global REGIME_SR_SIZING, REGIME_SR_RISK_PCT, REGIME_SHADOW_FILL, ALGO_MAX_STACK
    global ALGO_SIZE_STANDDOWN, ALGO_MAX_TRADE_RISK_PCT
    global TSMOM_LIVE, TSMOM_SHADOW, TSMOM_LOOKBACKS, TSMOM_SL_ATR, TSMOM_SL_PIPS
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
    ALGO_SIZE_STANDDOWN      = os.getenv("ALGO_SIZE_STANDDOWN", "true").lower() == "true"    # small-acct guard
    ALGO_MAX_TRADE_RISK_PCT  = float(os.getenv("ALGO_MAX_TRADE_RISK_PCT") or 0.02)           # เพดาน risk/ไม้
    TSMOM_LIVE               = os.getenv("TSMOM_LIVE", "false").lower() == "true"            # TSMOM directional engine
    TSMOM_SHADOW             = os.getenv("TSMOM_SHADOW", "false").lower() == "true"
    TSMOM_LOOKBACKS          = os.getenv("TSMOM_LOOKBACKS", "63,126,252")
    TSMOM_SL_ATR             = float(os.getenv("TSMOM_SL_ATR") or 3.0)
    TSMOM_SL_PIPS            = float(os.getenv("TSMOM_SL_PIPS") or 0)                        # fixed SL override (บัญชีเล็ก)

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
        "Pezeshkian", "Geneva"]
)
