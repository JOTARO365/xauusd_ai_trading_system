# DESIGN — Phase 2: algo-live (multi-strategy, per-tick, adaptive)

**status:** spec (flag-OFF ทั้งหมด). รวม directive owner 2026-07-19 หลัง REGIME_LIVE (Phase 1) ทำงาน.
**หลักที่ห้ามละเมิด (จากหลักฐานทั้ง session):** ไม่จูน param เข้า recent-score (overfitting); ทุกกลยุทธ์ใหม่ต้องผ่าน
gauntlet (OOS+null) ก่อน routing จริง; entry = deterministic จาก MT5 (0 LLM/MCP); LLM = SELECTION/sentiment เท่านั้น.

## สถานะ edge (ความจริง ณ ตอนนี้)
ไม่มี validated directional edge: H1 ตาย, H4 พัง OOS, D1 พัง null (artifact +0.14 baseline). momentum-in-TREND =
กลยุทธ์เดียวที่เหลือ (marginal). → live = lot จิ๋ว เก็บ data + หากลยุทธ์ใหม่ต่อ regime. **นี่คือเหตุผลของ Phase 2 ทั้งหมด.**

## ชิ้นงาน Phase 2

### 1. Multi-strategy registry ✅ (ทำแล้ว)
`scripts/regime_lib.py` STRATEGIES = {regime: strategy_fn}. แต่ละ strategy รับ context ครบ (เลือกเครื่องมือเองได้).
เพิ่มกลยุทธ์ต่อ regime = 1 บรรทัด — **แต่ต้องผ่าน gauntlet ก่อน**. RANGE/RISK-OFF/NEUTRAL = STAND-DOWN จนเจอตัวผ่าน.

### 2. Per-tick executor (fast loop) — ⚠️ live-money
เดิม executor รันต่อ cycle (bar-close ~5-15 นาที). เพิ่ม fast loop (คล้าย position_guardian):
- อ่าน **cache** ของ regime + Donchian level (คำนวณต่อ bar-close ครั้งเดียว) → ต่อ tick เช็คแค่ "ราคาทะลุ level?"
- ทะลุ → open_order ทันที (0.01, guards เดิม). ไม่เรียก LLM, ไม่ recompute indicator ต่อ tick (แค่เทียบราคา vs level)
- flag REGIME_LIVE_TICK (default OFF) + interval (เช่น 2-4s). kill = flag OFF. fail-soft.
- **ต่างจาก per-cycle แค่: เข้าเร็วขึ้นบน bar ที่ทะลุ** (signal เดิม) — ไม่ใช่กลยุทธ์ใหม่.

### 3. Algo-placed pending orders — ⚠️ live-money
ให้ algo วาง **STOP order ที่ Donchian level** ล่วงหน้า (แทนรอราคาทะลุแล้ว market): BUY_STOP ที่ N-bar high,
SELL_STOP ที่ N-bar low, SL/TP จาก ATR. ผ่าน `place_pending_order` เดิม (guards/expiry). flag-gated.
= "algo ทำ pending" ตามที่สั่ง. ยึด config (max_pending, expiry).

### 4. Sentiment → dashboard panel (display-only, 0 token)
LLM analyst sentiment (ข่าว X + ตัวเลขเศรษฐกิจ) ที่มีอยู่ → panel ใน dashboard (regime/bias/เหตุผล).
compute-in-code จาก output ที่มี ไม่เพิ่ม LLM call. = "sentiment ลง dashboard".

### 5. Weekly adaptive cycle — monitor + auto-disable + LLM-suggest (มีวินัย, owner-approved)
**cadence: ทุก 5 วันเทรด = 1 สัปดาห์ (จ-ศ), รันตอนตลาดปิด (เสาร์-อาทิตย์).** **ไม่จูน param.**
⚠️ ตัดสินใจจาก **หลายสัปดาห์สะสม** ไม่ใช่สัปดาห์เดียว (D1 = 5 แท่ง/สัปดาห์ = noise; ใช้ trend ข้ามสัปดาห์). แต่ละรอบ:
- (a) **score จริง** ต่อกลยุทธ์ จาก `logs/regime_live.jsonl` forward-labeled (intrabar+cost) → เทียบ null baseline
- (b) **auto-disable**: กลยุทธ์ที่ score decay ต่ำกว่าเกณฑ์ N วัน → ถอดออกจาก STRATEGIES อัตโนมัติ (kill switch) + log
- (c) **LLM วิเคราะห์ช่วงเศรษฐกิจ** → เสนอว่ากลยุทธ์ไหนเหมาะ regime/phase ไหน → **log เสนอ owner อนุมัติ** (ไม่ auto-enable)
- (d) re-fit param (ถ้าจะทำ) = OOS+null บน window ยาว, swap เฉพาะชนะ incumbent OOS — **ไม่ใช่ทุก 5 วันบน noise**
- feed score → dashboard Analytics panel (weekly, มีแล้ว)

## Safety invariants (ทุกชิ้น)
flag-OFF default · lot จิ๋ว · daily-cap/SL guard เดิม · owner คุม start · kill switch ต่อ flag · fail-soft ·
กลยุทธ์ใหม่ผ่าน gauntlet ก่อน · ไม่จูน-ตาม-noise · entry deterministic MT5-direct (0 LLM/MCP).

## ลำดับสร้าง (safe→risky)
4 (sentiment panel, safe) → 5 (adaptive monitor/score, analysis) → 3 (algo-pending) → 2 (per-tick).
เกี่ยว: `docs/DESIGN_regime_shadow.md` · `scripts/regime_lib.py` · `agents/regime_executor.py` · `scripts/regime_analytics.py`.
