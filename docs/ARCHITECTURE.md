# ARCHITECTURE — Stabilize & Complete: XAUUSD AI Trading System

> Written by: architect · Reads: PLAN.md (APPROVED, M2/M3 deferred) · Last updated: 2026-07-04
> Interfaces frozen: YES (2026-07-04)
> Scope นี้ครอบเฉพาะ **M1, M4, M5, M6** — M2 (security) / M3 (alerting) DEFERRED, ไม่ออกแบบ
> หลักการ: งาน stabilization ไม่ใช่ rebuild — เติมเฉพาะ gap, ไม่แตะ gate/agent/money logic

---

## §1 File Structure

| File | Responsibility | New/Changed |
|------|----------------|-------------|
| *(git ops only)* | M1 — commit working tree + cleanup, ไม่แก้ source | — (M1) |
| `dashboard/app.py` | M4: (a) `api_close_position` เลือก `type_filling` ให้ตรงโหมด broker + retry; (b) atomic write ฝั่ง dashboard (sync-merge trades.json); (c) `api_accounting` เพิ่ม TTL cache. M5/M6: endpoint ใหม่ `/api/burn`, `/api/ride-cohort`, `/api/calibration`, `/api/macro-strip`, `/api/cot` (display-only, อ่าน DB/ไฟล์ที่ script คำนวณไว้) | Changed |
| `agents/reporter.py` | M4: `_save_log` เขียนแบบ atomic (temp + `os.replace`); `_load_log` decode-error ต้องไม่ทำให้เกิด save ทับข้อมูลเดิม | Changed |
| `dashboard/templates/index.html` | M5/M6: card/strip แสดงผลของ endpoint ใหม่ (burn vs target, RIDE cohort, calibration, macro strip, COT). Front-end only, ไม่แตะ chart/zone เดิม | Changed |
| `scripts/report_burn.py` | M5: คำนวณ ฿/วัน จาก `agent_usage` เทียบเป้า 150–250฿ → เขียน `data/burn_daily.json` | New |
| `scripts/report_ride_cohort.py` | M5: segment trades ที่ comment ขึ้นต้น `RIDE ` จาก DB → win/loss/pnl/n → `data/ride_cohort.json` | New |
| `scripts/report_calibration.py` | M6: bin trades ตาม `technical_confidence` → realized WR ต่อ bin → `data/calibration.json` (computed-in-code, ไม่มี AI call) | New |
| `scripts/fetch_macro_strip.py` | M6: ดึง DXY-proxy / 10Y / real yield จาก AlphaVantage REST (pattern เดียวกับ `scripts/update_regime.py`) วันละครั้ง → `data/macro_strip.json` | New |
| `scripts/fetch_cot.py` | M6: ดึง COT รายสัปดาห์จาก CFTC public data (Socrata) → `data/cot.json` | New |
| `data/burn_daily.json` `data/ride_cohort.json` `data/calibration.json` `data/macro_strip.json` `data/cot.json` | display cache — เขียนโดย script (scheduled), อ่านโดย endpoint | New |
| `scripts/score_trend_mode.py` | M5: มีอยู่แล้ว — reuse; ยืนยัน gate n≥30 ก่อนรายงาน (ไม่แก้ logic เว้นแต่ n-guard ขาด) | Existing/verify |

> ไม่มีไฟล์ใน `agents/` (นอกจาก `reporter.py` ซึ่งเป็น logging layer ไม่ใช่ decision logic), `agents/prompts/*`, `config.py`, หรือ `db/writer.py|reader.py` schema อยู่ในขอบเขตแก้ไข logic. M6 อ่าน DB ผ่าน `db/reader.py` ที่มีอยู่เท่านั้น.

---

## §2 Data Flow

**M4 — atomic trades.json (แก้ race สอง process เขียนไฟล์เดียว)**
```
bot process (main.py → agents/reporter.py):  _load_log() ─► modify ─► _save_log()
dashboard process (dashboard/app.py sync):    read trades.json ─► merge MANUAL ─► write
                         ▲ ทั้งสองเขียน logs/trades.json ไม่ atomic = torn read/lost update
แก้: ทุก write = เขียน logs/trades.json.tmp แล้ว os.replace() (atomic บน NTFS, same-dir)
     ทุก read ที่ JSONDecodeError = คืน sentinel และ **ห้าม** เขียนทับ (กัน reset เป็น log ว่าง)
```

**M4 — /api/close (broker filling mode)**
```
POST /api/close {ticket}
  → mt5.positions_get(ticket) → symbol_info(symbol).filling_mode (bitmask)
  → เลือก type_filling: IOC ถ้ารองรับ, ไม่งั้น FOK, ไม่งั้น RETURN
  → order_send(...)  ── ถ้า retcode == 10030 (INVALID_FILL) → retry โหมดถัดไป
  → response shape เดิม {ok, ticket, closed_pnl}  (FROZEN — ไม่เปลี่ยน)
```

**M4 — /api/accounting cache**
```
GET /api/accounting?system&account
  → key=(system,account); ถ้า cache สด (< TTL) คืนทันที
  → ไม่งั้น get_accounting() recompute → เก็บ (value, timestamp) → คืน
  TTL = ACCOUNTING_CACHE_TTL_SEC (default 60). response shape เดิม (FROZEN)
```

**M5/M6 — display-only (ไม่มี recurring AI call)**
```
scheduled script (นอก bot loop) ─► คำนวณ/ดึงข้อมูล ─► เขียน data/*.json
dashboard endpoint ─► อ่าน data/*.json (หรือ DB ผ่าน db/reader) ─► jsonify
index.html (fetch ทุก N วินาที เหมือน card อื่น) ─► render
```
external fetch (macro/COT) อยู่ใน scheduled script เท่านั้น → **token/AI burn ไม่ขยับ**; endpoint แค่ serve ไฟล์.

---

## §3 API Contracts (FROZEN)

การเปลี่ยนสิ่งใดในหัวข้อนี้ต้องเปิด architect pass ใหม่ + log ใน §6.

### 3.1 `POST /api/close` — response **ไม่เปลี่ยน** (การแก้เป็น internal เท่านั้น)
```
200 {"ok": true,  "ticket": <int>, "closed_pnl": <float>}
4xx/5xx {"ok": false, "error": "<str>"}
```
FROZEN rule: filling mode เลือกจาก `mt5.symbol_info(symbol).filling_mode` (bitmask: bit0=FOK, bit1=IOC); retry บน `retcode == 10030`. ห้ามเปลี่ยน request body หรือ response keys.

### 3.2 Atomic JSON I/O contract — `logs/trades.json` (ทั้ง reporter.py และ dashboard/app.py)
```
WRITE(data): fd = open("logs/trades.json.tmp","w",utf-8); json.dump; flush+fsync; close
             os.replace("logs/trades.json.tmp","logs/trades.json")   # atomic, same dir
READ():      on JSONDecodeError/ValueError → return sentinel _EMPTY
             caller ที่ได้ _EMPTY เพราะ decode error ต้อง **ไม่** เรียก WRITE ทับในรอบนั้น
```
Schema ของ trades.json **ไม่เปลี่ยน** (trades[] + summary{}). แต่ละไฟล์ implement helper ของตัวเอง (semantics ตรงตามนี้) — ไม่สร้าง shared module import (ดู §5 #4).

### 3.3 `GET /api/accounting` — response **ไม่เปลี่ยน**, เพิ่ม cache layer โปร่งใส
key = `(system, account)`; TTL = `os.getenv("ACCOUNTING_CACHE_TTL_SEC") or 60`. response keys เดิมทั้งหมด (`summary, agents, today, daily, ok, system, source`).

### 3.4 M5 endpoints (ใหม่ — display-only)
```
GET /api/burn        → {"ok":true, "target_min":150, "target_max":250,
                        "days":[{"date":"YYYY-MM-DD","thb":<float>,"vs_target":"under|in|over"}],
                        "today_thb":<float>}
GET /api/ride-cohort → {"ok":true, "n":<int>, "win":<int>, "loss":<int>,
                        "wr":<float>, "pnl":<float>, "open":<int>, "trades":[...]}
```
(trend-mode weekly score = artifact จาก `scripts/score_trend_mode.py`, ไม่ต้องมี endpoint ใหม่ถ้าแสดงเป็นตัวเลขในรายงาน; ถ้าต้องขึ้นจอ ใช้ card อ่าน `data/`—ตัดสินตอน M5 impl.)

### 3.5 M6 endpoints (ใหม่ — display-only)
```
GET /api/calibration → {"ok":true, "bins":[{"conf_lo":60,"conf_hi":64,"n":<int>,
                        "wr":<float>,"pnl":<float>}], "updated":"<iso>"}
GET /api/macro-strip → {"ok":true, "dxy":{"val":<float>,"chg":<float>},
                        "y10":{"val":<float>,"chg":<float>},
                        "real_yield":{"val":<float>,"chg":<float>}, "updated":"<iso>"}
GET /api/cot         → {"ok":true, "report_date":"YYYY-MM-DD",
                        "noncomm_long":<int>,"noncomm_short":<int>,"net":<int>,
                        "net_chg":<int>, "updated":"<iso>"}
```
ทุก endpoint: ถ้าไฟล์ `data/*.json` หาย → `{"ok":true, ...empty...}` (ไม่ 500 — display-only ต้องไม่ทำหน้าจอพัง).

### 3.6 Data file schemas (FROZEN) — เขียนโดย script, อ่านโดย endpoint
`data/burn_daily.json`, `data/ride_cohort.json`, `data/calibration.json`, `data/macro_strip.json`, `data/cot.json` มี shape ตรงกับ payload ของ endpoint คู่กัน (§3.4–3.5) เพื่อให้ endpoint แค่ pass-through.

---

## §4 Dependencies

- **stdlib เท่านั้น** สำหรับ M4 atomic write (`os.replace`, `tempfile`/manual temp) — ไม่เพิ่ม lib
- **MetaTrader5** (มีอยู่) — `symbol_info().filling_mode`, `ORDER_FILLING_*`, retcode `10030`
- **Flask** (มีอยู่) — endpoint ใหม่
- **AlphaVantage REST** (มีอยู่ใน `scripts/update_regime.py`, key เดียวกัน, free 25 req/วัน) — M6 macro strip. ดึงวันละครั้งผ่าน scheduled script → อยู่ในโควตา
- **CFTC public data (Socrata `publicreporting.cftc.gov`)** — M6 COT, ฟรี, รายสัปดาห์ (ศุกร์). แหล่งใหม่, ไม่แตะโควตา AlphaVantage
- **db/reader.py** (มีอยู่) — M5/M6 อ่าน trades/agent_usage; **ห้ามแก้ schema**
- ไม่มี dependency ใหม่ที่ก่อ recurring AI/token cost (first-class constraint จาก PLAN)

---

## §5 Decisions & Rationale

| # | Decision | Rationale | Alternatives considered |
|---|----------|-----------|-------------------------|
| 1 | M4 trades.json ใช้ **temp + `os.replace`** (atomic rename) ไม่ใช่ file lock | `os.replace` atomic บน NTFS same-dir → reader ไม่มีวันเห็นไฟล์ครึ่งเขียน; ไม่ต้องเพิ่ม lib, ไม่มี lock ค้างถ้า process ตาย | `portalocker`/`msvcrt` lock — เพิ่ม dependency + เสี่ยง lock ค้างเมื่อ bot ถูก kill (เกิดจริง 07-03); ปฏิเสธ |
| 2 | reader ที่เจอ JSONDecodeError ต้อง **ไม่เขียนทับ** ในรอบนั้น | บั๊กที่แท้จริง: reporter `_load_log` decode fail → คืน log ว่าง → `_save_log` เขียนทับ = ประวัติหาย. atomic write กัน torn read เกือบหมด แต่กฎนี้เป็น safety net ชั้นสอง | แค่ทำ atomic write อย่างเดียว — ยังเสี่ยงถ้า decode fail จากเหตุอื่น; ปฏิเสธ |
| 3 | 3 การแก้ dashboard (close/atomic/cache) รวมเป็น **งานเดียว** (T-02) เพราะแตะ `dashboard/app.py` ไฟล์เดียว | เลี่ยง merge conflict ของ worker หลายตัวบนไฟล์เดียว; แต่ละ fix เล็กและ isolated เป็นคนละ endpoint | แยก 3 งาน parallel — ชนไฟล์เดียวกัน, unsafe ตาม template "no shared file writes"; ปฏิเสธ |
| 4 | atomic helper **local ในแต่ละไฟล์** (reporter.py + app.py) ไม่ทำ shared util | เลี่ยงสร้าง import dependency ข้าม module + ordering dep ระหว่าง 2 งาน; semantics ล็อกที่ §3.2 ให้เหมือนกัน โค้ดไม่กี่บรรทัด | shared `utils/atomic_json.py` — เพิ่มไฟล์ + ทำให้ T-02/T-03 ต้อง sequential; ปฏิเสธเพื่อคง parallelism |
| 5 | M6 fetch ใช้ **scheduled script + AlphaVantage REST** (ไม่ใช่ MCP) | runtime (bot/dashboard) เรียก MCP tool ไม่ได้ — MCP มีเฉพาะใน agent context. `scripts/update_regime.py` พิสูจน์แล้วว่า REST + key + cron (`run_update_regime.ps1`) ทำงานได้ และ endpoint แค่ serve ไฟล์ = token burn ไม่ขยับ (ดู flag ท้ายไฟล์) | ให้ endpoint ยิง API ตอน request — เปลือง quota + ช้า + ผูก uptime กับ AlphaVantage; ปฏิเสธ |
| 6 | M6 endpoint เมื่อไฟล์หาย → คืน `ok:true` payload ว่าง ไม่ 500 | display-only ต้องไม่ทำ dashboard พัง; ข้อมูลขาดหายเป็นภาวะปกติ (script ยังไม่รัน/rate-limited) | throw 500 — ทำ card เดียวล้มทั้งหน้า; ปฏิเสธ |
| 7 | M6 endpoint ทั้งสามเดินเป็น **sequential batch** ไม่ parallel | ทั้งสามเติมลง `dashboard/app.py` + `index.html` ไฟล์ร่วม → parallel = conflict. ลำดับให้ user เลือก (§ ท้าย TASKS) | parallel 3 worker — ชนสองไฟล์; ปฏิเสธ |
| 8 | M4 ทดสอบระดับ demo/simulation เท่านั้น; acceptance เทียบ baseline run | PLAN Open-Q: ห้ามแตะไม้จริง; และ `tests/test_all.py` time-of-day dependent → เทียบ baseline (git stash) ไม่ assume 0 fail (root CLAUDE.md) | รัน 1 ครั้งคาด 0 fail — false alarm จาก session gate; ปฏิเสธ |

---

## §5b PLAN Assumptions Contradicted by Code / Amendment (flags for user)

1. **PLAN Risks/Milestone body ยังอ้าง M2/M3 ที่ถูก DEFER** — ตาราง Risks บอก "M3 ทำก่อนฟีเจอร์ใดๆ; heartbeat เป็น alert ตัวแรก" และ "M2 เป็นงานแรกหลังเก็บ tree" ขัดกับ amendment 2026-07-04 (M2/M3 deferred). เป็นความไม่สอดคล้องภายใน PLAN.md — ไม่ใช่ scope ที่ architect เปลี่ยนได้ → flag ให้ planner/user ปรับถ้อยคำ. ผมออกแบบตาม **amendment** (ไม่ทำ M2/M3).
2. **ความเสี่ยง "บอทหยุดเงียบ" ไม่มี mitigation เชิงระบบ** เพราะ M3 deferred; PLAN ยอมรับว่าใช้ "เช็ค dashboard ด้วยตา" แทน. บันทึกว่าเป็นความเสี่ยงที่คงค้างโดยรู้ตัว — ไม่มีงานใน 4 milestone นี้ที่ปิดมัน.
3. **AlphaVantage "MCP" ใช้ที่ runtime ไม่ได้** — PLAN พูดถึง MCP quota 25/วัน แต่ bot/dashboard/script เรียก MCP tool ไม่ได้ (MCP = agent-context เท่านั้น). M6 จึงใช้ REST key เดิม (โควตาเดียวกัน) ผ่าน scheduled script. ไม่กระทบเป้าหมาย แต่กระทบวิธี implement → ต้องแจ้ง worker (สะท้อนใน §5 #5).

---

## §6 Interface Change Log

| Date | Change | Reason | Affected tasks |
|------|--------|--------|----------------|
| 2026-07-04 | Initial freeze (§3.1–3.6) | architect pass แรก | ทั้งหมด |
