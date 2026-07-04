# PLAN — News & Event Impact Analysis (backlog #10 + #11)

> Written by: planner · Last updated: 2026-07-04
> Status: APPROVED (user ตอบ Open Questions 2026-07-04 — ดูท้ายไฟล์)
> Cycle ก่อนหน้า (Stabilize & Complete) ปิดแล้ว — ดู git history + continue.md

## Goal

สร้างชั้นวิเคราะห์ "ข่าวและ event" แบบ display-first สองส่วนที่เสริมกัน เพื่อตอบคำถาม
"ตอนนี้เกิดอะไรขึ้น + ทองน่าจะไปทางไหน": (A) ให้คะแนน impact ของข่าว/โพสต์ **รายชิ้น**
(ทิศต่อทอง / ความมั่นใจ / ระดับความแรง / อายุของผล) แทน sentiment ก้อนเดียวที่ใช้อยู่ —
จะได้รู้ว่าข่าวชิ้นไหนขับทอง ทางไหน แรงแค่ไหน; และ (B) ยกระดับ Event Radar เดิมจาก prior
แบบเหมารวม เป็น scenario ที่ **ขึ้นกับ surprise** (actual ร้อน/เย็นกว่า consensus →
ทองไปทางไหน ขนาดเท่าไร) ทั้งสองส่วนเป็นเครื่องมือแสดงผล/บริบท ไม่ใช่ trigger เทรด
และต้องไม่เพิ่มต้นทุน AI ต่อ cycle (เป้า burn 150-250฿/วัน ยังเป็น first-class constraint)

## Scope

**Feature A — Per-post News Impact scoring** (ต่อยอด X/Twitter + web news ที่บอทอ่านอยู่แล้ว)
- Normalize โพสต์/ข่าวทุกแหล่งให้เป็น schema เดียวกัน
- **Pre-filter ในโค้ด (ฟรี)**: ทิ้งโพสต์ที่ไม่แตะปัจจัยทอง (Fed / CPI / yields / DXY /
  war / tariff / Trump) ก่อนจ่าย token — เป้าตัด noise 70-80%
- Dedupe ด้วย content hash (ข่าวเดียวกันหลายแหล่ง/รีโพสต์ นับครั้งเดียว)
- Scoring แบบ **batch** ด้วย Haiku: โพสต์ที่ผ่านตัวกรองใน window หนึ่ง → หนึ่ง LLM call
  คืนผลรายโพสต์ = {direction bull/bear/neutral ต่อทอง, confidence, magnitude_tier 1-3,
  half_life, reason} — **merge เข้า call สรุปข่าวเดิม** เป็นทางเลือกแรก ไม่เพิ่ม call/cycle
- Rolling aggregate score ถ่วงด้วย magnitude × ความสด (half-life decay)
- การ์ด "News Impact" บน dashboard: รายการโพสต์เด่นพร้อมคะแนน + ตัวเลข aggregate
- v1 เป็น display-only; การป้อนคะแนนเข้า macro regime / analyst = Open Question

**Feature B — Event scenario conditioned on surprise** (ยกระดับ Event Radar เดิม — ไม่รื้อ)
- **Sign table ต่อ event type**: นิยามทิศก่อน (เช่น CPI hot → gold down, NFP hot → down,
  FOMC hawkish → down) — user ยืนยันตารางก่อนแสดงผล
- **Conditional scenario บนการ์ด**: ใช้ consensus/forecast จาก calendar feed ที่ดึงอยู่แล้ว
  แสดง "ถ้า actual ร้อนกว่า consensus → ทองน่าจะ X | ถ้าเย็นกว่า → Y" เริ่มจาก sign +
  magnitude เดิมสองฝั่งที่มีอยู่ (ยังไม่ conditional) แล้วค่อยแทนด้วยสถิติจริง
- **Magnitude scale ตามขนาด surprise**: รวบรวมประวัติ actual-vs-consensus ต่อ event →
  ความสัมพันธ์ |surprise| → |move| (พลาด 0.1% กับ 0.5% คนละเรื่อง) — computed-in-code
  ทั้งหมด ไม่มี recurring AI cost

**ร่วมกันทั้งสอง feature — Magnitude honesty (milestone แยกชัดเจน ไม่ใช่สมมติฐานแฝง)**
- เก็บ realized price move ที่ +5 / +15 / +60 นาที หลังโพสต์ที่ถูก score และหลังเลขออก
- ใช้ calibrate rubric tier และ surprise-curve ทีหลัง — **ห้ามเดา magnitude / ห้ามอ้าง
  ความแม่นก่อนผ่านการ validate** (บทเรียน reverse-causality ของโปรเจกต์นี้)

**งานจิ๋วแถม**: โชว์ delta +$/−$ ชัดๆ บนการ์ด Event Radar (display บรรทัดเดียว ทำก่อนได้)

## Non-Goals

- **ไม่ trigger เทรดอัตโนมัติ** จากคะแนนข่าวหรือ scenario ใดๆ — display/บริบทเท่านั้น
- **ไม่แตะ** gate logic, confidence thresholds, money management, anti-fade guards,
  และ live prompt ของ agents ทุกตัว
- **ไม่เพิ่ม AI call ต่อ bot cycle** — scoring ต้อง merge เข้า call เดิมหรือเป็นงาน scheduled;
  ไม่ใช้ Sonnet สำหรับ scoring (Haiku เท่านั้น)
- **ไม่ rebuild Event Radar priors เดิม** (unconditional direction % + เป้าสองฝั่ง มีแล้ว
  ใช้ต่อ) — เพิ่มเฉพาะชั้น conditional + magnitude scaling
- ไม่เพิ่ม dependency หนักใหม่ (ML framework, vector DB ฯลฯ) — regression/สถิติทำด้วย
  เครื่องมือที่มีอยู่
- ไม่ทำ per-post scoring แบบ 1 call ต่อ 1 โพสต์ ไม่ว่ากรณีใด
- ไม่สัญญา "ทำนายราคา" — ทุกตัวเลขต้องระบุที่มา (prior / rubric / calibrated) บนการ์ด

## Milestones (เรียงถูก-ไว-เสี่ยงต่ำก่อน; แต่ละข้อ verify ได้อิสระ)

- **M0 — Quick win: delta $ บนการ์ด Event Radar** — แสดงเป้าเป็น +$/−$ จากราคาปัจจุบัน
  ชัดๆ. Verify: เปิด dashboard วันมี event เห็น delta ถูกต้องตรงกับ % เดิม
- **M1 — Feature A ชั้นโค้ดล้วน (ฟรี)**: normalize schema + pre-filter ปัจจัยทอง + dedupe.
  Verify: log อัตราการกรองจริง (เป้าตัด ≥70% ของโพสต์ดิบ) + ไม่มีข่าวปัจจัยทองหลุด
  เมื่อ spot-check ย้อนหลัง 1-2 วัน; token cost ยังเท่าเดิม
- **M2 — Feature B sign-based scenario**: sign table (user ยืนยันแล้ว) + บรรทัด conditional
  "hot → … / cool → …" บนการ์ด event ที่มี consensus. Verify: วันมี event การ์ดแสดง
  สอง scenario ถูกทิศตาม sign table; วันไม่มี consensus การ์ด fallback เป็นแบบเดิม
- **M3 — Feature A batch scoring + การ์ด News Impact**: Haiku คืนคะแนนรายโพสต์ใน call
  ที่ merge กับสรุปข่าวเดิม + rolling aggregate + การ์ดบน dashboard. Verify: จำนวน AI call
  ต่อ cycle เท่าเดิม (ดูจาก cost tracking); token/วัน เพิ่มไม่เกินงบที่ตกลง; คะแนนรายโพสต์
  ปรากฏบนการ์ดพร้อม reason
- **M4 — Realized-move logger (ทั้งสอง feature)**: บันทึกราคาที่ +5/+15/+60 นาที
  หลังโพสต์ tier สูงและหลังเลขออก ลง storage — เก็บอย่างเดียว ยังไม่ปรับอะไร.
  Verify: หลัง event/ข่าวใหญ่ 1 รอบ มี record ครบทุก horizon
- **M5 — Feature B surprise-magnitude จากข้อมูลจริง**: สร้างชุดประวัติ actual-vs-consensus
  ต่อ event (แหล่งตาม Open Question) → conditional split + |surprise|→|move| แทนตัวเลข
  rubric บนการ์ด พร้อมป้าย n และช่วงข้อมูล. Verify: ตัวเลข reproduce ได้จาก script เดียว +
  spot-check กับ event จริงย้อนหลัง (เช่น NFP miss ล่าสุด)
- **M6 — Calibration review (gate ด้วยจำนวน sample)**: เทียบ magnitude_tier และ
  surprise-curve กับ realized move ที่เก็บจาก M4; รายงานผล + ปรับ rubric/แสดงผล.
  Verify: รายงาน calibration มีตัวเลข hit-rate ต่อ tier; การ์ดแสดงสถานะ calibrated/ยังไม่

## Risks

- **Magnitude หลอก / reverse-causality** (สูง) — โปรเจกต์เคยเจ็บมาแล้ว (hold-time,
  CHART_SHADOW). Mitigation: M4+M6 เป็น milestone บังคับ; ก่อน calibrate การ์ดต้องติดป้าย
  "rubric — ยังไม่ validate"; ห้ามตัวเลข magnitude ใดขึ้นการ์ดโดยไม่มีที่มา
- **Token creep** (กลาง) — batch scoring ทำให้ call เดิมอ้วนขึ้นเงียบๆ. Mitigation:
  pre-filter+dedupe ก่อนเสมอ, cap จำนวนโพสต์ต่อ batch, วัด token/วัน เทียบ baseline
  ก่อน-หลัง M3 ผ่าน cost tracking ที่มีอยู่; เกินงบ → ลด window/cap ทันที
- **Consensus history หาไม่ครบ** (กลาง-สูง) — calendar feed ปัจจุบันให้ forecast ของ event
  ข้างหน้า แต่ conditional stats ต้องการประวัติย้อนหลังหลายปี. Mitigation: M2 (sign-based)
  ไม่พึ่งประวัติ จึง ship ได้ก่อน; M5 แยกอิสระ + Open Question เรื่องแหล่งข้อมูล
- **n เล็กเกินเมื่อ split ตาม surprise** (กลาง) — แบ่ง 173 CPI เป็น hot/cool/inline ×
  ขนาด surprise อาจเหลือ cell ละไม่กี่ตัว. Mitigation: แสดง n กำกับทุกตัวเลข; cell ที่
  n ต่ำกว่าเกณฑ์ → fallback เป็น sign + prior เดิม
- **Scoring คุณภาพต่ำจาก Haiku** (กลาง) — บทเรียน CHART_SHADOW: Haiku แทนงานวิเคราะห์
  ลึกไม่ได้. Mitigation: งานนี้เป็น classification สั้นต่อโพสต์ (ง่ายกว่า chart) + M6 วัด
  hit-rate จริงเทียบ realized move ก่อนเชื่อถือ/ต่อยอด
- **แหล่งข่าวภายนอกเปลี่ยน format/ล่ม** (กลาง) — RSS/scrape เปราะโดยธรรมชาติ.
  Mitigation: ทุกชั้นใหม่ fail-soft — พังแล้วการ์ดว่าง/ตกกลับพฤติกรรมเดิม ห้ามล้ม pipeline

## Open Questions — ตอบแล้ว (user 2026-07-04)

1. **sign table surprise→gold** → ✅ **ใช้ default มาตรฐาน**: CPI/Core CPI/NFP/PCE/
   Retail Sales/GDP hot→down, Unemployment สูงกว่าคาด→up, FOMC hawkish→down
   (ผ่านช่องทางค่าเงินจริง/yields). ยึดตารางนี้เป็น sign table ของ M2.
2. **แหล่ง consensus history (M5)** → ✅ **manual seed เฉพาะ CPI+NFP+FOMC** — คุมคุณภาพได้
   เริ่มเล็ก; ไม่ scrape/ไม่ใช้ AlphaVantage ในเฟสนี้.
3. **feed analyst หรือ display-only** → ✅ **display-only ใน v1** — ไม่แตะ AI pipeline/gate
   จน M6 calibration พิสูจน์คุณภาพก่อน แล้วค่อยพิจารณา feed ทีหลัง.
4. **calibration window + min-n** → ✅ default: **n≥30 ต่อ cell** ตามธรรมเนียม pre-registered;
   window ให้ architect เสนอ (ยาว 2012+ เป็นฐาน, เปรียบเทียบ recent regime ได้ถ้า n พอ).
5. **งบ token M3** → ✅ default: **≤10% ของ burn ปัจจุบัน** และรวมต้องอยู่ในเป้า 150-250฿/วัน —
   เป็นเกณฑ์ verify ของ M3.
