# PLAN — Stabilize & Complete: XAUUSD AI Trading System

> Written by: planner · Last updated: 2026-07-04
> Status: APPROVED (user amended scope 2026-07-04 — M2/M3 deferred, ดู Open Questions)

## Goal

เก็บงานค้างของระบบเทรด XAUUSD ที่รัน live ด้วยเงินจริงบนเครื่อง local ให้ "นิ่งและครบ":
ปิดช่องโหว่ที่เสี่ยงต่อเงินทุนก่อน (dashboard ที่สั่งปิดไม้ได้แต่ไม่มี auth, ไม่มีระบบแจ้งเตือน
เมื่อบอทหยุดเงียบ — เคยเกิดแล้ว), เก็บงานที่ค้างใน working tree ให้เข้าที่, เฝ้าผลการทดลอง
ที่เพิ่ง ship (MOMENTUM_RIDE) และเป้า cost ใหม่ (~150-250฿/วัน) ด้วยตัวเลขไม่ใช่ความรู้สึก,
แล้วจึงเติมเครื่องมือวิเคราะห์ที่เหลือแบบไม่เพิ่ม AI call

## Scope

- จัดระเบียบงานที่ยังไม่ commit (ฟีเจอร์ dashboard ชุดล่าสุด + script ใหม่ + ไฟล์หลงทาง)
- ยืนยันว่า process ที่รันอยู่จริงเป็นโค้ดเวอร์ชันล่าสุด (บทเรียน 07-03: บอทหยุดเงียบ 8 ชม.)
- ความปลอดภัย dashboard: บังคับ authentication หรือจำกัดเครือข่าย (มีปุ่มปิดไม้/แก้ config)
- ระบบแจ้งเตือนภายนอก (LINE หรือ Telegram): บอทหยุด/ขาดการเชื่อมต่อ, ไม้เปิด-ปิด, SL โดน
- แก้รายการค้างจาก audit: การปิดไม้ผ่าน dashboard ที่อาจล้มเหลวกับ broker บางโหมด,
  race condition ของไฟล์ trade log, ลดภาระ endpoint สรุปบัญชีด้วย caching
- จุดวัดผลตามนัด: RIDE cohort (1-2 สัปดาห์), burn รายวันเทียบเป้า, สกอร์ trend-mode รายสัปดาห์,
  D1 flip watch, ความพร้อมก่อน CPI 07-14 และ FOMC 07-29
- ฟีเจอร์วิเคราะห์เพิ่ม (คำนวณในโค้ด ไม่เรียก AI): macro strip (DXY / 10Y / real yield),
  COT รายสัปดาห์, confidence calibration view

## Non-Goals

- **BTC system** — backlog เดิม ยังไม่เริ่ม (สวิตช์ UI ถูกถอดไปแล้ว)
- **ปลุก VM / บัญชีที่ SO แล้ว** — user สั่ง "เก็บไว้ก่อน"; ไม่วางงานใดที่ต้องพึ่ง VM
- **ห้ามแตะ gate logic / confidence thresholds / money management / anti-fade guards /
  live prompts** — ทุกการเปลี่ยนต้องผ่าน explain-before-acting + user อนุมัติเท่านั้น
  (รวมถึง "ปรับ RIDE" ก่อนครบกำหนดเฝ้าผล)
- **ไม่เพิ่มฟีเจอร์ที่มี recurring AI-call cost** — cost เป็น first-class constraint
- **ไม่ start/stop บอท live หรือส่งคำสั่งเทรดอัตโนมัติจากงาน development** — user คุม process เอง
- ไม่รื้อ exit-management stack (validated +27,833฿) และไม่ re-derive ผลวิเคราะห์เดิม
- ไม่ redesign dashboard ครั้งใหญ่ — เติมเฉพาะ gap ที่ระบุ

## Milestones

(เรียงตามความเสี่ยงต่อเงินทุน — ของที่กันเงินหายมาก่อนของสวย)

1. **M1 — Working tree สะอาด + ยืนยันโค้ดที่รันจริง**
   ตัดสิน commit policy กับ user แล้ว commit/ทิ้งงานค้างทั้งหมด; ตรวจว่า process บอทและ
   dashboard ที่รันอยู่ใช้โค้ดล่าสุด (user เป็นคน restart)
   ✔ ตรวจได้: git status ว่าง, log ของบอทแสดงพฤติกรรมเวอร์ชันล่าสุดใน cycle จริง
2. ~~**M2 — Dashboard security**~~ **DEFERRED (2026-07-04)** — user ยืนยัน dashboard
   รันเฉพาะในเครื่องนี้ ไม่เปิดสู่เครือข่าย → ยังไม่ทำ; เงื่อนไขปลุกงานนี้: เมื่อใดที่จะเปิด
   port 5050 ให้เครื่องอื่นเข้าถึง ต้องทำ M2 ก่อนเสมอ
3. ~~**M3 — Alerting**~~ **DEFERRED (2026-07-04)** — user ยังไม่ต้องการระบบแจ้งเตือน;
   ความเสี่ยง "บอทหยุดเงียบ" ยังอยู่ → บรรเทาด้วยการเช็ค dashboard ด้วยตาตามรอบไปก่อน
4. **M4 — Audit fixes ชุด B/C** (ทดสอบระดับ demo/simulation เท่านั้น — user กำหนด)
   ปิดไม้จาก dashboard สำเร็จกับทุกโหมดคำสั่งของ broker; ขจัด race ของ trade log;
   endpoint สรุปบัญชีมี cache
   ✔ ตรวจได้: test ผ่าน + ปิดไม้ demo/ไม้จริงตามที่ user อนุญาตสำเร็จ, ไม่มี log corruption ซ้ำ
5. **M5 — Measurement checkpoints (งานเฝ้าผล มีนัดชัดเจน)**
   RIDE cohort ครบข้อมูล → สรุป win/loss ให้ user ตัดสิน knob; burn รายวันรายงานเทียบเป้า
   150-250฿; สกอร์ trend-mode รายสัปดาห์ (n≥30 ตามเกณฑ์ pre-registered); D1 flip watch;
   ก่อน CPI 07-14 ตรวจ Event Radar + prior ขึ้นจริงบนจอ
   ✔ ตรวจได้: มีรายงานตัวเลขต่อนัด และ CPI-readiness check ผ่านก่อน 07-12
6. **M6 — เครื่องมือวิเคราะห์ที่เหลือ (ไม่เพิ่ม AI call)**
   macro strip (DXY/10Y/real yield), COT รายสัปดาห์, confidence calibration view
   ✔ ตรวจได้: แสดงข้อมูลจริงบน dashboard โดย token burn รายวันไม่ขยับขึ้น

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| บอทหยุดเงียบโดยไม่มีใครรู้ (เกิดแล้ว 07-03) | สูง | สูง — พลาดโอกาส/ไม้ไร้คนดูแล | M3 ทำก่อนฟีเจอร์ใดๆ; heartbeat เป็น alert ตัวแรก |
| Dashboard ไม่มี auth แต่สั่งปิดไม้/แก้ config ได้ | กลาง | สูงมาก — คนอื่นสั่งเทรดแทนได้ | M2 เป็นงานแรกหลังเก็บ tree; ระหว่างรอ ห้ามเปิด port สู่ public |
| งานแก้ระบบชนกับ process live (เงินจริง) | กลาง | สูง | ทุก restart เป็นของ user; ทดสอบบน dashboard port แยก/ข้อมูลจำลองก่อน |
| CPI 07-14 / FOMC 07-29 volatility ชน SL กว้าง | กลาง | สูง | M5 readiness check ก่อนวันงาน; ไม่แก้ guard ใดๆ ใกล้วัน event |
| Token burn เด้งกลับเกินเป้าหลังเพิ่มฟีเจอร์ | กลาง | กลาง — ขาดทุนเชิงโครงสร้าง | ทุกฟีเจอร์ใหม่ต้อง non-AI-call; M5 วัด burn ทุกวัน |
| RIDE cohort ตัวอย่างน้อย → ตัดสินผิด | กลาง | กลาง | รอครบกำหนด/จำนวนไม้ขั้นต่ำ ไม่ตัดสินจากไม้เดียว |
| งานค้างไม่ commit สูญหาย/ทับกัน | กลาง | กลาง | M1 ปิดก่อนเริ่มงานอื่นทั้งหมด |
| แหล่งข้อมูลภายนอก (macro/COT) ติด rate limit หรือหยุดให้บริการ | กลาง | ต่ำ | ใช้ quota ฟรีอย่างประหยัด + cache; ฟีเจอร์เหล่านี้เป็น display-only |

## Open Questions

(user ตอบ 2026-07-04)

- [x] **Commit policy งานค้าง** → **commit เลย + เก็บกวาด**: commit ฟีเจอร์ dashboard
      ชุดล่าสุด, ลบภาพ screenshot สมัคร cloud, script ทดลองย้ายเข้า scripts/ หรือลบ
- [x] **Security approach** → **ยังไม่ทำ (DEFERRED)** — dashboard รันแค่ในเครื่องนี้
- [x] **ช่องทาง alert** → **ยังไม่ใช้ (DEFERRED)**
- [x] **ขอบเขตการทดสอบ M4** → **demo/simulation เท่านั้น** ห้ามแตะไม้จริง
- [ ] **RIDE decision date**: ล็อกวันตัดสินตายตัว (เช่น ~07-17) หรือเกณฑ์จำนวนไม้ขั้นต่ำ?
      (ไม่ block งานสร้าง — เป็นการตัดสินใจตอนอ่านผล)
- [ ] **ลำดับ M6**: architect เสนอลำดับได้เลย user จะเลือกตอน approve ARCHITECTURE.md
