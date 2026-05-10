# XAUUSD Trading Strategy — Trend & Range Rulebook
อัปเดต: 2026-05-10

ไฟล์นี้เป็น **rulebook หลัก** ที่ Agent 4 (Decision Maker) ต้องอ่านและ enforce ทุกรอบ

---

## 1. กำหนดทิศทางตลาด (Market Regime)

ใช้ค่า `TREND` จาก Agent 1 (ChartWatcher) ซึ่งอ้างอิง H4 EMA200 distance:

| TREND | เงื่อนไข | กลยุทธ์ |
|---|---|---|
| **BULLISH** | Price > EMA200 H4 (dist > 0.5%) | **BUY ONLY** — เข้าที่แนวรับ |
| **BEARISH** | Price < EMA200 H4 (dist > 0.5%) | **SELL ONLY** — เข้าที่แนวต้าน |
| **SIDEWAYS** | Price ≈ EMA200 H4 (dist ≤ 0.5%) | **RANGE MODE** — pending ที่กรอบ |

---

## 2. Trending Market — กฎการเข้าเทรด

### BULLISH (ขาขึ้น) → BUY เท่านั้น

เข้า **BUY** เฉพาะที่ **แนวรับ (Support)** ภายใน uptrend:

| Entry Setup | เงื่อนไข | ความสำคัญ |
|---|---|---|
| Bounce ที่ H4 Support | Rejection wick / Hammer / Bullish Engulfing | สูงสุด |
| Pullback EMA20 / EMA50 H1 | ราคา pullback แตะ EMA แล้ว bounce กลับ | สูง |
| DOJI ที่ H4 Support | Indecision ที่ zone แข็งแกร่ง | ปานกลาง |
| Breakout retest | Resistance ที่เพิ่ง break กลายเป็น Support | สูง |

**SELL signal → ปฏิเสธทันที** ไม่ว่า confidence จะสูงแค่ไหน  
ยกเว้นเดียว: SELL ที่ H4 STRONG Resistance + confidence ≥ 70 → อนุญาต scalp สั้น (1 trade)

---

### BEARISH (ขาลง) → SELL เท่านั้น

เข้า **SELL** เฉพาะที่ **แนวต้าน (Resistance)** ภายใน downtrend:

| Entry Setup | เงื่อนไข | ความสำคัญ |
|---|---|---|
| Rejection ที่ H4 Resistance | Shooting Star / Bearish Engulfing / Wick ยาว | สูงสุด |
| Pullback EMA20 / EMA50 H1 | ราคา pullback แตะ EMA แล้ว rejected | สูง |
| DOJI ที่ H4 Resistance | Indecision ที่ zone แข็งแกร่ง | ปานกลาง |
| Breakdown retest | Support ที่เพิ่ง break กลายเป็น Resistance | สูง |

**BUY signal → ปฏิเสธทันที**  
ยกเว้นเดียว: BUY ที่ H4 STRONG Support + confidence ≥ 70 → อนุญาต scalp สั้น (1 trade)

---

## 3. Sideways Market — Range Trading

### 3.1 กำหนดกรอบอัตโนมัติ (Auto-Range)

ระบบคำนวณกรอบจากข้อมูล ChartWatcher โดยอัตโนมัติ:

```
Range Upper = H4 Resistance ที่ต่ำที่สุดเหนือราคาปัจจุบัน
              (ถ้า PDH < Nearest Resistance → ใช้ PDH)

Range Lower = H4 Support ที่สูงที่สุดใต้ราคาปัจจุบัน
              (ถ้า PDL > Nearest Support → ใช้ PDL)

Range Width  = Upper − Lower
Trigger Zone = Width × 10%  (ใกล้กรอบภายใน 10% ของ width)
```

**ตัวอย่าง**: Upper=4650, Lower=4600, Width=50  
→ BUY trigger เมื่อ price ≤ 4605 (lower + 10%)  
→ SELL trigger เมื่อ price ≥ 4645 (upper − 10%)

---

### 3.2 Pending Order Rules (Sideways)

| ตำแหน่งราคา | Action | Order Type | ราคา |
|---|---|---|---|
| Price ≥ Upper − Trigger | วาง SELL pending | SELL_LIMIT | @ Range Upper |
| Price ≤ Lower + Trigger | วาง BUY pending | BUY_LIMIT | @ Range Lower |
| กลาง Range | ไม่ทำอะไร | — | — |

**SL / TP ของ Range Pending:**
```
BUY_LIMIT:
  SL = Range Lower − (Width × 15%)   ← ใต้กรอบล่าง
  TP = Range Upper − (Width × 15%)   ← ก่อนถึงกรอบบน (ขาย)

SELL_LIMIT:
  SL = Range Upper + (Width × 15%)   ← เหนือกรอบบน
  TP = Range Lower + (Width × 15%)   ← ก่อนถึงกรอบล่าง (ซื้อคืน)

ต้องมี RR ≥ 1.5 — ถ้าไม่ผ่านให้ขยับ TP จนผ่าน
```

---

### 3.3 เงื่อนไขยกเลิก Range Pending

- ราคาทะลุ Range Upper เกิน Width × 20% → ยกเลิก SELL_LIMIT ทั้งหมด
- ราคาทะลุ Range Lower เกิน Width × 20% → ยกเลิก BUY_LIMIT ทั้งหมด
- TREND เปลี่ยนจาก SIDEWAYS → BULLISH หรือ BEARISH → ยกเลิก Range pending ทั้งหมดทันที

---

### 3.4 Guards — ห้ามวาง Range Pending ถ้า

| เงื่อนไข | เหตุผล |
|---|---|
| Range Width < 2000 pips ($20) | กรอบแคบเกิน — ค่าธรรมเนียมกิน |
| ATR H4 > Width × 60% | ตลาดผันผวนเกิน กรอบอาจ break ทุกวัน |
| มี Range pending ฝั่งเดิมอยู่แล้ว | ห้ามซ้ำ — max 1 per side |
| Daily loss ≥ Max Daily Loss | หยุดวาง pending ใหม่ |

---

## 4. Sideways Pending vs Weekly Pending (ต่างกัน)

| | Range Pending (ใหม่) | Weekly Pending |
|---|---|---|
| Trigger | ราคาใกล้ Range boundary อัตโนมัติ | ต้นสัปดาห์ (manual/AI) |
| ราคา | Auto จาก H4 S/R + PDH/PDL | S/R หลักของสัปดาห์ |
| หมดอายุ | เมื่อ trend เปลี่ยน หรือ breakout | 48 ชั่วโมง |
| Comment tag | `RANGE:BUY` / `RANGE:SELL` | `WEEKLY:BUY` / `WEEKLY:SELL` |
| Max | 1 BUY_LIMIT + 1 SELL_LIMIT | ตาม MAX_PENDING config |
| ยกเลิก | อัตโนมัติเมื่อ trend เปลี่ยน | หมดอายุตามเวลา |

---

## 5. สรุปกฎ Decision Flow ตาม Regime

```
ทุกรอบ decision:

IF TREND == BULLISH:
    signal == SELL AND conf < 70  →  SKIP (ห้าม counter-trend)
    signal == BUY AND sr_zone == SUPPORT  →  EXECUTE ปกติ
    signal == BUY AND sr_zone != SUPPORT  →  ประเมิน conf ≥ 60

IF TREND == BEARISH:
    signal == BUY AND conf < 70  →  SKIP (ห้าม counter-trend)
    signal == SELL AND sr_zone == RESISTANCE  →  EXECUTE ปกติ
    signal == SELL AND sr_zone != RESISTANCE  →  ประเมิน conf ≥ 60

IF TREND == SIDEWAYS:
    Market order → ยกเว้น momentum breakout ที่แรงมาก (conf ≥ 65)
    Range pending → ดู Section 3 (ระบบจะจัดการแยกต่างหาก)
```
