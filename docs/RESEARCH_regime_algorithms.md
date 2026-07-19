# RESEARCH — Regime-Routed Trading Algorithms: Theory, Math, Detection (for XAUUSD bot)

**2026-07-19. รากฐานทฤษฎีสำหรับ `DESIGN_minimal_ai_regime_router.md`.**
สังเคราะห์จาก deep research (fan-out 27 sources → 122 claims). **หมายเหตุ:** verify/synthesis phase ชน session
limit → synthesize เองจาก **claims ที่ verify แล้ว (✅ 3-0)** + **claims จาก primary source ที่ยังไม่ได้ verify
เชิงปฏิปักษ์ (📄 sourced)** + ความรู้ quant + งาน HMM/harness ที่เรา validate เอง. honesty label ต่อข้อ.

> **⚠️ กฎเหล็กของทั้งเอกสาร:** ทฤษฎีเหล่านี้พิสูจน์บน **portfolio หลายสินทรัพย์ / equities รายวัน / อดีต** —
> **ไม่ใช่ intraday gold เดี่ยว** และ **edge เสื่อมตามเวลา** (session เราพิสูจน์: simple algo ไม่มี edge บน gold).
> ใช้เป็น **สมมติฐานที่ต้อง validate** (intrabar+cost+DSR+PBO+null) ไม่ใช่สูตรสำเร็จ.

---

## 0. Cross-cutting foundation (ใช้ทุก regime)
- **EV / breakeven:** เข้าเมื่อ `P(win)·RR − (1−P) > 0` + margin; breakeven WR = `1/(1+RR)`. 📘
- **Kelly sizing:** `f* = (b·p − q)/b` (b=RR, p=win prob, q=1−p) จาก max `E[log wealth] = p·ln(1+bf)+q·ln(1−f)`;
  ใช้ ¼–½ Kelly + cap fixed-fractional ≤2%. 📄[paperswithbacktest/Thorp]
- **Vol-target sizing:** size ∝ 1/σ (inverse-vol) — TSMOM ใช้ position = `0.60%/σ_{t-1}` ✅[verified: MOP 2012]
- **Validation (บังคับ):** **Deflated Sharpe** หัก N trials + non-normality; **45 trials บน 5 ปี → best Sharpe ≥1.0
  จากโชคล้วน** 📄[Bailey-LdP DSR, SSRN 2460551] → **regime library = ลอง strategy เยอะ = multiple-testing สูง**
  → ต้อง DSR/PBO/purged-CV/min-N (pypbo มี Python impl 📄). exit: MFE/MAE distribution. 📘

---

## 1. TRENDING / MOMENTUM

**(1) ทฤษฎี:** Time-Series Momentum (TSMOM) — return อดีตของสินทรัพย์เองทำนาย return อนาคต (positive
autocorrelation ระยะกลาง). ต่างจาก cross-sectional momentum (Jegadeesh-Titman) ที่เทียบข้ามสินทรัพย์.

**(2) Algorithm:** **sign(trailing return)** — long ถ้า past-k return > 0, short ถ้า < 0. + MA-crossover,
Donchian breakout (ทะลุ N-bar high/low), MACD. ✅[verified 3-0: MOP 2012]

**(3) Math:**
- rule: `signal = sign(r_{t−k,t})`, k=12 เดือน (บน daily/futures). ✅
- sizing: `position = target_vol / σ_{t−1}` (เช่น 0.60%/σ). ✅
- ATR exit/SL: `SL = k·ATR`, `TP = RR·SL` (self-scale ตาม vol). 📘
- Kalman-filter trend: state = [level, slope], ประมาณ trend แบบ adaptive (ลด lag เทียบ MA). 📄

**(4) Detection:** Hurst H>0.5 (persistent); Efficiency Ratio (Kaufman) สูง; ADX > 25 (trend strength). 📄

**(5) Failure modes:** **whipsaw ใน range/choppy** — H<0.42 trend-following ทำ **−0.43%** vs buy-hold +2.61%
📄[apjm]. edge เสื่อม + crowded. **intraday ≠ 12-month** (TSMOM พิสูจน์ที่ระยะเดือน บน futures หลายสินทรัพย์ —
การเอามาใช้ intraday gold เดี่ยว = สมมติฐานที่ยังไม่พิสูจน์). ✅[MOP: works ระยะ ~1 ปี แล้ว partial reversal]

**(6) Sources:** Moskowitz-Ooi-Pedersen (2012) *Time Series Momentum* ✅ · Jegadeesh-Titman · Kaufman · Ehlers.

---

## 2. MEAN-REVERTING / RANGING

**(1) ทฤษฎี:** residual/spread เป็น **Ornstein-Uhlenbeck** (stationary AR(1)) — ดึงกลับสู่ mean.

**(2) Algorithm:** **s-score contrarian** — เข้าสวนเมื่อ |s| สุดขั้ว, ปิดใกล้ equilibrium (Avellaneda-Lee stat-arb).
+ Bollinger-band fade, RSI fade. ✅[verified 3-0]

**(3) Math:** ✅[verified 3-0: Avellaneda Lecture 6 + Stat-Arb US Equities]
- OU: `dX = κ(m − X)dt + σ·dW`  (κ = speed, `1/κ` = characteristic time, half-life = `ln2/κ`)
- s-score: `s = (X − m)/σ_eq`, `σ_eq = σ/√(2κ)`
- entry/exit thresholds (empirical): **open long s<−1.25, open short s>+1.25, close long s>−0.50, close short s<+0.75** (asymmetric)
- **gate:** trade เฉพาะเมื่อ mean-reversion เร็วพอ: `κ > 252/30 ≈ 8.4` (half-life <1.5 เดือน); reject ถ้า AR(1)
  coef `b→1` (ช้าเกิน) ✅. estimated: κ≈40, half-life ~6-7 วัน (US ETF 2006-07) ✅

**(4) Detection:** Hurst H<0.5 (anti-persistent); ADF test (reject unit-root = stationary → tradable);
Variance-Ratio < 1; half-life สั้น. 📄

**(5) Failure modes:** **แตกเมื่อ breakout/trend** (spread ไม่กลับ = ขาดทุนหนัก, tail risk). **edge เสื่อมชัด:**
Sharpe **1.44 (1997-2007) → 0.9 (2003-2007)** net 10bps round-trip; บาง sector **Sharpe ลบ 2005-2007** ✅[verified].
gold เดี่ยวไม่มี "residual" ตามธรรมชาติ → ต้องนิยาม spread (เช่น gold − β·DXY − γ·real-yield = residual) ก่อนใช้ OU.

**(6) Sources:** Avellaneda-Lee *Statistical Arbitrage in the US Equities Market* ✅ · Chan *Algorithmic Trading* · Ornstein-Uhlenbeck (1930).

---

## 3. HIGH-VOLATILITY / RISK-OFF / CRISIS

**(1) ทฤษฎี:** volatility **clustering + persistence** → GARCH family. vol ทำนายได้ (ต่าง direction). regime มี
low/high-vol states ชัด.

**(2) Algorithm:** **inverse-vol targeting** (ลด exposure เมื่อ σ สูง) + **defensive stand-down** ใน high-vol state.
ไม่ใช่ directional — เป็น risk overlay.

**(3) Math:**
- **GARCH(1,1):** `σ²_t = ω + α·ε²_{t−1} + β·σ²_{t−1}` (α+β = persistence, ~1 = สูงเกิน → smooth เกิน 📄[Marcucci])
- vol-target: `size = target_vol / σ̂_t`
- realized vol: `σ = √(Σ r²)` rolling

**(4) Detection:** HMM/Markov-switching vol regime (เรา validate แล้ว!); GARCH σ̂ สูง; VIX/realized-vol สูง.

**(5) Evidence (📄 sourced, ยังไม่ verify เชิงปฏิปักษ์):**
- vol-targeting ลด **crisis maxDD 48% → 31%**, Sharpe 0.23→0.34, skew −0.88→+0.03 (Canadian pension proxy 1990-2010) 📄[Hillsdale]
- HMM 3 vol-regime: **high-vol 8%เวลา (σ33%, ret −38%/yr)** · medium 45% (σ12%, +7%) · **low-vol 47% (σ6%, +19%)**
  → **premium ส่วนใหญ่อยู่ใน low-vol** 📄[Hillsdale] — **ตรงกับ HMM ทองเรา: RISK-OFF ทอง −10%/yr!** ✅[งานเรา]
- MRS-GARCH ชนะ GARCH ที่ 1-day horizon 📄[Marcucci]

**(6) Sources:** Bollerslev (GARCH 1986) · Marcucci (MRS-GARCH) · Hillsdale (vol-target/HMM) · Hamilton.

---

## 4. BREAKOUT / VOLATILITY-EXPANSION (regime transition)

**(1) ทฤษฎี:** vol **หด (contraction) → ขยาย (expansion)** เป็นวงจร — squeeze ก่อน breakout.

**(2) Algorithm:** **Bollinger-band squeeze** (band แคบผิดปกติ → รอ breakout ทิศ), ATR-compression breakout,
range-expansion (ทะลุ N-bar range หลัง compression). + **false-breakout filter** (confirm buffer/vol/volume). 📄

**(3) Math:**
- squeeze: BB width `(upper−lower)/mid` ต่ำ percentile (เช่น <20th) หรือ BB อยู่ใน Keltner channel
- ATR compression: ATR ต่ำ rolling percentile → energy สะสม
- breakout: close > range-high + β·ATR (buffer กัน false break)

**(4) Detection:** BB-width / ATR percentile ต่ำ = pre-breakout; vol expansion เริ่ม = trigger.

**(5) Failure modes:** **false breakout สูง** (session เราเจอ: breakout algo บน gold/BTC ไม่มี edge net-cost);
squeeze ไม่การันตีทิศ. ต้อง confirm + net-cost.

**(6) Sources:** Bollinger (Bollinger Bands) · Kaufman *Trading Systems and Methods* · StockCharts (squeeze) 📄.

---

## 5. REGIME DETECTION (หัวใจของ router)

**(1) HMM / Markov regime-switching (Hamilton 1989):** latent state `s_t` = 2-state Markov chain,
`Pr(s_t=j | s_{t−1}=i) = p_ij`, infer ผ่าน **Hamilton filter** (Kalman-like recursion). ✅[verified 3-0]
→ **เราสร้าง+validate แล้ว** (`hmm_regime.py`/`hmm_risk_regime.py`, ผ่าน 4/4).

**(2) Hurst exponent:** `Var(τ) ∝ τ^(2H)` — H<0.5 mean-revert, >0.5 trend, =0.5 random walk. 📄[Chan]
- ⚠️ **estimation ไม่น่าเชื่อถือ:** R/S **bias ขึ้น** (true-0.5 walk → H≈0.60!); DFA เที่ยงกว่า (center 0.50) แต่ variance 2x;
  GHE variance ต่ำสุด. threshold ต้อง Monte-Carlo calibrate ต่อ estimator (DFA: <0.42/0.42-0.58/>0.58) 📄[apjm/arxiv]
- **intraday ยิ่งไม่น่าเชื่อ** (skill เราเตือน) → ใช้เป็น **1 input ของ router ไม่ใช่ switch เดี่ยว**

**(3) Efficiency Ratio (Kaufman):** `ER = |net change| / Σ|change|` ต่อ N bar — ~1 trend, ~0 chop. เราใช้ใน harness แล้ว. 📄

**(4) ADX:** > 25 = trending, < 20 = ranging (trend strength ไม่ใช่ทิศ). 📄[StockCharts]

**(5) Failure modes:** ⚠️ **regime detection เอง overfit ได้** — threshold estimator-specific; regime "รู้ทีหลัง" (lag);
**edge conditional + reverses** (H<0.42 trend-follow −0.43% vs +2.61% buy-hold) 📄. → **fuse หลาย signal + validate**.

**(6) Sources:** Hamilton (regime-switching) ✅ · Chan (Hurst) · Kaufman (ER/KAMA) · arxiv 1201.4786 (Hurst estimators).

---

## 6. สรุป: REGIME → ALGO → MATH → DETECTION → SOURCE → FAILURE
| regime | algorithm | core math | detect | source | failure mode |
|--------|-----------|-----------|--------|--------|-------------|
| **TREND** | sign(trailing) / Donchian / MA-cross | `sign(r)`, ATR SL, Kalman | H>0.5 · ER↑ · ADX>25 | MOP 2012 ✅ | whipsaw ใน chop (−0.43%) |
| **MEAN-REVERT** | s-score contrarian / BB-fade | OU `dX=κ(m−X)dt+σdW`, s=(X−m)/σ_eq, \|s\|>1.25 | H<0.5 · ADF · VR<1 · half-life สั้น | Avellaneda-Lee ✅ | trend breakout = tail loss; edge เสื่อม |
| **HIGH-VOL/RISK-OFF** | inverse-vol / stand-down | GARCH σ²=ω+αε²+βσ², size=tgt/σ | HMM vol-regime · VIX↑ | Bollerslev/Hillsdale 📄 | ทองอ่อน −10%/yr (งานเรา ✅) |
| **BREAKOUT** | squeeze → range-expansion | BB-width/ATR percentile + buffer | BB-width ต่ำ | Bollinger/Kaufman 📄 | false-break สูง (งานเรา: no edge) |
| **(router)** | fuse | HMM (Hamilton filter) + Hurst + ER + ADX | — | Hamilton ✅ | detection overfit; lag; reverses |

---

## 7. นัยต่อ design เรา (P1)
1. **ที่เรามี+validate แล้ว:** HMM regime (router core §5) ✅ · ER/ATR/S-R math (chart_watcher) · harness (validate).
2. **gold เดี่ยว intraday ต้องระวัง:** TSMOM = multi-asset ระยะเดือน; stat-arb ต้องมี residual (gold − β·DXY − γ·real-yield);
   ทฤษฎีเหล่านี้ **ไม่ได้พิสูจน์บน gold M15** → ทุก algo **ต้องผ่าน gauntlet เอง** (session เราแสดง breakout/MR บน gold = no edge).
3. **ตัวที่มีหลักฐานแข็งสุด = vol/risk overlay** (inverse-vol, stand-down high-vol) — เพราะ **vol ทำนายได้** (§3, ตรงงาน HMM เรา)
   ≠ directional (ที่พิสูจน์แล้วว่ายาก). → **design ควรเน้น risk/sizing overlay ก่อน directional algo**.
4. **regime library = multiple-testing เยอะ** → DSR/PBO เข้มพิเศษ; min-N ต่อ regime; ต่อ algo shadow→validate→enable.

เกี่ยว: `DESIGN_minimal_ai_regime_router.md` · skill `quant-systematic-trading` (+`references/regime-and-volatility.md`) ·
`VALIDATION_CHECKLIST.md` · harness ใน `scripts/`. [[entry-exit-quant-overhaul]].
