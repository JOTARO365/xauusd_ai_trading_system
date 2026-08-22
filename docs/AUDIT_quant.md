# AUDIT_quant.md — UHAS filters on `cdc_zone` (XAUUSD D1)

Auditor: quant-adversarial pass. Posture: try to REFUTE. Default verdict = REJECT unless the edge
survives OOS + null/placebo + cost + PSR/deflation + trials-correction. Read-only; 0 orders.

Claim under test (from `scripts/uhas_ablation_cdc.py`): two UHAS-terminal features, wired as SKIP-RUN
entry filters on the live gold algo `cdc_zone` (CDC Action Zone, D1 trend-follow, long-only, exit-on-flip,
2N disaster stop), improve per-trade edge:
- (2) zone-strength (support with ≥6 touches ≤2 ATR below price): n=47, exp_R +0.931, Δ+0.205, t2.03, OOS+2.43
- (1) fair-value (long only when gold not >1σ expensive vs rolling OLS XAU~[DXY,XAG]): n=45, exp_R +0.912, Δ+0.186, t1.92, OOS+2.36

## Reproduction (numbers are real, the interpretation is not)

Command (numpy lives on the python.org 3.11 interpreter, not the WindowsApps stub — per memory note):
`"C:/Users/pornnatcha/AppData/Local/Programs/Python/Python311/python.exe" scripts/uhas_ablation_cdc.py`

Every headline number reproduces to the digit:
- baseline cdc long: n=56, exp_R +0.726, t +1.84, OOS +2.132, WR 39.3  (`uhas_ablation_cdc.py:147`)
- (2) sup≥6 tol2.0: n=47, exp_R +0.931, Δ+0.205, t +2.01, OOS +2.432  (`:165-167`)
- (1) FV z<1.0: n=45, exp_R +0.912, Δ+0.186, t +1.90, OOS +2.356  (`:152-154`)
- (3) inv-vol sizing: Δ −0.016 ; (4) no-res: best Δ+0.131 at n=22.

Leakage checks — PASS:
- `fair_value_z` fits OLS on `c[i-win:i]` and evaluates at bar `i` → causal, no future rows
  (`uhas_ablation_cdc.py:72-78`).
- `compute_cluster_map` uses `close[-lookback:]` / `close[-1]` on the trailing slice `h[w0:i+1]`,
  w0=i-599 → no future bars; current bar's OHLC is known at its close = the entry point. Causal
  (`agents/cluster_map.py:31-55`, called at `uhas_ablation_cdc.py:160-164`).
- Backtest logic `bt_cdc_abl` mirrors the live-parity `bt_cdc` (exit-on-flip, close-based 2N disaster
  stop, single round-trip cost) — faithful (`uhas_ablation_cdc.py:82-108` vs `cdc_backtest.py:46-69`).

So the code is honest. The claim still fails on statistics.

## The decisive refutation — PLACEBO (random skip of the same # of runs)

The filters are SKIP-RUN: at a fresh CDC bull-flip they accept/reject the whole run. There are 51 fresh
bull-runs in the window. Zone accepts 43/51 (drops 8); FV accepts 42/51 (drops 9). The only real question
is: **does the filter's CHOICE of which runs to drop carry information, or would dropping the same number
of runs AT RANDOM lift exp_R just as much?** (3000-seed placebo, `scratchpad/attack.py`.)

| filter | real Δexp_R | placebo Δ mean | placebo Δ 95th pct | P(random drop ≥ real) |
|--------|-----------:|---------------:|-------------------:|----------------------:|
| zone sup≥6 tol2.0 | +0.205 | +0.000 | **+0.227** | **0.088** |
| FV z<1.0          | +0.186 | +0.001 | +0.256 | **0.152** |

Both real lifts sit **below the 95th percentile of pure random run-dropping**. Randomly discarding 8 of 51
bull-runs raises exp_R by +0.23R at the 95th percentile — the "edge" is smaller than that. The feature
adds essentially nothing beyond mechanical trade-count reduction. Unadjusted placebo p = 0.088 (zone) /
0.152 (FV): neither clears even a naive 5% bar.

(A run-level bootstrap that *conditions on the already-chosen flag* gives a smaller SE and P(Δ≤0)=0.007 for
zone — but that test is invalid here: it assumes the flag was fixed in advance, whereas it was SELECTED as
the best of 11 variants, and it does not ask the placebo's question. The placebo is the apples-to-apples
adversarial null and it is the one that governs.)

## Multiple testing / deflation

11 filter variants were run in one script (4 FV thresholds + 3 zone + 1 vol + 3 no-res), and that ignores
the upstream search (which UHAS features, cdc src/sl_atr, the 2013+ window). N≥11 is a **floor**.

- Family-wise on the best variant: P(≥1 of 11 zero-edge trials beats placebo-p 0.088) = **0.637**.
  Expected number of variants at p≤0.088 under the global null = 11×0.088 ≈ **1.0**. Finding exactly one
  variant this "good" is precisely the null expectation. Bonferroni-adjusted p: zone 0.97, FV 1.00.
- Deflated absolute bar (tsmom idiom `_c_n`, `tsmom_pairs_screen.py:35-38,88`), N=11, c_N=1.62,
  bar = σ_R·(c_N+1.65)/√n: baseline needs >1.29R (has 0.726), zone >1.51R (has 0.931), FV >1.57R (has
  0.912). **None clear it.** Reproduced in `scratchpad/attack.py`.

## Small-N / power / OOS

- σ_R ≈ 2.95–3.22 (trend-following: many small −R, few large +R). SE(exp_R) ≈ 3.1/√47 ≈ **0.45R**. A
  +0.2R Δ on ~50 trades has SE ≈ 0.12–0.17R (bootstrap 0.117 / placebo 0.174) → **≤1.2σ**, inside noise.
- Baseline itself fails the system's own ROBUST bar (n=56 < 100, t=1.84 < 2). The filter's t=2.01 is a
  mechanical artifact of pruning 8 losing runs, not new signal; n never reaches 100. Consistent with the
  prior (memory: cdc_zone n53<80 → SHADOW).
- OOS = last 30% of trades ≈ **15–17 trades**. With σ_R≈3, SE(OOS mean) ≈ 3/√16 ≈ **0.75R**. OOS +2.43 vs
  baseline +2.13 (Δ0.30) = **0.4σ = noise**. The OOS being +2.1R while full-sample is +0.7R is a
  **regime signature** (the recent 2023–2025 gold blow-off is a stronger trend), not evidence the filter
  generalises — both baseline and filtered ride the same tail. OOS is not independent confirmation.

## Cost sensitivity — not the deciding factor

At cost ×2 (0.60 price units ≈ 60 pips r/t): baseline 0.726→0.718, zone 0.931→0.923, FV 0.912→0.904; Δ
unchanged (`scratchpad/attack2.py`). Cost is negligible because the 2N stop makes risk ≈ 40–80 price
units, so cost/risk ≈ 0.01R. Robust to cost — but that does not rescue a statistically absent edge, and
0.30 r/t is on the optimistic side for gold (one-way spread+slippage alone can be ~20–40 pips).

## Verdicts

| feature | verdict | deciding numbers |
|--------|--------|------------------|
| (2) zone-strength filter | **REJECTED** | placebo p=0.088 (below 95th pct of random drop); family-wise 0.64; Bonferroni 0.97; below deflated bar (0.931<1.51); n=47<100, OOS Δ=0.4σ |
| (1) fair-value filter | **REJECTED** | placebo p=0.152; family-wise 0.84; below deflated bar (0.912<1.57); Δ ≤1.0σ |
| (3) vol-clock sizing | **NULL (no edge)** | Δ −0.016 |
| (4) conditional-reject | **REJECTED / UNPROVEN-UNDERPOWERED** | best n=22–25, Δ mixed sign, no variant near significance |

## Blocking issues (what would change the verdict)

1. The improvement is indistinguishable from dropping the same number of runs at random (placebo p≥0.088).
   To revisit: the filter must beat the random-skip placebo at the family-wise-corrected level (needs real
   Δ above the placebo ~99th percentile given 11 trials), not merely be positive.
2. Underpowered by the system's own standard (n never ≥100; the OOS is ~15 trades of pure regime tail).
   Only more independent trend-runs — realistically years more D1 data, or the same filter validated
   out-of-window on a second instrument — could power this. A single 2013+ walk-forward is one path.
3. Trials are only partially logged (11 in-script; upstream UHAS-feature/param search undisclosed). Until
   the full trial count is logged, the deflation N is a floor and the result stays uninterpretable.

## Go / no-go for live enablement

- (2) zone-strength: **NO-GO.** Not an edge — matches random run-pruning. Keep OFF.
- (1) fair-value: **NO-GO.** Weaker than (2); pure noise.
- (3) vol-sizing / (4) conditional-reject: **NO-GO.** Null / underpowered.

No LIVE flag currently enables these (research-only script, per `uhas_ablation_cdc.py:13,195`; iron rule
requires approval to wire). Recommendation: do **not** propose wiring any UHAS filter into live `cdc_zone`.
This is not yet evidence of an edge — only a hypothesis produced by an 11-variant search on ~50 trades.
Keep it OFF, keep `cdc_zone` in SHADOW, collect more independent D1 runs, then re-test against the placebo
and a deflated bar before reconsidering.

---

# AUDIT #2 (2026-08-22) — Long-only Donchian(40) breakout, XAUUSD H4, trail exit

Auditor: quant-adversarial pass (Fable 5). Posture: REFUTE. Read-only; 0 orders; candidate is NOT live.

Claim under test (from `scripts/breakout_long_v3.py`, N-sweep line 105): long-only close>Donchian(40)-high
breakout, exit close<Donchian(20)-low or SL=1.5×ATR(Wilder-14), no regime filter, MAX_HOLD 400 bars.
Claimed: n=166, exp_R +0.82, t +2.56, OOS(last 30%) +1.50, cost×2 +0.79, all 4 entry-index quartiles
positive ("STABLE") → structural edge, shadow candidate.

## Reproduction — numbers are real

`"C:/Users/pornnatcha/AppData/Local/Programs/Python/Python311/python.exe" scripts/breakout_long_v3.py --tf h4`
reproduces to the digit: N40 n=166 WR31.9% exp_R+0.818 t+2.56 OOS+1.502 cost2+0.791, quartiles
+0.75(23)/+0.24(48)/+0.70(50)/+1.61(45). N60 n=137 t2.05 PASS and D1 n=59 t2.20 (below MIN_N) also
reproduce. Data `data/xau_h4.json` = 20,000 H4 bars **2013-07-29 → 2026-07-17** (~13y; includes the
2013–2015 bear — full history, not a bull-window slice). Bars carry OPEN at index [1] (unused by v3).

## Look-ahead / causality — PASS (no leak found)

- `_roll_max`/`_roll_min` (`breakout_long_v3.py:40-51`) use `x[i-n:i]` — current bar excluded. Causal.
- SL-first intrabar (`:74-75` checks `l[j]<=sl` before band exit) — pessimistic, correct.
- ATR at decision bar i uses data through bar i, decision at close of i — causal. Non-overlap enforced
  (`i = exit_i + 1`, `:81`).
- Fill realism (my re-run with entry `o[i+1]`, band-exit `o[j+1]`, scratchpad `attack_breakout.py`):
  n=169, exp_R **+0.759**, t **+2.41** vs close-fill +0.818/+2.56 → optimism only ≈0.06R. Not material.

## Cost — mislabeled but not decisive

`cost/sl_pips` is subtracted **once per trade** (`breakout_long_v3.py:75,78,80`) → 30 points is per
**round trip**, not per side as claimed. 30 pts r/t is thin for XAU (spread alone 20–35 pts); cost×2
(60 r/t) is the realistic base. Swap on multi-day holds (mean hold 40 H4 bars ≈ 6.7 days, max 249 bars)
is NOT modeled: stress at 15/30 pts per day held → exp_R +0.734 (t2.34) / +0.649 (t2.11). Combined
next-open + cost60 + swap15/day: **+0.650, t+2.10**. Cost does not kill it. Statistics do.

## THE decisive refutation — drift-null (random-long with the same exits)

A long-only strategy on an asset that went 1326→4017 must beat "random long entry, identical SL/trail
exit", not zero. Matched-n null (1000 sims, ~160 non-overlapping random long entries each, same
1.5×ATR SL + Donchian(20)-low trail; `scratchpad/attack2b.py`):

| statistic | null (random-long) | candidate | empirical p |
|---|---|---|---|
| exp_R | **+0.414** ± 0.219 (p95 +0.804, max +1.336) | +0.818 | **0.043** |
| t-stat | p95 +2.37, p99 +2.73 | +2.56 | **0.019** |

**Half the claimed edge (+0.41R of +0.82R) is bull drift + convex exit, with no breakout signal at all.**
The breakout timing itself is worth p=0.019–0.043 — a single-test 2–4% result, which then dies under
trials correction (below).

## "STABLE across quartiles" — the flag has no discriminative power

Under the same matched-n random-long null, **84% of null sims are also "STABLE" (≥3/4 quartiles positive;
37% are 4/4)**. Quartile B&H drift: Q1 −5%, Q2 +25%, Q3 +25%, Q4 +102%. Quartile excess over null:

| Q | period | cand | null | excess | p |
|---|---|---|---|---|---|
| Q1 | 2013-07→2016-10 (gold −5%) | +0.75 (t1.16) | +0.06 | +0.69 | 0.023 |
| Q2 | 2016-10→2020-01 (+25%) | +0.24 | +0.29 | **−0.06** | 0.537 |
| Q3 | 2020-01→2023-04 (+25%) | +0.70 | +0.41 | +0.29 | 0.240 |
| Q4 | 2023-04→2026-07 (+102%) | +1.61 | +0.86 | +0.75 | 0.100 |

Q1 — the only genuinely non-bull era and the only nominally significant excess — rests on **one trade**:
2016-01-26, R+11.56 (the Jan–Feb 2016 risk-off spike). Drop Q1's best trade → +0.26; drop two → **+0.015
≈ zero**; drop three → −0.23. The "works in the bear era" claim is a 1–2-trade story on n=23.

## Outlier concentration — drop-best-k

Top-5 trades (3% of 166) = R {34.9, 18.9, 13.1, 11.6, 11.6} = **66% of total sumR** (90/136). Jackknife:
k=1 → t2.49; k=3 → t2.03; **k=4 → t1.79 (below the system's own t>2 bar)**; k=8 → +0.113/t0.71;
k=10 → **+0.028/t0.18 — edge fully gone after removing 6% of trades**. Fat right tail is inherent to
trend-following, but skew 4.55 / kurtosis 32.3 at n=166 means the t-stat is CLT-fragile; the entire
above-drift excess lives in <10 trades over 13 years (<1 per year).

## OOS is not independent confirmation

OOS = last 30% of trades = **2023-02-01 → 2026-07-03, gold 1950→4057 (+108%)** — the strongest bull leg
in the sample. Null exp_R in that quartile is +0.86; OOS +1.50 is drift-dominated (excess p=0.10). Same
regime-tail signature as Audit #1.

## Multiple testing — the kill shot on the residual

Session trial count: reversion ~20 + v1 33 + v2 13×2TF=26 (self-admitted `breakout_trend_v2.py:166`) +
v3 5×2TF=10 ≈ **89 configs**; verifiable in-script floor (v2+v3 alone) = 36. The candidate is also the
best-of-5 within v3's own sweep (N80 already fails at t1.81). Corrections on the drift-null p:
- Bonferroni, most charitable (p=0.019, N=13): adj-p ≈ 0.25. At N=36: 0.68. At N=89: ~1.0. Šidák at
  N=89: 1−(1−0.043)^89 ≈ 0.98. **Fails every correction, even the friendliest.**
- Deflated Sharpe (vs zero-null, trade-level SR=0.198, skew/kurt-corrected): N_trials=13 → DSR 0.989;
  N=89 → **0.936 < 0.95 FAIL**. And this deflates against SR=0 — against the correct drift-null the
  candidate is far below any deflated bar.
- PSR(SR>0)=1.00 and bootstrap 95% CI on mean R [+0.25, +1.49] (p(≤0)=0.0014) — it beats **zero**
  convincingly. Zero is the wrong null for long-only gold 2013–2026.

## What survives (for the record)

No look-ahead; honest SL-first fills; next-bar-open costs only 0.06R; genuine parameter plateau
(sl_atr 1.0–2.5 all t2.18–2.56; exit_M 10–40 all t2.16–2.67 — no cliff); survives cost×2+swap stress
mechanically. The code is honest. The interpretation is not.

## Verdict

| claim | verdict | deciding numbers |
|---|---|---|
| "Long-only Donchian(40) H4 breakout has a structural directional edge" | **REFUTED** | drift-null explains +0.41R of +0.82R; breakout timing p=0.019–0.043 single-test → Bonferroni ≥0.25 at charitable N=13, ~1.0 at session N=89; DSR(N=89)=0.936 FAIL |
| "STABLE across 4 quartiles ⇒ not bull-bias" | **REFUTED** | 84% of random-long nulls are also "STABLE"; only Q1 excess nominal (p=0.023) and it is 1–2 trades (drop-2 → +0.015) |
| "OOS +1.50 confirms" | **REFUTED** | OOS window = 2023–2026 +108% bull; null earns +0.86 there |
| Residual timing effect (+0.40R over drift) | **INSUFFICIENT-EVIDENCE** | concentrated in <10 trades/13y; k=4 jackknife → t1.79; cannot clear trials-corrected bar on this sample |

Consistent with the system prior: gold **direction** is not mechanically predictable; what this backtest
found is (a) gold went up and (b) cut-losses/let-winners-run is convex — both already known.

## Blocking issues (what would change the verdict)

1. Must beat the matched-n random-long drift-null at a trials-corrected level (needs empirical p ≲
   0.0006 at N=89, or a pre-registered single hypothesis going forward) — currently p=0.019–0.043.
2. The above-drift excess must not vanish under drop-best-4 (currently t 2.56→1.79) — i.e., more
   independent big-trend episodes are required; at <1 driver-trade/year that means years of forward data
   or cross-instrument confirmation on a pre-frozen config.
3. Trial log: 89 is a session estimate; only 36 are verifiable in-script. Full search history must be
   logged for any future deflation to be interpretable.

## Go / no-go for live enablement

- **NO-GO for live. NO-GO even for the "auto-promote on validation-pass" path** (memory 08-07): the
  in-script PASS flags (t>2/OOS>0/cost2>0/n≥100, `breakout_long_v3.py:123`) are met but are computed
  against the wrong null — this must not auto-promote.
- **Shadow-forward-only is acceptable** (costless, pre-frozen config N40/M20/1.5ATR, log-only): the
  mechanics are honest and a pre-registered forward test is the only way this hypothesis can ever earn
  a corrected p. Treat as hypothesis, not edge.
- Live-flag check: this candidate is wired to **nothing**. `ALGO_ROUTER_LIVE=false` (`.env:343`);
  the existing live pending-breakout path is the separate regime-router momentum_breakout N20
  (`regime_lib.py:39,178-189`), unaffected by this audit. No current real-money exposure to this claim.

Commands/artifacts: `scratchpad/attack_breakout.py` (quartile forensics, jackknife, next-open fills,
swap stress, DSR, neighbors), `scratchpad/attack2b.py` (matched-n drift-null, bootstrap, OOS forensics).

---

# AUDIT #3 (2026-08-22) — M1 scalp no-edge refutation

Auditor: quant-adversarial pass on a **NEGATIVE** claim: "no tradeable M1 XAUUSD scalp exists
(SL=300pt, TP<SL, spread 28pt) given 3mo of M1 data." Posture inverted: I tried hard to FIND the
edge / find a harness bug that suppresses one. Read-only; 0 orders; all sims offline.

**VERDICT: NEGATIVE-CONFIRMED** — no M1 scalp config passes any honest gate at realistic cost, and
the one interesting gross signal is a best-of-108 parameter cliff that cannot pay even half the spread.

## 1. Reproduction — parent's numbers are real

`SCALP_COST=28 python scripts/m1_scalp_search.py` → **PASS 0/108** (112 grid entries, 4 scored n<10 →
header "testing 112" vs "0/108" is benign). Independent re-implementation (precomputed outcome tables,
`scratchpad/core.py`) matches the parent's `_simulate` (`scripts/m1_scalp_search.py:101-123`)
row-for-row at SL-first/cost28, e.g. `rsi n7,lo5,hi95 TP200: exp −0.0933, t −0.80` identical in both.

Data sanity (`data/xau_m1.json`, 90,001 bars 2026-05-13→08-21): 0 OHLC violations; bar 0 is a 9-day
orphan (221.8h gap) — harmless past warm=260; median M1 range **170pt** (SL300 ≈ 1.8 bars of noise;
TP75 is inside one bar's noise); 9.5% of bars can hit SL300+TP75 in the same bar; weekend gaps to
±2,730pt exist (gap-through-SL modeled at SL price = optimistic, i.e. the harness *over*states edge
there, not under).

## 2. Attack: harness bugs that could hide an edge — audited, none change the verdict

- **SL-first tie-break is material but not verdict-changing.** Ambiguous (SL&TP same bar) = 1.60% of
  all bars at TP75 / 0.52% at TP200, but signal bars are high-vol so it bites harder there. Re-scored
  the full 108-grid under coin-flip tie-break: at cost28 best exp_R goes −0.093 → **+0.007** (t≈0.06);
  still 0/108 PASS. Under TP-first + cost0 (absolute upper bound) 16/108 "pass" — meaning the parent's
  pessimism suppresses *t* but there is nothing tradeable under any fair setting.
- **MAX_HOLD=120 truncation: zero effect.** Champion config has **0/2081 timeouts**; MAX_HOLD=360
  reproduces exp/t exactly (+0.0444, t+2.51 both).
- **entry=close[i] is slightly OPTIMISTIC, not unfair**: realistic open[i+1] entry *degrades* the
  champion (t +2.51 → +2.11). The parent convention flatters, not suppresses, fades.
- **Non-overlap doesn't discard winners**: taking every overlapping signal gives *lower* per-trade
  exp (+0.022 vs +0.044) with autocorrelated t. Non-overlap is the correct and kinder accounting.
- **Matched-null machinery**: symmetric (null trades use identical exit tables); p stable across
  seeds 1/7/12345 (p=0.0013–0.0025 for the champion gross). No bias found.

## 3. The only real signal — and why it still isn't an edge

Fair scoring (coin tie-break, cost0) of the whole grid leaves exactly one gross survivor:
**zscore n60 thr2.5 TP200: n=2081, gross exp_R +0.0476, t +2.69, matched-null p 0.001, 3/3 thirds,
OOS +0.040** — genuine-looking M1 mean-reversion. It dies on three independent counts:

1. **Cost.** Breakeven cost = **13–14pt vs real spread 28pt**. Cost curve (coin): 0pt → +0.044/t+2.51;
   10pt → +0.011/t+0.62; 14pt → −0.002; 20pt → −0.022; 28pt → **−0.049/t−2.77**. Even at an
   optimistic liquid-hours 15–20pt spread it is negative; at 10pt it is statistical noise.
2. **Parameter cliff, not plateau.** Neighbors (cost0, TP200): n45→t+1.43, n90→**t−0.25**,
   thr2.25→t+0.16, thr2.75→t+0.76, thr3.0→t−0.07. The signal exists at exactly one grid point.
3. **Trials correction.** Best-of-108 with p=0.001 → Bonferroni ≈ 0.11–0.27 across seeds. Across the
   whole audit (~280 configs incl. mine), expected max t under a global null ≈ √(2·ln 280) ≈ 3.4 —
   the observed best fair t (+2.85, gap-excluded variant) is **below** what pure noise would produce.

So even the *gross* mean-reversion claim is not established; the *net* claim is firmly negative.

## 4. Attack: LIMIT/maker entry (the "most likely refutation") — makes it WORSE

Modeled correct bid/ask fills (bars are bid; buy limit L fills when l≤L−28; short SL/TP shifted by
spread; SL-first; TTL 5/15/30; offsets 0/25/50; TP150/200; 5 signal families; `scratchpad/attack2_limit.py`).
**All 90 limit configs have negative exp_R** (best: zscore off50 ttl30 −0.033R, t−1.94). Mechanism =
adverse selection: fills only occur after 28pt+ *further* adverse move, and the instant-bounce winners
never fill — e.g. rsi_n14 15/85 WR drops 73%→55% vs market entry. Fill-conditioning costs more than the
spread it saves. The refutation path is closed.

## 5. Attack: untried families at the cost-0 ceiling — 0/63 pass

Tick-volume imbalance (index [5], w30/60 × thr2.0/2.5 × fade/follow): best t +0.67. Session-VWAP fade:
n up to 7,996 but BE ≤ +4pt. Day-open fade: negative. Opening-range breakout (day-open & NY-16:30-srv,
15/30-bar OR): best t +0.38. Hour-gated champion (3 sessions): best slice London TP200 gross +0.0596
(t+1.82, **BE=18pt**) — still below even a generous 15–20pt session spread, and it is a searched slice
of an already best-of-108 signal (session-gate overfit is a documented trap in this repo). **PASS 0/63.**

## 6. Scoreboard

| Attack on the negative | Result |
|---|---|
| Reproduce parent 0/108 @cost28 | reproduced exactly |
| SL-first / tie-break bias | real but verdict-unchanged (0/108 under coin @cost28) |
| MAX_HOLD / non-overlap / entry-timing suppression | none (0 timeouts; overlap weaker; open[i+1] worse) |
| Limit entry rescues spread | **refuted** — 0/90 positive, adverse selection dominates |
| New families (volume/session/ORB/VWAP) | 0/63 at cost-0 ceiling |
| Session-restricted + tighter spread | best BE 18pt < any realistic spread |
| Best gross signal survives trials+neighbors | no — cliff + Bonferroni p≈0.1–0.3 |

Caveat that would apply even to a pass: 3 months / one regime (high-vol gold, median M1 range 170pt),
single OOS path — insufficient for live regardless. The structural summary: M1 fade "alpha" here is
≤ ~14pt/trade, i.e. **at most half the spread**; the market maker earns this edge, the taker cannot.

## Go / no-go

- **NO-GO — NEGATIVE-CONFIRMED.** No M1 scalp config may be promoted, shadowed-for-promotion, or fed
  to the auto-backtest→live path; nothing here meets t>2/OOS/null/cost simultaneously under fair scoring.
- Live-flag check: `scripts/m1_scalp_search.py` is imported by no live module; live "scalp" strings are
  the shadow-algo `klass` label (`agents/algo_registry.py:48`) and swing comments (`config.py:822`).
  **No current real-money exposure to this hypothesis.**

Commands/artifacts: `scratchpad/attack1_tiebreak.py` (tie-break × cost grid re-score),
`attack1b_fair_gross.py` (fair gross + breakeven), `attack2_limit.py` (bid/ask limit fills),
`attack3_families.py` (volume/VWAP/ORB/session), `attack5_robust.py` (hold/entry/gap/overlap/cost-curve/
seeds/neighbors), all under the session scratchpad; interpreter
`C:/Users/pornnatcha/AppData/Local/Programs/Python/Python311/python.exe` (numpy).
