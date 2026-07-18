# DESIGN — BTC trading module (algorithmic / 0-LLM / paper-first)

**Status: DESIGN PROPOSAL. ยังไม่มี code.** ต้องอนุมัติ + probe ยืนยัน broker ก่อนเริ่ม implement.
**หลักการ:** skill `quant-systematic-trading` — SELECTION (เลือก algorithm) แยกจาก EXECUTION (สูตรตายตัว);
enter เมื่อ EV>0; validate ก่อน live.

## Decisions (user-confirmed 2026-07-18)
1. **Data/exec = MT5 broker** (ถ้ามี BTCUSD) → reuse order exec + lot sizing, รันเป็น **process แยก `SYMBOL=BTCUSD`**
   - ⚠️ **PREREQUISITE:** probe ยืนยัน broker มี BTCUSD symbol ก่อน (เหมือน WTI probe — user รัน)
2. **0 LLM** ในการเข้า — quant algorithm ล้วน + analysis (macro/news) เป็น bias/filter เท่านั้น (ประหยัด token, deterministic)
3. **Paper/backtest ก่อน** — validate (DSR/PBO/cost) → shadow → ค่อย live

---

## 1. Architecture — parallel BTC instance (single-symbol-per-process)
ระบบเป็น single-symbol/process (global `config.SYMBOL`) → friction ต่ำสุด = **instance แยก** reuse ชั้น data/exec/DB/dashboard, มี quant decision nodes ของตัวเอง (ไม่แตะ gold pipeline).

```
[BTC process, SYMBOL=BTCUSD, 0-LLM]
  price (reuse get_ohlcv/get_current_price)
    → Regime classifier (Hurst + structure HH/HL + vol state)   ← noisy filter (skill §5)
    → เลือก algorithm จาก library (deterministic)
    → analysis bias: macro_strip (DXY/risk-on, reuse) + crypto-news filter (build-new)
    → EV check: P(win)·R − (1−P) > 0, P จาก per-algo calibrated stats  ← skill §1-2
    → deterministic entry / SL / TP (BTC-calibrated, ATR-based)   ← skill §3-4
    → fixed-fractional size (reuse calculate_lot_size, 0.5-2%)
    → MFE/MAE exit
  → shadow-log ทุก decision (P1b-style decision_snapshots_btc.jsonl)
```

### Reuse map (จาก Explore)
| ชั้น | action |
|------|--------|
| price data, lot sizing (`calculate_lot_size`/`_calc_pip_value`) | ✅ reuse-as-is (symbol/broker-driven) |
| order exec, position-mgmt | ✅ reuse ผ่าน process แยก (อ่าน global SYMBOL) |
| DB/schema/dashboard `?system=btcusd` + aliases | ✅ reuse-as-is |
| macro_strip (DXY/yields) | ✅ reuse เป็น risk-on context |
| chart TA (SR/fib/FVG/momentum/structure) | ⚠️ reuse-with-tweak — **แทน `point=0.01` ด้วย `info.point`** (BTC point ≠ 0.01) |
| pipeline DAG shell | ⚠️ reuse structure, **swap LLM nodes → quant nodes** |
| news keyword / macro_regime / COT | ❌ build-new crypto keyword (กลไก reuse); regime.md drop (0-LLM) |
| pip config (SL/TP 2000/5000 คาลิเบรตบนทอง) | ❌ **build-new BTC-calibrated** (rescale เป็น BTC point/ATR) |

---

## 2. Algorithm library (deterministic — SELECTION แยก EXECUTION)
แต่ละ algorithm = **preconditions (regime+state) + สูตร entry/SL/TP ตายตัว**. Selector เลือกตัวที่ precondition ครบ + EV สูงสุด, ไม่งั้น STAND-DOWN.

| algorithm | regime | precondition | entry / SL / TP |
|-----------|--------|--------------|-----------------|
| `momentum-breakout` | trending (Hurst>0.5) | ทะลุ range-high/low + vol expand | breakout close; SL = k·ATR; TP = RR·SL |
| `mean-reversion` | mean-revert (Hurst<0.5) | แตะ band สุดขั้ว (เช่น ±2σ / BB) + no trend | reversion; SL beyond extreme; TP = mid |
| `range-fade` | range | ที่ขอบ range (S/R) + no breakout | fade เข้า range; SL beyond edge; TP = opposite edge |
| `STAND-DOWN` | — | ไม่มี algo ไหน precondition ครบ / EV≤0 | ไม่เข้า |

- **BTC-calibrated:** SL/TP เป็น **k·ATR** (ไม่ใช่ fixed pips) → self-scale ตาม vol BTC (skill §4)
- **analysis bias:** macro risk-on (DXY↓/risk-on) + crypto-news = ปรับ P หรือ filter ทิศ (ไม่ใช่ตัวเข้า)
- **RR≥2** hard floor; EV>0 required

---

## 3. Intermarket synergy — BTC data ↔ gold (user insight)
BTC price ที่เก็บ → **shared data source:**
1. ป้อน BTC algorithms
2. คำนวณ **BTC-gold rolling correlation + divergence** → **F8 feature ให้ gold model** (เข้า decision_snapshots ทอง)
3. ขยาย `scripts/probe_intermarket.py` รับ BTC เป็นอีก series
- ⚠️ (skill) corr BTC-gold **ไม่คงที่** → rolling, noisy feature, **ต้อง validate ว่าทำนายจริง** ไม่ assume

---

## 4. Validation plan (ตาม docs/VALIDATION_CHECKLIST.md — บังคับ)
1. **backtest** algorithm library บน BTC OHLCV history (reuse get_ohlcv)
2. **นับ N** ทุก variant/param; **purge+embargo CV**; **PBO(CSCV) + Deflated Sharpe**; **net of cost** (crypto spread/fee สูง!)
3. robustness = plateau; min-N
4. **shadow** — รัน 0-LLM decision log คู่ (ไม่วางออเดอร์) เก็บ decision_snapshots_btc + forward-label
5. ผ่าน → **enable ทีละ algorithm** ที่มั่นใจสุด, kill-switch flag, guard (fixed SL/daily-loss) bind

---

## 5. Phased plan
```
Phase B0  probe: ยืนยัน broker มี BTCUSD + วัด BTC-gold corr (user รัน)  ← PREREQUISITE
Phase B1  offline backtest harness + algorithm library (pure-price, BTC-calibrated) — SAFE
Phase B2  BTC data collection (shadow decision-log) + BTC-gold F8 feature (ป้อน gold ด้วย)
Phase B3  backtest + validate (VALIDATION_CHECKLIST: DSR/PBO/cost)
Phase B4  paper/shadow live → enable ทีละ algorithm
```
**ทุก phase flag-OFF/paper จนกว่า validate ผ่าน** — ไม่แตะ gold pipeline; BTC เป็น process/module แยก.

---

## 6. สิ่งที่ build-new vs reuse (สรุป implement)
- **build-new:** BTC config (point/ATR-based), quant decision nodes (regime+algo library+EV), crypto-news keyword, backtest harness, BTC-gold divergence feature
- **reuse:** price feed, lot sizing, order exec (via SYMBOL=BTCUSD), DB/dashboard, macro_strip, chart TA math (แก้ point)

เกี่ยว: skill `quant-systematic-trading`, `VALIDATION_CHECKLIST.md`, `ROADMAP_quant_entry_migration.md`,
`scripts/probe_intermarket.py`, [[entry-exit-quant-overhaul]].
