# DESIGN — TSMOM-D1 Integration (รออนุมัติก่อนเขียน code)

**สถานะ:** DESIGN ONLY — ตาม iron rule (money-management/agent logic ต้องอธิบาย+อนุมัติก่อน). ยังไม่แตะ code.
**วันที่:** 2026-07-21

## 1. ทำอะไร & ทำไม

Integrate **TSMOM-D1** (time-series momentum รายวัน) เป็น directional engine ของบอท — เป็น edge **เดียว**
ที่ validated จริงจากการทดสอบ ~31 กลยุทธ์ (4 personas):
- L-sweep plateau (Sharpe 0.4-0.6, L=42-252) · 4/4 quartile บวก · survives deflation (t3.0 > 1.84/27trials) · WR 51.8%

**ทำไมแทน momentum_breakout ปัจจุบัน:** intraday momentum breakout = −EV grade C (พิสูจน์แล้ว). TSMOM = +EV.

**⚠️ caveat ที่ต้องยอมรับ (เขียนไว้ให้ชัด):**
- edge **modest** (Sharpe ~0.6) และ **ส่วนใหญ่เป็น gold-beta** (long-short 0.53 < buy&hold 0.65) ไม่ใช่ timing alpha ล้วน
- นี่คือ **forward-validation deployment** ไม่ใช่ "เจอ money-maker" — deploy เพื่อเก็บ forward evidence + จับ trend-beta อย่างมีวินัย
- **entry timing ปรับไม่ได้** (Setup#1 pullback พิสูจน์แล้วว่า −EV) → edge อยู่ที่ "ถือตามเทรนด์" ไม่ใช่จังหวะ

## 2. สถาปัตยกรรม — position-based daily overlay (ไม่ใช่ intraday entry)

TSMOM ต่างจาก algo ปัจจุบันโดยพื้นฐาน: เป็น **target position ที่ถือยาว** (วัน-สัปดาห์) ไม่ใช่ไม้ entry+SL/TP รายชั่วโมง.
→ โมดูลแยก `agents/tsmom_manager.py` ทำงาน **1 ครั้ง/แท่ง D1 ใหม่** (เหมือน manage_algo_pending ที่ทำ 1 ครั้ง/บาร์):

```
node_position_mgmt (ทุก cycle)
  └─ manage_tsmom()               ← ใหม่ (fail-soft, flag-gated)
       1. แท่ง D1 ใหม่ปิดหรือยัง? (ไม่ใหม่ → return)
       2. คำนวณ target = (direction, lot)
       3. reconcile กับ position ALGO-TSMOM ปัจจุบัน
```

## 3. Signal & Sizing spec (deterministic, 0 token)

**Signal (ensemble — robust กว่าเลือก L เดียว):**
```
สำหรับ L ∈ {63, 126, 252} (วัน): sign_L = sign(close_D1[t] − close_D1[t−L])   # ใช้แท่ง D1 ปิดแล้ว
direction = majority vote ของ 3 sign  (2:1 ก็เอา; ถ้า net 0 = FLAT)
```
**Sizing (vol-target, reuse algo_lot):**
```
SL_distance = TSMOM_SL_ATR × ATR(D1,22)        # chandelier catastrophic, default 3.0×ATR
lot = algo_lot(SL_distance_pips)               # = equity×RISK_PCT/(SL_pips×pipval), clamp MIN/MAX_LOT
```
**Exit:** หลัก = **signal flip** (direction กลับ → ปิด+กลับข้าง). ไม่มี fixed TP (trend-following ปล่อยวิ่ง).
SL = chandelier (trailing เฉพาะ tighten) เป็น disaster stop เท่านั้น.
**Rebalance:** เช็คทุกแท่ง D1 ใหม่ (flip เกิดไม่บ่อย = turnover ต่ำ = cost drag น้อย).

## 4. Order path & reconciliation (comment tag `ALGO-TSMOM`)

| สถานะปัจจุบัน | target | action |
|---|---|---|
| ไม่มี position | BUY/SELL | เปิด market order ตาม dir + lot + SL=chandelier |
| มี ทิศเดียวกัน | เดิม | ถือ (อัพเดต trailing SL ให้แคบลงเท่านั้น; optional resize ถ้า vol เปลี่ยนมาก) |
| มี ทิศตรงข้าม | flip | ปิด position เดิม → เปิดตรงข้าม |
| มี | FLAT | ปิด position |

⚠️ **bypass DecisionMaker** เหมือน ALGO path เดิม (deterministic ไม่ใช่ LLM) — consistent กับระบบ แต่บันทึกไว้ว่าเป็น order path ใหม่ (path ที่ 4 นอกเหนือ pending/zre/swing).

## 5. Coexistence กับ momentum_breakout เดิม (สำคัญ — กัน conflict)

TSMOM + intraday momentum = directional exposure ทับกันบนทอง → ต้องไม่รันชนกัน:
- **Phase shadow:** TSMOM log target เฉยๆ (ไม่วาง order); momentum เดิมยังรัน → เทียบ
- **Phase live:** `TSMOM_LIVE=true` → **ปิด intraday momentum entry** (executor/tick stand-down) ให้ TSMOM เป็น directional engine เดียว. fade pending (RANGE) จะคงไว้หรือปิดด้วย = คำถามเปิด (ดู §11)

## 6. Flags & kill switch (config.py + .env, default OFF)

```
TSMOM_SHADOW   = false   # คำนวณ+log target ไม่วาง order (เก็บ forward data)
TSMOM_LIVE     = false   # วาง/บริหาร position จริง (kill = false, live-reload)
TSMOM_LOOKBACKS = "63,126,252"
TSMOM_SL_ATR   = 3.0     # chandelier catastrophic SL (× ATR D1)
TSMOM_RISK_PCT = 0.005   # หรือ reuse REGIME_SR_RISK_PCT
```

## 7. Rollout discipline (ตาม skill quant-systematic-trading)

1. **Shadow** (TSMOM_SHADOW=true) — log target position + would-be orders ข้าง live; รันบน demo 50k ที่เปิดอยู่
2. **Validate forward** — เทียบ shadow signal vs realized (สัปดาห์-เดือน); ยืนยัน flip logic + sizing ถูก
3. **Tiny live** (TSMOM_LIVE=true, demo) — เปิด position จริงบน demo, ปิด intraday momentum
4. **กลับ real เงินจริง** — เฉพาะเมื่อ forward ยืนยัน + เปิด stand-down guard กลับ (ทุนถึงเกณฑ์)

## 8. Risk guards (คงเดิม ทั้งหมด binding)

daily-loss cap (decision_maker ใช้ balance จริง), MAX_RISK_PCT cap ใน algo_lot, MAX_OPEN, ALGO_MAX_STACK,
MIN_AI_EQUITY. TSMOM position นับรวม exposure. chandelier SL = disaster protection.

## 9. ไฟล์ที่แตะ (whitelist — ตอน implement)

| ไฟล์ | เปลี่ยน |
|---|---|
| `agents/tsmom_manager.py` | **ใหม่** — signal + sizing + reconciliation (fail-soft, flag-gated) |
| `config.py` | +5 flags (module + reload) |
| `agents/trading_graph.py` | +1 call `manage_tsmom()` ใน node_position_mgmt |
| `.env` | +flags (user คุม) |
| `agents/regime_executor.py` + `regime_tick.py` | +guard: stand-down เมื่อ TSMOM_LIVE (กัน conflict) |
| `docs/continue.md` | log |

**ไม่แตะ:** DecisionMaker gates, money-management สูตร (reuse algo_lot เดิม), prompts.

## 10. Data & cost

D1 bars จาก connector (`get_ohlcv` tf=D1, มี tf_map แล้ว) — ต้องมี ≥252 แท่ง D1 (มี xau_d1.json 6000 แท่ง).
0 token (คำนวณล้วน). turnover ต่ำ (flip นาน ๆ ครั้ง) = cost drag เล็ก.

## 11. คำถามเปิด (ต้องตอบก่อน implement)

1. **Signal:** ensemble 63/126/252 (แนะนำ, robust) หรือ single L=126?
2. **Rollout:** shadow ก่อน (แนะนำ) หรือ tiny-live เลยบน demo (เก็บ data เร็วกว่า)?
3. **Coexistence:** เมื่อ TSMOM live → ปิด momentum intraday ด้วยไหม? แล้ว fade pending (RANGE) เก็บหรือปิด?
4. **Sizing:** reuse REGIME_SR_RISK_PCT 0.5% หรือ TSMOM_RISK_PCT แยก?
