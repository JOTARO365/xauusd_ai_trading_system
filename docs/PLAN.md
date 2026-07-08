# PLAN — Regime Auto-Enrichment & System De-cruft (cycle #12)

> Written by: planner · Last updated: 2026-07-08
> Status: DRAFT — รออนุมัติจาก user ก่อนเข้า Architecture
> Cycle ก่อนหน้า (#10/#11 News & Event Impact) **ปิดแล้ว** — shipped: economic
> calendar + event_scenarios + per-post news_impact + realized-move/calibration.
> PLAN.md เดิมถูกแทนที่ (rolling one-plan-per-cycle) — ของเก่าอยู่ใน git history + continue.md.

---

## Motivation (จากการสำรวจ 2026-07-08 — 2 subagents, read-only; หลักฐาน file:line ใน continue.md)

ผู้ใช้ถาม 2 ข้อ: (1) ระบบเดิมอันไหนไม่ใช้แล้ว (2) การ "ส่งวิดิโอให้วิเคราะห์" ยังจำเป็นไหม
+ ทำยังไงไม่ต้องส่งทุกครั้ง. พบข้อเท็จจริงสำคัญ:

- **บอทไม่ได้ส่งภาพ/วิดิโอ chart เข้า AI เลย** — ไม่มี base64/vision ใน agents. "การส่งวิดิโอ"
  = การป้อน **narrative ของ `agents/prompts/macro_regime.md`** ด้วยมือ (ดู YouTube macro →
  youtube-to-knowhow → กลั่นเป็น regime). analyst อ่านไฟล์นี้ทุก cycle เป็น context สูงสุด.
- **`macro_regime.md` มี 2 ชั้น:** MACRO_AUTO (auto CPI/Fed/10Y จาก AlphaVantage ผ่าน
  `update_regime.py`, REST-only zero token) + narrative (PHASE/DRIVERS/FILTER/CATALYSTS/
  geopolitics — ป้อนมือ). narrative ปัจจุบันลงวันที่ 07-02 (เก่า) และไฟล์บอกเอง "อัปเดตเมื่อ
  regime เปลี่ยน ไม่ใช่ทุกวัน". ลบ narrative = analyst กลับ default gold_factors (ปลอดภัย).
- **เซอร์ไพรส์:** ฟีดใหม่จาก cycle #10/#11 (news_impact, event_scenarios, macro_strip, cot)
  เกือบทั้งหมด **dashboard-only — ไม่เคยไหลเข้า analyst**. เราจ่าย Haiku ให้คะแนน news_impact
  ทุกรอบอยู่แล้ว (ทิศ + geopolitics tag) แต่ผลไปโผล่แค่ dashboard.
  → ตรงกับ **Open-Q#3 ของ cycle #10/#11** ที่ตอบไว้ว่า "display-only ใน v1 → feed เข้า analyst
  ทีหลังเมื่อ calibration พิสูจน์คุณภาพ". **cycle #12 คือการหยิบ step 'feed ทีหลาง' นั้นมาทำ**
  โดยเริ่มจากช่องทาง regime (ไม่ใช่ trade gate).
- **AlphaVantage NEWS_SENTIMENT** provision ไว้แต่ไม่เคยเรียก (grep = 0).
- **Dead/noise ที่ยืนยัน:** 2 orphan prompt `.md` (`trend_strategy.md`, `news_gatherer.md`);
  `twitter_client.py` (Nitter) น่าจะคืน 0 tweet ทุก cycle (Nitter ล่มปี 2025); news prefilter
  ถูกคำนวณซ้ำ 2 รอบ/cycle (observe-only แล้วทิ้ง + ของจริงใน news_cache).

**แก่นที่ลดไม่ได้ (ต้องใช้คน/วิดิโอ):** PHASE thesis + playbook เงื่อนไข (RECONCILE/FILTER,
"Warsh อ่านไม่ได้อย่าเดา", "ห้าม fade spike") — การตีความล่วงหน้า ไม่ใช่ตัวเลข.

---

## Goal

ลดการพึ่งพา "ป้อน narrative ด้วยมือ/วิดิโอทุกครั้ง" โดย (ก) auto-generate ส่วน mechanical
ของ regime จากฟีดที่มี/จ่ายไปแล้ว, (ข) เตือนคนเฉพาะตอน regime เปลี่ยนจริง, และ (ค) เก็บกวาด
dead code / งานซ้ำซ้อน. **ต้องไม่เพิ่มต้นทุน AI ต่อ cycle** และ **ต้องไม่เปลี่ยนพฤติกรรมเทรด
โดยไม่ได้ตั้งใจ** (live-money).

---

## Scope (3 threads)

### Thread 1 — Regime MACRO_AUTO enrichment (ตัวหลักของการลดวิดิโอ)
ขยาย `scripts/update_regime.py` (REST-only, zero Claude token) ให้เขียนบรรทัด auto เพิ่ม:
- **auto CATALYSTS line** — จากปฏิทิน ForexFactory + `event_scenarios.json`/`event_stats.json`
  (วัน + ทิศ hot/cool ที่คำนวณไว้แล้ว) แทนการพิมพ์ catalysts มือ.
- **auto sentiment/geopolitics tilt line** — จาก AlphaVantage NEWS_SENTIMENT และ/หรือ
  aggregate `data/news_impact.json` (Haiku จ่ายแล้ว) → สรุปทิศ hawkish/dovish + geopolitics
  เป็น 1 บรรทัดสั้น.
- คุมความยาว: analyst รัน **Sonnet ทุก cycle ไม่มี prompt cache** → เพิ่ม **1-2 บรรทัด terse
  เท่านั้น**, ห้าม dump ข้อความข่าวดิบ.
- **สอดคล้อง Open-Q#3 เดิม:** เป็นการ feed เข้า *regime context* (บริบท) ไม่ใช่ trade gate;
  ยังไม่แตะ decision path โดยตรง.

### Thread 2 — Regime-shift detector + ping
ใน `update_regime.py` ตรวจ "regime เปลี่ยน" จากค่าที่คำนวณอยู่แล้ว (fed direction flip /
real-rate sign flip / sentiment tilt ข้าม threshold) → เขียน state ล่าสุดลงไฟล์ + ส่งสัญญาณ
เตือน เพื่อให้ **คนรัน youtube-to-knowhow เฉพาะตอน shift**. เพิ่ม cadence เป็นรายวัน
(AV ใช้ 3-6/25 req/วัน). infra scheduled มีอยู่แล้ว (setup_vm_regime.ps1 weekly → เปลี่ยนเป็น daily).

### Thread 3 — De-cruft (noise/dead cleanup, independent, low-risk)
- ลบ orphan prompt docs: `agents/prompts/trend_strategy.md`, `agents/prompts/news_gatherer.md`
  (verify grep 0 refs ก่อนลบ).
- **ยืนยัน twitter=0 จาก log ก่อน** — ถ้า Nitter คืน 0 tweet จริงต่อเนื่อง → เสนอ disable/ลด
  cadence (แยก decision ให้ user; ห้ามตัด news flow มั่ว).
- ตัด news prefilter ที่คำนวณซ้ำใน node_news (observe-only) — verify เป็น instrumentation ล้วนก่อน.

---

## Milestones (เรียงตาม dependency + ความเสี่ยงต่ำ→สูง; verify ได้อิสระ)

- **M0 — ยืนยันข้อเท็จจริงเสี่ยงต่ำ** (ไม่แตะ path เทรด): grep log ยืนยัน twitter=0; ยืนยัน
  orphan .md 0 refs; ยืนยัน prefilter เป็น observe-only. Verify: หลักฐานชัดในแต่ละข้อ.
- **M1 — Architecture freeze**: architect เขียน `docs/ARCHITECTURE.md` — format บรรทัด auto
  (ตายตัว), field จาก NEWS_SENTIMENT/news_impact/calendar ที่ใช้, กติกา shift-detect +
  state-file schema, kill-switch. **แสดง user อนุมัติก่อน worker เริ่ม** (iron rule).
- **M2 — Thread 3 cleanup** (low-risk): ลบ orphan docs + ตัด prefilter ซ้ำ. Verify: pipeline
  รันปกติ, ไม่มี import พัง, token/cycle ไม่เพิ่ม.
- **M3 — Thread 1 enrichment**: update_regime.py เพิ่ม auto CATALYSTS + sentiment tilt.
  Verify: บล็อก MACRO_AUTO มีบรรทัดใหม่ถูก format; วัด token/cycle ที่ analyst จริง
  (before/after) ไม่พองเกินงบ; fail-soft เมื่อ AV/news_impact ว่าง.
- **M4 — Thread 2 shift-detector + ping** + cadence รายวัน. Verify: จำลอง fed/real-rate flip
  → state เปลี่ยน + ping ยิง; ไม่มี false-positive ในข้อมูลนิ่ง (debounce).
- **M5 — Audit**: auditor เทียบ vs ARCHITECTURE + วัด (ก) narrative งานมือลดจริง (มีบรรทัด auto
  แทน catalysts/sentiment) (ข) token/cycle ไม่พอง (ค) **พฤติกรรมเทรดไม่เปลี่ยน** —
  shadow/replay วันมี regime (CPI/NFP/FOMC) เทียบ bias ก่อน-หลัง.

---

## Risks

- **R1 (สูง) — เปลี่ยนพฤติกรรมเทรดโดยไม่ตั้งใจ:** narrative → analyst.bias → force ทิศเทรดได้
  เมื่อ NEWS_FIRST + conf≥55. บรรทัด auto ใหม่อาจเลื่อน bias. **บรรเทา:** auto line เป็น
  "ทิศ + เหตุผลสั้น" เชิงบริบท ไม่ใช่คำสั่ง; shadow ก่อนเปิด; kill-switch (ลบบล็อก = default).
- **R2 — token/cycle พอง:** Sonnet ทุก cycle ไม่มี cache. **บรรเทา:** จำกัด 1-2 บรรทัด, วัด
  before/after ผ่าน cost tracking; เกินงบ → ตัดทันที.
- **R3 — NEWS_SENTIMENT ทิศเพี้ยน/ล่ม/quota:** free 25/วัน. **บรรเทา:** fail-soft (ไม่มีข้อมูล
  → ไม่เขียนบรรทัดนั้น, ของเดิมอยู่ครบ); cross-check กับ news_impact; sanity ทิศก่อนเชื่อ.
- **R4 — ตัด twitter ผิด:** disable ทั้งที่ยังได้ tweet = เสีย signal. **บรรเทา:** ตัดสินจาก log
  จริงเท่านั้น, เสนอ user, ไม่ auto-remove.
- **R5 — regime-shift false positive:** ping บ่อย = กวน. **บรรเทา:** threshold + debounce +
  state persistence.
- **R6 — news_impact/sentiment ยังไม่ calibrate** (จาก cycle เดิม พบ AI overconfident):
  การ feed เข้า regime = ใช้สัญญาณที่ยัง validate ไม่เต็ม. **บรรเทา:** ใช้เป็น context ทิศ
  หยาบเท่านั้น (ไม่ใช่ magnitude/คำสั่ง), ติดป้ายที่มา, ยังไม่แตะ gate.

---

## Non-goals (cycle นี้ **จะไม่ทำ**)

- **ไม่** เปิด NEWS_GATE / เปลี่ยน gate logic ใน decision_maker (แยกเรื่อง; validate ไม่พอ).
- **ไม่** ตัด narrative แก่นทิ้ง (PHASE thesis + playbook ยังมาจากคน).
- **ไม่** แตะ live prompt `.json`, money management, `_run_gates`, SL/TP, confidence thresholds
  (iron rules).
- **ไม่** ทำให้ event_scenarios/macro_strip/cot กลายเป็น trigger เทรด (ยัง display-only).
- **ไม่** ส่งภาพ/วิดิโอ chart เข้า AI (ยืนยันแล้วว่าไม่มี — ไม่ใช่ประเด็น).

---

## Open Questions — ตอบแล้ว (user 2026-07-08)

1. **Thread 1 แหล่ง sentiment** → ✅ **ใช้ทั้งคู่ยืนยันกัน** (NEWS_SENTIMENT + news_impact) —
   เขียนบรรทัด auto เฉพาะตอน 2 แหล่งชี้ทิศเดียวกัน (กัน false signal).
2. **Thread 2 ช่องทาง ping** → ✅ **Dashboard flag** (zero setup, เห็นตอนเปิดดู).
3. **Thread 3 twitter** → ✅ **เช็ค log ก่อน** — ผล M0: twitter ALIVE → **ไม่แตะ**.
4. **ลำดับ** → ✅ **M0 + Thread 3 ก่อน** แล้ว 1→2.

## M0 Results (2026-07-08 — read-only verification)

⚠️ **verification พลิกสมมติฐาน dead-code เกือบทั้งหมด:**
- **twitter/Nitter = ALIVE** — `logs/system.log` 07-08: 75 tweets/cycle (@cnnbrk/@BBCBreaking/
  @ZeroHedge/@markets/@kun_purich ×15), กรองเหลือ 22/75 แตะปัจจัยทอง. **ไม่ disable.**
- **`trend_strategy.md`** = rulebook กลยุทธ์ 167 บรรทัด (คนเขียน, ref ใน QUICKREF) → dead-as-code
  แต่เป็นเอกสาร. **เก็บ.**
- **`news_gatherer.md`** = prompt spec 117 บรรทัด; `news_gatherer.py` (57 บรรทัด) **ไม่เรียก LLM**
  → prompt ไม่เคยถูกใช้จริง (orphaned design artifact) แต่ลบแล้วไม่ได้อะไร. **เก็บ.**
- **prefilter double-compute** (`trading_graph.py:138-142`) = M1 measurement observe-only,
  ไม่มี AI cost. ตัดแล้วเสีย metric. **เก็บ.**

**→ Thread 3 (de-cruft) แทบเป็นศูนย์** — ระบบเก่าไม่ตาย แค่ "ยังไม่ต่อเข้า analyst" = งานของ
Thread 1. งานจริงเหลือ Thread 1 (enrich) + Thread 2 (shift-detect+ping). ขั้นถัดไป = **M1
architect freeze (ARCHITECTURE.md)** รอ user อนุมัติ design ก่อน worker เริ่ม.
