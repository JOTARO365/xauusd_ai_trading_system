# DESIGN PROPOSAL — Discretion Cockpit (assisted-discretion execution)

> สถานะ: **DRAFT — รออนุมัติก่อน build**. ยังไม่แตะ code/live. (explain-before-acting, iron rule)
> วันที่: 2026-08-18 · ต่อจาก: UHAS mining (null บนทองแบบ mechanical) → ข้อสรุปว่า edge ทองของ user = ดุลยพินิจ+context

## 1. ทำอะไร / แก้ปัญหาอะไร
Backtest พิสูจน์แล้ว: ทองไม่มี **mechanical** entry edge (UHAS signal/feature = null, auditor ยืนยัน placebo).
แต่ **user เทรดทองได้กำไรด้วยดุลยพินิจ+context**. → อย่าแปลงดุลยพินิจเป็นกฎ (ล้มแล้ว) — ให้ **เอาดุลยพินิจ user เป็นคนเลือก
entry แล้วบอททำสิ่งที่บอทเก่ง: execution + risk วินัย ไม่มีอารมณ์**.

Cockpit = 3 ชั้น: (1) โชว์ context board รวมจุดเดียว → (2) user ตัดสิน BUY/SELL+จุด → (3) บอท execute + คุม risk กลไก.

**Invariant-compliant:** invariant "entry=คำนวณ ไม่ทำนาย" ห้าม **บอท**เดา entry. Cockpit = **มนุษย์**ตัดสิน entry (คนละเรื่อง);
บอทยังไม่เดาอะไร มันแค่ execute + บังคับ risk. ดุลยพินิจเลือก *อะไร/เมื่อไหร่* · บอทบังคับ *เสี่ยงเท่าไหร่*.

## 2. ทำงานยังไง (flow + ไฟล์)

```
[Context Board]           [Decision]            [Mechanical Execution + Risk]
bot_status.json  ─┐                              ┌─ structural_sl (D1/H4 wick PICK)
fair-value model ─┤─→ dashboard  ─→ user กด ─→  ┤─ risk guards (cap/margin/min-lot/LONG_ONLY_ALL)
zones/liq/vol/fib ┤   cockpit panel  BUY/SELL   ├─ open_order (มีอยู่แล้ว)
news/event/regime┘   (display-only)  +price/size └─ manage (BE/trail เหมือน MSE)
                                          │
                                    POST /api/cockpit/order (flag-gated + confirm)
```

**ชั้น 1 — Context Board (display-only, 0 token, 0 risk):** รวม context ที่บอท**คำนวณอยู่แล้ว**ต่อ symbol เป็น panel เดียว:
S/R zones+strength+recency (sr_meta), fair-value gap (โมเดล XAU~DXY/XAG ที่เพิ่ง build), liquidity pools, volume profile,
fib, regime, sentiment score, news/event countdown, vol-clock. เกือบทั้งหมดมีใน `bot_status.json` แล้ว → แค่ render รวม.

**ชั้น 2 — Decision Input:** ปุ่มบน dashboard ต่อ symbol: ทิศ (BUY/SELL), entry (market/limit price), size hint (optional),
note. = สัญญาณ "มนุษย์ตัดสิน" (แหล่ง entry ใหม่แหล่งเดียว).

**ชั้น 3 — Mechanical Execution + Risk (reuse ของเดิม, ไม่ reinvent money-mgmt):**
decision → ผ่าน **risk layer เดิมทุกตัว** → `open_order`. บอท manage ต่อ (BE/trailing/structural-SL) แบบ MSE.

## 3. ไฟล์ที่แตะ (scope)
**Phase 1 — Context Board (display-only, ZERO risk):**
- `dashboard/app.py`: +`GET /api/cockpit/<symbol>` = aggregate context จาก bot_status + fair-value calc (computed-in-code)
- `dashboard/templates/index.html`: +cockpit panel (render context board). **ไม่มี order path. 0 token. reversible.**

**Phase 2 — Manual Execution (LIVE order path, behind flag, ต้องอนุมัติแยก):**
- `config.py`: +`COCKPIT_LIVE` (default false) master flag + `.env.example`
- `dashboard/app.py`: +`POST /api/cockpit/order` → validate → risk layer → `open_order`
- `agents/cockpit_executor.py` (ใหม่): manual decision → structural-SL + guards + open_order + manage (pattern เดียวกับ `multi_symbol_executor`, own magic `MANUAL-<sym>`)
- `README.md`: document + kill switch (structural-change rule)

## 4. Reuse (ไม่แตะ money-mgmt iron rule)
- `connectors/mt5_connector.open_order(symbol=)` — margin/cap/min-lot guard มีในตัว
- structural-SL D1/H4 wick PICK (memory: farthest D1 > nearest H4) — บังคับทุกไม้
- `LONG_ONLY_ALL` — บล็อก SELL (ถ้ายังเปิด) แม้ user กด SELL → เตือน+บล็อก
- caps: MSE_MAX_POSITIONS/TOTAL, daily-loss, MAX_RISK_PCT
- management: pattern `multi_symbol_executor` (BE/trailing R/ATR self-contained)

## 5. Safety (live-order path = ระวังสูงสุด)
1. **`COCKPIT_LIVE=false` default** → Phase 2 ไม่ทำงานเลย (Phase 1 display ไม่มี order path อยู่แล้ว)
2. **per-order confirm** บน dashboard (เหมือนยืนยันซื้อของ) — ไม่ one-click วางจริง
3. **risk guard เดิมบังคับทุกตัว** — manual path bypass แค่ **DecisionMaker ENTRY logic** (เพราะมนุษย์ = entry decision)
   แต่ **ไม่ bypass RISK guard** (structural-SL/cap/LONG_ONLY_ALL/margin). ⚠️ = order path ใหม่ → ต้องอนุมัติชัด
4. reversible: `COCKPIT_LIVE=false` = ปิดทันที · Claude ไม่กดวางเอง (user กดเท่านั้น; Claude ห้ามวาง/ปิด order)

## 6. Token / cost
Context Board = **computed-in-code 0 token** (render ของที่มีอยู่ + fair-value เลขคณิต). ไม่มี AI call เพิ่ม.
(ออปชันเสริมทีหลัง: ปุ่ม "สรุป context ด้วย AI" 1 call/กด — opt-in, ไม่ default)

## 7. ทางเลือกที่พิจารณา
- **B (approval gate):** บอทเสนอ candidate, user approve. ดีแต่ผูกกับ algo signal (ทองไม่มี candidate ดีให้ approve). Cockpit
  อิสระกว่า (user เริ่ม entry เอง) → เหมาะกับทองที่ algo ไม่มี edge
- **D (log manual → ML):** ทำ**คู่ขนาน**ได้ (Cockpit log ทุก decision + context ณ ตอนเข้า → เป็น dataset ให้ D อัตโนมัติ)
- **A (context filter):** มีแล้ว, อ่อนบนทอง

## 8. Phased build (ขออนุมัติทีละ phase)
- **Phase 1 (display-only, 0 risk):** context board panel. build ได้เลยถ้าอนุมัติ — ไม่มี order path, reversible, 0 token
- **Phase 2 (manual live execution):** order path หลัง `COCKPIT_LIVE` — **อนุมัติแยกต่างหาก** (live money)
- **Phase 3 (optional):** log decision+context → dataset สำหรับ D (learn ดุลยพินิจทีหลัง)

## 9. คำถามค้าง (ก่อน build)
1. เริ่ม **Phase 1 (display-only)** ก่อนใช่ไหม? (0 risk, ได้ context board ให้ลองใช้จริง)
2. Phase 2 execution — symbol ไหนก่อน (ทอง? หรือทดสอบ BTC/WTI demo ก่อน)?
3. LONG_ONLY_ALL — cockpit เคารพต่อ (บล็อก SELL) หรือ manual override ได้? (แนะนำ: เคารพก่อน, ปลดทีหลัง)
