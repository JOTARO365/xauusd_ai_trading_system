# XAUUSD AI Trading System — Profitability Fix Progress

## Branch
`claude/investigate-profitability-pY79v`

## วัตถุประสงค์
แก้ไขสาเหตุหลักที่ทำให้ระบบยังไม่ทำกำไร จากการวิเคราะห์พบ 10 ปัญหา — **แก้ครบทั้งหมดแล้ว**

---

## ✅ แก้ไขเสร็จแล้ว (ทั้งหมด)

### Issue #1 — R:R ต่ำเกินไป + SL ใหญ่เกินไป
**Files:** `agents/chart_watcher.py`, `config.py`, `agents/decision_maker.py`, `agents/prompts/chart_watcher.md`

- `SL_MIN_PIPS`: 1000 → 500, `SL_MAX_PIPS`: 2000 → 3500
- เพิ่ม `calc_sl_atr_floor()` — SL = max(wick_sl, 1.0×H4_ATR) ป้องกันโดน H4 noise
- `min_rr_ratio`: 1.5 → **2.0** (breakeven WR ลดจาก 40% → 33%)
- `default_tp_pips`: 3000 → **5000**
- `_effective_min_rr()` floor: 1.0 → **1.5** (hot market ไม่ต่ำกว่า 1.5:1)
- SL validation range: 1000–3000 → 500–3500

---

### Issue #2 — Position sizing ไม่ปรับตาม Confidence
**Files:** `connectors/mt5_connector.py`, `agents/decision_maker.py`, `config.py`

- `calculate_lot_size()` + `open_order()` รับ `confidence_scale` parameter
- สูตร: `scale = max(conf_min_scale, min(1.0, confidence / conf_full_size_at))`
- Config defaults: `CONF_FULL_SIZE_AT=80`, `CONF_MIN_SCALE=0.5`

| Confidence | Scale | Effective risk |
|---|---|---|
| 50% | 0.63× | ~0.31% |
| 65% | 0.81× | ~0.41% |
| 80%+ | 1.0× | 0.5% |

---

### Issue #3 — Gate หลายชั้นทำให้ Claude ได้ context มากเกินไป
**Files:** `agents/decision_maker.py`, `agents/prompts/decision_maker.md`

- แยก gate logic ทั้งหมดออกเป็น `_run_gates()` (Python-only)
- Gate 12 ชั้น — daily loss, trend filter, SR zone, ATR, regime, streak, SL validation ฯลฯ
- Claude รับแค่ **8 บรรทัด clean summary** — input tokens ~600 → ~150 ต่อ call
- `decision_maker.md`: 136 บรรทัด → 40 บรรทัด

---

### Issue #4 — Entry Signal ไม่มี Edge จริง
**Files:** `agents/chart_watcher.py`, `agents/prompts/chart_watcher.md`

- **ลบ** `EMA_CROSS H1` และ `MACD_CROSS H1` — lagging signals
- **เพิ่ม** `_check_h1_structure()` — ตรวจ higher lows / lower highs จาก swing จริง
- **เพิ่ม** `_check_bb_squeeze()` — BB touch มี edge เฉพาะเมื่อ squeeze ก่อน
- **เพิ่ม** H1 structure bonus (+8–10 pts) ใน SR_ZONE setups
- **เพิ่ม** `STRUCTURE_PULLBACK` setup (score 70)
- `EMA_PULLBACK` ต้องการ candle body ≥ 40%, RSI thresholds ขยับเป็น 30/70

---

### Issue #5 — Trend Definition ล้าหลัง
**Files:** `agents/chart_watcher.py`, `agents/prompts/chart_watcher.md`

แทน `h4_bias` ด้วย **4-component score** (ต้องได้ ≥ 3/4 จึงเป็น BULLISH/BEARISH):
1. Price vs EMA200
2. H4 EMA50 slope (5-bar comparison)
3. H1 EMA stack (close > EMA20 > EMA50)
4. H4 recent swing structure (HH+HL = bull)

ผล: จับ trend change เร็วขึ้น 2–5 H4 candle

---

### Issue #6 — ไม่มีระบบ Profit-Taking
**Files:** `connectors/mt5_connector.py`, `main.py`

- เพิ่ม `manage_partial_close()` ใน `mt5_connector.py`
- **Stage 1 (1R hit):** ปิด 50% → ขยับ SL มา BE+100 pips
- **Stage 2 (2R hit):** ปิด 60% ของที่เหลือ (= 30% ต้นฉบับ) → trail SL ที่ 50% ของ move
- **20% สุดท้าย:** วิ่งไป TP เต็ม
- ใช้ `_partial_stage` dict ป้องกัน double-close
- เรียกทั้งใน `run_cycle()` และ `run_status_cycle()` ก่อน `manage_breakeven()`

---

### Issue #7 — Portfolio Protection ทำงานหลังเกิดความเสียหาย
**Files:** `agents/decision_maker.py`

แทนที่ hard block ด้วย **gradual position reduction:**

| Streak | Size Scale |
|---|---|
| 1 | 1.0× (ปกติ) |
| 2 | 0.80× |
| 3 | 0.60× |
| 4 | 0.40× |
| ≥ 5 | 0.25× |

- `_run_gates()` คืน `streak_scale` แทนการ fail
- `make_decision()` คูณ `conf_scale × streak_scale` ก่อนส่งไป `open_order()`

---

### Issue #8 — MOMENTUM_BREAKOUT ถูก gate block บ่อยเกินไป
**Files:** `agents/decision_maker.py`

- เพิ่ม `is_mom_fast` flag ใน `_run_gates()`:
  - `MOMENTUM_BREAKOUT` + conf ≥ 70 → ข้าม gate 7 (SR_ZONE) + gate 8 (ATR)
  - `MOMENTUM_BREAKOUT` + London/NY overlap (13–17 UTC) + conf ≥ 68 → ข้ามเช่นกัน

---

### Issue #9 — Pending Orders ไม่ได้ใช้งานเต็มที่
**Files:** `agents/reporter.py`, `config.py`, `.env.example`

- `entry_perf_text` แสดง PENDING vs MARKET aggregate WR แยกกัน:
  ```
  PENDING entries:   8 trades | WR=62.5% | P&L=+87.50
  MARKET  entries:  18 trades | WR=44.4% | P&L=+12.30
  ```
- `PENDING_EXPIRY_HOURS` default: 48 → **24**

---

### Issue B — Strategy Versioning (data contamination fix)
**Files:** `agents/reporter.py`, `db/schema.sql`, `db/writer.py`

- Trades ใหม่ทุกตัวได้ `strategy_version=2`
- `entry_perf_text` กรองเฉพาะ v2 trades — ตัด EMA_CROSS/MACD_CROSS ออก
- Warning `(low sample)` เมื่อ v2 มี trades < 5 ตัว
- `db/schema.sql`: เพิ่ม `strategy_version SMALLINT DEFAULT 1`

---

### Issue C — Monte Carlo Backtest
**Files:** `backtest/monte_carlo.py`

- Pure simulation ไม่ใช้ v1 historical data
- `--sweep` mode เปรียบเทียบ WR 35–50%

| WR | P(ruin >10%) | สรุป |
|---|---|---|
| 38% | 6% | ⚠️ borderline |
| 40% | 2.3% | ✅ ยอมรับได้ |
| 42%+ | <1% | ✅ ปลอดภัย |

```bash
python -m backtest.monte_carlo --sweep
python -m backtest.monte_carlo --wr 0.42
```

---

## Architecture Overview (Final)

```
main.py (loop ทุก 300s)
  ├── chart_watcher.analyze_chart()
  │     ├── calculate_indicators() [H4/H1/M15]
  │     ├── scan_entry_setups()    ← 4-component h4_bias (#5)
  │     │     ├── _check_h1_structure()  ← #4
  │     │     ├── _check_bb_squeeze()    ← #4
  │     │     └── setups: SR_ZONE, STRUCTURE_PULLBACK, EMA_PULLBACK,
  │     │                 RSI_*, BB_*, EMA200_TOUCH, MOMENTUM_BREAKOUT
  │     └── calc_sl_from_wick() [ATR floor] ← #1
  │
  ├── analyst.analyze_sentiment()
  │     └── news_cache → vector_search() [Gemini, news only]
  ├── market_advisor.advise()
  │
  └── decision_maker.make_decision()
        ├── _run_gates() ← Python-only, 12 gate (#3)
        │     ├── MOMENTUM_BREAKOUT fast path (#8)
        │     └── streak → streak_scale (#7)
        └── Claude (8-line summary) → EXECUTE/SKIP
              └── open_order(conf_scale × streak_scale) ← #2 #7
                    └── manage_partial_close() ← #6
                          Stage 1 (1R): -50%, SL→BE
                          Stage 2 (2R): -30%, trail SL
                          Remaining 20%: run to TP

backtest/monte_carlo.py  ← C
reporter.log_trade(strategy_version=2)  ← B
```

## Key Config Values (current defaults)

```
min_rr_ratio         = 2.0    (was 1.5)
default_tp_pips      = 5000   (was 3000)
SL_MIN_PIPS          = 500    (was 1000)
SL_MAX_PIPS          = 3500   (was 2000)
ATR_SL_MULT          = 1.0    (new)
CONF_FULL_SIZE_AT    = 80     (new)
CONF_MIN_SCALE       = 0.5    (new)
PENDING_EXPIRY_HOURS = 24     (was 48)
strategy_version     = 2      (new — trades ใหม่ทุกตัว)
```

## DB Migration สำหรับผู้ที่มี Supabase อยู่แล้ว

```sql
ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_version SMALLINT DEFAULT 1;
```

## สิ่งที่ยังไม่ได้ทำ (Optional / Future)

- **Walk-forward testing** — แบ่ง v2 trades เป็น in-sample/out-of-sample เมื่อมีข้อมูลพอ (≥ 50 trades)
- **Live WR monitoring** — alert เมื่อ WR v2 ต่ำกว่า 38% ติดต่อกัน 20 trades
