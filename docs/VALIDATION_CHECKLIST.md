# VALIDATION CHECKLIST — gate ก่อน enable entry/exit model ใดๆ

**ใช้เมื่อ:** กำลังจะ fit / backtest / enable evidence-based entry (`DESIGN_evidence_based_entry.md`)
หรือ statistical exit (`DESIGN_statistical_exit.md`) จาก data ที่ P1b/P1c สะสม.
**มาจาก:** deep research quant (2026-07-18) → skill `quant-systematic-trading` (López de Prado/Bailey/Chan).
**กฎเหล็ก:** ผ่านไม่ครบ = ยังไม่มี edge มีแค่ hypothesis → อยู่ **OFF** (crude guard/baseline คุมต่อ).

---

## 0. Audit — สถานะเทียบหลัก quant

| หลัก quant | สถานะเรา |
|-----------|----------|
| EV entry (breakeven `1/(1+R)`) | ✅ design ใช้แล้ว (τ=breakeven) |
| MFE/MAE exit | ✅ SEL design + P1c เก็บ excursion |
| Regime routing | ✅ algorithm-selector |
| Probability calibration | ⚠️ design มี Platt/isotonic — **บังคับทำ** (LLM ECE 0.45, raw confidence ใช้ไม่ได้) |
| Selection-bias data | ✅ P1b log ไม้ที่ไม่เข้าด้วย (แก้ n=3 circular) |
| **Backtest rigor** | ❌ **replay counter_spike/ZRE = single-path, no-cost, undisclosed-N, proxy เอียง WIN → ไม่พอ** |
| **Position sizing** | ❌ fixed lot 0.02 (quant = fixed-fractional/ATR/fractional-Kelly) — money-mgmt, ทีหลัง |

---

## 1. ✅ VALIDATION GATE — ต้องผ่าน**ครบทุกข้อ**ก่อน enable

### A. Data (ปิด bias ก่อน fit)
- [ ] **Unbiased labeled set** — features-at-decision → forward outcome, รวม**ไม้ที่ไม่เข้า/ถูกบล็อก**
  (`decision_snapshots.jsonl` P1b) ไม่ใช่แค่ไม้ที่เข้า (trades = selection bias)
- [ ] **Forward label ถูกต้อง** — WIN/LOSS วัดด้วย OHLC จริง (ไม่ใช่ spot proxy ที่เอียง WIN แบบ replay รอบแรก)
- [ ] **Min-N** — labeled events ≥ เกณฑ์ที่ตั้งไว้ล่วงหน้า (ไม่กี่สิบ = noise). ต่ำกว่า → OFF
- [ ] **No leakage** — ทุก feature รู้ได้ ณ ตอน decision (F1-F7); label ใช้แต่ราคาอนาคต; audit ก่อน fit

### B. Fit
- [ ] **นับ N (trial count)** — บันทึกทุก variant/threshold/param ที่ลอง (undisclosed-N = "worthless")
- [ ] **Purge + embargo CV** — trading data non-IID รั่วบน k-fold ธรรมดา; drop train label ที่ overlap test +
  embargo ~0.01·T bars
- [ ] **Regularized (ridge)** + bootstrap CI ต่อ weight; drop feature ที่ CI คร่อม 0
- [ ] **Calibrate** — Platt/isotonic บน held-out; reliability diagram ±0.1; P ต้อง "หมายความตามค่า" ก่อนขับ EV/size

### C. Judge (ไม่ใช่ walk-forward เดี่ยว)
- [ ] **PBO (CSCV)** ต่ำ — combinatorial purged CV; overfitting = IS-best < median OOS
- [ ] **Deflated Sharpe** สูง — หัก selection-over-N + fat tails; DSR > ~0.95
- [ ] **Net of cost** — model spread/slippage ทอง (edge บางตายหลังหักจริง = เหตุ live < backtest)
- [ ] **ชนะ baseline** — Σ R(model) > Σ R(crude guard/fixed-TP) บน held-out, **net cost**
- [ ] **ไม่เพิ่ม tail** — จำนวน/ขนาด −1R loss ไม่แย่ลงกว่าเดิม (ดู distribution ไม่ใช่ mean)
- [ ] **Robustness = plateau** — sensitivity analysis; param เปลี่ยนนิด result ไม่ควรพลิก (cliff = fragile, ห้าม fine-tune ยอด)

### D. Rollout
- [ ] **Shadow** — รัน flag-OFF คู่ live, log decision ที่ *จะ* ทำ เทียบ guard จริง 2-4 สัปดาห์
- [ ] **Enable ทีละ segment** — เริ่มที่ replay/shadow มั่นใจสุด (เช่น bullish-dip+strong-support), kill-switch = flag
- [ ] **Guard เดิม bind ตลอด** — fixed SL/daily-loss/streak/slot ยังทำงาน; model ปลด false-block ได้ ห้าม bypass gate

---

## 2. Seven sins — เช็คก่อนเชื่อ result
survivorship · look-ahead · selection/data-snooping · storytelling · turnover/cost · outliers · asymmetric-cost
+ **regime change** (edge ตายเงียบเมื่อ regime เปลี่ยน)

## 3. Position-sizing gap (money-mgmt proposal, ทีหลัง — iron rule)
fixed lot → **fixed-fractional** `size=equity×risk%÷|entry−stop|` (0.5-2%) + **ATR stop** (`size∝1/ATR`)
+ **fractional Kelly** `f*=p−(1−p)/b` ×¼-½ (เพดานไม่ใช่เป้า). **Kelly ต้องใช้ p ที่ calibrate แล้ว** ไม่งั้น over-bet.

---
**meta-rule:** ถ้าตอบไม่ได้ว่า (a) ลองกี่ variant (N), (b) PBO/DSR net-cost เท่าไร, (c) ผลหลังหัก cost,
(d) sample size — **ยังไม่มีหลักฐาน edge**. ดู skill `quant-systematic-trading` + `references/validation-rigor.md`.
