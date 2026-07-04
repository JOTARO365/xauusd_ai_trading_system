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

- [DONE] **T-04** | agent: worker | scope: `scripts/report_burn.py` (new) + `dashboard/app.py` (`/api/burn`) + `dashboard/templates/index.html` (card) | deps: T-02 (แตะ app.py ต่อจาก T-02) |
      input: ARCHITECTURE §3.4, §3.6 |
      output: burn ฿/วัน เทียบเป้า 150–250฿ ขึ้นจอ
      acceptance: `/api/burn` คืน shape §3.4 จาก `agent_usage`; แสดงวันนี้ + N วันย้อนหลัง + สถานะ under/in/over; ไม่มี AI call.

- [DONE — deviation, ดู F-01] **T-05** | agent: worker | scope: `scripts/report_ride_cohort.py` (new) + `data/ride_cohort.json` | deps: T-01 |
      input: ARCHITECTURE §3.4, §3.6 |
      output: สรุป RIDE cohort (segment comment ขึ้นต้น `RIDE `) win/loss/pnl/n
      acceptance: อ่าน DB ผ่าน `db/reader.py`; นับเฉพาะไม้ tag RIDE; รายงานตัวเลขให้ user ตัดสิน knob (ไม่ตัดสินเอง, ไม่แตะ RIDE logic). *(ถ้าจะขึ้น card ใช้ endpoint pass-through data/—ตัดสินตอน impl; ถ้า card แตะ app.py ให้ dep T-04)*

- [DONE] **T-06** | agent: worker | scope: `scripts/score_trend_mode.py` (verify/extend) | deps: T-01 |
      input: PLAN M5 (n≥30 pre-registered), QUICKREF |
      output: สกอร์ trend-mode รายสัปดาห์ + D1 flip watch report
      acceptance: รายงานมี gate n≥30 (ไม่รายงานถ้า sample ไม่พอ); ไม่แก้ scoring logic เว้นแต่ n-guard ขาดหาย (ถ้าแก้ต้อง explain-before-acting).

- [DONE] **T-07** | agent: worker | scope: read-only verification (ไม่แก้ source) | deps: T-01 |
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

- [DONE] **T-08** | agent: worker | scope: `scripts/report_calibration.py` (new) + `dashboard/app.py` (`/api/calibration`) + `index.html` (view) + `data/calibration.json` | deps: T-02, T-04 |
      input: ARCHITECTURE §3.5, §3.6 |
      output: confidence calibration view (predicted conf bin → realized WR)
      acceptance: bin ตาม `technical_confidence`, realized WR/pnl ต่อ bin จาก DB; computed-in-code, **token burn รายวันไม่ขยับ**; ไฟล์หาย → endpoint คืน empty ไม่ 500 (§5 #6).

- [DONE] **T-09** | agent: worker | scope: `scripts/fetch_macro_strip.py` (new) + `dashboard/app.py` (`/api/macro-strip`) + `index.html` (strip) + `data/macro_strip.json` | deps: T-08 |
      input: ARCHITECTURE §3.5, §3.6, §5 #5 |
      output: macro strip DXY / 10Y / real yield
      acceptance: fetch ผ่าน **scheduled script + AlphaVantage REST** (ไม่ใช่ MCP, §5 #5), วันละครั้ง อยู่ในโควตา; endpoint serve `data/macro_strip.json`; burn รายวันไม่ขยับ; ไฟล์หาย → empty ไม่ 500.

- [DONE] **T-10** | agent: worker | scope: `scripts/fetch_cot.py` (new) + `dashboard/app.py` (`/api/cot`) + `index.html` (card) + `data/cot.json` | deps: T-09 |
      input: ARCHITECTURE §3.5, §3.6 |
      output: COT รายสัปดาห์ (non-commercial net positioning gold)
      acceptance: fetch จาก CFTC public data รายสัปดาห์ (scheduled); endpoint serve `data/cot.json`; ไม่แตะโควตา AlphaVantage; burn ไม่ขยับ; ไฟล์หาย → empty ไม่ 500.

Gate: auditor final — ทุก acceptance ผ่าน + burn รายวันไม่ขยับ → milestone ปิด

---

## Fix Tasks (filed by auditor — 2026-07-04 final audit)
<!-- - [ ] F-01 | root cause: ... | from AUDIT.md item #N | scope: ... -->

- [DONE 2026-07-04] **F-01** | agent: architect (amendment) + worker (docstring) | from AUDIT.md T-05 |
      root cause: ARCHITECTURE/T-05 สั่งอ่าน RIDE cohort "จาก DB ผ่าน db/reader.py" แต่ตาราง `trades`
      ไม่มีคอลัมน์ `comment` — tag RIDE อยู่ใน MT5 order comment เท่านั้น และ §4 ห้ามแก้ schema
      → spec เป็นไปไม่ได้ตามตัวอักษร; worker ใช้ MT5 deal history (ถูกทางเดียวที่ทำได้).
      งาน: (1) architect log §6 amendment: T-05 data source = MT5 deal history + ปลดคำว่า
      `/api/ride-cohort` ใน §1 (card ใช้ `/api/ride-stats` เดิม, shape §3.4 คงไว้ใน data/ride_cohort.json);
      (2) ลบ claim เท็จ "DB reader.py get_trades() is still called to cross-check" ใน
      `scripts/report_ride_cohort.py:16-17` (ไม่มี import db.reader จริง). scope: docs + docstring เท่านั้น.

- [DONE 2026-07-04] **F-02** | agent: worker | from AUDIT.md (process) |
      root cause: worker ของ Batch 2-4 อัปเดต TASKS.md + commit message แต่ข้ามกฎบังคับ
      continue.md (root CLAUDE.md Override #2 + หัว TASKS.md ข้อ ⚠️ แรก).
      งาน: backfill `.claude/context/continue.md` — 1 entry ต่อ batch (T-02/T-03, T-04..T-07,
      T-08..T-10) ตาม format ใน .claude/CLAUDE.md จาก commit 7cd9586 / 13d116e / 5d9a979 + AUDIT.md.
      scope: `.claude/context/continue.md` เท่านั้น.

- [DONE 2026-07-04] **F-03** | agent: worker | from AUDIT.md T-03 |
      root cause: log call ใหม่ใน `agents/reporter.py:57-60,69-72` ใช้ printf-style
      `logger.warning("... %s ...", path)` — loguru ใช้ `{}` format จึงพิมพ์ `%s` ตรงๆ และ path หาย
      (พิสูจน์จาก audit run). งาน: เปลี่ยนเป็น f-string 2 จุด — ห้ามแตะ logic guard/atomic.
      scope: `agents/reporter.py` (2 บรรทัด log เท่านั้น).

- [ ] **F-04** | agent: architect/user review (advisory — pre-existing, ไม่ใช่ผลงาน pipeline) |
      finding: `.env SYMBOL=GOLD#` ทำให้ bot เขียน `logs/gold#_trades.json`
      (`agents/reporter.py:15-17` — โค้ดเดิม) แต่ dashboard ใช้ `logs/trades.json` เสมอ
      (`dashboard/app.py:86-94`) → สองโปรเซสเขียนคนละไฟล์: MANUAL merge ของ dashboard กับ
      AI log ของ bot ไม่เห็นกัน; premise §2 ("ทั้งสองเขียนไฟล์เดียว") เป็นจริงเฉพาะ SYMBOL=XAUUSD.
      งาน: user/architect ตัดสินว่า split นี้ตั้งใจหรือไม่ ก่อน file งานแก้ใดๆ.

- [ ] **F-05** | agent: worker (advisory — pre-existing) |
      finding: `& $PY tests\test_all.py` ตามที่ ./CLAUDE.md ระบุ ล้มที่ `import config`
      (test_all.py ไม่มี sys.path bootstrap — ต้องตั้ง PYTHONPATH=repo root ถึงรันได้) และ
      `.gitignore:14` ignore ทั้ง `tests/` → suite + tests/test_db.py (ย้ายมาใน T-01) untracked.
      งาน: เลือกทาง (a) เพิ่ม bootstrap 2 บรรทัด + เลิก ignore tests/ หรือ (b) บันทึก PYTHONPATH
      requirement ลง ./CLAUDE.md. ต้องให้ user เลือกก่อนทำ (แตะ .gitignore = นโยบาย repo).
