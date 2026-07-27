# DESIGN — ML Algo Selector (meta-learning เลือก algo จาก performance รวมข้ามผู้ใช้)

สถานะ: **DRAFT — plan-first, ยังไม่โค้ด** · research อ้างอิงเติมจาก workflow `wf_28b93722-222`
วันที่: 2026-07-27

## 1. Idea (จาก user)
ใช้ ML เลือกว่าจะเข้า **algo ไหน** โดยรวมสถิติการเข้า order ของทุก algo **ข้ามผู้ใช้ทุกคน** →
vote ว่าควรเข้า algo ไหน จาก algo ที่เคยเข้าแล้วได้กำไร (ต่อ regime).

## 2. Reframe เชิงทฤษฎี
= **Algorithm selection / online learning with expert advice / contextual bandit**.
ไม่ใช่ "ทำนายราคา" (CORE INVARIANT เดิมยังอยู่: entry = algo คำนวณจาก data) — เป็น **layer เลือกว่า
รอบนี้เชื่อ algo ไหน** (meta-labeling / router). SELECTION (uncertain, ML) แยกจาก EXECUTION (algo เดิม, deterministic).

ทฤษฎีที่ใช้ได้ (จาก skill quant-systematic-trading + research):
- **Contextual Multi-Armed Bandit + Thompson Sampling** — arm=algo, context=regime/symbol/vol,
  reward=realized R (net cost). เลือก+explore/exploit อัตโนมัติ, Bayesian จัดการ uncertainty.
- **Prediction with Expert Advice / Hedge (multiplicative weights)** — vote ถ่วงน้ำหนักตามกำไรอดีต + regret bound.
- **Meta-labeling (López de Prado)** — ML ตัดสิน take/skip ต่อ signal ของ primary algo.
- **Hierarchical Bayesian (partial pooling)** — วิธีรวมข้ามผู้ใช้ที่ถูก: shrink per-user → global ถ่วงตาม N.

## 3. กับดัก (ทำ idea นี้พังถ้าไม่แก้) + วิธีแก้
| กับดัก | ผล | แก้ |
|---|---|---|
| **Winner's curse / selection bias** | vote เลือกตัวชนะอดีต ≠ ชนะอนาคต (ตัวฆ่าอันดับ 1) | deflated Sharpe ต่อจำนวน algo, min-N, ไม่ greedy (bandit ยัง explore) |
| **Correlated users → effective-N พอง** | 1000 ไม้จาก 100 คนบน GOLD# ≠ 1000 อิสระ | นับ **effective-N** (cluster ต่อ user/symbol/เวลา) ไม่ใช่ราว count; hierarchical shrinkage |
| **Non-stationarity** | algo ที่เคยกำไรตายเมื่อ regime เปลี่ยน | condition on regime + decay/rolling window; bandit ปรับตาม |
| **Survivorship** | เห็นแค่ user ที่ยังรัน (คนเจ๊งเลิก) → bias สูงเกิน | เก็บ user ที่เลิกด้วย / ระวังตีความ |
| **Simpson's paradox** | algo ดีรวม แต่แย่รายregime | **condition on regime เสมอ** (ห้าม pool ข้าม regime) |
| **ไม่ calibrate** | vote = raw win-count ไม่ใช่ probability | calibrate P(กำไร) (Platt/isotonic) ก่อนใช้ |

## 4. สถาปัตยกรรม (leverage ของที่มี)
ระบบมีแล้ว: `real_edge` ต่อ (algo,symbol) + **by_regime + by_session** · `shadow_matrix` · regime detect
(`regime_lib`) · DB (`trades` มี comment=algo + account_login = cross-user) · `algo_registry`.

```
[ทุก user] real_fills/DB (algo, symbol, regime, realized R, account_login)
        │  aggregate ข้าม user (DB) + effective-N + hierarchical shrinkage
        ▼
[offline] expectancy + deflated-sig ต่อ (algo, regime)  ← "vote แบบมีวินัย"
        │  (shadow: โชว์ Shadow Matrix by_regime ที่มีอยู่)
        ▼
[online] Contextual Thompson Sampling: regime ปัจจุบัน → sample posterior ต่อ algo → เลือก (ยัง explore)
        │  shadow-first: log ว่าจะเลือก algo ไหน vs ที่รันจริง
        ▼
[enable] ทีละ segment (regime/คู่ มั่นใจสุดก่อน) · kill switch · risk guard เดิมคง
```

## 5. Milestones (validated-or-off)
- **P0 — data**: ยืนยัน real_fills เก็บ (algo, regime, R, account_login) ครบ + aggregate cross-user ผ่าน DB.
  *(ส่วนใหญ่มีแล้ว — real_edge by_regime + DB comment/account_login)*
- **P1 — offline stats (shadow)**: คำนวณ expectancy ต่อ (algo,regime) ข้าม user + **effective-N + deflated significance**.
  แสดงใน Shadow Matrix (มี by_regime อยู่แล้ว). 0 order. = พิสูจน์ว่า "vote" มีสัญญาณจริงก่อน.
- **P2 — online selector (shadow)**: contextual Thompson sampling → log pick vs actual. ยังไม่คุม entry จริง.
- **P3 — enable ทีละ segment**: selector คุมเฉพาะ combo ที่ผ่าน gauntlet · most-confident first · flag + kill switch.

## 6. Validation gates (ต้องผ่านก่อน enable — §6 skill)
- min-N ต่อ (algo,regime) หลัง effective-N correction (≥100 scalp / ≥20 swing)
- deflated Sharpe > bar (แก้ multiple-testing ต่อจำนวน algo×regime ที่แข่ง)
- OOS / purged-CV + PBO · net of cost · plateau ไม่ใช่ cliff
- calibration: reliability diagram ของ P(กำไร) ที่ selector ใช้

## 7. Non-goals
- ไม่ทำนายราคา/ทิศทาง (SELECTION เท่านั้น; entry ยังเป็น algo เดิม) — CORE INVARIANT
- ไม่ pool ข้าม regime (Simpson) · ไม่ raw-count vote (correlated) · ไม่ greedy (winner's curse)
- ไม่แตะ money management / _run_gates / DecisionMaker path เดิม

## 8. Research findings (workflow wf_28b93722-222 · 4/6 agents + synth)

**Verdict (ทั้ง 3 หัวข้อชี้ทิศเดียว):** idea ทำได้จริง มีทฤษฎีรองรับ **แต่คุณค่าคือ "ชั้นกรอง/ลด variance กัน overfit"
ไม่ใช่เครื่องปั่น alpha** — เพดานอยู่ที่ edge ของ primary algo. งาน wisdom-of-crowds ชี้ improvement ระดับ
**หลักหน่วย %** (ไม่ใช่หลายเท่า) และหดอีกเมื่อ trader correlated. **ยังไม่ควรเปิด live ตอนนี้** เพราะ n ต่อเซลล์
น้อยเกิน (ตรง memory: 97% กำไรจากไม้เดียว n=6) → ต้องสะสมไม้ **อิสระ** (หลังปรับ ESS) อีกมากก่อน fit.

**Pipeline 4 ชั้น (คนละชั้น ไม่ใช่ทางเลือกแข่งกัน):**
- **A. Meta-labeling** (López de Prado, AFML Ch.3) — algo=primary (ให้ side) → meta-model ทำนาย P(algo กำไร | regime,features) = take/skip. *primary ต้องมี edge ก่อน ไม่งั้นแค่ลดจำนวนไม้*
- **B. Hierarchical Bayes / empirical-Bayes shrinkage** (beta-binomial, user=random effect) — **ทำก่อนสุด, 0 token, compute-in-code**. shrink edge ต่อ (algo×symbol×regime) เข้า prior ตาม n (James-Stein ลด MSE เมื่อ n น้อย) = "wisdom-of-crowds ที่ถูกทางสถิติ"
- **C. Discounted/Change-detection Thompson Sampling** — arm=algo, prior=posterior จาก B (per regime). **"vote" ที่ถูก = probability-matching (posterior-weighted) + bagging seeds/folds — ไม่ใช่ majority/mean ดิบ** (ผิด ESS + selection bias)
- **D. GATE (ยาม winner's curse)** — เซลล์ผ่านเมื่อ **DSR>0.95 AND haircut BHY/FDR (N=#cells) AND PBO ต่ำ** ประเมินด้วย **Purged CV + embargo/CPCV**. คาดว่าตอนนี้ตกเกือบหมด = ถูกต้อง

**กับดักเพิ่มจาก research (นอกจาก §3):**
- **ESS collapse**: ปรับ `ESS ≈ N/(1+(N−1)·ρ̄)` ก่อนคำนวณ CI · de-dup เป็น "signal event" ไม่ใช่ "fill"
- **Sanity haircut 25–60%** จาก in-sample edge ก่อน sizing (McLean & Pontiff 2016: anomaly ตก ~26% OOS, ~58% หลังตีพิมพ์)
- **calibration**: isotonic (n พอ) / Platt (n น้อย) — เฝ้า reliability + Brier
- **herding/copy-trading**: ρ̄ จริง → อย่าเชื่อ "จำนวนคน" · **normalize เป็น R-multiple ไม่ใช่บาท** (ต่าง broker/lot)
- **label**: features ณ เวลาเข้าไม้เท่านั้น · ใช้ `trades.json` ไม่ใช่ MT5 magic (broker reset)

**ลำดับคุ้มค่า/ความเสี่ยง:** (1) hierarchical shrinkage ก่อน (0 token) → (2) meta-labeling → (3) DSR+PBO guard บังคับ.
ใช้ซ้ำได้: `scripts/multiple_testing_demo.py`, skill `quant-systematic-trading`, pattern SHADOW=ON.

**อ้างอิงหลัก:**
- López de Prado (2018) *AFML Ch.3 Meta-Labeling* · QuantConnect "Not a Silver Bullet" · Hudson&Thames toy example
- Niculescu-Mizil & Caruana (ICML 2005) *Predicting Good Probabilities* (isotonic vs Platt)
- Albert&Hu *Bayesian Hierarchical Ch.10* · D.Robinson *empirical-Bayes beta-binomial* · Efron&Hastie *James-Stein (CASI Ch.7)*
- Portfolio Optimizer *Effective Number of Bets* · Doering et al. (Mgmt Sci 2020) *Copy Trading*
- arXiv 2305.10718 *Discounted TS* · 2009.02791 *Change-Detection TS*
- Bailey & López de Prado (2014) *Deflated Sharpe* · Bailey et al. *PBO/CSCV* · Harvey&Liu (2015) *Haircut Sharpe* · Harvey,Liu,Zhu (2016) *t-stat→3.0* · McLean&Pontiff (2016)

_(research: 4/6 agents สำเร็จ — bandit + expert-advice fail schema retry แต่ Thompson/bandit ครอบใน crowd-agg+synth)_
