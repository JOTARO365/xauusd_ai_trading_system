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

---

# AUDIT #4 (2026-08-22) — live-algo audit + tuning

Auditor: quant-adversarial pass (Fable 5) on the CURRENTLY-LIVE roster, using the new battery
(driftless synthetic stress, matched drift-nulls, CVaR/Sortino, trials-correction). Read-only; 0 orders;
MT5 used for `copy_rates` data fetch only. Posture: REFUTE each live edge.

**Live roster audited** (`data/algo_switches.json:2,30,41`; BTC shadow `:13`):
`regime_momentum:XAUUSD` (LIVE), `macro_momentum:XAUUSD` (LIVE), `tsmom_d1:WTIUSD` (LIVE),
`tsmom_d1:BTCUSD` (SHADOW, allowlisted).

**Structural fact that changes what "the live strategy" is:** ALL live combos are long-only.
`data/algo_dir_mode.json` sets tsmom_d1/macro_momentum/regime_momentum = "long", and
`LONG_ONLY_ALL=true` (`.env:61`) blocks every SELL at `mt5_connector.py:898-900`. Exit-on-flip
*closes* are not SELL orders, so tsmom long positions still exit on signal flip. Every backtest below is
therefore run in **live parity = long-leg only + live gates**, not the symmetric algo the older claims
were measured on. Live configs: WTI SL×0.7 (`.env:71`, applied `multi_symbol_executor.py:714` → disaster
SL 2.1×ATR), TSMOM lookbacks 21/63/126 + confirm 21 (`.env:176-177`), macro RR=4.0 override
(`data/algo_pair_config.json` macro_momentum.XAUUSD), SR-gate allowlist = the 3 gold/XAU combos
(`.env:386`), block-NEUTRAL live (`.env:62-63`, `agents/gold_regime_filter.py:43-80`).

Interpreter for all runs: `C:/Users/pornnatcha/AppData/Local/Programs/Python/Python311/python.exe`.

## A. tsmom_d1:WTIUSD — **VERDICT: NULL (no edge). DEMOTE to SHADOW.**

The key open question of this audit. The founding claim (memory 07-25: "WTI momentum SL×0.7 = edge แท้,
exp_R +2.4R, t-stat 15") predates the drift-null discipline and was **already flagged internally** as
window-bias/logic-mismatch (`.claude/context/continue.md:6767`: "plan อ้าง WTI t15 = window bias (recent
20k) / logic mismatch"). It was never re-validated; the user kept WTI live on the strength of that stale
number (`continue.md:60`).

Re-derivation on `data/wti_d1.json` (MT5 futures OHLC, 4,275 D1 bars 2010-08→2026-08), live spec parity
(`algo_registry.py:135-233` + `backtest_all.py:190-219` accounting, intrabar SL, cost 0.05 $/rt):

| variant | n | exp_R | t | OOS(30%) | notes |
|---|---|---|---|---|---|
| both-dir (algo signal) | 173 | +0.161 | **+1.17** | +0.39 | nowhere near t15 |
| **LONG-leg (live parity)** | 83 | +0.214 | **+1.09** | +0.76 | expo 50% of days, mean hold 26d |
| long-leg drop-best-1/2/3 | 82/81/80 | +0.093 / **+0.008** / **−0.066** | +0.60/+0.06/−0.60 | edge = 2–3 trades in 16 years |

Nulls (all fail):
- **Random-long matched-exposure** (same number of spans, same span lengths, random placement, same
  2.1×ATR SL accounting, 1500 sims): null mean +0.034, 95pct **+0.219** vs real +0.214 → **p=0.056**
  (p on sumR 0.055). The live combo does not beat "hold WTI long the same fraction of days at random".
- Daily accounting: strat mean +0.034%/d (t+0.99); matched-exposure random-sign (P_long=0.43, 2000 sims)
  **p=0.161**; block-persistent (7d runs) p=0.159; on the demeaned real path p=0.191.
- **Driftless synthetic stress with the LIVE lookbacks** (21/63/126+confirm21, 300 sims/mode):
  GBM-0drift survival 52.7% p0.467; block-boot-demean 52.7% p0.427; regime-0drift 47.3% p0.550 —
  **NO-EDGE in all three modes** (contrast BTC below, which at least survives block-boot).
- Independent confirmations: `scripts/wti_momentum_audit.py` (Donchian style, 16y): exp_R +0.0155,
  t+0.26, OOS −0.023, matched-null p=0.057. `scripts/tsmom_btc_wti_backtest.py` (40y AV spot,
  63/126/252): Sharpe +0.12, matched-exposure p=0.118, halves unstable.

Cost is not the issue (cost 0→0.10 moves exp_R only +0.23→+0.20): **the issue is that there is no
timing signal at all** — four independent null formulations, two datasets, two signal variants, all
p≥0.055, and the entire positive mean sits in 2–3 outlier trades. CVaR5 −1.02R / PF 1.62 / maxDD 7.5R
(tail well-capped by the disaster SL — risk plumbing is fine; the edge is absent).

**Go/no-go: NO-GO — demote `tsmom_d1:WTIUSD` to SHADOW now.** This is live real money on a claim whose
own repo history calls it window-biased and which fails every test in the new battery.

## B. macro_momentum:XAUUSD — **VERDICT: OVERFIT / drift-harvest (INSUFFICIENT-EVIDENCE as alpha).**

Claim trail (three different numbers for the same combo — already a red flag):
`continue.md:7078` t1.91→2.00 n589 · `docs/reviews/sr-gate-eval.md:9` (regenerated 08-20) +0.235/t2.08/
n354 → +0.254/t2.21/n349 · today's re-run of the **same code path** (`backtest_all.bt_macro` RR4 + same
`sr_entry_gate.blocks_at`, MT5 gold H4 20000 bars + EURUSD H4): **n327 +0.210/t1.79 → n322 +0.229/t1.93.
The recorded pass (t≥2) no longer holds two days later on refreshed data.** The authorization record
`data/sr_gate_combos.json` (criteria `t≥2`) is stale — the pass was a knife-edge, not a plateau.

Live-parity re-derivation (RR4 + long-only + SR-gate, cost 30, MT5 full data; offline DXY-proxy run
agrees in sign on its 27%-coverage subsample):

- LIVE config: n=211, exp_R **+0.317, t+2.11**, OOS +0.66, survives cost×2 (t1.95) and drop-best-3
  (t1.77). Sortino +0.31, CVaR5 −1.05R, maxDD 9.7R. Looks good — until the nulls:
- **Random-dir at the same signal bars** (RR2 both, 300 sims): p=**0.273** → the macro-confirmed
  *direction choice carries no information* beyond coin-flip at those bars.
- **SELL leg is −EV** (n224, −0.087, t−0.93; RR2): all of the combo's positivity is the BUY leg —
  i.e. long gold 2013→2026. The live long-only block is what "fixed" this combo, and that is beta.
- **Random-LONG matched-n drift null** (RR4, 300 sims): p=**0.020** single-test. Same family and same
  ballpark as AUDIT #2's long-Donchian p=0.019–0.043 — which died under trials correction. This
  hypothesis family (long gold breakout × {BRK,MLB,RR,SL,gate}) has had ≥100 session trials (AUDIT #2
  count 89 + the 6-RR exit sweep `docs/reviews/momentum-exit.md:11-16` that *selected* the live RR4 +
  this audit's 18 neighbors). Šidák at even a charitable N=10: 1−(1−0.02)^10 ≈ **0.18. FAIL.**
- **The macro filter subtracts value**: identical long-breakout with NO macro filter = n298, +0.395,
  **t+3.06** > with-macro +0.317/t2.11. The "macro-aligned" story is storytelling (sin #4) — the filter
  the algo is named after makes the result *worse*. What remains is exactly AUDIT #2's refuted object:
  long-only gold H4 breakout + convex exit on a +108% Q4 (quartiles: Q1 +0.03, Q4 +0.64; OOS window =
  the 2023-26 blow-off).
- Neighbor sweep is a smooth plateau (12 BRK×MLB configs t1.70–3.41) — but a plateau in a
  drift-dominated statistic is drift's plateau, not signal (AUDIT #2: 84% of pure-drift nulls "STABLE").

**Go/no-go: NO-GO as a validated alpha.** As a *declared* gold-drift-harvest vehicle (beta + loss
shaping) it is the least-bad gold expression the system has: SELL-leg blocked, best Sortino/recovery of
the gold combos, tail capped. If the user knowingly wants long-gold beta, keep it live **re-labeled as
beta, minimum size, max 1 position** — but the system must stop citing t≥2 as its justification, and
the stale `sr_gate_combos.json` pass should be re-run (it fails its own criterion today).

## C. regime_momentum:XAUUSD — **VERDICT: NULL (loss-shaped drift). DEMOTE to SHADOW.**

Live parity = H1 Donchian(20) TREND-gated breakout (`regime_lib.py:178-189`) + BUY-only + block-NEUTRAL
+ SR-gate. Reproduction on `data/xau_h1.json` (70,000 bars 2014→2026, `regime_backtest` parity, cost 30):

| variant | n | exp_R | t | notes |
|---|---|---|---|---|
| baseline algo (both-dir) | 1575 | −0.054 | −1.52 | reproduces `trend_filter_backtest.py` to the digit |
| BUY + block-NEUTRAL | 823 | +0.047 | +0.93 | = the claimed "gold-fit" number, reproduced exactly |
| **LIVE parity (+SR-gate)** | 818 | **+0.054** | **+1.06** | PSR₀ = **0.858** (< 0.95) |
| LIVE at cost×2 (60) | 818 | **+0.011** | +0.22 | edge dies inside the cost error-bar |

- Random-long at matched TREND/non-NEUTRAL bars (matched-n 818, 400 sims): null mean +0.011,
  95pct +0.062, real +0.054 → **p=0.102. Fails.**
- Quartiles unstable: Q1 −0.50, Q2 +0.35, Q3 −0.25, Q4 +0.15 — sign flips across regimes.
- This matches the system's own labels: `config.py:410-412` documents block-NEUTRAL as loss-reduction
  ("drift-harvest ไม่ใช่ alpha, t0.93"), and `gold_regime_filter.py:5` says the same. The audit
  confirms those labels are accurate: the gates turned −0.054 into +0.054 by *deleting losing slices*
  (valid risk-shaping), not by adding signal. At realistic doubled cost the residual is +0.01R ≈ 0.

**Go/no-go: NO-GO as an edge — demote to SHADOW.** Consistent with the system prior (12+ failed gold
directional strategies): gold direction remains unpredictable; keep collecting shadow data. If the user
keeps it live as deliberate drift-harvest, it is strictly dominated by macro_momentum (B) — running both
= two correlated long-gold-breakout tickets; keep at most one.

## D. tsmom_d1:BTCUSD (SHADOW) — **VERDICT: INSUFFICIENT-EVIDENCE — keep SHADOW (current state is correct).**

Reproduced `scripts/synthetic_stress.py` to the digit: driftless survival — GBM 50.2% (p0.455),
**block-boot-demean 94.2% (p0.052)**, regime 46.2% (p0.480) → edge exists only where autocorrelation is
preserved, and at borderline significance. Reproduced `scripts/tsmom_btc_wti_backtest.py`: real-path
matched-exposure p=0.000, halves stable (1.43/0.63) but short leg ≈ 0 (Sharpe +0.03) and prior bar-level
gates unmet (n<100 per memory 08-18). This is the only roster member with any driftless-null signal at
all. Do not promote on this; pre-freeze the config and let shadow-forward decide.

## Tuning recommendations (risk/exit envelope only — gold entry has no edge to tune)

Ranked by impact; tags: **[risk]** = correctness/risk-shaping, safe to apply; **[alpha]** = claims new
edge, requires the full battery (driftless null + trials-corrected p + OOS + cost×2) before live.

1. **[risk] DEMOTE `tsmom_d1:WTIUSD` → SHADOW** (`data/algo_switches.json:41`). Highest impact: it is
   the largest unproven live exposure (D1 swing, 26-day mean hold, 50% time-in-market on oil). Every
   null fails (p 0.055–0.19); the t15 authorization is documented window-bias. Nothing to tune — the
   edge does not exist. Shadow costs nothing and preserves the forward test.
2. **[risk] Collapse the two live gold combos into one declared-beta ticket.** regime_momentum:XAUUSD
   (H1) and macro_momentum:XAUUSD (H4) are the same long-gold-breakout bet at two frequencies; the H1
   one has PSR₀ 0.858 and dies at cost×2, the H4 one is stronger on every downside metric (Sortino
   +0.31 vs +0.05, maxDD 9.7R vs 58R, recovery 6.9 vs 0.75, and 211 vs 818 trades → ~4× less cost
   bleed). **Demote regime_momentum:XAUUSD to SHADOW; keep macro_momentum:XAUUSD only, re-labeled
   drift-harvest/beta, max 1 position, minimum lot.** If instead both stay, cap combined gold-algo
   at-risk positions to 1.
3. **[risk] Pre-declared downside budget + CVaR gate for whatever stays live.** Live parity numbers to
   anchor it: macro live WR 28% (RR4) → long loss streaks are structurally certain (~16 trades/yr);
   CVaR5 ≈ −1.05R. Declare before the forward run: e.g. "demote mechanically at 12R drawdown or a
   15-loss streak" (≈ 95th-pct null path), so the demote decision is data-triggered, not narrative.
   Wire `quant_metrics.panel` (already built) into the shadow report so CVaR5/Sortino/recovery are
   logged per combo alongside t.
4. **[risk] Refresh stale pass records on every re-validation cycle.** `data/sr_gate_combos.json`
   (generated 08-20) authorizes the SR-gate on a t2.08→2.21 result that re-runs at t1.79→1.93 today.
   Rule: any `t≥2` authorization must be re-derived on current data before the combo stays live —
   knife-edge passes (2.0–2.2) should require a margin (e.g. t≥2.5) given the documented window drift.
5. **[alpha — do NOT apply without full validation] Macro-filter removal / RR retune.** The no-macro
   long breakout backtests better (t3.06) and RR5 better than RR4 — but both are best-of-N selections
   inside a 100+-trial family whose drift-null-corrected p is ~1. Explicitly do not chase these;
   they are listed only to document that the "macro" and "RR4" components carry no validated signal.
6. **[risk] WTI/BTC tsmom mechanics if ever re-promoted:** keep SL×0.7 (2.1×ATR) — CVaR5 −1.02R shows
   the tail cap works; keep confirm-21 (stand-down, not reversal); keep exit-on-flip closes exempt from
   LONG_ONLY (verified: closes route via `tsmom_flip` mgmt, not `open_order`, so no stuck-position bug).

## Which live combos should be demoted NOW

| combo | today | evidence-based state | action |
|---|---|---|---|
| tsmom_d1:WTIUSD | LIVE | NULL (all nulls p≥0.055; 2-outlier-trade mean; t15 = documented window bias) | **DEMOTE → SHADOW now** |
| regime_momentum:XAUUSD | LIVE | NULL (PSR₀ 0.858; +0.011R at cost×2; null p=0.102) | **DEMOTE → SHADOW** (or fold into tuning #2) |
| macro_momentum:XAUUSD | LIVE | drift-harvest beta, not alpha (dir-choice p=0.273; drift-null p=0.020 pre-correction ≈ 0.18+ corrected; macro filter negative value; pass record stale) | keep only as **declared beta, min size, 1 position**, else demote |
| tsmom_d1:BTCUSD | SHADOW | borderline autocorr-dependent signal (p0.052 block-boot) | keep SHADOW, pre-frozen config |

Honest ceiling, restated: **gold = risk-shaping only** (three audits, 12+ strategies, and this one all
agree — the gates cut losses, they do not find direction); **WTI fails the new battery outright**;
**BTC is the only hypothesis left alive, and only in shadow.** No live combo currently passes
`VALIDATED` (OOS + driftless-null + cost + PSR>0.95 + trials-corrected); real-money exposure today
rests on drift plus two stale pass records.

Commands/artifacts (session scratchpad): `audit4_wti.py` (live-parity both/long/short + daily
matched-exposure + driftless synthetic with live lookbacks), `audit4_wti_long.py` (long-leg parity +
random-long matched-exposure null + drop-best-k), `audit4_macro.py` (offline DXY-proxy),
`audit4_macro_mt5.py` (full-data reproduction + both nulls), `audit4_macro_neighbors.py` (neighbor
plateau + no-macro ablation), `audit4_regime.py` (live-gate parity + PSR₀ + TREND-bar random-long
null); plus re-runs of `scripts/wti_momentum_audit.py`, `scripts/synthetic_stress.py`,
`scripts/tsmom_btc_wti_backtest.py`, `scripts/trend_filter_backtest.py` (all reproduced to the digit).

# AUDIT #5 (2026-08-22) — full-registry audit (6 shadow algos) + fix attempts

Auditor: quant-adversarial pass (Fable 5) on the 6 NOT-yet-audited registry algos
(`agents/algo_registry.py`: mean_reversion:94, regime_momentum_fvg:236, sweep_reversal:273,
confluence_15m:424, cdc_zone:525, pullback_buy:588). Battery = AUDIT #4 discipline: matched
drift-null (random-entry-same-exit-same-exposure, NOT zero), look-ahead/causality code read,
driftless synthetic stress, trials correction, honest OOS, cost×2. Per user directive, each failing
algo got ONE fix attempt (risk-shaping only) re-tested under the same battery. All runs offline on
cached data (`data/xau_{d1,h1,h4,m15,w1}.json`, `data/drv_eurusd_m15.json`, BTC AV cache); 0 orders;
read-only except this report. Scratch scripts (session scratchpad): `s1_cdc.py`, `s1b_cdc.py`,
`s2_pullback.py`, `s3_conf15m.py`, `s4_dead3.py`.

Reproduction baseline: `data/backtest_results.json` (matrix 08-12) reproduced to the digit where
windows match — e.g. cdc XAUUSD last-3000-D1 = n48 exp+0.945 t+2.01 OOS+2.481 vs matrix n47
+0.983/t2.05/OOS+2.478 (data refresh); mean_reversion/sweep/fvg within refresh noise. The engines are
faithful; the *claims* are what fail below.

## A. cdc_zone — **VERDICT: NULL as alpha (gold drift-harvest, same family as macro_momentum). KEEP-SHADOW only if relabeled beta; do not promote on backtest.**

Claim (`algo_registry.py:529-531`): XAUUSD exp_R+0.88 t1.99 OOS+2.38 n53. Reproduced (n48 +0.945
t2.01). Refutation results (XAU D1, cost 30 pips, `s1_cdc.py`/`s1b_cdc.py`):

- **Matched-exposure random-long drift-null**: same span-count/lengths/2N-SL accounting, 1000 sims.
  Last-3000 window (the claim's window): null mean **+0.549R/trade** (random long placement on gold
  earns half the claim by itself), real +0.945 → **p=0.105. FAIL.** Full-6000 (2003-2026): p=0.015
  single-test — but the cdc family counts ≥30 trials (modes long/both/long+W1 × 5 pairs ×
  src close/ohlc4 × pullback variants + phase-2 Turtle/Fib): Šidák 1−(1−0.015)^30 ≈ **0.37. FAIL.**
- **Driftless synthetic stress** (long/flat cdc on mu=0 GBM + block-boot-demean paths, 300 sims):
  survival 58.7%, vs-random p **0.493 / 0.447** → **zero timing skill without drift**. The full-window
  p=0.015 is drift × convexity (cut-loss/let-run on a rising asset) = beta, exactly AUDIT #4's
  macro_momentum verdict.
- **Honesty ladder**: the parity engine (`backtest_all.py:138-139`) uses a close-based disaster SL
  that *truncates* the recorded loss to −1R even when the close-loss is worse; honest accounting
  (intrabar low SL + next-open fill): exp +0.945 → **+0.755, t1.78**, null p=0.168.
- **Outlier concentration**: drop-best-2 of 48 → exp+0.414 t1.46; best 3 trades = +16.4R, +9.9R,
  +7.5R. The "edge" is 2-3 trades.
- n=48 << 80 (its own MIN_N), and forward shadow so far: 1 resolved trade, −1.0R
  (`logs/shadow/cdc_zone__XAUEUR.jsonl`).
- BTCUSD leg: window-dependent (last-3000 null p=0.008 but full-2010-2026 p=0.447, matrix OOS only
  +0.14) — INSUFFICIENT, and BTC momentum is already covered by tsmom_d1:BTCUSD shadow.
- **FIX ATTEMPTED — W1 CDC bull gate** (the existing `cdc_backtest.py` long+W1 variant): full-window
  exp+1.006 t2.78, survives cost×2 (t2.74), null p=0.011 single-test — but same ≥30-trial family
  (corrected ≈0.28) and same driftless-stress failure. **Fix improves the beta expression; it does
  not create alpha.** Claim-window (last3000) p=0.063 — still FAIL.

Recommendation: **KEEP-SHADOW (relabeled drift-harvest/beta)** — it is the honest D1 expression of
the long-gold thesis and shadow costs nothing — but the t1.99/OOS+2.38 numbers must stop being cited
as validation, and promotion must come from forward shadow n≥20 vs a drift benchmark, not this
backtest. If the registry is to be thinned aggressively: it is redundant with macro_momentum (same
beta, lower frequency).

## B. pullback_buy — **VERDICT: NULL + statistically invalid claim (overlap-inflated t). REMOVE-FROM-REGISTRY (or shadow only with corrected stats).**

Claim (`algo_registry.py:592-593`): XAUUSD OOS+0.278 t3.88, XAUEUR OOS+0.138 t2.05. Two independent
kills (`s2_pullback.py`):

1. **The t3.88 is pseudo-replication.** `scripts/pullback_buy_backtest.py:70-91` collects EVERY
   trigger bar (`i += 1`, no dedup) and resolves each 72-bar trade independently → overlapping trades
   counted as independent samples. Reproduced exactly: report-style overlap = OOS n649 exp+0.255
   **t+3.56** (report: n650 +0.270 t3.76); the registry-parity engine (`backtest_all.py:168-187`,
   sequential non-overlap, same data) = OOS n203 exp+0.207 **t+1.65**. Same signal, half the claimed
   t once the double-counting is removed. The XAUEUR "t2.05" is the same construction — and its own
   IS is *negative* (−0.012, `docs/reviews/pullback-buy.md`): the classic OOS-window artifact this
   session already condemned.
2. **The trigger carries zero information beyond drift.** Matched-n random-long at D1-uptrend bars
   (same SL-in-ATR distribution, RR3, mh72, 400 sims): ALL n1000 real +0.055 vs null +0.064 →
   **p=0.570**; OOS-only real +0.178 vs null +0.186 → **p=0.532**. The EMA20-reclaim entry performs
   *identically* to buying at random moments in a D1 uptrend. IS honest = +0.002 (t0.03); cost×2 IS
   = −0.048. Yearly segmentation: sign flips 2015-2022 (−0.18…+0.20), positive only 2023-2025 =
   the gold parabola.
- **FIX ATTEMPTED — RISK-OFF vol gate** (block vol_percentile ≥ 0.8, structural `regime_lib`
  threshold): OOS t1.65→1.94, cost×2 OOS +0.187 — looks better, but drift-null on the fixed variant:
  **p=0.410**. The fix shapes the same beta; still no information in the trigger. FAIL.
- Wiring note: despite registration 08-15 there is **no `logs/shadow/pullback_buy__*.jsonl`** —
  either the H1 shadow engine never fires it or it is not wired; worth checking before trusting any
  forward stats.

Recommendation: **REMOVE-FROM-REGISTRY** (like sr_fade). If kept for data collection, the registry
docstring must be corrected to "t1.65 non-overlap, drift-null p=0.53 = indistinguishable from random
long in uptrend" — the current numbers are wrong, not merely optimistic.

## C. confluence_15m — **VERDICT: NULL / OVERFIT — and the live-tradeable leg is NEGATIVE. REMOVE-FROM-REGISTRY (gold); BTC/other legs already −EV in matrix.**

Claim (`algo_registry.py:427-428`): gold M15 exp_R+0.035 OOS+0.199, ~166 fires/yr. The claim is
already unstable in the repo's own records: +0.035 (registry) vs OOS 0.006 (`continue.md:287`) vs
+0.1285/t1.34 (matrix 08-12). Offline live-parity re-derivation (M15 100k bars, EURUSD-macro
coverage 2024-02→2026-07, session 13-21, BRK12 RR2 SL1×ATR vk1.5; `s3_conf15m.py`):

- Parity: n176, exp **+0.076 t+0.69**, fires/yr ≈ 73 (not 166). **Cost×2: exp +0.018 t+0.16 — dead
  at cost stress** (median cost share 0.053R/trade at SL≈$5.6).
- **Direction-info null** (random ±1 at the same signal bars): p=**0.237** — the 5-condition
  confluence direction choice is indistinguishable from a coin flip. Random-bar matched null:
  p=0.073.
- **Leg split is perverse: BUY n123 exp −0.025 (t−0.20, in the biggest gold bull ever); SELL n53
  exp +0.310 (t1.49, noise-n).** Live has `LONG_ONLY_ALL=true` (`.env:61`) → the deployed combo can
  ONLY trade the negative leg. All backtest positivity sits in a leg the system blocks.
- Trials: `tune_confluence.py` alone = 54 gold configs (6 sessions × 3 SL × 3 RR) + 27 BTC + the
  original research_15m family → any p here is uninterpretable without correction; none is near
  passing even uncorrected.
- **FIX ATTEMPTED — long-only (live parity)**: exp −0.025, cost×2 −0.088, vs random-long null
  p=0.443. FAIL — the fix that live enforces makes it strictly worse.
- Matrix cross-section (`data/backtest_results.json`): −EV on 8/11 pairs (t to −3.2); forward shadow
  gold legs: XAUUSD 0 resolved, XAUEUR −1.04 (n2). (FX-pair forward blips like EURUSD n10 +1.7 are
  3-week small-n noise on legs the matrix scores −EV.)

Recommendation: **REMOVE-FROM-REGISTRY.** It is an 80+-trial artifact whose tradeable projection is
−EV; keeping it in shadow only spends cycles collecting data on a signal with a coin-flip direction
p.

## D. mean_reversion — **VERDICT: NULL (confirmed −EV; fix fails). REMOVE-FROM-REGISTRY.**

Already cut from live routing 07-19 (P2 OOS −EV 0/27, `regime_lib.py:14-15`). Re-derived XAUUSD H1
70k bars (`s4_dead3.py`): exp −0.070 t−3.55 OOS −0.056 (matrix: −EV all 11 pairs, t to −19.9).
Forward shadow confirms: XAUUSD n22 mean −0.466 t−2.40; XAUEUR −0.584; XAUJPY −0.779
(`logs/shadow/mean_reversion__*.jsonl`). **FIX ATTEMPTED — BUY-only (drift-aligned fade):** exp
−0.045 t−1.63, cost×2 −0.100 t−3.59. Still structurally negative; fading gold H1 loses in both
directions. Recommendation: **REMOVE** (it has now failed backtest, P2 OOS, AND forward shadow —
three independent datasets; nothing left to learn).

## E. sweep_reversal — **VERDICT: NULL (−EV as designed; "less bad than random" is not a trade). REMOVE-FROM-REGISTRY.**

Self-documented −EV (`algo_registry.py:278`). Reproduced XAUUSD H1: exp −0.056 t−1.91 OOS −0.040;
matrix −EV 10/11 pairs; forward shadow XAUUSD n16 −0.16. **FIX ATTEMPTED — BUY-only (fade prior-day-
low sweep only):** exp −0.057, cost×2 −0.116 t−3.00. FAIL. Curiosity worth recording: BUY-only sweep
bars beat matched random-longs at NEUTRAL/RANGE bars (p=0.003) — the sweep-reclaim bar is a *less
bad* long location, but its absolute EV is still negative after cost, so there is no trade; at most
this is a future entry-timing refinement for some other +EV strategy. Recommendation: **REMOVE**
(keep the p=0.003 note in the graveyard doc, not a live registry slot).

## F. regime_momentum_fvg — **VERDICT: NULL / window-noise; filter adds nothing. REMOVE-FROM-REGISTRY (redundant).**

Self-documented "no OOS edge / window bias" (`algo_registry.py:241-242`) — confirmed and worse: the
sign itself is window-dependent (full 70k H1: exp **−0.107 t−1.98**; last 50k: −0.011 t−0.18; matrix
08-12 window: +0.046 t0.69). **FIX ATTEMPTED — BUY-only (live LONG_ONLY parity):** −0.047 t−0.65,
cost×2 −0.093; and the marginal value of the FVG filter vs plain momentum BUY-only on the same window
is +0.057 vs +0.047 (both t<0.8) — i.e. the filter's contribution is statistically zero. Its base
algo (regime_momentum) was itself ruled NULL in AUDIT #4. A filter with no marginal value on top of a
null base = two registry slots for one dead hypothesis. Recommendation: **REMOVE** (regime_momentum
shadow already collects the base data).

## Ranked disposition (registry proposal — NOT applied; registry untouched)

| rank | algo | verdict | fix result | action |
|---|---|---|---|---|
| 1 | confluence_15m | NULL/OVERFIT; live-tradeable leg −EV; dead at cost×2 | long-only fix FAIL (−0.025→−0.088) | **REMOVE now** (all pairs) |
| 2 | pullback_buy | NULL; claimed t3.88 = overlap-inflation (true t1.65, drift-null p0.53) | RISK-OFF gate FAIL (p0.41) | **REMOVE now** (+ fix stale docstring if kept) |
| 3 | mean_reversion | NULL (3 independent datasets negative) | BUY-only FAIL | **REMOVE now** |
| 4 | regime_momentum_fvg | NULL; window-noise; zero marginal filter value | BUY-only FAIL | **REMOVE now** (redundant) |
| 5 | sweep_reversal | NULL (−EV; sweep-bar timing note archived) | BUY-only FAIL | **REMOVE** (archive p=0.003 timing note) |
| 6 | cdc_zone | NULL as alpha; honest beta (drift-harvest), W1 fix helps the beta (t2.74 @cost×2) but trials-corrected p≈0.28 | W1 gate: improves, does not validate | **KEEP-SHADOW, relabeled beta**; promotion only via forward n≥20 vs drift benchmark |

**Go/no-go per edge: NO-GO for live enablement for all six.** None passes VALIDATED (OOS + matched
drift-null + cost×2 + trials-corrected). No LIVE flag currently enables any of the six
(`data/algo_switches.json`: all SHADOW) — the audit found no live-money exposure here; the risk was
reputational (three stale "validated" docstrings citing t1.99/t3.88/OOS+0.199 that do not survive
re-derivation) and one wiring gap (pullback_buy produces no shadow journal at all).

Consistency check vs system priors: 6/6 audited algos land exactly on the established prior — gold
direction is not mechanically predictable; every positive number traced to (a) long-gold drift,
(b) window selection, or (c) a statistics bug (overlap inflation). The registry's only defensible
survivors after AUDIT #4+#5: regime-null shadows for data collection, tsmom_d1:BTCUSD (borderline,
frozen), and cdc_zone as a *declared* beta shadow. Everything else is graveyard material.
