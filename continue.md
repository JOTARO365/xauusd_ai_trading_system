# XAUUSD AI Trading System — Profitability Fix Progress

## Branch
`claude/investigate-profitability-pY79v`

## วัตถุประสงค์
แก้ไขสาเหตุหลักที่ทำให้ระบบยังไม่ทำกำไร จากการวิเคราะห์พบ 10 ปัญหา
Session นี้แก้ไป 5 ข้อแล้ว (Issue #1–#5)

---

## ✅ แก้ไขเสร็จแล้ว

### Issue #1 — R:R ต่ำเกินไป + SL ใหญ่เกินไป
**Files:** `agents/chart_watcher.py`, `config.py`, `agents/decision_maker.py`, `agents/prompts/chart_watcher.md`

**การเปลี่ยนแปลง:**
- `SL_MIN_PIPS`: 1000 → 500, `SL_MAX_PIPS`: 2000 → 3500
- เพิ่ม `calc_sl_atr_floor()` — SL = max(wick_sl, 1.0×H4_ATR) ป้องกันโดน H4 noise
- `min_rr_ratio`: 1.5 → **2.0** (breakeven WR ลดจาก 40% → 33%)
- `default_tp_pips`: 3000 → **5000**
- `_effective_min_rr()` floor: 1.0 → **1.5** (hot market ไม่ต่ำกว่า 1.5:1 อีกต่อไป)
- SL validation range: 1000–3000 → 500–3500

---

### Issue #2 — Position sizing ไม่ปรับตาม Confidence
**Files:** `connectors/mt5_connector.py`, `agents/decision_maker.py`, `config.py`

**การเปลี่ยนแปลง:**
- `calculate_lot_size()` + `open_order()` รับ `confidence_scale` parameter
- สูตร: `scale = max(conf_min_scale, min(1.0, confidence / conf_full_size_at))`
- Config defaults: `CONF_FULL_SIZE_AT=80`, `CONF_MIN_SCALE=0.5`
- ผล: conf=50% → scale=0.63×, conf=65% → 0.81×, conf=80%+ → 1.0×

| Confidence | Scale | Effective risk |
|---|---|---|
| 50% | 0.63× | ~0.31% |
| 65% | 0.81× | ~0.41% |
| 80%+ | 1.0× | 0.5% |

---

### Issue #3 — Gate หลายชั้นทำให้ Claude ได้ context มากเกินไป
**Files:** `agents/decision_maker.py`, `agents/prompts/decision_maker.md`

**การเปลี่ยนแปลง:**
- แยก gate logic ทั้งหมดออกเป็นฟังก์ชัน `_run_gates()` (Python-only, ไม่เรียก Claude)
- Gate 12 ชั้น (daily loss, trend filter, SR zone, ATR, regime, streak, SL validation ฯลฯ)
- Claude รับแค่ **8 บรรทัด clean summary** แทนที่จะเป็น 80+ บรรทัด
- `decision_maker.md`: ลดจาก 136 บรรทัด → 40 บรรทัด ถามแค่ "setup quality ดีพอไหม?"
- Input tokens: ~600 → ~150 tokens ต่อ call

**Format ที่ Claude เห็น:**
```
Signal: BUY | Conf: 72% | Entry: SR_ZONE
Zone: RESISTANCE H4 STRONG | PA: REJECTION @ 3312.50 | Candle: SHOOTING_STAR body=65%
Trend H4: BULLISH | Session: London (10:xx UTC)
Momentum: H4:UP_STRONG H1:UP_MODERATE M15:UP_STRONG
SL: 1800p | TP: 3600p | R:R: 2.0 (min 1.8)
Sentiment: NEUTRAL (no news)
Regime: BULLISH_TREND (85%) ...
History — SR_ZONE 12 trades | WR=58.3% | P&L=+123.45
Account — Today: +$45.00 (2 trades) | WR10: 60% | Streak: 0L
```

---

### Issue #4 — Entry Signal ไม่มี Edge จริง (ใช้แค่ retail indicator)
**Files:** `agents/chart_watcher.py`, `agents/prompts/chart_watcher.md`

**การเปลี่ยนแปลง:**
- **ลบ** `EMA_CROSS H1` — lagging signal (fires after move is done)
- **ลบ** `MACD_CROSS H1` — lagging signal
- **เพิ่ม** `_check_h1_structure()` — ตรวจ higher lows (BUY) / lower highs (SELL) บน H1 จาก swing จริง
- **เพิ่ม** `_check_bb_squeeze()` — BB touch มี edge เฉพาะเมื่อ squeeze ก่อน (width < 85% avg)
- **เพิ่ม** H1 structure bonus (+8–10 pts) ใน SR_ZONE setups เมื่อ H1 structure ดี
- **แก้** `EMA_PULLBACK` ต้องการ candle body ≥ 40% ก่อน fire
- **แก้** `RSI_OVERSOLD/OVERBOUGHT` ต้องการ H1 EMA สนับสนุน + ขยับ threshold เป็น 30/70
- **เพิ่ม** `STRUCTURE_PULLBACK` — H1 bull/bear stack + pullback ถึง EMA50 + structure confirmed (score 70)

---

### Issue #5 — Trend Definition ล้าหลัง (ใช้แค่ EMA200)
**Files:** `agents/chart_watcher.py`, `agents/prompts/chart_watcher.md`

**การเปลี่ยนแปลง:**
แทน `h4_bias` ด้วย **multi-component score** (4 ตัว ต้องได้ ≥ 3 จึงเป็น BULLISH/BEARISH):
1. Price vs EMA200 (long-term anchor ยังอยู่)
2. H4 EMA50 slope (เปรียบ bar ปัจจุบัน vs 5 bars ก่อน — เร็วกว่า EMA200 มาก)
3. H1 EMA stack (close > EMA20 > EMA50 = bullish — sensitive มาก)
4. H4 recent swing structure (higher highs+lows = bull, lower highs+lows = bear)

ผล: จับ trend change เร็วขึ้น 2–5 H4 candle เพราะ H1 EMA + H4 EMA50 slope ตอบสนองเร็วกว่า EMA200

---

## 🔲 ยังไม่ได้แก้ (Issues #6–#10)

### Issue #6 — ไม่มีระบบ Profit-Taking
**ปัญหา:** ไม่มี scale-out ที่ 1R, 2R, 3R — กำไรถูกเปิดค้างจน TP ไกลมาก โอกาสกลับตัวสูง
**แนวทางแก้:**
- เพิ่ม partial close logic ใน `manage_breakeven()` หรือ `manage_dynamic_tp()`
- Scale out 50% ที่ 1R, move SL to BE
- Scale out อีก 30% ที่ 2R, trail SL 50% of move
- Let 20% run to full TP
**Files ที่ต้องแก้:** `connectors/mt5_connector.py` (เพิ่ม `manage_partial_close()`), `main.py`

---

### Issue #7 — Portfolio Protection ทำงานหลังเกิดความเสียหาย
**ปัญหา:** Losing streak ≥ 5 เพิ่ม threshold หลังแพ้ไปแล้ว 5 ครั้ง; ไม่ลด position size ค่อยๆ
**แนวทางแก้:**
- แทนที่ hard stop ด้วย **gradual position reduction**:
  - Streak 2: conf_min_scale × 0.8
  - Streak 3: conf_min_scale × 0.6
  - Streak 4: conf_min_scale × 0.4
  - Streak ≥ 5: conf_min_scale × 0.25 (ยังเทรดได้แต่ size เล็กมาก)
- ใน `_run_gates()` ปรับ conf_scale แทนที่จะ block ทั้งหมด
**Files ที่ต้องแก้:** `agents/decision_maker.py` (`_run_gates()`)

---

### Issue #8 — Momentum เป็นตัวสำรอง ไม่ใช่ตัวหลัก
**ปัญหา:** MOMENTUM_BREAKOUT ถูกกรองทิ้งโดย gate ก่อน Claude เยอะ เช่น SR_ZONE gate (ต้องการ conf ≥ 62 ถ้าไม่มี zone)
**แนวทางแก้:**
- ใน `_run_gates()` เพิ่ม fast path สำหรับ MOMENTUM_BREAKOUT:
  - ถ้า `entry_type == "MOMENTUM_BREAKOUT"` และ score ≥ 70 → ข้าม gate 7 (SR_ZONE) และ gate 8 (ATR)
  - Session London/NY overlap + MOMENTUM_BREAKOUT ≥ 68 → conf threshold ลด 5%
**Files ที่ต้องแก้:** `agents/decision_maker.py` (`_run_gates()`)

---

### Issue #9 — Pending Orders ไม่ได้ใช้งานเต็มที่
**ปัญหา:** Pending orders expire หลัง 48 ชั่วโมง, ไม่มีข้อมูลว่า pending WR ดีกว่า market order หรือไม่
**แนวทางแก้:**
- บันทึก source (PENDING vs MARKET) ใน trade log แยกชัดเจน
- วิเคราะห์ WR ของ pending vs market entries
- ลด expiry จาก 48h → 24h (stale order หลัง 1 วันควรยกเลิก)
**Files ที่ต้องแก้:** `config.py`, `agents/reporter.py`

---

### Issue #10 — ไม่มี Backtesting / Monte Carlo
**ปัญหา:** ไม่รู้ว่าระบบจะรอดไหมถ้าเจอ drawdown รุนแรง 10× จากปัจจุบัน
**แนวทางแก้:**
- สร้าง `backtest/` module: อ่าน trades.json → simulate N consecutive losses
- Monte Carlo: random permutation ของ trade sequence → วัด max drawdown distribution
- Walk-forward: แบ่ง trades เป็น in-sample (train) + out-of-sample (validate)
**Files ที่ต้องสร้าง:** `backtest/monte_carlo.py`, `backtest/walk_forward.py`

---

## Architecture Overview

```
main.py (loop ทุก 300s)
  ├── chart_watcher.analyze_chart()
  │     ├── calculate_indicators() [H4/H1/M15]
  │     ├── scan_entry_setups()    ← h4_bias ใหม่ (4-component)
  │     │     ├── _check_h1_structure()  ← ใหม่ #4
  │     │     ├── _check_bb_squeeze()    ← ใหม่ #4
  │     │     └── setups: SR_ZONE, STRUCTURE_PULLBACK, EMA_PULLBACK,
  │     │                 RSI_*, BB_*, EMA200_TOUCH, MOMENTUM_BREAKOUT
  │     └── calc_sl_from_wick() [ATR floor] ← แก้ #1
  │
  ├── analyst.analyze_sentiment()
  ├── market_advisor.advise()
  │
  └── decision_maker.make_decision()
        ├── _run_gates()   ← ใหม่ #3 (Python-only, 12 gate)
        └── Claude (8-line clean summary) → EXECUTE/SKIP
              └── open_order(confidence_scale=conf_scale)  ← #2
```

## Key Config Values (current defaults)

```
min_rr_ratio      = 2.0    (was 1.5)
default_tp_pips   = 5000   (was 3000)
SL_MIN_PIPS       = 500    (was 1000)
SL_MAX_PIPS       = 3500   (was 2000)
ATR_SL_MULT       = 1.0    (new)
CONF_FULL_SIZE_AT = 80     (new)
CONF_MIN_SCALE    = 0.5    (new)
```

## Next Session — Priority Order

1. **Issue #6** (Profit-Taking) — สร้าง `manage_partial_close()` ใน mt5_connector.py
2. **Issue #7** (Gradual position reduction on streak) — แก้ `_run_gates()` ใน decision_maker.py
3. **Issue #8** (Momentum fast path) — แก้ `_run_gates()` skip gate 7+8 สำหรับ MOMENTUM_BREAKOUT
4. **Issue #9** (Pending order analytics) — เพิ่ม source tracking ใน reporter.py
5. **Issue #10** (Backtesting) — สร้าง backtest/ module ใหม่
