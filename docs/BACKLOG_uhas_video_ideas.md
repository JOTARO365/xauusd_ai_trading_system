# BACKLOG — UHAS Terminal + Live-Stream Ideas (DRAFT / not approved)

> **สถานะ: RESEARCH BACKLOG — ยังไม่อนุมัติ / ยังไม่มี code**
> ที่มา: วิเคราะห์ video `fs-wQmy9E-I` (LIVE "มองทองคำ 16 ก.ค.") + รูป UHAS terminal 6 รูป
> (`docs/img/Screenshot 2026-07-17 07*.png`) · วันที่: 2026-07-17
> คัดเฉพาะที่ **NEW (ระบบยังไม่มี)** + จัดลำดับตามต้นทุน/ความเสี่ยง. logic changes ต้องผ่าน
> EXPLAIN-BEFORE-ACTING + อนุมัติ + replay ตาม iron rule ([[system-wiring-audit]]).

หมายเหตุ: video เป็น live stream signal ต่ำ (ส่วนใหญ่ราคา/ข่าว/นอกเรื่อง) — ที่ systematizable จริงมีน้อย.
UHAS terminal ในรูปเป็น "institutional trade-desk simulation" (multi-agent committee + exec brief).

---

## A. เทคนิคเทรด (NEW, ไม่ขัด logic เดิม)

### A1. WTI-vs-gold divergence dampener  ·  ⭐ คุ้มสุด — DESIGN (รอ probe + อนุมัติ)
> source: video @ ~1:40:45, ~1:56:30 · ต่อยอด `scripts/probe_intermarket.py`

**1. ทำอะไร:** เมื่อมี narrative "oil/inflation กดทอง" → เช็คว่า WTI ขยับยืนยันจริงมั้ย ถ้าทองร่วงแรง
แต่น้ำมันแทบไม่ขยับ (divergence) = ทอง overdone → ลดน้ำหนัก bearish / อนุญาต fade ตามเทคนิค.

**2. ทำงานยังไง:**
- WTI feed 2 ทาง: (a) MT5 symbol `USOIL`/`WTI`/`XTIUSD` (เร็ว, 0 token) — **ต้อง probe ยืนยันว่า broker มี**;
  (b) AlphaVantage `WTI` (ช้า, 25/วัน) = fallback
- compute-in-code: `gold_move% (fast)` vs `wti_move% (same window)` → flag `oil_divergence` เมื่อ
  `|gold_move| ≥ G_THR` และ `|wti_move| ≤ W_THR` และทิศสวน expectation (ข่าว oil-bearish แต่ WTI ไม่ลง)
- feed เป็น **1 vote เข้า (ก) NEWS-dampener** (enable แล้ว) — เพิ่มน้ำหนัก contradiction เมื่อ divergence

**3. ผลกระทบ:** token 0 (MT5) · แตะ decision dampener = logic → อนุมัติ+replay · เสี่ยง: corr gold-WTI
ไม่คงที่ (บางช่วง ~0) → probe วัด rolling corr ก่อน

**4. Tunables (default):** `OIL_DIVERGENCE_ENABLED=false`, `OIL_G_THR=300p`, `OIL_W_THR=0.3%`, `OIL_WINDOW=M15×3`

**5. ⚠️ PREREQUISITE (user ต้องรัน):** `& $PY scripts\probe_intermarket.py` ตอน MT5 เปิด →
ยืนยัน (1) broker มี WTI symbol (2) corr gold-WTI valid. **ถ้า corr อ่อน = พับ A1**. ยังทำ code ไม่ได้จนกว่า probe ผ่าน.

**6. Rollout:** flag OFF → probe ผ่าน → replay → shadow → enable (เหมือน ZRE/[[zre-news-dampener-live]])

### A2. Event-precedence dampening
- **ทำอะไร:** event tier สูงที่มา**ก่อน** (เช่น rate decision) ลด impact ของ event เล็กที่ตามมา (เช่น NFP ถัดไป)
- **ทำไม:** refine news-impact conf-floor — discount event ที่ถูก pre-empt
- **ต้นทุน/ขัด:** compute-in-code; ไม่ขัด (ปรับ news-impact ที่มีอยู่)
- source: @ ~0:59:20, ~1:24:46

### A3. Bollinger squeeze (M5) breakout precursor
- **ทำอะไร:** BB บีบ/พันตัว = สัญญาณ move แรงใกล้มา (2-3 แท่งถัดไป) → ติดอาวุธ momentum-breakout ที่มีอยู่
- **ต้นทุน/ขัด:** compute-in-code (BB width detector); ไม่ขัด (trigger refinement)
- source: @ ~1:53:50

### A4. ADR%-consumed exhaustion filter  ·  PARTIAL
- **ทำอะไร:** ใช้ average daily range; ราคากิน ~100% ADR ของวันแล้ว → หยุดเข้าไม้ใหม่ + ใช้ ADR วาง TP/SL
- **ทำไม:** throttle late-in-move entries เสริม counter-spike
- **ต้นทุน/ขัด:** มี fast-move/counter-spike แล้ว แต่ไม่มี %-ADR-consumed; ไม่ขัด
- source: @ ~1:37:55

### A5. Mid-range no-trade block  ·  PARTIAL
- **ทำอะไร:** กลาง box = RR แย่ ~50/50; เข้าเฉพาะขอบ (S/R) ไม่เข้ากลาง
- **ต้นทุน/ขัด:** มี range-bounce ที่ S/R แล้ว แต่อาจไม่ block กลาง range ชัด; ไม่ขัด (เสริม SIDEWAYS gate)
- source: @ ~1:01:30

### ❌ ตัดทิ้ง — Volatility-adaptive SL
SL scale ตาม ATR (25-30$) — **ขัด fixed-SL iron rule** โดยตรง. เก็บเป็น note เฉยๆ ไม่ทำ.

---

## B. UHAS terminal features (NEW)

### B1. Continuation-vs-reversal % ต่อ zone  ·  ⭐ ถูกสุด (display, 0 token)
- **คือ:** แนบ probability ต่อ zone target เช่น "ถึง 4019 → 73% ไปต่อ / 27% กลับตัว"
- **build:** คำนวณจาก touch/bounce stats ที่มีใน sr_meta อยู่แล้ว (break_pct/bounce_pct) → แสดงบน dashboard
- source: รูป + video @ ~45:48, ~2:00:23

### B2. Session & Deadline countdown gate  ·  0 token
- **คือ:** agent "Time" ของ UHAS = ติดตาม session + นับถอยหลังถึง event/deadline ถัดไป
- **build:** compute-in-code "นาทีถึง red-event ถัดไป + session phase" ป้อน decision_maker (ต้องอนุมัติ = logic)
- source: รูป (Aurum Office session scheduler) + @ 42:03

### B3. COT net-position → analyst input  ·  logic
- **คือ:** UHAS agent "Oat" ใช้ COT Managed-Money net (+114,854) เป็น gold tilt
- **build:** เรามี `cot.json` (net/net_chg) แต่ dashboard-only → promote net-position **delta** เป็น analyst fundamental
- source: @ 42:09, ~1:20:55

### B4. Quantified macro-delta bias  ·  logic
- **คือ:** real yield / breakeven / DXY กรอบด้วย "level แต่ไม่ขยาย" (เช่น "ดอลลาร์สูงแต่ไม่ขยาย → แรงกดคลาย")
- **build:** เรามี `macro_strip.json` (dxy/y10/real_yield {val,chg}) dashboard-only → ป้อน **delta/expanding-flag** เป็น bias
- source: @ ~1:20:55–1:21:50

### B5. Two-sided conditional plan (candidate)  ·  logic + replay
- **คือ:** plan ระบุ bull-trigger (reclaim swing-high → target X) + bear-trigger + invalidation เป็น "candidate"
  ที่ **arm เมื่อ M15 confirm** เท่านั้น (ก่อนหน้า = รอ ไม่เข้า)
- **ทำไม:** ลด mid-zone FOMO; ตรงกับปรัชญา pullback-preference
- source: รูป (INSTITUTIONAL TRADE DESK BRIEF: "รอแท่ง M15 ยืนยัน") + @ ~1:22:32

### B6. Numeric market-structure score (signed −1..+1)  ·  logic
- **คือ:** UHAS โชว์ structure เป็นเลข (H4 = −0.667) แทน label
- **build:** expose market_structure เป็น scalar ให้ gate threshold ได้ (แทนอ่าน text)
- source: รูป @ 37:19–38:05

### UHAS UI features ที่ implement บน dashboard แล้ว (07-17)
Trade Desk Brief hero card + macro ticker (DXY/10Y/R.Yld/COT) — display-only. ที่ยังเหลือจาก UHAS layout:
gate pills, entry-corridor ladder, active-blockers panel, Bull/Base/Bear cards, committee-consensus bar,
event countdown card (= "Full UHAS layout" scope, ทำทีหลังถ้าต้องการ).

---

## ลำดับแนะนำ (ถ้าจะเดินต่อ)
1. **B1 zone continuation-%** + **B2 session countdown (display)** — 0 token, ไม่ขัด, ถูกสุด
2. **A1 WTI-divergence** — ต่อยอด intermarket probe ที่เขียนไว้ (`scripts/probe_intermarket.py`)
3. ที่เหลือ (A2-A5, B3-B6) = logic → explain + อนุมัติ + replay ทีละอัน
เกี่ยว: [[zre-news-dampener-live]], [[token-roi-stance]], `docs/DESIGN_entry_proposals.md`.
