# Learning Roadmap — พัฒนา XAUUSD AI Trading System ให้อยู่รอด + ดีขึ้นจริง

> เขียน 2026-07-18 หลัง session ที่ทดสอบหา edge 6 ทาง**ไม่เจอสักทาง** (BTC / gold structure /
> intermarket lead / LLM confidence) แต่ได้ **validation harness + drift-control + HMM regime +
> vol-sizing** มา. roadmap นี้ผูกกับสิ่งที่**เจอจริงในโปรเจคนี้** ไม่ใช่ curriculum ทั่วไป.

## หลักการก่อนเริ่ม (อ่านก่อนทุกครั้ง)
1. **"อยู่รอด" ≠ "หา edge เจอ"** — อยู่รอด = จัดการความเสี่ยง + ไม่หลอกตัวเอง ระหว่างที่หา.
2. **Retail ส่วนใหญ่ไม่มี edge จริง** — นี่คือ base rate ไม่ใช่ความล้มเหลว. คนรอด = ไม่ระเบิดพอร์ตระหว่างหา.
3. **เรียนตามลำดับผลต่อการรอด** — ปกป้องทุน (1) > ไม่หลอกตัวเอง (2) > เข้าใจว่าอะไรทำนายได้ (3) > หา signal.
   คน retail ส่วนใหญ่ทำกลับด้าน (ทุ่มหา signal, ละเลย risk+validation) → ตาย.
4. **เรียนแบบ hands-on บนโปรเจคนี้** — ทุก track มี "แบบฝึกบนระบบเรา" ที่ใช้ harness/data ที่มีอยู่แล้ว.

---

## Track 1 — Risk management & survival math ⭐ ด่วนสุด
**ทำไม (จาก session):** บอทมี expectancy **−103฿/ไม้** (WR 20%), บัญชี **2,147฿** = ตายทางคณิตศาสตร์ถ้าไม่คุม.
นี่คือสิ่งที่กำหนดการรอด **โดยไม่เกี่ยวกับการทำนายเลย**.

**เรียน:**
- Expectancy / R-multiples: `E = WR·avgWin − LR·avgLoss`; breakeven WR = 1/(1+RR)
- **Risk of ruin** — สูตร + ทำไมบัญชีเล็ก + expectancy ลบ = ตายแน่นอน (แค่เรื่องเวลา)
- Position sizing: fixed-fractional (0.5-2%/ไม้), fractional Kelly (เพดาน ไม่ใช่เป้า), ATR/vol-target
- Drawdown math: ทำไม −50% ต้อง +100% ถึงกลับ; daily-loss limit ควรตั้งเท่าไร (30% = อันตราย)
- Path dependency: variance ระยะสั้นฆ่าได้แม้ expectancy บวก

**Resources:** Van Tharp *Trade Your Way to Financial Freedom* (R-multiple/expectancy/sizing/psych) ·
Ralph Vince *The Mathematics of Money Management* (optimal-f) · Thorp on Kelly · skill `quant-systematic-trading` §1,§4

**แบบฝึกบนระบบเรา:**
- คำนวณ risk-of-ruin ของบอทตอนนี้ (expectancy −103฿, บัญชี 2147฿, 0.02 lot) → กี่วันคาดตาย?
- รัน `scripts/analyze_losses.py` / trades.json → หา avgWin/avgLoss/WR จริง → หา sizing ที่ ruin < X%
- เข้าใจว่าทำไม `REGIME_SIZING` (RISK-OFF ลด lot) + `MAX_RISK_PCT` cap ช่วยลด ruin

**Milestone:** อธิบายได้ว่า "ที่ config นี้ พอร์ตรอดกี่สัปดาห์ที่ WR เท่านี้" + ตั้ง sizing ให้ ruin ต่ำได้เอง

---

## Track 2 — Validation rigor / ไม่หลอกตัวเอง ⭐ ตัวฆ่าอันดับ 1
**ทำไม (จาก session):** คุณเห็นกับตา — **gold DSR 0.98 → intrabar 0.05** (close-path artifact);
**"+0.030R edge" → null-test = drift-bias**. backtest เขียวหลอกตาคือสาเหตุที่ retail ระเบิดหลัง deploy.

**เรียน:**
- **Multiple testing / นับ N trials** — ลอง 20 config ได้ "significant 5%" แม้ไม่มี edge จริง
- **Deflated Sharpe Ratio (DSR)** — หัก selection over N + fat tails
- **PBO (Prob. of Backtest Overfitting) ผ่าน CSCV**
- **Purged + embargoed CV** (ทำไม k-fold ธรรมดา leak บน time series)
- **Out-of-sample / walk-forward** + ทำไมอันเดียวยัง overfit ได้
- **Fill realism** — close-path vs intrabar (บทเรียนโหลดแบก!), net-of-cost เสมอ
- **Synthetic null / empirical PBO** — รันกลยุทธ์บน data สุ่มที่ไม่มี edge → ถ้ากำไร = harness bias
- **7 sins of quant** (survivorship/look-ahead/selection/storytelling/cost/outlier/regime-change)

**Resources:** **López de Prado *Advances in Financial ML*** (bible ของ track นี้) · Bailey & LdP papers
(Deflated Sharpe SSRN 2460551, PBO/CSCV) · Luo et al. *Seven Sins* (Deutsche Bank) ·
**David Aronson *Evidence-Based Technical Analysis*** (ทำไม TA ส่วนใหญ่ = data-mining + วิธีทดสอบ rule ทางสถิติ)
· skill `quant-systematic-trading` §6 + `references/validation-rigor.md`

**แบบฝึกบนระบบเรา:**
- อ่าน + รัน `scripts/btc_validate.py`, `gold_entry_sim.py`, `gold_sim_nulltest.py` ให้เข้าใจทุกบรรทัด
- เปลี่ยน fill จาก intrabar → close-path ใน `gold_entry_sim.py` เอง → ดู DSR พองเป็น artifact
- เขียน null-test ของตัวเองสำหรับกลยุทธ์ใหม่ก่อนเชื่อผลใดๆ

**Milestone:** รับ backtest เขียวมา 1 อัน แล้ว**หา 3 เหตุผลที่มันอาจหลอก**ได้เอง + validate เป็น

---

## Track 3 — สถิติ & ความน่าจะเป็น (เครื่องมือของ 1-2)
**ทำไม:** ทุกอย่างข้างบนต้องใช้ intuition สถิติ. ไม่ต้องเก่งเลข แต่ต้องเข้าใจลึกพอไม่หลงตัวเลข.

**เรียน:** distribution + fat tails · sampling variance / ทำไม n น้อย = noise มี weight ·
correlation ≠ causation · base rate / Bayesian updating · overfitting/regularization ·
**probability calibration** (Platt/isotonic, reliability diagram, Brier, ECE) · hypothesis testing + p-hacking

**Resources:** Wasserman *All of Statistics* (reference) · Aronson (บทสถิติ ประยุกต์กับ trading ตรงมาก) ·
Annie Duke *Thinking in Bets* (decision under uncertainty — เบา แต่เปลี่ยน mindset) · skill §2 (calibration)

**แบบฝึกบนระบบเรา:**
- เข้าใจว่าทำไม **LLM confidence ไม่ informative** (WR แบน 33-54% ทุก bin) = calibration พัง (ECE สูง)
- อ่าน `agents/calibrator.py` + `scripts/fit_calibrator.py` → เข้าใจ isotonic/Platt
- เข้าใจ `MIN_N` gate ใน `analyze_decision_snapshots.py` = ทำไมต่ำกว่า 150 ห้าม fit

**Milestone:** อธิบายได้ว่าทำไม "โมเดลฉลากขึ้นบน data เดิม ≠ edge" + calibration คืออะไร ทำไมสำคัญ

---

## Track 4 — อะไรทำนายได้ vs ไม่ได้ (ความคาดหวังที่ถูก)
**ทำไม (จาก session):** เราพิสูจน์ — **direction ทำนายไม่ได้** (BTC/gold/intermarket ทุกทาง),
**volatility ทำนายได้** (HMM regime ผ่าน 4/4). รู้เส้นนี้ = เลิกไล่ล่าสิ่งที่ทำไม่ได้.

**เรียน:** Efficient Market Hypothesis (weak/semi/strong) + ข้อจำกัด · Adaptive Markets (edge เกิด/ตายตาม
การแข่งขัน) · **volatility clustering / GARCH** (ทำไม vol persist) · regime-dependence (correlation ไม่คงที่ —
real-yield-gold พังหลัง 2022) · ที่ edge จริงมาจากไหน (microstructure/flow/สิ่งที่คนอื่นไม่มี ไม่ใช่ TA บน OHLC)

**Resources:** Andrew Lo *Adaptive Markets* · Bollerslev GARCH + Halls-Moore *AAT* (ปฏิบัติ) ·
deep research เรา: `docs/reviews/quant-entry-backtest-findings.md` + intermarket findings ·
skill `references/regime-and-volatility.md` (vol≠direction insight)

**แบบฝึกบนระบบเรา:**
- อ่าน + รัน `scripts/hmm_regime.py` + `hmm_risk_regime.py` ให้เข้าใจว่าทำไมมันผ่าน validation (จับ vol)
- เข้าใจ insight: **ทองไม่ใช่ haven ง่ายๆ** (RISK-OFF ทอง −10%/yr) = regime-dependence ของจริง

**Milestone:** แยกได้ว่าไอเดียใหม่กำลังเดิมพัน "direction" (ระวัง) หรือ "vol/risk" (ทำได้) + net-of-cost ผ่านมั้ย

---

## Track 5 — Systematic strategy design (EV-driven)
**ทำไม:** หลังมี track 1-4 แล้วค่อยออกแบบกลยุทธ์**อย่างมีวินัย** (ไม่งั้นคือ track 2 พังซ้ำ).

**เรียน:** EV entry (P(win) > breakeven + margin) · calibrated probability → sizing · **exit จาก MFE/MAE**
(stop จาก MAE ของ winner, TP จาก MFE percentile, edge-decay/time exit) · regime routing · meta-labeling (LdP)

**Resources:** Ernest Chan *Quantitative Trading* + *Algorithmic Trading* + *Machine Trading* (ปฏิบัติ retail) ·
Kaufman *Trading Systems and Methods* (reference ครบ) · Sweeney (MFE/MAE) · skill §1,§3,§5 ·
เรามี design ไว้แล้ว: `docs/DESIGN_evidence_based_entry.md`, `docs/DESIGN_statistical_exit.md`, `docs/ROADMAP_quant_entry_migration.md`

**แบบฝึกบนระบบเรา (= capstone):**
- **เมื่อ decision_snapshots สะสมพอ (~150+, F1-F7 + F8 regime)** → รัน `analyze_decision_snapshots.py`
  (drift-controlled) → ทดสอบว่า **zone bounce_pct / F1-F7 มี edge เหนือ drift มั้ย** = สมมติฐานหลักที่ยังไม่ถูก refute
- ถ้ามี → build entry model + validate เต็ม (DSR/PBO/null) → shadow → enable ทีละ segment
- ถ้าไม่มี → ยอมรับ + โฟกัส risk management (track 1)

**Milestone:** ออกแบบ + validate กลยุทธ์ 1 ตัวครบ pipeline (design→collect→fit→validate→shadow→enable) เองได้

---

## Track 6 — Domain: gold / macro / execution / pipeline นี้
**ทำไม:** เข้าใจสนามที่เล่น + ระบบที่มี (secondary กว่า 1-4 แต่จำเป็นเพื่อ implement).

**เรียน:** gold drivers (real yield/DXY/GPR — regime-dependent, deep research เราสรุปไว้) · intermarket
(coincident ไม่ใช่ lead — เราพิสูจน์แล้ว) · MT5 mechanics (lot/pip/order/spread) · pipeline เรา
(ChartWatcher→Advisor→Analyst→DecisionMaker→MT5, gates, LLM cost) · HMM/regime · dashboard data flow

**Resources:** deep research เรา (intermarket + data shopping list) · World Gold Council research ·
`.claude/context/QUICKREF.md` + `docs/` ทั้งหมด · `memory/*` (system-wiring-audit ฯลฯ)

**แบบฝึกบนระบบเรา:** อ่าน continue.md ทั้ง session นี้ (a-n) = ประวัติการตัดสินใจ + บทเรียนครบ

**Milestone:** วาด flow ของ order 1 ไม้ตั้งแต่ราคาเข้า→gate→ออเดอร์ ได้ + รู้ทุก path ที่ bypass DecisionMaker

---

## Track 7 — Programming & tooling
**ทำไม:** ต้อง implement + validate เองได้ ไม่งั้นพึ่งคนอื่นตลอด.

**เรียน:** Python (pandas/numpy) · event-driven backtesting (แต่ระวัง look-ahead/fill — track 2) ·
data handling (OHLCV, alignment — บทเรียน timezone!) · reproducibility (seed, cache, version) · basic ML (sklearn)

**Resources:** Halls-Moore *Successful Algorithmic Trading* (backtester from scratch) · harness เราทั้งหมดใน `scripts/`

**แบบฝึกบนระบบเรา:** อ่าน harness เราให้เข้าใจ + เขียน probe/validation ของตัวเองได้

---

## 🗓️ ลำดับที่แนะนำ (phased)
```
เดือน 1  : Track 1 (risk/survival) + Track 2 (validation) ← ด่วนสุด, ปกป้องทุนก่อน
เดือน 2  : Track 3 (สถิติ) + Track 4 (predictable vs not) ← รากฐานความเข้าใจ
เดือน 3+ : Track 5 (strategy design) + Track 6-7 (domain/tooling) ← ค่อยสร้าง edge อย่างมีวินัย
ตลอดทาง : เก็บ decision_snapshots ต่อ (บอทรัน/DRY_RUN) → capstone track 5
```

## 🚫 Anti-patterns ที่ต้อง "unlearn" (กับดักที่เราเจอ session นี้)
- ❌ backtest เขียว = พร้อม deploy → **ต้องผ่าน DSR/PBO/intrabar/null-test ก่อน**
- ❌ ไล่หา directional signal ใหม่ตลอด → **direction ทำนายไม่ได้; ทุ่ม risk/vol**
- ❌ enable/เข้า live ตอนหลักฐานบาง (ความหวัง) → **shadow → validate → enable**
- ❌ data เยอะ/โมเดลฉลาก = edge → **ยิ่งเพิ่ม overfitting surface; validate หนักขึ้น**
- ❌ ปรับ param จน backtest สวย → **นั่นคือ overfitting (selection bias)**

## 🎯 หมุดหมายว่า "พร้อมพัฒนาระบบเองแล้ว"
1. คำนวณ risk-of-ruin + ตั้ง sizing ให้พอร์ตรอดได้เอง
2. รับ backtest เขียวมาแล้วหาช่องหลอกได้เอง + validate เต็ม
3. แยก "direction (ระวัง) vs vol/risk (ทำได้)" ของทุกไอเดีย
4. รัน capstone: validate F1-F7 entry บน decision_snapshots (drift-controlled) → ตัดสินใจด้วยหลักฐาน
5. กล้าสรุป "ไม่มี edge → ปกป้องทุน" แทน bleed ด้วยความหวัง

---
**เกี่ยว:** skill `quant-systematic-trading` (+ references) · `docs/VALIDATION_CHECKLIST.md` ·
`docs/reviews/quant-entry-backtest-findings.md` · `docs/ROADMAP_quant_entry_migration.md` · harness ใน `scripts/`
