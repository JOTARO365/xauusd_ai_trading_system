# DESIGN — Minimal-AI Regime-Routed Algorithm Library

**Status: DESIGN PROPOSAL (2026-07-19). ยังไม่มี code. ต้องอนุมัติ + validate ทีละ algo ก่อน enable.**
**หลักการ:** ใช้ AI เฉพาะที่มันเก่งจริง (อ่าน context เชิงคุณภาพ) — **SELECTION** (เลือก algo ตาม regime, งานที่ไม่แน่นอน)
**แยกจาก** **EXECUTION** (สูตร deterministic ตายตัว). ตรง skill `quant-systematic-trading` §5 + first-principles
(AI ไม่มี edge เรื่องทิศ แต่มี edge เรื่องอ่านข่าว/regime).

## 🔒 CORE INVARIANT (user directive 2026-07-19 — ห้ามละเมิดทุกกรณี)
1. **การตัดสินใจเข้า order = ไม่ prediction** — **คำนวณจาก data ที่ได้เท่านั้น** (deterministic math บนราคา/โครงสร้าง)
   ไม่มีการ "ทำนายว่าราคาจะไปทางไหน". ทิศ/entry/SL/TP มาจากสูตร ไม่ใช่การเดา.
2. **ข่าว/AI = บอก sentiment เท่านั้น** → เป็น **guide ในการเลือก algo (regime routing)** — **ไม่ตัดสินทิศ/เข้า order**.
   AI อยู่ชั้น SELECTION เท่านั้น, ไม่แตะ EXECUTION.
→ ทุก component ต้องผ่าน invariant นี้. ถ้า design/code ไหนให้ AI หรือ prediction ตัดสิน entry = ผิด, ต้องแก้.

---

## 1. Motivation
finding session นี้: (ก) LLM confidence **ไม่ informative** เรื่องทิศ (ข) direction ทำนายไม่ได้ (ค) vol/regime
ทำนายได้ (HMM ผ่าน validation) (ง) AI แพง token. → **design ปัจจุบัน (AI ตัดสินทิศ) จ่าย token แลกกับสิ่งที่ AI
ทำไม่ได้.** minimal-AI = ย้าย AI ไปชั้น **regime/context** (ที่มันเก่งกว่า rule เดียว) + ให้ **deterministic math**
ตัดสินการเข้า (ถูก/consistent/testable).

## 2. Architecture
```
┌─ REGIME DETECTION (fusion) ─────────────────────────────────┐
│  A) AI news/macro layer  ← LLM (จุดแข็งเดียว: อ่านข่าวเชิงคุณภาพ)   │
│       reuse: analyst + news_impact + macro_regime            │
│       → risk-on/off · event-proximity (Fed/NFP) · theme      │
│  B) HMM vol/risk regime  ← deterministic (validated แล้ว)        │
│       reuse: hmm_risk_regime.py → RISK-ON/NEUTRAL/RISK-OFF    │
│  C) structural regime    ← deterministic                      │
│       Hurst / Efficiency-Ratio / ADX → TREND vs RANGE         │
│  → FUSE (rule) → regime label + eligible-algo set             │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
┌─ ALGORITHM LIBRARY (deterministic, quant/math) ─────────────┐
│  regime → algo (SELECTION = router, ไม่ใช่ AI ทำนายทิศ)          │
│  • TREND      → momentum-breakout (ATR-based, RR≥2)          │
│  • RANGE      → mean-reversion (z-score/OU, Bollinger, S/R)  │
│  • RISK-OFF   → STAND-DOWN หรือ size ต่ำมาก (gold −10%/yr!)     │
│  • EVENT-NEAR → STAND-DOWN (AI อ่าน calendar)                  │
│  • ไม่มี algo ไหน precondition ครบ → STAND-DOWN                 │
└──────────────────────────────┬──────────────────────────────┘
                               ▼
   EV GATE → SIZING → EXIT → EXECUTION  (ทั้งหมด deterministic)
```

## 3. Components

### 3.1 AI regime/context layer (= minimal AI, จุดเดียว)
- **หน้าที่เดียว:** อ่านข่าว/macro/calendar → output **regime context** (risk-on/off, event-proximity, theme)
  — **ไม่ตัดสินทิศ, ไม่ให้ confidence ต่อไม้**
- reuse pipeline ที่มี: `agents/analyst.py` (news sentiment), `data/news_impact.json`, `macro_regime.md`
- **cost-efficient:** เรียก AI ต่อ **news-update / ทุก N cycle** (ไม่ใช่ต่อ entry) → token ลดฮวบ
- output = label + flags (structured) ป้อน fusion

### 3.2 Regime detection (fusion 3 แหล่ง — deterministic)
รวม A(AI news) + B(HMM vol) + C(structural) ด้วย **rule ตายตัว** → regime + eligible algos.
เช่น: `event_near` (AI) → STAND-DOWN override ทุกอย่าง; `RISK-OFF` (HMM) → size↓/stand-down;
`TREND` (Hurst/ER) + not-risk-off → momentum eligible; `RANGE` → mean-reversion eligible.
**validated แล้ว:** HMM (B) ผ่าน 4/4. A/C ต้อง validate ว่าเพิ่มค่าเหนือ B.

### 3.3 Algorithm library (deterministic — SELECTION แยก EXECUTION)
แต่ละ algo = **precondition (regime+state) + สูตร entry/SL/TP ตายตัว** (ไม่มี AI, ไม่มี discretion):
| algo | regime | entry / SL / TP |
|------|--------|-----------------|
| momentum-breakout | TREND | ทะลุ range-high/low + vol expand; SL=k·ATR; TP=RR·SL |
| mean-reversion | RANGE | z-score/OU สุดขั้ว (±2σ) + no-trend; SL beyond extreme; TP=mid |
| range-fade | RANGE (ที่ S/R) | fade ที่ขอบ range; SL beyond edge; TP=opposite edge |
| STAND-DOWN | RISK-OFF/EVENT/ไม่ครบ | ไม่เข้า |
- คณิตศาสตร์: ATR/vol-scaling, Ornstein-Uhlenbeck (mean-reversion), Hurst/ER (regime), GARCH (vol), Kalman (ถ้าทำ pairs)
- reuse: `agents/chart_watcher.py` (S/R/structure/momentum math ที่มีอยู่ — เป็น deterministic อยู่แล้ว)

### 3.4 EV gate (calibrated)
เข้าเฉพาะ **P(win)·RR − (1−P) > 0 + margin**; P จาก **per-algo per-regime historical stats + calibrator**
(Platt/isotonic — reuse `agents/calibrator.py`). ไม่มี setup EV>0 → STAND-DOWN (คำตอบที่ถูกต้องบ่อย).

### 3.5 Sizing (deterministic)
fixed-fractional (≤2% ของ equity) + **vol-target scaling ตาม regime** (reuse `REGIME_SIZING` logic);
fractional-Kelly เป็นเพดาน (¼-½, cap 2%). ทั้งหมดสูตร ไม่มี AI.

### 3.6 Exit (deterministic)
MFE/MAE-based (SL จาก MAE-distribution ของ winner, TP จาก MFE-percentile) + edge-decay/time-stop.
reuse `manage_*` ที่มี + design `docs/DESIGN_statistical_exit.md`.

## 4. Reuse map (ไม่ต้องสร้างใหม่ทั้งหมด)
| มีอยู่แล้ว | ใช้ทำ |
|-----------|-------|
| chart_watcher (S/R/structure/momentum/ATR math) | deterministic algo primitives |
| hmm_risk_regime.py / hmm_regime.py (validated) | regime B (vol/risk) |
| analyst + news_impact + macro_regime | AI regime A (news/context) |
| calibrator.py + fit_calibrator.py | EV gate P-calibration |
| REGIME_SIZING + calculate_lot_size | sizing |
| harness (btc_validate/gold_entry_sim/nulltest/analyzer) | **validate ทุก algo ก่อน enable** |

## 5. ⚠️ Honest caveats (วินัย session นี้ — สำคัญสุด)
1. **นี่คือ "โครงสร้างที่ถูก" ไม่ใช่ "edge ที่พิสูจน์แล้ว"** — session นี้แสดงว่า simple algo (breakout/mean-rev)
   **ไม่มี edge** บน BTC/gold. algo ใน library **อาจไม่มี edge เหมือนกัน** → ต้องผ่าน gauntlet, บางตัว(หรือทั้งหมด)อาจตก
2. **AI regime-selection ยังไม่พิสูจน์ว่าเพิ่มค่า** — ต้อง validate ว่า A(news) เพิ่มเหนือ B(HMM) จริง
3. **ทุก algo: shadow → validate (DSR/PBO/intrabar/null/net-cost) → enable ทีละตัว** — ห้าม wire ของยังไม่ validate
4. **บัญชีบาง** — จนกว่ามี algo ที่ validate ผ่าน + ทุนพอ → รันแค่ shadow/DRY_RUN เก็บ data
5. **first-principles ชี้ว่าโครงนี้ถูก แต่ market efficient** — คาดหวังตามจริง: อาจไม่มี algo ไหนมี edge net-cost

## 6. Phased plan
```
P0  design freeze + regime taxonomy + fusion rules (doc) — ตอนนี้
P1  build deterministic regime detector (B+C, ไม่มี AI) + algo library skeleton — offline, flag-OFF
P2  backtest ทุก algo per-regime บน xau history (harness เดิม: intrabar+DSR+PBO+null) — คัดตัวที่รอด
P3  เพิ่ม AI layer A (news→regime) + validate ว่าเพิ่มค่าเหนือ B — shadow
P4  EV gate + calibration + sizing — shadow-log คู่ decision จริง
P5  enable ทีละ algo ที่ validate ผ่าน (flag-gated, kill-switch, guard bind)
```
**ทุก phase flag-OFF/shadow จนกว่า validate ผ่าน.** ไม่แตะ live money จนกว่ามี algo พิสูจน์ + ทุนพอ.

## 7. เทียบ design ปัจจุบัน
| | ปัจจุบัน (AI ตัดสินทิศ) | minimal-AI (นี้) |
|---|---|---|
| AI ทำ | ทิศ + confidence (ที่ทำไม่ได้) | regime/context เท่านั้น (ที่ทำได้) |
| entry | LLM (non-det, แพง) | deterministic math (ถูก, testable) |
| token | ต่อ entry | ต่อ news-update (ลดฮวบ) |
| validate | ยาก (non-det) | ง่าย (deterministic → gauntlet ได้) |
| edge ทิศ | ไม่พิสูจน์ | ไม่อ้างว่ามี (structure+regime, validate) |

เกี่ยว: skill `quant-systematic-trading` (§1 EV, §2 calibration, §3 exit, §4 sizing, §5 regime, §6 validation) +
`references/regime-and-volatility.md`, `docs/DESIGN_evidence_based_entry.md`, `docs/DESIGN_statistical_exit.md`,
`docs/VALIDATION_CHECKLIST.md`, harness ใน `scripts/`. [[entry-exit-quant-overhaul]].
