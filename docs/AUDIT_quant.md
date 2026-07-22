# QUANT AUDIT — algo v2 + live flags (2026-07-21)

ผู้ตรวจ: quant-auditor (self-audit — agent registry ยังไม่ reload; ทำตาม iron-rule #12 + skill
`quant-systematic-trading`). Posture: **adversarial — พยายาม refute edge**. ตัวเลขทุกตัว reproduce เอง.

> **สรุปผู้บริหาร:** ระบบ live ตอนนี้วางไม้เงินจริงบน **2 กลยุทธ์ที่ไม่มี validated edge** (momentum −EV,
> fade −EV). justify ได้แค่ "lot จิ๋ว + เก็บ data". **RANGE fade (real order) = NO-GO — ปิดทันที.**

---

## EDGE 1 — RANGE fade ที่ S/R zones  →  VERDICT: **NULL (ไม่มี edge)**

**หลักฐาน (reproduce: `python scripts/fade_zone_gauntlet.py`, 70k H1):**
- KDE mid-strength zones (16-25 touches), intrabar-pessimistic + net cost + OOS 60/40 + null(random-level fade):
  - RR1.5: expR −0.002 (20p) → −0.050 (40p); PSR₀ 0.10-0.48; OOS **OUT expR −0.058** ❌
  - RR2.0: expR +0.003 (20p แทบ 0) → −0.045 (40p); OOS **OUT −0.065** ❌; **REAL (−0.021) แย่กว่า NULL (−0.005)**
- ล้มทุกเกณฑ์: expR≤0 หลัง cost จริง · PSR₀ ≪ 0.95 · แพ้/เสมอ null · OOS พังทั้ง 2 RR (in-sample→OOS = ลายเซ็น overfit)

**🔴 REAL-MONEY FLAG:** `.env REGIME_PENDING_FADE=true` = วาง **BUY_LIMIT/SELL_LIMIT จริง** บนกลยุทธ์นี้.
→ **NO-GO. ปิด `REGIME_PENDING_FADE=false` ทันที** (live-reload). เก็บ shadow ผ่าน journal (REGIME_SR_ENTRY) พอ.

---

## EDGE 2 — KDE mid-strength zone "edge" (respect 47% / +11.6% null)  →  VERDICT: **proxy artifact / INSUFFICIENT**

**หลักฐาน (`scripts/cluster_kde_research.py`):** respect-rate +11.6% เหนือ null (n=373) — **แต่เป็น proxy metric**
(react ≥0.8ATR ก่อนทะลุ) ไม่ใช่ trade EV. เมื่อ sim fade จริง (Edge 1) edge **หายเกลี้ยง** (−EV, แพ้ null).
= ตัวอย่างคลาสสิกที่ skill เตือน: **proxy ดูมี edge, trade จริงไม่มี.**
→ ใช้ได้แค่ **decision-support display** (KDE คัดโซนคม 8 vs 20 — ok) **ห้ามเป็น signal.** ไม่ใช่ edge.

---

## EDGE 3 — Momentum breakout (TREND) — **live entry ปัจจุบัน**  →  VERDICT: **INSUFFICIENT (−EV after cost)**

**หลักฐาน (reproduce: `data/regime_analytics.json`, regenerated 05:53 วันนี้):**
- TREND / momentum_breakout: N=1575, WR 33.1%, **exp_R −0.054 (−EV หลัง cost 30p)**, sharpe −0.038,
  **PSR₀ 0.067**, breakeven_wr 34.9% (WR 33.1% < breakeven), grade **C**.
- D1 momentum เคยผ่าน OOS แต่ **ตก null test** (artifact จาก fat-tail baseline) — ดู continue.md.

**🔴 REAL-MONEY FLAG:** `REGIME_LIVE_TICK=true` วาง market entry จริงจาก momentum นี้.
→ **marginal NO-GO.** เทรด signal −EV. justify ได้แค่ lot จิ๋ว (risk 0.5%, MAX 0.03) เพื่อเก็บ data จริง.
แนะนำ: ยอมรับเปิดต่อ**เฉพาะถ้า**ตั้งใจจ่ายค่า −EV เล็กน้อยแลก data live; ไม่งั้น shadow.

---

## EDGE 4 — entry_gate p_edge / RSI-confirm  →  VERDICT: **VALID (data-collection only), INVALID as live gate**

`agents/entry_gate.py` W = ILLUSTRATIVE, `fitted=False` — น้ำหนัก log-odds **ไม่ได้ fit/calibrate** กับ outcome จริง.
`p_edge` **ไม่ใช่ calibrated probability** → ใช้ตัดสิน EV/gate live ไม่ได้ (skill §2/§7).
✅ ถูกต้องที่ปัจจุบัน entry_gate ใช้ **journal-only** (ไม่แตะ live pending — pending ใช้ `_weak` veto แยก).
→ คง journal-only. ก่อนใช้ gate live: fit weights จาก journal + reliability diagram + OOS.

---

## EDGE 5 — algo_journal counterfactual methodology  →  VERDICT: **VALIDATED (sound basis)**

`agents/algo_journal.py`: intrabar first-touch (`_resolve`), assume-SL เมื่อ TP+SL แท่งเดียว (pessimistic),
net cost 30p, MFE/MAE, resolve จาก forward bars หลัง signal bar (outcome labeling — ไม่ใช่ feature leak),
dedup 1/bar, pending 2-phase (fill→TP/SL/EXPIRED). **ไม่มี look-ahead ใน labeling.**
✅ เป็น data pipeline ที่ถูกต้องสำหรับ validation อนาคต (fit model + calibrate). 1 caveat: fade capture ใช้
entry_gate near-gate (บันทึกเมื่อราคาใกล้) — dataset จะ bias ไป near-events; ระวังตอน fit.

---

## Go / No-Go สรุป (live enablement)

| flag | edge | verdict | action |
|---|---|---|---|
| `REGIME_PENDING_FADE` | fade S/R | **NULL** | 🔴 **ปิดทันที** (real order บน −EV) |
| `REGIME_LIVE_TICK` (momentum) | TREND breakout | INSUFFICIENT (−EV) | 🟠 shadow หรือรับ −EV จิ๋วแลก data |
| `REGIME_SR_EXIT` | TP/trailing | n/a (exit refinement) | 🟡 ต่ำเสี่ยง แต่สร้างบน entry ที่ยัง unvalidated |
| `REGIME_SR_SIZING` | sizing | valid (กลไก) | 🟢 ok |
| `REGIME_SR_ENTRY` | fade→journal | valid (shadow) | 🟢 keep — เก็บ data |

**Bottom line:** ยังไม่มี directional edge ที่ VALIDATED เลย (สอดคล้อง prior: ทองทิศทำนายไม่ได้ด้วย retail TA).
สิ่งที่ควรทำ live = **shadow เก็บ data + risk management** ไม่ใช่ real directional bets. หากต้องการ live จริง
ควรจำกัดที่ lot จิ๋วสุด + ยอมรับว่าจ่ายค่า negative-EV เพื่อ data (เป็น research cost ไม่ใช่กลยุทธ์ทำกำไร).

*Meta: audit นี้ทำโดย self (agent registry reload session หน้า). `.claude/agents/quant-auditor.md` พร้อม
audit อิสระครั้งต่อไป.*

---
---

# QUANT AUDIT — TSMOM-D1 "validated edge" (adversarial, 2026-07-21)

Subject: TSMOM-D1 directional engine (`agents/tsmom_manager.py`), claimed as the **single validated
edge** from the ~31-strategy / 4-persona search, and currently wired LIVE (`.env:150 TSMOM_LIVE=true`).
Posture: refute. Every load-bearing number re-derived independently (commands shown).

## TL;DR — OVERALL VERDICT: **FAIL** (edge is beta, not timing alpha; failed the pre-registered gauntlet)

- Deployed strategy did **NOT pass** the system's pre-registered gauntlet (`strategy_search.py`):
  **0 of 13** candidates passed; TSMOM-D1 failed the **WR≥51%** gate (WR 45.7%).
- It was blessed by a **separate, differently-specified** script (`tsmom_develop.py`) that drops the WR
  gate and scores Sharpe-vs-zero. Post-hoc goalpost move.
- Re-derived: long-short ensemble Sharpe **0.628 < buy&hold 0.673**. Long-only barely beats its own
  vol-targeted always-long benchmark (Δ Sharpe ≈ **+0.07**; at L=63 it *loses*).
- Regression alpha of the deployed long-short signal on the market: **t(alpha)=1.79** — below even the
  under-counted deflation ceiling (expected-max-z(27)=1.84).
- **`TSMOM_LIVE=true` (`.env:150`) = live order path on an unproven edge → NO-GO. Turn OFF (shadow).**

**Reproduction:** `<py> scripts/tsmom_develop.py` · `<py> scripts/strategy_search.py` ·
`<py> scratchpad/refute_tsmom.py`. All of `tsmom_develop.py`'s printed numbers reproduce exactly
(ensemble Sharpe 0.63, WR 51.8%, quartile 4/4, LS 0.53 vs B&H 0.65, t 3.00 vs emax-z 1.84). The
numbers are real; the interpretation is wrong.

### Issue 1 — Pre-registered gauntlet FAILED. **FAIL (goalpost move)**
`strategy_search.py:104-109` gate = WR≥51 ∧ EV+ ∧ OOS+ ∧ beat-null ∧ PSR>0.95 ∧ Q≥3/4. Full run:
**0/13 passed.** TSMOM line: `WR 45.7%  expR +0.192  OOS +0.371  null +0.099  PSR 1.00  Q 3/4` →
passes [EV+ OOS+ null PSR Q≥3] but **fails WR≥51** → ❌. `tsmom_develop.py:120` then discards the WR gate
("ตัดสินที่ Sharpe/EV net ไม่ใช่ WR"). Inventing a passing test after the registered one fails =
specification search. (Also: the two are not the same strategy — harness = L63 fixed SL/TP triple
barrier; develop = continuous position-flip overlay. WR 45.7% vs 51.8% differ due to exit, not edge.)

### Issue 2 — Beta, not alpha. **FAIL** (load-bearing)
`refute_tsmom.py`, identical vol-target sizing+cost on both legs:

| series | Sharpe |
|---|---|
| Buy&hold gold (raw) | 0.673 |
| **TSMOM long-short ensemble (DEPLOYED)** | **0.628** |
| Vol-targeted always-long (no timing) | 0.767 |
| TSMOM long-only ensemble | 0.834 |

Deployed LS (0.628) < buy&hold (0.673). LO beats its correct benchmark (VT-always-long 0.767) by only
**+0.07**, and per-L it vanishes (L=63: LO 0.725 < VT 0.749). Regression alpha: LS beta 0.214, ann
alpha 2.93%, **t=1.79** (ns); LO beta 0.386, ann alpha 2.26%, **t=2.35** (marginal, uncorrected).
`tsmom_develop.py:99-105` prints the tell (LS 0.53 < B&H 0.65) but the VERDICT (`:118`) keys off
`ensemble Sharpe>0.5`, satisfied by beta alone.

### Issue 3 — Deflation: right formula, wrong null. **FAIL**
`tsmom_develop.py:111-115`: t = Sharpe×√(n/252) = 0.63×√(5747/252)=**3.00** ✓; expected-max-z(27)=**1.84**
✓ (Bailey–LdP reproduced). But the null is zero. Buy&hold's own t = 0.673×√(6000/252)=**3.28 > 3.00** —
beta "survives deflation" better, so the test is vacuous. The quantity that must clear the ceiling is
the **alpha** t (1.79 LS / 2.35 LO). `N_TRIALS=27` under-counts (omits the ~31-strategy brainstorm, each
candidate's tuned internal params, and the ensemble-L pick). Realistic N≈60–200 →
emax-z(60)=2.17, (124)=2.44, (200)=2.61. Even best-case LO t=2.35 < ceiling(124). LS t=1.79 not close.

### Issue 4 — "Plateau" is jagged. **CAVEAT**
L-sweep LS: 21→0.08, 42→0.49, 63→0.40, 90→0.59, 126→0.53, 189→**0.29**, 252→0.60. Swings 0.29↔0.60
between neighbours; deployed ensemble (63,126,252) drops weak 42/189 = mild L-selection. Not a clean
plateau.

### Issue 5 — Look-ahead/leakage. **PASS**
Live signal `tsmom_manager.py:36-44` uses `close[-2]` (last closed D1) — no forming-bar peek. Acts once
per new closed D1 (`:120-121`); deterministic sizing (`algo_lot`) → respects SELECTION/EXECUTION
invariant. Harness ML fits IS-only, predicts holdout (`strat_candidates2.py:94,138,184`). Clean.
(OOS>IS Sharpe — ens 0.505→0.810 — is a beta artifact: last 40% = gold 2019–25 bull, not proof of edge.)

### Issue 6 — Cost. **PASS (not binding)**
Low turnover (~163 flips/5874 bars, L126). Spread 0.30→0.533, 0.50→0.502, 1.0→0.425, 2.0→0.272,
3.0→0.119. Degrades, doesn't kill. Missing alpha is the problem, not cost. `TSMOM_SL_PIPS=0` keeps
chandelier 3×ATR (config.py:230 warns fixed narrow SL destroys it — respected).

### Issue 7 — Sample size. **CAVEAT**
n=5747 daily, but only **~163 independent flips** (L126) in 23 years — thin to claim a +0.07 Sharpe
alpha survives a 27–200-way search. Overlapping lookbacks → effective DoF ≪ 5747.

### Overfit/snooping signatures found
Pre-registered test failed→replaced post-hoc (1); edge gone vs beta benchmark, alpha ns (2/3); trials
under-declared + wrong null (3); ensemble-L cherry-picked from jagged sweep (4); MOP-anomaly
storytelling for a searched result inside the noise band. Consistent with repo prior: gold direction
not mechanically predictable by retail TA — this is vol-targeted long-beta relabeled.

### Actionable recommendations
1. **NO-GO live.** Set `.env:150 TSMOM_LIVE=false`; `TSMOM_SHADOW=true` for data (`tsmom_manager.py:128`
   supports shadow). Currently a real order path on an unproven edge.
2. **Re-benchmark vs beta** (vol-targeted always-long), not zero; require alpha t > emax-z at the
   **honest** trial count (log every strategy+param; N≈60–200). LS t=1.79 fails; LO t=2.35 borderline,
   re-test purged/embargoed.
3. If keeping exposure, **long-only** (short leg has negative alpha on gold), sized/labeled as a
   vol-targeted beta overlay — not a timing edge. Note TSMOM_LIVE disables momentum-intraday+fade
   (config comment), concentrating risk into this beta bet.
4. **Fix scripts:** `tsmom_develop.py` — keep/justify the WR gate, deflate against buy&hold, count all
   trials in `N_TRIALS`.
5. **Collect forward OOS** before revisiting; ~160 bets can't separate +0.07 Sharpe from noise.

**GO/NO-GO (live enablement): NO-GO.** TSMOM-D1 is not a validated directional edge — it is
vol-targeted gold beta that failed the pre-registered gauntlet and shows no significant timing alpha.
Turn `TSMOM_LIVE` OFF.

---
---

# QUANT AUDIT — A1 band-edge scalp backtest (adversarial, 2026-07-23)

Subject: A1 band-edge mean-reversion scalp (`scripts/a1_scalp_backtest.py`), the structure-gate redesign
out of Phase 0 (`scripts/regime_dwell_phase0.py`) per `docs/DESIGN_dual_sleeve.md`. Claimed: N=1944,
WR net 50.5%, expR +0.076 @31p, PSR 1.00, sumR +148 → "＋EV ผ่าน" (แต่แพ้ null +0.141, OOS +0.018,
Q1 +0.614 vs Q2-4 ~+0.02). Posture: refute. ตัวเลข load-bearing ทุกตัว re-derive เอง.

**Reproduction:** `<py> scripts/a1_scalp_backtest.py` → ตรงทุกตัว (N=1944, 50.5%, +0.076, PSR 1.00,
sumR +148.4, null +0.141, OOS +0.018, Q1 +0.614). ตัวเลขจริง — **แต่ +EV ทั้งก้อนเป็น fill-model artifact.**
Audit script: `scratchpad/a1_audit.py` (fair/strict fill variants + rebuilt nulls + param sweep).
Data: `data/xau_h1.json` 70k bars, 2014-10-24 → 2026-07-17, ราคา 1230 → 4017 (ยืนยันจาก ts col 0).

## TL;DR — OVERALL VERDICT: **REFUTED (fill-model artifact; แก้ fill แล้ว −EV ทุก slice ยกเว้น Q1 ยุค 2014-17)**

| variant | N | WR | expR@31 | PSR | sumR |
|---|---|---|---|---|---|
| A0 base (ตามสคริปต์) | 1944 | 50.5% | **+0.076** | 1.00 | +148 |
| B1 ตัด TP บน fill bar (pessimistic) | 1944 | 46.3% | **−0.015** | 0.27 | −30 |
| FAIR: TP fill-bar เฉพาะ close ยืนยัน | 1944 | 46.3% | **−0.014** | 0.28 | −28 |
| C1 strict fill (`low<edge` trade-through) | 1842 | 48.2% | +0.026 | 0.85 | +48 |
| **C2b strict + no fill-bar TP (realistic)** | 1842 | 43.9% | **−0.068** | 0.00 | **−126** |
| C2 ต้องทะลุ 31p + no fill-bar TP | 1784 | 42.4% | −0.101 | 0.00 | −180 |

realistic variant: OOS −0.082, Q4 (2023-07→2026-07) −0.096, cost 45p → −0.083, 60p → −0.099.
**ไม่มี config ที่แก้ fill แล้วยัง +EV.** A1 ตายด้วย.

### Issue 1 — Fill-bar TP look-ahead = แหล่งที่มาของ +EV ทั้งหมด. **REFUTED (fatal)**
`a1_scalp_backtest.py:47` — `_sim` เริ่มสแกน exit ที่ `j = fi` (fill bar เอง). BUY limit fill ตอน low แตะ
`bl`; บาร์เดียวกันถ้า `high >= tp` นับ TP ทันที ทั้งที่**ไม่รู้ลำดับ intrabar** (high อาจเกิดก่อน low → ก่อน fill).
วัดจริง: **275/973 TPs (28.3%) เกิดบน fill bar.** ตัดออก (B1): +0.076 → **−0.015**. แบบแฟร์ที่สุด
(นับ TP fill-bar เฉพาะเมื่อ close ปิดเลย TP — path จาก low กลับไป close ต้องผ่าน TP จริง): **−0.014** —
เหมือนกัน เพราะเคส close-ยืนยันแทบไม่มี. สังเกต: SL บน fill bar นับได้เสมอ (ราคาต้องผ่าน entry ก่อนถึง SL)
— ความ asymmetry นี้แปลว่าโค้ดเดิม optimistic ฝั่งเดียว. คอมเมนต์ "pessimistic" (`:6,:43`) ครอบเฉพาะเคส
SL+TP ชนกัน ไม่ครอบเคสนี้ → **backtest ไม่ pessimistic อย่างที่อ้าง.**

### Issue 2 — Touch-fill optimism ซ้ำอีกชั้น. **CONFIRMED (compounding)**
`a1_scalp_backtest.py:71-73` — fill เมื่อ `low[j] <= bl` ที่ราคา `bl` เป๊ะ. limit จริงที่ exact touch มัก
ไม่ fill (ต้อง trade-through) + เจอ adverse selection (ไม้ที่ fill คือไม้ที่ราคาทะลุ). strict `<` อย่างเดียว:
+0.076 → +0.026 (PSR 0.85, N หาย 102). รวมกับ Issue 1 (C2b): **−0.068**; ถ้าต้องทะลุ 31p: **−0.101**.

### Issue 3 — Null ในสคริปต์พังทั้งสองทาง. **CONFIRMED (null invalid) — แต่ null ที่ถูกก็ไม่ช่วย A1**
`a1_scalp_backtest.py:81` — null สุ่มแค่ index (`ei = rng.randint(...)`) แต่**คงราคา entry/SL/TP ของ box
เดิม (absolute level)**. ทอง 1230→4017: ที่บาร์สุ่ม ราคาห่าง level เป็นพันจุด → BUY ต่ำกว่าตลาด insta-TP
(+1.2R), SELL insta-SL. วัดจริง: **1931/1944 (99%) ของ null trades จบภายใน entry bar เดียว** → expR
+0.141 = ขยะ, การสรุป "A1 แพ้ null" จาก null นี้ = โมฆะ. null ที่สร้างใหม่:
- **F1 re-anchored random-time** (ระยะ SL/TP เดิม, entry ที่ close ของบาร์สุ่ม, 20 seeds): mean −0.048
  [p5 −0.084, p95 +0.006] → base +0.076 "ชนะ" — แต่ base ถูก inflate ด้วย Issue 1/2 จึงไม่ valid;
  variant ที่แก้ fill แล้ว (−0.014 fair) ก็แค่เสมอ null-band ขอบบน.
- **F3 block-bootstrap** (48-bar blocks ของ ΔH/ΔL/ΔC, รัน strategy เต็มบน path สังเคราะห์ 15 เส้น —
  ทำลาย structure ยาว, คง intrabar): null mean **+0.057**, p95 **+0.088** → base +0.076 **ไม่เกิน p95.**
  แปลว่า ~75% ของ +0.076 เป็น mechanics (fill artifact + geometry) ที่ path สุ่มก็ให้ได้.
- F2 direction-flip ที่ fill เดียวกัน (breakout แทน fade): −0.269 → fade ดีกว่า breakout ที่ box edge
  ก็จริง แต่ "ดีกว่ากลยุทธ์ที่แย่มาก" ≠ +EV.

### Issue 4 — Edge กระจุกใน Q1 (2014-17) = regime/spec artifact. **CONFIRMED**
base: Q1 sumR **+106.9 จาก +148.4 ทั้งหมด (72%)**, WR 75.3%, expR +0.614 — เทียบ Q2 +0.022 /
Q3 +0.040 / Q4 +0.015 (PSR 0.61-0.80 = noise). สาเหตุเชิงกล: `WIDTH_MIN=2500` เป็น **จุดคงที่** —
ที่ราคา ~1200 (2014-17) box 2500p = ~2% ของราคา (range แท้ที่หายาก) แต่ที่ 4000 (2025-26) = 0.6%
(เกิดเป็นปกติ) → spec คนละความหมายข้ามยุค, ไม่ stationary. และภายใต้ strict fill Q1 เหลือ N=80,
expR +0.112, PSR 0.82 — เกินครึ่งของ Q1 "edge" คือ exact-touch fills ที่ไม่มีจริง. OOS(40%, ≥2021-10):
base +0.018 (PSR 0.72), realistic **−0.084 (PSR 0.00)**. ทศวรรษล่าสุด = −EV ชัดเจน.

### Issue 5 — PSR 1.00 เกินจริงเล็กน้อยจาก overlap; ไม่ใช่ตัวตัดสิน. **CAVEAT**
COOL=6, MAXHOLD=60 → ไม้ซ้อนเวลากันได้ (concurrency mean 1.2, max 3; autocorr lag1 +0.11) →
effective N ≈ 1206 จาก 1944. PSR(Neff) = 0.992 — ยังสูง แต่ประเด็นนี้รองจาก Issue 1/2 (PSR ที่ 1.00
เป็นของ artifact series อยู่ดี; series ที่แก้แล้ว PSR = 0.00-0.28).

### Issue 6 — Multiple testing / specification search. **CONFIRMED (uncorrected)**
params อย่างน้อย 7 ตัว (DON 20, WIDTH_MIN 2500, TP 0.30, SL 0.25, FILL_WIN 6, COOL 6, MAXHOLD 60 —
`a1_scalp_backtest.py:27-33`) ไม่มี trial log + Phase 0 เองคือ selection step (gate regime → พัง →
สลับเป็น gate structure ที่ "81% proxy" — `regime_dwell_phase0.py:132-150`) ทับบน prior ~12 กลยุทธ์
ที่ตายแล้ว. sweep เพื่อน: DON=10 ให้ +0.118/OOS +0.091 "ดีกว่า" config ที่เลือก → ผิว search ยังมี
"ผลดีกว่า" ให้เก็บ = คลาสสิก snooping surface (ทุกค่าบน optimistic fill; แก้ fill แล้วตายหมดเหมือนกัน).
ไม่มี Deflated-Sharpe/PBO. โชคดีที่ไม่ต้อง deflate — แก้ fill อย่างเดียวก็ −EV แล้ว.

### Issue 7 — Cost model. **PASS (ไม่ใช่ตัวฆ่า) / RR geometry ถูกต้อง**
avg sl_pips = 1254 → cost@31p = 0.025R/ไม้ (เล็ก). breakeven net (1+cR)/(1+RR) = 46.6% ✓ ตรงกับ
สคริปต์ (`a1_scalp_backtest.py:106`). RR = 0.30w/0.25w = 1.2 ✓ (entry ที่ edge, SL/TP สมมาตรตามสูตร).
แต่ WR-vs-breakeven ใช้ตัดสินไม่ได้เมื่อมี TIME exits (R ไม่ใช่ ±1/+1.2 เสมอ) — expR คือตัวจริง และ expR
หลังแก้ fill < 0 ทุก cost (31/45/60p). หมายเหตุ: 31p เป็น floor; ช่วงข่าว spread กว้างกว่า → แย่กว่านี้อีก.

### Overfit/artifact signatures found
Same-bar look-ahead ที่ fill bar (28% ของ TPs) เป็นแหล่ง +EV ทั้งหมด (1); touch-fill ที่ราคา limit เป๊ะ (2);
null level-confounded 99% insta-exit → เทียบอะไรไม่ได้ (3); edge 72% อยู่ใน quartile เดียวเมื่อ 9-12 ปีก่อน
บน spec จุดคงที่ที่ความหมายเปลี่ยนตามราคา (4); ไม่ log trials + Phase-0 pivot = selection (6).
สอดคล้อง prior ของ repo: retail TA ไม่มี directional edge บนทอง — mean-reversion ที่ box edge ก็เช่นกัน.

### Actionable recommendations
1. **A1 ตายด้วย — DO NOT shadow, DO NOT enable.** ไม่ใช่ "edge อ่อนรอ data" แต่เป็น artifact ที่พิสูจน์แล้ว:
   แก้ fill model แล้ว −EV ทุก period ทุก cost (OOS −0.082, ยุคปัจจุบัน −0.096). shadow มีแต่ค่าเสียโอกาส.
2. ถ้าจะรีไซเคิลอะไร: F2 บอกว่า **fade > breakout ที่ box edge** (−0.014 vs −0.269 ที่ fill เดียวกัน) —
   เป็น structural fact เกี่ยวกับทอง H1 แต่ **ยังไม่พอเป็น +EV หลัง cost**; อย่าตีความเป็น edge.
3. แก้ harness ก่อนใช้ทดสอบตัวถัดไป (ไม่งั้น false positive ซ้ำ): (a) ห้าม TP บน fill bar เว้น close ยืนยัน,
   (b) fill ต้อง trade-through (`<` หรือ edge−buffer), (c) null ต้อง re-anchor ราคา หรือ block-bootstrap
   path แล้วรัน strategy เต็ม, (d) spec width เป็น % ของราคา/ATR ไม่ใช่จุดคงที่, (e) log trial count.
4. `regime_dwell_phase0.py` "structure-gate 81% reversion proxy" ต้องถูกอ่านใหม่: proxy hit-rate ไม่ใช่
   trade EV (บทเรียนเดียวกับ EDGE 2 KDE ข้างบน) — และตอนนี้ trade EV จริงพิสูจน์แล้วว่า ≤ 0.

**GO/NO-GO (live/shadow enablement): NO-GO — REFUTED.** A1 ไม่มี edge; +0.076R คือ look-ahead ที่
fill bar + touch-fill optimism บวก quartile เดียวจากยุค 2014-17 ที่ตายไปแล้ว. ไม่มี live flag ผูก A1
อยู่ ณ วันนี้ (ตรวจ `config.py` + grep ทั้ง repo: พบแค่ 2 research scripts) — ให้คงสถานะนั้นไว้.
