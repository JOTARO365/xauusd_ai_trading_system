# DESIGN — Algo v2: S/R-aware deterministic entry/exit (minimal-AI)

สถานะ: DRAFT (2026-07-20) · ผู้เขียน: Claude (orchestrator) · รอ user review
เป้าหมาย: ยกเครื่อง entry/exit ของ algo จาก "momentum breakout เดี่ยว" เป็น **S/R + cluster + indicator
aware, regime-routed** ตาม directive ผู้ใช้ (recap 2026-07-20). LIVE MONEY — ทุก logic ใหม่ **flag-OFF +
journal shadow ก่อน** ไม่แตะไม้จริงจนพิสูจน์ edge.

---

## 0. CORE INVARIANT (ห้ามละเมิด)

1. **Entry/exit = คำนวณจาก data ล้วน** (S/R, cluster, indicator, vol, ATR) — ไม่ prediction, ไม่มี AI ในชั้น EXECUTION.
2. **AI/LLM = SELECTION guide เท่านั้น** — sentiment + วิเคราะห์เศรษฐกิจ → ลง dashboard เป็น guide, **ไม่สั่ง entry**.
3. **ทุก entry-logic ใหม่ → journal counterfactual ก่อน** → พิสูจน์ realized_R เป็น + (ผ่าน min-N) → user flip flag → live.

---

## 1. สถาปัตยกรรม 2 ชั้น

```
SELECTION (จังหวะช้า, event-driven)              EXECUTION (จังหวะเร็ว, ทุก tick)
├─ regime = detect_regime(ER/ADX/volpct)         ├─ sr_engine: multi-TF S/R view (P-A)
├─ sentiment (LLM, ข่าว) → dashboard guide        ├─ entry_gate: cluster+indicator+vol/mom (P-B)
└─ เลือก "โหมด pending" ตาม regime               ├─ pending regime-routed: STOP/LIMIT (P-C)
   TREND→breakout · RANGE→fade                    ├─ exit: TP ตามแนว + trailing vol+S/R (P-D)
                                                  └─ sizing เหมาะทุน (P-E)
```

**regime เลือกกลยุทธ์ (SELECTION) — sr_engine/indicator คำนวณจุด (EXECUTION).** LLM ไม่อยู่ใน path ขวา.

---

## 2. Components + Interface (frozen)

### P-A `agents/sr_engine.py` — S/R view กลาง
รวม `sr_meta` (chart_watcher `_build_sr_meta`, ยังคำนวณใน REGIME_LIVE) + `cluster_map` (dwell density) เป็น
view เดียวให้ entry/exit อ่าน. **decoupled: consume sr_meta ที่มีอยู่ ไม่ rebuild scorer.**

```python
build_sr_view(sr_meta: list, price: float, atr: float, cluster: dict|None=None) -> dict
# คืน:
{ "ok": bool, "price": float, "atr": float,
  "resistance": {level, tf, grade, score, touches, bounce_pct, break_pct, n_tests,
                 dist_atr, dist_pips, cluster_density} | None,   # nearest เหนือราคา
  "support":    {...same...} | None,                            # nearest ใต้ราคา
  "targets_up":   [ {level, tf, grade, score, dist_atr}, ... ],  # res เรียงตามระยะ (สำหรับ TP)
  "targets_down": [ {level, tf, grade, score, dist_atr}, ... ],  # sup เรียงตามระยะ
  "clusters":     [ ... จาก cluster_map ... ] }

level_significance(lvl: dict) -> str    # "MAJOR"(W1/D1 + grade A + cluster หนา) / "MINOR"(H1) / "MID"
pick_tp_target(sr_view, direction, entry, min_rr, sl_pips) -> dict
    # เข้าที่แนว MAJOR (W1) → TP แนวไกลกว่า · MINOR (H1) → TP แนวถัดไปใกล้ๆ. floor ด้วย min_rr.
sr_trailing_stop(sr_view, direction, entry, atr, buffer_atr=0.3) -> float|None
    # long: SL ใต้ support แข็งแรงเล็กน้อย (level - buffer_atr·ATR) · short: เหนือ resistance
from_live() -> dict    # assemble sr_meta จาก logs/bot_status.json + cluster จาก MT5 → build_sr_view
```

### P-B `agents/entry_gate.py` — ทิศ + vol/momentum gate
```python
entry_direction(sr_view, indicators: dict) -> dict
# ใช้ cluster + indicator (RSI/ADX/ER/volume tilt) → คืน:
{ "dir": "BUY"|"SELL"|None, "at": "SUPPORT"|"RESISTANCE"|"BREAKOUT", "conf": 0..1, "why": str }

vol_momentum_gate(indicators, direction) -> dict
# ก่อน fill: แรงผิดจังหวะ (ATR spike / momentum สวน / ADX พุ่ง) → block
{ "pass": bool, "reason": str }
```
indicators = ค่าที่ chart_watcher คำนวณอยู่แล้ว (RSI/ADX/ATR/ER/momentum_tf/volume_profile) — 0 คำนวณซ้ำ.

### P-C `agents/regime_pending.py` (ขยายของเดิม) — pending regime-routed
- **TREND** → BUY_STOP @ resistance / SELL_STOP @ support (breakout) — ของเดิม (Donchian → เปลี่ยนเป็น sr_engine level)
- **RANGE** → BUY_LIMIT @ support / SELL_LIMIT @ resistance (fade) — **ใหม่, gated**
- ทั้งคู่: เมื่อราคาเข้าใกล้ level (≤ near_atr·ATR) → `vol_momentum_gate` → ไม่ผ่าน → **cancel pending รอ**
- flag: `REGIME_PENDING` (มีอยู่) + sub-flag `REGIME_PENDING_FADE` (RANGE fade, default OFF จนพิสูจน์)

### P-D exit (executor/tick/guardian)
- TP = `pick_tp_target` (ตามความสำคัญแนว) แทน RR2 คงที่
- Trailing = `sr_trailing_stop` (vol + S/R buffer) — เสริม/แทน swing_H4 เดิมสำหรับไม้ ALGO

### P-E sizing — SL/TP เหมาะทุน
- risk-per-trade % ของ equity → lot (ประสาน REGIME_SIZING เดิม); SL distance จาก ATR/S/R, lot ปรับให้ risk คงที่

---

## 3. Validation gate (บังคับก่อน live fill)

ทุก logic P-B/P-C/P-D ที่เปลี่ยน "เข้า/ออกไม้ไหน":
1. รัน **shadow ผ่าน `agents/algo_journal.py`** (counterfactual: signal → realized_R net cost) — 0 order จริง
2. เก็บจน **n_closed ≥ min-N** (σ=1.41R: δ=0.2R→389, δ=0.3R→173)
3. `python agents/algo_journal.py` → exp_R เป็น + (PSR>0) → **user flip flag → live fill**
4. ⚠️ RANGE-fade: gauntlet เดิมพิสูจน์ naive z-score fade = −EV. เวอร์ชันนี้ **gated (cluster+indicator+vol/mom)**
   ต่างจากที่เทสต์ → ต้องผ่าน journal ก่อนเสมอ ห้าม flip ตรง

---

## 4. Flag scheme (ทั้งหมด default OFF ใน config, live ผ่าน .env, live-reload)

| flag | คุม | default |
|---|---|---|
| REGIME_LIVE | algo entry (per-cycle) | live=true |
| REGIME_LIVE_TICK | per-tick executor | live=true (07-20) |
| REGIME_PENDING | pending straddle (TREND breakout STOP) | OFF |
| REGIME_PENDING_FADE | RANGE fade LIMIT (P-C) | OFF จนพิสูจน์ |
| REGIME_SR_ENTRY | entry_gate fade → journal shadow (P-B) | OFF (เก็บ data) |
| REGIME_SR_EXIT | sr TP-by-แนว + trailing vol/S/R (P-D) | OFF จนพิสูจน์ |
| REGIME_SR_SIZING | lot risk-based ตามทุน (P-E) + REGIME_SR_RISK_PCT=0.005 | OFF |

kill switch ทุกตัว = flag=false (live-reload). per-tick/pending thread ต้อง restart.

## 7. สถานะ implement (2026-07-20)

ครบทั้ง 5 phase — ทุก module flag-OFF, unit-test ผ่าน, ยังไม่แตะไม้จริง:
`agents/sr_engine.py` (P-A) · `agents/entry_gate.py` (P-B) · `agents/regime_pending.py` (P-C, extended) ·
`agents/algo_exit.py` (P-D) · `agents/algo_sizing.py` (P-E) · `open_order/place_pending_order` +lot override.
ลำดับเปิด live (แนะนำ): REGIME_SR_ENTRY (เก็บ fade data) → พิสูจน์ journal → REGIME_SR_EXIT/SIZING → REGIME_PENDING(_FADE).

---

## 5. Reuse map (ไม่เขียนซ้ำ)

| ใช้ของเดิม | จาก | ใน |
|---|---|---|
| sr_meta scorer (touches/bounce_pct/grade/confluence) | chart_watcher `_build_sr_meta` | P-A |
| S/R ladder | zone_mapper `_build_ladder` | P-A |
| dwell cluster | cluster_map `compute_cluster_map` | P-A |
| indicators (RSI/ADX/ATR/ER/vol) | chart_watcher chart_data | P-B |
| regime detector + constants | regime_lib `detect_regime`/POINT/ATR_SL/RR | ทั้งหมด |
| pending place/cancel | pending_manager + mt5_connector | P-C |
| counterfactual outcome | algo_journal | validation |
| zone-prior P(bounce) Beta-smoothed | docs/DESIGN_evidence_based_entry.md + evidence_entry_reference.py | P-B (optional) |

---

## 6. ลำดับ build

P-A (S/R engine, ฐาน) → P-B (entry gate) → P-C (pending routed) → P-D (exit) → P-E (sizing).
แต่ละ phase: build flag-OFF → unit test → wire → journal shadow. P-A ไม่มี order (view/helper) = ปลอดภัยสุด เริ่มก่อน.
