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
