# DESIGN — Dual-Sleeve (Scalp A + Swing B) + Coordination Layer

**สถานะ: DESIGN ONLY — รออนุมัติก่อนเขียน code ใดๆ** (explain-before-acting, iron rule).
**วิธี:** 3-persona adversarial workflow (fable 5): propose → destroy → filter → 3 attacks → revise.
**วันที่:** 2026-07-23

---

## 0. Grounding (measured จาก MT5 live probe + repo)

| ตัวเลข | ค่า | label |
|---|---|---|
| Spread GOLD# | 24–31 points (ใช้ **31 เป็น floor**, กว้างขึ้นตอนข่าว) | **measured** (MT5 probe) |
| Commission | **0** (spread-only) | **measured** (deals) |
| Swap | long **−81.44** pt/lot/คืน · short **+8.79** · 3× วันพุธ | **measured** (symbol_info) |
| tick_value / contract / min-lot | $1/pt/lot · 100oz · 0.01 | measured |
| Loop | 5–15 นาที + LLM latency → Sleeve A ต้อง pending-order | measured |
| EMA_PULLBACK | WR 31%, −$594, n=13, hard-blocked | measured |
| Directional edge | **ไม่มี** (momentum/fade/TSMOM=beta/reversion/cross-asset/trailing OOS ล้มหมด) | measured (session นี้) |
| B10 lock bug | `swing_manager` raw `mt5.order_send/positions_get` ไม่ผ่าน `_mt5_lock` → order-corruption risk | measured (code) |

**⚠️ n = 0 วันนี้ — ทุก WR ในเอกสารนี้เป็นสมมติฐาน ไม่มี family ไหนมี proven edge.**

---

## 1. VERDICT (ตรงไปตรงมา)

**Ship เป็นระบบเงินจริงวันนี้ = 0 sleeve. Candidate ที่รอดไป shadow = 1 (A1+A2 merged).**

| Family | คำตัดสิน | เหตุผลคณิต (net-of-cost) |
|---|---|---|
| **A1 (+A2 variant)** | ✅ **SURVIVES → shadow → pilot 0.01 หลังผ่าน gate** | required WR (+0.05R net) = **50.9%**, breakeven net **48.6%** (cost 30p ดัน +3.1pp); ~17 ไม้/เดือน → n=294 (Bonferroni K=10) ใน ~1.7 ปี |
| A2 standalone | 🔀 **MERGE เข้า A1** | กลไกเดียวกัน; แยก = หาร n สอง → ไม่ถึง min-N |
| **A3 (post-news fade)** | ❌ **KILLED** | event-spread ~150p ดัน required WR 62–64% + n≈9/ปี → 19 ปีถึง significance = unfalsifiable (NFP 1.44× move จริง แต่ monetize ไม่ได้ที่ n นี้) |
| **B (swing)** | ⚠️ **DEMOTED → data-collection paper-only (ไม่มีเงินจริง)** | swap-adj breakeven **35.3%** > analog 33.1%; portfolio hurdle WR≥41%; Kelly@analog **ติดลบ**; 2 ไม้/เดือน → 7.2 ปีถึง n=173; B10 lock unverified |
| **Book A+B รวม** | ❌ **DOES NOT SHIP** | ที่ measured-analog WR: median **−5.5%/ปี**, P(ปีขาดทุน) **74.6%**, P(DD>10%) 71.6% (MC) |

**สิ่งที่ ship ได้จริง = เครื่องเก็บหลักฐาน 1 เครื่อง (A1 shadow) + ท่อเก็บ data ของ B** — นี่คือ outcome ที่ valid ไม่ใช่ความล้มเหลว.

---

## 2. SURVIVING — Sleeve A1 spec (final หลังรับทุก attack)

**ทำไมไม่ซ้ำรอย EMA_PULLBACK:** EMA_PULLBACK ตายเพราะ market-order จ่าย spread กลาง range + profit = "trend ไปต่อ" (directional, falsified). A1 กลับด้าน: **limit order ที่ extreme เชิงโครงสร้าง** (positive selection), profit = mean-reversion/liquidity ไม่ใช่ทิศ, regime-gated. **Caveat:** H1 mean-reversion always-on = −EV [measured] → A1 ต่างที่ box/session/limit-conditioned แต่ **ยัง unproven จน min-N**.

| องค์ประกอบ | ค่า | label |
|---|---|---|
| Regime gate | RANGE ยืนยัน **M แท่ง** (M เลือกจาก dwell-data Phase 0) — hysteresis ที่ชั้น consumption **ไม่แตะ `detect_regime`** | proposal |
| Structure | box จาก sr ladder, width ≥ 2500p, ATR_M15 < width×60% | measured guards |
| Entry | **limit only** — BUY lower-edge +100p / SELL upper-edge −100p | proposal |
| SL / TP | SL 25% width (floor 800p), TP 30% width → **R:R ~1.2** | assumed |
| Net math | breakeven **48.6%**, required WR **50.9%** | computed |
| Session | London+NY 07:00–20:00 UTC | proposal |
| Pending guards (อิสระจาก regime) | TTL cancel · vol-fuse (ATR spike → pull) · **intraday tripwire** (\|move วันนี้\|>1.5×ATR_D → cancel ทั้งวัน; คืน ~2pp/ปี) | proposal |
| Caps | ≤3 ไม้/วัน (replay: 7+ = −411) · risk 0.3%/ไม้ · daily stop −0.9% | measured/proposal |
| Kill-switch | family cutoff **−0.15R @30 ไม้** · filter rolling-50 WR<53.6% → ML OFF | computed |

---

## 3. Sleeve B — data-collection program (paper-only)

- **ถอด "gate n≥20 / paper 6 เดือน" ออก** — ที่ n=20 CI±0.62R = noise แต่งเป็น gate (อนุมัติตัว −0.3R จริง 17%). Review = **LCB kill-only** (kill ได้ real-time, approve ไม่ได้)
- Rule-audit ณ entry: TREND confirmed · **swap-adj breakeven recomputed ต่อไม้ (35.3% — 7 คืน/สัปดาห์รวม triple Wed; design เดิมลืม 28%)** · no-event · structure stop ในงบ
- **Time-stop 10 คืน ห้าม ship** จน re-derive จาก MFE-timing ของ winner จริง
- ถ้าจะ pilot เงินจริงวันหน้า (ต้องผ่าน paper LCB WR≥41% ก่อน): **0.3–0.5% ไม่ใช่ 1.0%** (Kelly@analog ติดลบ)
- **swap short +8.79 (measured)** → hold budget SHORT ยาวกว่า LONG ได้ (asymmetric)

---

## 4. Coordination Layer (ฉบับหด — เหลือ money-sleeve เดียว + B paper)

| # | ข้อ | ค่า final |
|---|---|---|
| 1 | **Capital** | A: 0.3%/ไม้, cap −0.9%/วัน · B: paper=0 เงินจริง · **account daily cap 30%→5% (iron rule — ต้อง user approve)** |
| 2 | **Conflict** | A สวน B-paper: **BE-lock เท่านั้น** (OR-clause regime→RANGE ถูกลบ — false-RANGE ทำ A มี E<0) |
| 3 | **Exposure** | gross ≤0.04 lot, net ≤0.03 · margin@1:1000 ไม่ binding · **worst-day −2.3 ถึง −2.5%** (crash gap+pyramid slip) < 5% cap |
| 4 | **Attribution** | magic-number primary (+1=A1/+10=B) + comment รอง — ดู §5 |
| 5 | **Routing** | hysteresis slow-in/fast-out: เปิด risk = confirmed state · ตัด risk = raw แท่งเดียว · RISK-OFF cancel = defense-in-depth (placebo ถ้าใช้เดี่ยว, lag 60 นาที) |
| — | **Diversification claim** | **ถอดออก** — เท็จในหน่วยสัมบูรณ์ (A+B σ/MDD > B-only เสมอ); ρ=0.068 all-days, **ρ_tail≈1** (crash = 1 ไม้ ไม่ใช่ 2) |

---

## 5. Attribution schema (ห้าม pool 2 sleeve เด็ดขาด)

| ชั้น | Spec |
|---|---|
| Primary | **magic offset** จาก SYSTEM_MAGIC: +1=A1, +2=A2, +10=B-paper, +11=B-PYR (comment ถูก broker แก้ได้) |
| Secondary | comment prefix `A1-`/`B-` |
| DB | `trades` + columns `sleeve`, `family`, `manual_touched` — เขียน **ณ จุดส่ง order** ห้าม derive ย้อนจาก comment |
| Reconciliation | job รายวัน: ไม่ match → `family=UNKNOWN` ตัดจาก stats |
| Manual exclusion | ไม้ที่ user แก้ผ่าน dashboard → `manual_touched=true` แยก discretionary stream |
| R computation | จาก `planned_sl_pips` (leakage-free) ไม่ใช่ SL สุดท้าย |

---

## 6. Validation

- **Pre-req เด็ดขาด: append-only per-cycle feature log** (persist สิ่งที่ entry เห็นจริง) — `bot_status.json` overwrite ไม่ persist → ไม่มีไฟล์นี้ = **ห้าม fit/claim replay**
- Shadow-fill: **pessimistic** (fill เฉพาะ trade-through เกิน limit ≥ spread+buffer) — กัน adverse-selection bias
- Label: resolve ด้วย M1 path; drop แท่งที่ TP+SL อยู่ range เดียว (log drop-rate)
- ML filter (extend `ml/train_filter.py`, flag OFF): **calibrate (Platt/isotonic OOS) ก่อน** threshold 0.55 · walk-forward purged+embargo (ไม่ใช่ shuffled KFold) · feature ≤8-10 @ n=100
- **Pre-registration**: freeze config grid ลง ledger **ก่อน** shadow ไม้แรก; K=10 @Bonferroni → **min-N enable ≈294** (ไม่ใช่ 173)
- Enable gate/family: n≥294 + net expectancy>0 + parameter **plateau** + walk-forward AUC>0.55 ทุก fold + precision ≥ breakeven+5pp OOS

---

## 7. Integration + Flags (default OFF ทุกตัว, ผ่าน approval)

| จุด | ทำอะไร |
|---|---|
| `pending_manager` (extend) | A1 limit + TTL + vol-fuse + tripwire |
| module ใหม่: regime-consumption wrapper | อ่าน `detect_regime` → confirmed-state M แท่ง (**ไม่แตะ detect_regime** = analytics เดิมไม่พัง) |
| `swing_manager` (**B10 fix ก่อนฝั่ง B ทุกอย่าง**) | ย้าย `@_locked` ลง `_place_leg`/`_close_all_legs` (RLock reentrant) + assert lock-held |
| DB schema | columns §5 — architect pass |
| Flags | `SLEEVE_A_SHADOW`, `SLEEVE_A_ENABLED`, `SLEEVE_A_ML_FILTER`, `SLEEVE_B_PAPER` — แยกหมด default OFF |
| **Token-cost delta** | **0 new LLM call/cycle** (ทั้งหมด computed-in-code; เพิ่มแค่ disk I/O feature log ~KB/cycle) |

---

## 8. Combined MC (เลขที่เอกสารถือ)

| Scenario (A/B WR) | median/ปี | P(ปีขาดทุน) | อ่าน |
|---|---|---|---|
| OPTIMISTIC (55/40) | +8.2% | 17.9% | กำไรเฉพาะเมื่อ "เชื่อ" WR ที่ไม่มีหลักฐาน |
| BASE (50/35) | −0.2% | 50.8% | เหรียญ |
| **MEASURED-analog (45/33)** | **−5.5%** | **74.6%** | ขาดทุน 3/4 ปี = เหตุผล book ไม่ ship |
| A-only @OPTIMISTIC | Sharpe +0.76 (vs A+B +0.29) | | A แบก Sharpe ทุก scenario |

---

## 9. Sequencing (dependency-ordered)

```
Phase 0 — MEASURE (ฟรี, 0 order-path code, เริ่มได้ทันที)
  S0-1 transition/dwell script บน data/xau_h1.json → GATE: p25 dwell RANGE < duration ไม้ A1?
       ไม่ผ่าน = routing H1 โมฆะ → redesign ก่อน shadow ไม้เดียว
  S0-2 verify swap (long/short + triple-Wed) — ทำแล้ว: -81.44/+8.79 ✓
  S0-3 freeze pre-registration ledger (A1 grid K configs → min-N inflated)
Phase 1 — PLUMBING (architect pass + user approval: schema + iron rules)
  S1-1 DB columns + magic offsets + reconciliation
  S1-2 append-only per-cycle feature log (pre-req validation)
  S1-3 B10 lock fix (ก่อนแตะ Sleeve B ใดๆ)
Phase 2 — A1 SHADOW (flag SLEEVE_A_SHADOW, pending_manager + regime-consumption wrapper)
  → เก็บ shadow-fill pessimistic + feature log; ยังไม่วาง order จริง
Phase 3 — A1 GATE → pilot 0.01 (เฉพาะเมื่อ n≥294 + net>0 + plateau + AUC>0.55)
Phase 4 — B PAPER (flag SLEEVE_B_PAPER, หลัง B10 fix) — data collection, ไม่มีเงินจริง
```

---

## 10. สิ่งที่ต้องขออนุมัติก่อนเริ่ม (iron-rule/config)

1. **Account daily-loss cap 30% → 5%** (ป้องกัน book นี้; iron-rule config)
2. **DB schema change** (columns sleeve/family/manual_touched) — architect pass
3. เริ่ม **Phase 0 (measure-only, ฟรี, 0 order code)** — dwell gate ตัดสินว่า routing H1 ใช้ได้ไหม

**ถ้า Phase 0 dwell gate ไม่ผ่าน → แม้แต่ A1 ก็ต้อง redesign ก่อน shadow.**
