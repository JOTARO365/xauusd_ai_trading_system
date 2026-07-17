# ROADMAP — ยกเครื่องการเข้า/ออก order เป็น quant (phased migration)

**สถานะ:** แผน — Phase 0 done (shadow logging live), Phase 1+ รอ data + อนุมัติทีละ phase.
**หลักการ:** distilled จาก skill `quant-systematic-trading` (deep research: López de Prado/Bailey/Chan).
**กฎ:** ไม่ rewrite ทีเดียว — **แทน "การเดา" ทีละชั้นด้วย "calibrated + fitted + validated"** แต่ละ phase
flag-OFF → fit → ผ่าน `docs/VALIDATION_CHECKLIST.md` → shadow → enable. LIVE-money = ทุก gate/money change ต้องอนุมัติ.

---

## ปัจจุบัน → เป้าหมาย

```
ตอนนี้ (LLM เดา + heuristic guard):
  ChartWatcher(LLM: signal+confidence) → Analyst/Advisor → DecisionMaker(LLM)
    → _run_gates (threshold เลือกมือ: counter_spike 500p, floor 62, ...) → order (fixed lot, fixed TP)

เป้า (EV-driven quant):
  Features(F1-F7) → Regime classifier → algorithms ที่เข้าเงื่อนไข
    → per-algorithm P(win) [CALIBRATED] → EV = P·R − (1−P) → เลือก max-EV หรือ STAND-DOWN
    → deterministic entry/SL/TP → size(calibrated P) → safety gates เดิม → order
    → exit: MFE-percentile TP + edge-decay
```

**การเปลี่ยนหลัก:** แทน LLM confidence (uncalibrated) + gate threshold (เดา) ด้วย **calibrated P(win) → EV**,
ห่อด้วย **algorithm-selector**, ทุกอย่าง **fit จาก data + validate** ก่อนใช้.

---

## Phases (เรียงตาม dependency — ห้ามสลับ)

### Phase 0 — Data collection (shadow) ✅ DONE
- `agents/decision_snapshot.py` (P1b) → `logs/decision_snapshots.jsonl`: F1-F7 + outcome ทุก decision
- `agents/trade_excursion.py` (P1c) → `logs/trade_excursions.jsonl`: MFE/MAE ต่อ open position
- `scripts/build_entry_dataset.py` — offline labeler
- **enabler ของทุก phase** — ไม่มี data = fit ไม่ได้. **ต้องรันบอทสะสม (ตอนนี้ ~9 snapshots, ต้องหลักร้อย).**

### Phase 1 — Calibration layer 🎯 ทำก่อน (unlock EV + Kelly)
- **ทำอะไร:** fit `P(win)` จาก decision_snapshots (Platt/isotonic) — แทน/เสริม LLM confidence ที่ overconfident (ECE 0.45)
- **code:** + module `agents/calibrator.py` (fit offline, load weights); decision_maker อ่าน P (ไม่แตะ gate ยังแค่คำนวณ+log)
- **ต้องมีก่อน:** P1b พอ (~100+ labeled, min-N)
- **validate:** reliability diagram ±0.1; Brier ดีขึ้น
- **risk:** ต่ำ (แค่คำนวณ P + log เทียบ conf เดิม — ยังไม่ตัดสินใจด้วย P)

### Phase 2 — EV-gate
- **ทำอะไร:** เปลี่ยน `conf ≥ MIN_TECHNICAL_CONFIDENCE(62)` → `P(win) ≥ 1/(1+R)` (EV ≥ 0, RR2 = P≥33%)
- **code:** `decision_maker.py` gate 6 (min-conf floor)
- **ต้องมีก่อน:** **Phase 1** (ต้องมี P calibrated ก่อน)
- **validate:** replay net-R ชนะ floor เดิม + ไม่เพิ่ม tail (VALIDATION_CHECKLIST)
- **risk:** gate change → อนุมัติ + replay + shadow

### Phase 3 — Algorithm-selector
- **ทำอะไร:** entry_type (SR_ZONE/EMA_PULLBACK/MOMENTUM_BREAKOUT/TREND_CONT) = library ชัด; เลือก max-EV algorithm ต่อ regime
- **code:** `specialist_router.py` (refine rank key เป็น EV) + decision_maker; regime จาก trend/d1 (+ Hurst = noisy filter เสริม)
- **ต้องมีก่อน:** Phase 1-2 + per-algorithm P model
- **ref:** `docs/DESIGN_evidence_based_entry.md` §1.5
- **risk:** gate/routing → อนุมัติ + replay

### Phase 4 — counter_spike → evidence-based
- **ทำอะไร:** `abs(fast_move)≥500` (เดา) → P(bounce) model + 4-way falling-knife veto (news+reversal+momentum+prior)
- **code:** `decision_maker._counter_spike_reason`
- **ต้องมีก่อน:** Phase 1 + counter_spike replay รอบ 2 (multi-regime + OHLCV + cost)
- **ref:** `docs/DESIGN_evidence_based_entry.md` §6, `docs/reviews/counter-spike-replay.md`
- **risk:** anti-fade iron-rule guard → อนุมัติ + replay (replay รอบแรกบอก gate ถูกส่วนใหญ่ ตึงแค่ bullish+strong-support)

### Phase 5 — Statistical exit (SEL)
- **ทำอะไร:** MFE-percentile TP (ปิดที่ percentile ที่ hazard reversal พุ่ง) + edge-decay exit (P_cont ตก)
- **code:** `manage_*` / Guardian (เพิ่ม trigger, ไม่แทนที่ SL/BE/trailing เดิม)
- **ต้องมีก่อน:** **P1c พอ** (MFE/MAE distribution)
- **ref:** `docs/DESIGN_statistical_exit.md`
- **risk:** exit/money → อนุมัติ + replay (วัด give-back vs left-on-table)

### Phase 6 — Position sizing
- **ทำอะไร:** fixed lot 0.02 → **fixed-fractional** `size=equity×risk%÷|entry−stop|` (0.5-2%) + **ATR stop** (size∝1/ATR)
  + **fractional Kelly** `f*=p−(1−p)/b` ×¼-½ (เพดานไม่ใช่เป้า)
- **code:** `mt5_connector.calculate_lot_size` (+ MAX_RISK_PCT cap เดิมยังคุม)
- **ต้องมีก่อน:** **Phase 1** — Kelly ต้องใช้ P calibrated (conf ดิบ = over-bet)
- **risk:** money-management iron-rule → อนุมัติ + replay

---

## กฎเหล็กจาก skill (binding ทุก phase)
1. **Phase 1 (calibration) ต้องก่อน** Phase 2/6 — EV & Kelly ต้องใช้ P ที่เชื่อได้
2. **ทุก phase ผ่าน `docs/VALIDATION_CHECKLIST.md`** — trial-count N + purge/embargo + PBO + Deflated Sharpe + net-cost + min-N. replay เดี่ยวไม่พอ (multiple testing)
3. **guard เดิม bind ตลอด** — fixed SL / daily-loss / streak / slot ยังทำงาน; ชั้น quant *ปลด false-block* หรือ *เลือก algorithm* ได้ แต่ห้าม bypass safety gate หรือยืด SL
4. **shadow ก่อน enable ทุก phase** — log decision ที่ *จะ* ทำ เทียบ live 2-4 สัปดาห์ → เทียบ outcome → ค่อยเปิดทีละ segment, kill-switch = flag

## step ถัดไป (บอลที่ user)
**restart บอท** (ได้ direction/f3 ถูกหลัง fix a0a89d6 + P1c เริ่มเมื่อมีไม้เปิด) → **รันสะสม data หลักร้อย** → กลับมาเริ่ม **Phase 1 (calibration)**.
เกี่ยว: [[entry-exit-quant-overhaul]], `DESIGN_evidence_based_entry.md`, `DESIGN_statistical_exit.md`, `VALIDATION_CHECKLIST.md`.
