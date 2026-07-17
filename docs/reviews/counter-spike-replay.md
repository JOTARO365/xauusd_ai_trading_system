# counter_spike Gate — Blocked-BUY Forward-Price Replay

**Everything below is HYPOTHETICAL.** It replays BUY signals the live gate
*blocked* against real forward price to ask: did the gate block good trades or
bad trades? No orders were placed, no code/config touched. Read-only research.

**Verdict up front:** The gate is **NET-SAVING money in aggregate is NOT a safe
conclusion — but it is clearly right on BEARISH-trend dips and clearly too tight
on BULLISH-trend dips at strong support.** Do **NOT** loosen the gate globally.
There is a defensible, quantified case to *narrow* it for one segment only
(BULLISH-trend + STRONG support), but the evidence base is thin and
regime-confounded — see Caveats and Verdict. **Recommendation: keep the gate as
is for now; if released, release ONLY the BULLISH+STRONG-support segment and
only via the existing MOMENTUM_RIDE waiver path, not by lowering
`COUNTER_SPIKE_PIPS`.**

---

## 1. Method & data

| Item | Value |
|---|---|
| Gate under test | `decision_maker._counter_spike_reason()` — blocks BUY when `fast_move_pips ≤ -500` (price dropping fast) |
| Blocked signals | `logs/gate_blocks.jsonl`, filter `gate=="counter_spike" & signal=="BUY"` |
| # blocked BUYs | **107** |
| Window | 2026-06-28 22:28 → 2026-07-17 16:41 UTC (~19 days) |
| Entry (hypothetical) | block row's own `price`, at block `at` |
| SL | `default_sl_pips` = 2000 pips = **$20** below entry |
| TP | no resistance levels are logged on these rows → used the `_calc_tp_pips` fallback = **2.0×SL = $40** above entry (so **RR = 2.0** on every trade) |
| Resolution horizon | `pending_expiry_hours` = 24h |
| Rule | WIN if price reaches entry+$40 before entry−$20 within 24h; LOSS if −$20 first; else EXPIRED/CENSORED |
| No-lookahead | only price samples strictly *after* the block timestamp are used |

### Price source — READ THIS (it changes how much to trust the numbers)
I did **not** connect to MT5. My standing safety constraint is "do not connect
to MT5 live," and MT5 exposes a single non-thread-safe connection that the live
bot may be holding — initialising it from a side script risks disrupting the
running bot. So I used the **documented cached fallback**: a spot-price series
reconstructed from the `price`/`at` field logged on **every** row of
`gate_blocks.jsonl` (781 observations) plus `logs/spec_shadow.jsonl`
(55 `current` prices). Combined series spans the whole window at **~6 min median
resolution** (p90 gap 9.7 min; a few weekend/downtime gaps up to ~7 days).

**These are cycle-time spot prices, NOT OHLCV bars.** Consequence: I see price
only every ~6 min and **cannot see intrabar wicks between samples.** A fast $20
wick down that stops out the trade and then recovers is invisible to this method
— and that is *precisely* the falling-knife scenario the gate targets. So this
method **systematically under-counts SL hits during fast drops and biases
results toward WIN.** The sensitivity analysis in §3 is the honest guard against
this bias; trust it over the headline.

### Resolvability
| Outcome | n |
|---|---|
| Resolved (WIN or LOSS) | **96** |
| CENSORED (data gap / ran out before 24h, <12h coverage, no hit) | 11 |
| EXPIRED (24h, no level hit) | 0 |

96 of 107 resolvable.

---

## 2. Headline (HYPOTHETICAL) — taking all blocked BUYs

| Metric | Value |
|---|---|
| Resolved | 96 |
| WIN / LOSS | 54 / 42 |
| Win rate | **56.2 %** |
| Avg winner | +2.0R (fixed RR) / avg loser −1.0R |
| Total R | **+66.0R** |
| Expectancy / trade | **+0.69R** |

At face value the blocked BUYs would have been net-profitable. **But do not stop
here** — this number is (a) inflated by the spot-sampling WIN-bias above, (b)
dominated by one bull rally, and (c) built from auto-correlated cycles, not
independent trades. The segmentation below is where the real signal is.

---

## 3. Segmentation (the actual insight)

### By trend
| trend | resolved | WR | total R | exp/trade | reading |
|---|---|---|---|---|---|
| **BULLISH** | 29 | **82.8 %** | +43.0R | **+1.48R** | gate wrongly blocking winners |
| **BEARISH** | 55 | **38.2 %** | +8.0R | **+0.15R** | gate correctly protecting (≈ breakeven even in a bull window) |
| SIDEWAYS | 12 | 75.0 % | +15.0R | +1.25R | winners, but n tiny |

R contribution: BULLISH +43R (29 trades) and SIDEWAYS +15R (12 trades) supply
**58 of the +66R total**; the 55 BEARISH trades net only **+8R** — noise-level in
a window that was net bullish.

### By confidence tier
| conf | resolved | WR | exp/trade |
|---|---|---|---|
| 78+ | 13 | 61.5 % | +0.85R |
| 70–77 | 52 | 67.3 % | +1.02R |
| 62–69 | 23 | 43.5 % | +0.30R |
| <62 | 8 | 12.5 % | −0.62R |
Monotone: higher conf → better. `<62` blocked BUYs were correctly killed.

### By support
| segment | resolved | WR | exp/trade |
|---|---|---|---|
| at SUPPORT | 92 | 57.6 % | +0.73R |
| at **STRONG** SUPPORT | 79 | 62.0 % | +0.86R |
| not at support | 4 | 25.0 % | −0.25R |

### By fast_move magnitude
| bucket | resolved | WR | exp/trade |
|---|---|---|---|
| 500–700 p | 29 | 55.2 % | +0.66R |
| 700–1000 p | 30 | 46.7 % | +0.40R |
| >1000 p | 37 | 64.9 % | +0.95R |
(No monotone "bigger drop = worse." The >1000 bucket is skewed by SIDEWAYS
spike-and-revert cases during the 07-01 event — treat as regime artefact, not a
rule. `fast_move` is parsed from the reason string and, per the task note, looked
inconsistent — I trusted real forward price for outcomes and used `fast_move`
only for bucketing.)

### Key cross-tab
| segment | resolved | WR | exp/trade |
|---|---|---|---|
| **BULLISH & STRONG support** | 27 | **85.2 %** | **+1.56R** |
| BEARISH & STRONG support | 43 | 41.9 % | +0.26R |

This is the crux: the gate is **wrongly blocking BULLISH-trend dips at strong
support** (they bounce) and **correctly blocking BEARISH-trend dips** (they keep
falling), *even though both look identical to the gate* (fast drop into a
support zone).

### SL-width sensitivity — the fragility test
The whole edge depends on how wide the SL really is. Re-resolving with tighter
SLs (proxy for the intrabar wicks the spot series can't see) at fixed RR=2:

| SL | overall WR | overall exp | BULLISH exp | BEARISH exp |
|---|---|---|---|---|
| **$20 (bot default)** | 56.2 % | **+0.69R** | +1.48R | **+0.15R** |
| $15 | 51.0 % | +0.53R | +1.28R | **−0.07R** |
| $12 | 41.8 % | +0.26R | — | — |
| $10 | 38.8 % | +0.16R | +0.86R | **−0.47R** |
| $8 | 37.3 % | +0.12R | +0.66R | **−0.41R** |

Reads:
- **BULLISH stays clearly positive even at a $8 SL (+0.66R).** Robust — the
  wick-bias does not overturn it.
- **BEARISH flips negative as soon as the SL is tightened at all** (−0.07R at
  $15, −0.47R at $10). The BEARISH "+0.15R" at the bot's own SL is fragile and
  most likely overstated by the unsampled-wick bias. The gate is protecting
  these.
- Direct wick check at the real $20 SL: of the 54 WINs, only **6** dipped within
  75 % of the SL ($−15) and only **2** within 90 % ($−18) at sample resolution —
  so at the bot's actual wide SL the sampled WINs are mostly clean, but the
  sensitivity table shows how little headroom there is.

---

## 4. Concrete cases (timestamps)

### Gate CORRECTLY protected — BEARISH dips that kept falling (LOSS)
Late-June downtrend leg; each is a BUY blocked into a fast drop that then hit
−$20 before +$40:
- `2026-06-29T13:38:36` BEARISH conf72 STRONG-sup fast=791p entry 4035.64 → LOSS
- `2026-06-29T13:53:50` BEARISH conf72 STRONG-sup fast=1185p entry 4035.30 → LOSS
- `2026-06-29T14:00:21` BEARISH conf72 STRONG-sup fast=1500p entry 4032.15 → LOSS
- `2026-06-30T08:52:04` BEARISH conf72 STRONG-sup fast=860p entry 4015.70 → LOSS
- `2026-06-30T20:58:12` BEARISH conf65 STRONG-sup fast=1276p entry 4007.12 → LOSS
These are textbook falling knives — high conf, at "strong support," and the
support broke. This is the gate earning its keep.

### Gate WRONGLY blocked — BULLISH dips that bounced (WIN)
Mostly the 07-01/07-02 uptrend; dips into strong support that RR2-resolved up:
- `2026-07-01T12:39:49` BULLISH conf78 STRONG-sup fast=627p entry 4024.15 → WIN
- `2026-07-02T13:19:30` BULLISH conf72 STRONG-sup fast=1644p entry 4115.77 → WIN
- `2026-07-02T16:31:12` BULLISH conf78 STRONG-sup fast=1869p entry 4109.76 → WIN
- `2026-07-02T17:33:35` BULLISH conf78 STRONG-sup fast=633p entry 4111.76 → WIN
- `2026-07-02T19:40:18` BULLISH conf78 STRONG-sup fast=1001p entry 4112.59 → WIN
(In principle MOMENTUM_RIDE should already waive counter_spike for exactly these
— M15 STRONG + H1 + H4 BULLISH. That these were still blocked means the 3-tier
momentum stack was not aligned at block time. See Verdict.)

---

## 5. Caveats (must read before acting)

1. **No costs.** Spread, slippage, commission all ignored. On XAUUSD spread
   alone is often a few dollars — a real drag on a $20-SL / $40-TP trade. Real
   expectancy is lower than shown.
2. **Spot samples, not OHLCV (~6 min).** Under-counts SL hits during fast drops
   → **WIN-biased**, worst exactly in the falling-knife population the gate
   targets. §3 sensitivity is the honest correction.
3. **Not independent observations.** 95 of 107 blocks fall in **06-29 → 07-02**,
   i.e. one volatile drop-then-rally episode (blocks/day: 06-29:13, 06-30:19,
   07-01:36, 07-02:27; then only 11 across the next two weeks). The effective
   sample is roughly a handful of independent episodes, not 107 trades. Treat all
   win rates as illustrative, not statistically settled.
4. **Regime-confounded.** That episode included a ~$150 up-move (≈3970→4120) that
   lifts almost any dip-buy with a $40 TP. The +0.69R headline is inflated by
   this one rally. The BEARISH segment — which still lost in a bull-friendly
   window — is the regime-robust read that the gate is protective there.
5. **`fast_move` from the reason string** and the log's own note that the field
   looked inconsistent — used only for bucketing; outcomes come from real price.
6. **`conf` is 0 on 3 rows** (logged before confidence was populated); binned as
   `<62`.
7. TP used the flat 2×SL fallback (no logged resistance) → RR is a clean 2.0 but
   ignores that a nearer real resistance would cap some winners (lower WR).

---

## 6. Verdict

**Is `counter_spike` net-saving or net-costing?** Segment first — the aggregate
is misleading:

- **BEARISH-trend dips (60 % of all blocks): gate is CORRECT / protective.**
  ≈breakeven (+0.15R) even in a bull-tilted window, and turns clearly negative
  under any realistic tightening or trading cost. These are falling knives.
  **Keep blocking. Do not touch.**
- **BULLISH-trend dips at STRONG support (n=27): gate is TOO TIGHT.** WR 85 %,
  +1.56R, and the edge survives even an $8-SL stress test (+0.66R). This is the
  segment the gate is wrongly costing money on.
- Low conf (<62) and not-at-support blocks: gate correct (negative expectancy).

**If — and only if — the user wants to release something**, the safe, quantified
target is **BULLISH-trend + STRONG-support dips**, and the right lever is the
**existing MOMENTUM_RIDE waiver**, not lowering `COUNTER_SPIKE_PIPS`:
- Lowering the pip threshold would release BEARISH knives too — net-losing.
- These BULLISH winners were blocked because MOMENTUM_RIDE's 3-tier stack
  (M15 STRONG + H1 aligned + H4 BULLISH) was not fully aligned at block time.
  Any loosening should be tested as a *narrowing of that waiver's momentum
  requirement for the BULLISH+STRONG-support case*, so BEARISH dips stay blocked.

**Because this touches an iron-rule anti-fade guard on a live-money system, and
because the evidence is one regime episode of ~5–8 independent moves with a
WIN-biased price proxy and no costs, my recommendation is: KEEP the gate as-is
now.** The BULLISH-dip signal is directionally strong and worth acting on, but it
warrants a second replay over a wider, multi-regime window using true OHLCV
(intrabar highs/lows) and modeled spread before changing any live guard. The one
change I would endorse without that: scope any future waiver to
BULLISH+STRONG-support only — never a blanket threshold cut.

---
*Scripts: `scratchpad/replay.py`, `scratchpad/robust.py`. Raw per-trade output:
`scratchpad/replay_out.json`. Filtered input: `scratchpad/cs_buys.jsonl`.*
