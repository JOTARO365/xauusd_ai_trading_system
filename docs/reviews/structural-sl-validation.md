# Structural SL — validation (2026-07-30)

**ปัญหา:** algo momentum เข้าถูกทางแต่โดน SL ก่อน — SL แบบ fixed/ATR วางในที่ว่าง ไม่พิงโครงสร้าง D1+
→ noise เขี่ยออกก่อนราคาไปต่อ.

**แนวทาง:** วาง SL พ้นแนว D1/W1 swing ที่ใกล้สุด + `buffer×ATR`, clamp `[MIN,MAX]×ATR`,
นอกช่วง → fallback SL เดิม (opt-in ต่อไม้). TP คง RR เดิม.

## Backtest (no look-ahead)

`scripts/structural_sl_backtest.py` — signal ใช้ข้อมูล ≤ i · HTF pivot ใช้บาร์ day+ time ≤ signal ·
forward-sim จาก i+1 · บาร์เดียวชน SL+TP นับ SL ก่อน (pessimistic) · เทียบ fixed vs structural บน signal ชุดเดียวกัน.

window = 60,000 H1 (MT5 ให้เท่าที่มี) · momentum breakout (regime_lib) ใน regime=TREND.

### GOLD# (ALGO-mom, mult=1.0)

| buffer×ATR | delta expR | rescued (fix SL→str TP) | worsened (fix TP→str SL) |
|---|---|---|---|
| 0.2 | **+0.031** | 79 | 64 |
| 0.3 | **+0.033** | 85 | 69 |
| 0.5 | **+0.040** | 95 | 76 |
| 0.8 | **+0.011** | 71 | 66 |

→ บวก **ทุก** buffer, rescued > worsened สม่ำเสมอ = ไม่ใช่ knife-edge. **เปิดได้.**

### OILCash# / WTI (regime_momentum, mult=0.7 = live)

| buffer×ATR | delta expR | rescued | worsened |
|---|---|---|---|
| 0.3 | **−0.019** | 97 | 105 |
| 0.5 | **−0.035** | 104 | 120 |

→ **แย่ลง**, worsened > rescued. SL กว้างขึ้นทำลาย edge tight-SL×0.7 (edge หลักของ WTI = t-stat 15 จาก SL แคบ).
**ห้ามเปิด MSE.**

## สรุป / การตั้งค่า

- `STRUCTURAL_SL_GOLD=true` → เปิดสำหรับทอง (ผ่าน backtest)
- `STRUCTURAL_SL_MSE=false` → ปิดเสมอสำหรับ MSE momentum (backtest แย่ลง)
- default OFF ทั้งคู่ · ต้อง restart บอทหลัง flip (logic เป็น code ไม่ใช่ reload-only)

## caveat

- window เดียว (in-sample เทียบ relative) — ยังไม่ forward-live. เปิดบน demo เก็บ forward OOS ก่อน.
- sim ไม่รวม spread/slippage ต่อไม้ (เทียบ relative จึงหักล้าง); tsmom (no-TP, exit-on-flip) ไม่อยู่ในเทสนี้.
