# DESIGN — Statistical Exit Layer (SEL) — proposal

**Status: DESIGN PROPOSAL ONLY. Flag-OFF. Nothing wired into the live pipeline.**
คู่กับ `docs/DESIGN_evidence_based_entry.md` (ใช้ EV framework + feature เดียวกัน) — อันนั้น = *เข้า*, อันนี้ = *ออก*.

**Iron rules ที่ผูกไว้ (ไม่เปลี่ยน):** RR≥2 บน entry, fixed SL เป็น hard floor เสมอ, ไม่ averaging/martingale,
guard/exit เดิม (breakeven/trailing/momentum-exit/zone-break/partial-close/Guardian) **ยังทำงานครบ** — SEL เป็น
*ชั้นเพิ่ม* ไม่แทนที่. flag-OFF จนกว่า user อนุมัติ **และ** replay ผ่าน.

---

## 0. TL;DR
User vision: *"เข้าเมื่อสถิติบอก EV>0, และปิดทันทีเมื่อ P(ขาดทุน) ขึ้น หรือกำไรถึงจุดสูงสุดตามสถิติ."*
Entry (EV>0) = design แยกทำแล้ว. **เอกสารนี้ทำ *exit* 2 trigger:**
1. **Edge-decay exit** — ปิด/ลดไม้เมื่อ `P(ไปต่อในทิศไม้)` ตก (edge หมด) หรือ `EV(ถือต่อ) ≤ EV(ปิดตอนนี้)`.
2. **Statistical take-profit (MFE-percentile)** — ล็อก/ปิดกำไรที่ระดับที่สถิติบอกว่า "โอกาสวิ่งต่อลดฮวบ / โอกาสกลับตัวพุ่ง" — แทน fixed TP.

**Honesty clause (เหมือน entry):** exit ที่ไม่ได้ fit จาก history = เดาอีกแบบ. SEL ต้องพิสูจน์บน replay ว่า
net-R ดีกว่า fixed TP/SL **และไม่ตัด winner ตัววิ่งทิ้งมากเกิน** ก่อนเปิด. ตอนยังไม่ fit → SEL = no-op
(exit เดิมคุมล้วน) ไม่มีวันปิดเร็ว/หลวมกว่าเดิม.

---

## 1. หลัก quant ที่ใช้
| หลัก | ใช้ยังไง |
|------|----------|
| **MFE / MAE** (Max Favorable / Adverse Excursion) | วัด distribution ว่า winner วิ่งไปไกลแค่ไหนก่อนกลับ, loser สวนไปเท่าไรก่อนถึง SL → หา "จุดสูงสุดตามสถิติ" |
| **Edge decay** | edge ไม่คงที่ — recompute `P(continue)` ต่อ cycle, edge หมด = ปิด |
| **Hold-vs-Close EV** | ถือต่อคุ้มมั้ย: `EV(hold) = P(ถึง TP)·reward_เหลือ − P(ชน SL)·risk_เหลือ` เทียบกำไรที่ถืออยู่ |
| **Time-stop / opportunity cost** | winner ส่วนใหญ่วิ่งภายใน N bar — เกินแล้วยังนิ่ง = edge decayed → ปล่อยทุนไปหาไม้อื่น |
| **Scale-out** | ปิดเป็นส่วนที่ percentile ต่างกัน (ล็อกกำไร ไม่ตัด runner ทิ้งหมด) |

---

## 2. Trigger 1 — Edge-decay exit (ปิดเมื่อ P(loss) ขึ้น)
ต่อ cycle (หรือ Guardian poll) recompute **P(favorable-continuation)** จาก feature เดิม (F1..F7 ของ entry model
+ สถานะไม้): momentum พลิกสวน, `reversal_confirm` สวนทิศไม้, ราคาใกล้ชน opposing zone (grade สูง), news สวนเข้ามาใหม่.

```
P_cont = logistic( prior_ยังไปต่อ + w·evidence_ปัจจุบัน )       # โมเดลเดียวกับ entry, refit บน "in-trade" labels
close_signal ⟺  P_cont < τ_exit    OR    EV(hold) ≤ unrealized_pnl − cost
```
- `EV(hold) = P_cont · reward_เหลือ(ถึง TP) − (1−P_cont) · risk_เหลือ(ถึง SL)`
- τ_exit **fit จาก data** (ไม่เดา) — sweep บน replay หา net-R สูงสุด. ต่างจาก entry τ (breakeven) เพราะ in-trade มี unrealized ต้องชั่ง.

## 3. Trigger 2 — Statistical TP (MFE-percentile)
จาก history วัด favorable-excursion `X` ต่อ setup-type/regime → distribution.
วาง scale-out targets ที่ percentile ที่ **P(วิ่งต่อ | มาถึงตรงนี้) ตก** (hazard พุ่ง):
```
เช่น setup support-bounce: MFE p50=+1.2R, p70=+2.1R, p85=+3.4R
→ ปิด 50% ที่ p70, ล็อก BE, ปล่อย runner 50% ให้ trailing เดิม
```
- ไม่ fix TP — target ปรับตาม setup + vol (ATR). RR≥2 ยังเป็น floor ของ target แรก.

## 4. ผลกระทบ
- **แตะ exit/money-management path** (`manage_*`, Guardian daemon) → **iron rule: ต้องอนุมัติ + replay**
- token: **0** (compute-in-code จาก feature ที่มี)
- reuse: Guardian poll (ถี่ ~4s) + `manage_partial_close`/`manage_trailing_stop`/`manage_momentum_exit` เดิม → SEL เพิ่ม trigger เข้าไป ไม่สร้าง path ใหม่
- **ความเสี่ยง 2 ทาง (ต้อง calibrate):** ปิดเร็ว = ตัด winner วิ่ง (วัด "left on table"); ปิดช้า = คืนกำไร (วัด "give-back")

## 5. ⚠️ Data prerequisite — P1c (ต่อยอด P1b)
fit exit ไม่ได้ถ้าไม่มี **MFE/MAE ต่อไม้ + in-trade feature timeline**:
- **P1c:** log excursion ต่อไม้ (peak favorable, peak adverse, time-to-peak, ราคาต่อ cycle ระหว่างถือ) + exit outcome
- ต่อยอด P1b (`decision_snapshots.jsonl`) → เพิ่ม `trade_excursions.jsonl` (ผูก ticket → timeline)
- **ต้องบอทรันสะสมก่อน** เหมือน entry — ไม่มี data = fit ไม่ได้ = SEL อยู่ OFF

## 6. Rollout (phased, ปลอดภัยสุดก่อน)
```
v0  Statistical partial-TP อย่างเดียว (ล็อกกำไรบางส่วนที่ MFE-percentile, ไม่ปิดหมด)
    → ปลอดภัยสุด: ไม่ตัด runner ทิ้ง, downside แค่ "ล็อกเร็วไปนิด"
v1  + Edge-decay full/partial exit
v2  + dynamic MFE-TP ต่อ regime
```
แต่ละ v: flag-OFF → P1c สะสม data → fit → **replay เทียบ fixed-TP/SL** (net-R + left-on-table + give-back) → shadow → enable

## 7. Acceptance criteria (ก่อนเปิด)
1. `Σ R(SEL) > Σ R(fixed TP/SL)` บน held-out replay (net cost)
2. **ไม่ลด winner tail มากเกิน** — วัด left-on-table; SEL ห้ามตัดกำไรรวมของ runner ทิ้ง > X%
3. give-back ลดลง (ล็อกกำไรได้ก่อนคืน)
4. calibrated: P_cont ตรง realized continuation (reliability diagram)
5. ไม่ทำให้ loss เฉลี่ยแย่ลง (SEL ปิด loser เร็วขึ้นได้ แต่ห้ามเพิ่ม loss)

## 8. ความสัมพันธ์กับ exit เดิม (ไม่แทนที่)
ระบบมี: fixed SL (hard floor), breakeven (BE_TRIGGER_R), trailing, momentum-exit, zone-break-close, partial-close, Guardian daemon.
→ **SEL = ชั้นสถิติบนสุด** เพิ่ม trigger "ปิดเชิงความน่าจะเป็น" — SL/BE/guard เดิมยัง bind. SEL ปิด*เร็วขึ้น*ได้เมื่อ edge หมด แต่ **ห้ามยืด SL / ห้ามถือเกิน guard เดิม**.

---

## 9. หนึ่งประโยค
> เข้าเมื่อ EV>0 (entry design), **ออกเมื่อ edge หมด (P_cont ตก) หรือกำไรถึง MFE-percentile ที่สถิติบอกว่าใกล้กลับตัว** —
> ทั้งคู่ fit จาก data จริง (P1b+P1c), พิสูจน์บน replay, flag-OFF จนกว่าจะชนะของเดิม. Derive, don't assume.
