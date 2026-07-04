# TASKS — Stabilize & Complete: XAUUSD AI Trading System

> Written by: architect · Status updates by: workers/auditor
> Status legend: [ ] todo · [WIP] in progress · [DONE] complete · [BLOCKED: reason]
> Reads: ARCHITECTURE.md (interfaces FROZEN 2026-07-04). ห้าม worker แก้ไฟล์นอก scope ของตน.
> ⚠️ ทุกงานต้อง log ลง `.claude/context/continue.md` (root CLAUDE.md Override #2) นอกเหนือจาก mark สถานะที่นี่.
> ⚠️ ห้ามแตะ gate logic / confidence thresholds / money management / anti-fade guards / `agents/prompts/*.json`.
> ⚠️ ห้าม start/stop bot หรือปิดไม้จริง — test = demo/simulation เท่านั้น. `$PY = C:\Users\pornnatcha\AppData\Local\Microsoft\WindowsApps\python.exe`.

---

## Batch 1 — sequential (M1 ก่อนทุกอย่าง)

- [DONE] **T-01** | agent: worker | scope: git ops + ลบ/ย้ายไฟล์ที่ระบุ (ไม่แก้ source) | deps: — |
      input: PLAN Open-Q (commit policy = "commit เลย + เก็บกวาด") |
      output: working tree สะอาด, งานค้างเข้า commit
      งาน: (1) commit dashboard feature set ที่ค้าง (`agents/chart_watcher.py`, `dashboard/templates/index.html`, `main.py`) + pipeline docs (`docs/*.md`, root `CLAUDE.md`) — commit as-is ไม่แก้เนื้อ; (2) **ลบ** `azure-signup.png`, `gcp-signin.png` (screenshot สมัคร cloud); (3) `db/test_db.py` — ย้ายเข้า `tests/` หรือลบถ้าเป็น throwaway (worker ถาม/ตัดสินตามเนื้อไฟล์); (4) `scripts/analyze_losses.py`, `scripts/auto_resume_claude.ps1`, `scripts/delete_bad_pending.py` อยู่ใน `scripts/` แล้ว → commit; (5) ยืนยันว่า process ที่รันอยู่เป็นโค้ดล่าสุด — **user เป็นคน restart** (worker ห้าม restart), แค่รายงานว่าต้อง restart อะไรบ้าง.
      acceptance: `git status --short` ว่าง (ไม่มี `??`/`M` ที่ไม่ได้ตั้งใจ ignore); commit message อธิบายชุดงาน; ไม่มีการแก้ `.py` source ใน commit นี้นอกจากที่ค้างอยู่แล้ว.

Gate: auditor ยืนยัน tree สะอาด → เริ่ม Batch 2

---

## Batch 2 — parallel (M4 audit fixes B/C — สองงานคนละไฟล์/process)

- [DONE] **T-02** | agent: worker | scope: `dashboard/app.py` **เท่านั้น** | deps: T-01 | (demo-close verify: DEFERRED to user — logic mock-tested)
      input: ARCHITECTURE §3.1, §3.2 (ฝั่ง dashboard), §3.3 |
      output: 3 fix ใน dashboard/app.py (รวมเป็นงานเดียวเพราะไฟล์เดียว — §5 #3)
      งาน: (a) `api_close_position` เลือก `type_filling` จาก `symbol_info().filling_mode` bitmask + retry บน retcode 10030 (§3.1) — **response shape เดิม**; (b) การเขียน `logs/trades.json` ในฟังก์ชัน MT5-sync (บรรทัด ~314) เปลี่ยนเป็น temp+`os.replace`, และ read ที่ decode fail ห้ามเขียนทับ (§3.2); (c) `api_accounting` เพิ่ม in-memory TTL cache keyed (system,account), TTL=`ACCOUNTING_CACHE_TTL_SEC` default 60 (§3.3) — **response shape เดิม**.
      acceptance: ปิดไม้บน **demo** สำเร็จกับ broker (retcode DONE) — ผู้ทดสอบ/ผู้ใช้ยืนยัน; `/api/accounting` เรียกซ้ำเร็วขึ้น (cache hit) และ payload keys ไม่เปลี่ยน; `& $PY tests\test_all.py` ไม่มี fail ใหม่ **เทียบ baseline** (git stash) — ไม่ assume 0 fail (§5 #8).

- [DONE] **T-03** | agent: worker | scope: `agents/reporter.py` **เท่านั้น** | deps: T-01 |
      input: ARCHITECTURE §3.2 |
      output: atomic write + decode-safe read ฝั่ง bot
      งาน: `_save_log` เขียน `logs/trades.json.tmp` แล้ว `os.replace` (§3.2); `_load_log` decode fail คืน `_empty` sentinel และ caller ต้องไม่เข้าเส้นทางที่ `_save_log` ทับ log เดิมในรอบนั้น. helper local — ไม่สร้าง shared module (§5 #4). **ห้ามแตะ decision/gate logic ในไฟล์นี้** (แตะเฉพาะ `_save_log`/`_load_log`/จุดเรียก).
      acceptance: unit/integration: เขียนพร้อมอ่านไม่เกิด torn read; จำลอง trades.json เสีย (ตัดกลางไฟล์) แล้ว `_load_log`→`_save_log` **ไม่** ทำให้ประวัติหาย; `& $PY tests\test_all.py` ไม่มี fail ใหม่เทียบ baseline.

Gate: auditor integration check (ปิดไม้ demo OK, ไม่มี trades.json corruption ซ้ำ, cache ทำงาน) → เริ่ม Batch 3

---

## Batch 3 — parallel (M5 measurement checkpoints — คนละ script/endpoint)

- [ ] **T-04** | agent: worker | scope: `scripts/report_burn.py` (new) + `dashboard/app.py` (`/api/burn`) + `dashboard/templates/index.html` (card) | deps: T-02 (แตะ app.py ต่อจาก T-02) |
      input: ARCHITECTURE §3.4, §3.6 |
      output: burn ฿/วัน เทียบเป้า 150–250฿ ขึ้นจอ
      acceptance: `/api/burn` คืน shape §3.4 จาก `agent_usage`; แสดงวันนี้ + N วันย้อนหลัง + สถานะ under/in/over; ไม่มี AI call.

- [ ] **T-05** | agent: worker | scope: `scripts/report_ride_cohort.py` (new) + `data/ride_cohort.json` | deps: T-01 |
      input: ARCHITECTURE §3.4, §3.6 |
      output: สรุป RIDE cohort (segment comment ขึ้นต้น `RIDE `) win/loss/pnl/n
      acceptance: อ่าน DB ผ่าน `db/reader.py`; นับเฉพาะไม้ tag RIDE; รายงานตัวเลขให้ user ตัดสิน knob (ไม่ตัดสินเอง, ไม่แตะ RIDE logic). *(ถ้าจะขึ้น card ใช้ endpoint pass-through data/—ตัดสินตอน impl; ถ้า card แตะ app.py ให้ dep T-04)*

- [ ] **T-06** | agent: worker | scope: `scripts/score_trend_mode.py` (verify/extend) | deps: T-01 |
      input: PLAN M5 (n≥30 pre-registered), QUICKREF |
      output: สกอร์ trend-mode รายสัปดาห์ + D1 flip watch report
      acceptance: รายงานมี gate n≥30 (ไม่รายงานถ้า sample ไม่พอ); ไม่แก้ scoring logic เว้นแต่ n-guard ขาดหาย (ถ้าแก้ต้อง explain-before-acting).

- [ ] **T-07** | agent: worker | scope: read-only verification (ไม่แก้ source) | deps: T-01 |
      input: PLAN M5 (CPI 07-14 readiness, ก่อน 07-12) |
      output: checklist ยืนยัน Event Radar + prior แสดงบนจอจริงก่อน CPI
      acceptance: รายงาน pass/fail ว่า dashboard แสดง event radar + prior 1 บรรทัดสำหรับ CPI; ถ้า fail → file เป็น fix task (ไม่แก้เองใน T-07).

Gate: auditor รวบ M5 reports → เริ่ม Batch 4

---

## Batch 4 — sequential (M6 analysis features — แชร์ `dashboard/app.py` + `index.html` จึงห้าม parallel, §5 #7)

> **ลำดับที่ architect เสนอ (user เลือกตอน approve):**
> 1. **T-08 calibration ก่อน** — pure computed-in-code, ไม่มี external dep/quota risk, ใช้ได้ทันทีเพื่อดู confidence-band สำหรับงานเฝ้าผล M5 (RIDE/threshold).
> 2. **T-09 macro strip** — reuse pattern `update_regime.py` ที่พิสูจน์แล้ว, effort ต่ำ, คุณค่ารายวันสูง.
> 3. **T-10 COT ท้ายสุด** — แหล่งใหม่ (CFTC), รายสัปดาห์, integration risk สูงสุด → ทำหลังของที่ชัวร์.

- [ ] **T-08** | agent: worker | scope: `scripts/report_calibration.py` (new) + `dashboard/app.py` (`/api/calibration`) + `index.html` (view) + `data/calibration.json` | deps: T-02, T-04 |
      input: ARCHITECTURE §3.5, §3.6 |
      output: confidence calibration view (predicted conf bin → realized WR)
      acceptance: bin ตาม `technical_confidence`, realized WR/pnl ต่อ bin จาก DB; computed-in-code, **token burn รายวันไม่ขยับ**; ไฟล์หาย → endpoint คืน empty ไม่ 500 (§5 #6).

- [ ] **T-09** | agent: worker | scope: `scripts/fetch_macro_strip.py` (new) + `dashboard/app.py` (`/api/macro-strip`) + `index.html` (strip) + `data/macro_strip.json` | deps: T-08 |
      input: ARCHITECTURE §3.5, §3.6, §5 #5 |
      output: macro strip DXY / 10Y / real yield
      acceptance: fetch ผ่าน **scheduled script + AlphaVantage REST** (ไม่ใช่ MCP, §5 #5), วันละครั้ง อยู่ในโควตา; endpoint serve `data/macro_strip.json`; burn รายวันไม่ขยับ; ไฟล์หาย → empty ไม่ 500.

- [ ] **T-10** | agent: worker | scope: `scripts/fetch_cot.py` (new) + `dashboard/app.py` (`/api/cot`) + `index.html` (card) + `data/cot.json` | deps: T-09 |
      input: ARCHITECTURE §3.5, §3.6 |
      output: COT รายสัปดาห์ (non-commercial net positioning gold)
      acceptance: fetch จาก CFTC public data รายสัปดาห์ (scheduled); endpoint serve `data/cot.json`; ไม่แตะโควตา AlphaVantage; burn ไม่ขยับ; ไฟล์หาย → empty ไม่ 500.

Gate: auditor final — ทุก acceptance ผ่าน + burn รายวันไม่ขยับ → milestone ปิด

---

## Fix Tasks (filed by auditor)
<!-- - [ ] F-01 | root cause: ... | from AUDIT.md item #N | scope: ... -->
