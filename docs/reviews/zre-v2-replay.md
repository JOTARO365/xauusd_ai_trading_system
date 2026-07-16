# ZRE v2 (Zone Re-Entry, RR≥2, fixed-SL) — Replay Validation

> **STATUS: HYPOTHETICAL / SIMULATED — flag-OFF research. No code, config, or
> trading file was modified. No MT5 order was placed/closed/modified. main.py was
> not touched.** Every number below comes from an actual replay run
> (`scratchpad/zre_replay.py` → `scratchpad/zre_result.json`), not an estimate.
> Author: replay-validator · Date: 2026-07-16

---

## 0. TL;DR verdict

**PROCEED TO SHADOW — NOT to ENABLED (yet).**

ZRE v2 is **net-positive but thin and regime-dependent**: +17.65R over 91
hypothetical orders (~5 months), expectancy **+0.245R/trade**, but the *entire*
edge comes from **trending** D1 regimes (DOWNTREND +11.5R, UPTREND +6.7R).
**SIDEWAYS is a net drag (−0.6R).** The false-bounce (loss) rate is high (61% of
filled orders), and the strategy only survives because winners average 2.2R.
The edge sits **inside the fidelity noise** of the offline sr_meta reconstruction
(see §7), so it cannot be trusted enough to go live on this replay alone — SHADOW
with the bot's *live* sr_meta scores is exactly the confirmation step needed.

---

## 1. Data source + window

| Item | Value |
|---|---|
| Symbol | **GOLD#** (the broker's real XAUUSD symbol; `SYMBOL=XAUUSD` maps to `GOLD#`) |
| Source | **Live MT5 terminal** (reachable), `copy_rates_from_pos`, read-only |
| Timeframes pulled | H1 (5000), H4 (2000), D1 (600), W1 (200), M15 (10000) bars |
| Replay window | **2026-02-11 19:45 → 2026-07-16 02:00 UTC** (~155 days) |
| H1 bars evaluated | **2502** (one decision per H1 close) |
| Why this window | Window is bounded by **M15 history start (2026-02-11)** — M15 is required for the `counter_spike` fast-move guard. Earlier H1 exists but would run that guard blind. |
| Zone derivation | sr_meta **recomputed at every H1 close** by calling the **real chart_watcher functions** (`find_swing_levels`, `find_key_levels`, `calc_fibonacci`, `_build_sr_meta`, `_score_zone`) on no-lookahead closed-bar slices (H4≤200, H1≤100, D1≤60, W1≤30). D1 trend from `calc_d1_trend` logic (D1 EMA20, closed bar). |
| No-lookahead | Decision + order placement occur at the **H1 bar CLOSE**; fills/TP/SL are resolved only on **M15 bars strictly after** that close. |

Guard constants mirrored from source: `default_sl_pips=2000` (=$20),
`min_rr_ratio=2.0`, `COUNTER_SPIKE_PIPS=500`, `max_pending_*=4`,
`MAX_TRADES_PER_DAY=6`, `MIN_DIST/DUPLICATE_ZONE=0.3%`, `PENDING_EXPIRY=24h`.
ZRE params: `ZRE_MIN_SCORE=78`, `ZRE_MAX_BARS_SINCE=3`, `ZRE_PROXIMITY_PCT=0.4%`,
`ZRE_PER_ZONE=1`, SL mode = **fixed 2000p**.

---

## 2. Trigger counts (funnel + per regime)

**Funnel** — from raw zone candidates to actually-placed pending LIMITs:

| Stage | Count |
|---|---|
| Raw candidates (grade A/B, score≥78, fresh≤3 bars, within 0.4%, valid side) | **645** |
| − blocked by D1-counter guard (`_d1_counter`) | −359 |
| − blocked by counter_spike (price breaking through zone ≥500p fast) | −93 |
| − blocked by 1-per-zone dedup (`ZRE_PER_ZONE`) | −102 |
| − blocked by per-side slot cap (max 4) | −0 |
| − blocked by daily cap (6/day) | −0 |
| **= ZRE v2 orders placed** | **91** |

Multi-lane is genuinely adding candidates: **645 raw hits** across the window, of
which the guards keep the placed count to **91** (~0.6/day). The **slot cap and
daily cap were never hit** — ZRE stays comfortably bounded on its own (peak ≈4
concurrent SELL pendings). The **D1-counter guard is by far the dominant filter**
(359 rejects), which is the intended behaviour (it kills counter-trend fades).

**Per-regime (by D1 trend at trigger):**

| Regime (D1) | Placed | Sides | WIN | LOSS | Never-filled | Total R |
|---|---|---|---|---|---|---|
| **DOWNTREND** (BEARISH) | 41 | SELL 41 | 13 | 19 | 8 | **+11.53** |
| **UPTREND** (BULLISH) | 14 | BUY 14 | 6 | 6 | 2 | **+6.72** |
| **SIDEWAYS** (NEUTRAL) | 36 | BUY 26 / SELL 10 | 9 | 19 | 8 | **−0.60** |

(In DOWNTREND/UPTREND the D1-counter guard forces trend-aligned side only; in
SIDEWAYS both sides fire — and that bucket is where ZRE bleeds.)

---

## 3. Hypothetical outcomes

All outcomes simulated on M15 forward bars. Same-bar TP+SL tie → counted **LOSS**
(conservative). "EXPIRED" here = filled but data ended before TP/SL resolved
(1 censored case at the very end of the window).

| Metric | Value |
|---|---|
| Placed | **91** |
| NEVER-FILLED (limit never touched in 24h) | 18 (20%) |
| Filled | 73 |
| **WIN** | **28** |
| **LOSS** | **44** |
| EXPIRED (censored, data ended) | 1 |
| **Win-rate (resolved 72)** | **38.9%** |
| Avg winner R:R realized | **2.20** |
| Avg R over resolved | **+0.245** |
| **Total R** | **+17.65** |

Expectancy check: 0.389 × 2.20 − 0.611 × 1.0 = **+0.24R/trade** — positive, but
thin, and highly sensitive to the win-rate (a 4-point drop to ~35% flips it to
roughly breakeven).

**Trend vs Range lanes (by side):**

| Lane | Placed | WIN | LOSS | Never-filled | Win-rate | Total R |
|---|---|---|---|---|---|---|
| SELL (fade resistance) | 51 | 17 | 23 | 10 | 42% | **+15.53** |
| BUY (fade support) | 40 | 11 | 21 | 8 | 34% | **+2.12** |

SELL carried the book; BUY was barely above water.

**Hold times (resolved, hours):** median **3.2h**, mean **7.7h**, max **76.8h**;
**67/72 (93%) resolved within 24h**, 68/72 within 48h, only 2 held >72h. So the
"fixed 2000p SL ⇒ far TP ⇒ long holds" concern is **real but modest** — gold's
$40 (2R) target is usually reached same-day; the long-hold tail is small.

**RR-target distribution:** 61 of 91 used the 2.0R floor (nearest opposite zone
too close); the rest ran to a farther opposite zone (up to 5.2R target).

---

## 4. False-bounce cases (the key failure mode)

**44 of 72 resolved orders (61%) were false bounces** — the limit filled at the
zone, then price broke *through* it to the fixed SL instead of bouncing.
Concrete quick-break examples (filled and hit SL in <3h):

| Timestamp (UTC) | Side | Zone | Ctx | Result |
|---|---|---|---|---|
| 2026-02-24 15:00 | BUY | 5145.15 | grA sc86, D1 BULLISH | filled → broke to SL 5125.15 in 0.2h |
| 2026-03-03 12:00 | BUY | 5260.39 | grA sc79, D1 BULLISH | filled → broke to SL 5240.39 in 0.2h |
| 2026-03-03 21:00 | BUY | 5130.34 | grA sc79, D1 BULLISH | filled → broke to SL in 0.0h (same bar) |
| 2026-03-30 12:00 | SELL | 4543.97 | grA sc88, D1 BEARISH | filled → broke to SL 4563.97 in 0.2h |
| 2026-03-31 18:00 | SELL | 4602.32 | grA sc82, D1 BEARISH | filled → broke to SL in 0.0h (same bar) |
| 2026-04-02 08:00 | BUY | 4667.03 | grA sc97, D1 NEUTRAL | filled → broke to SL 4647.03 in 0.0h |

Note several are **grade-A, high-score, trend-aligned** zones — i.e. the false
bounces are not obviously filterable by score/grade alone. This is the core risk:
a "strong zone" that breaks looks identical to one that holds until after fill.

---

## 5. Comparison

**vs. doing nothing:** ZRE v2 adds ~91 entries / ~5 months for a hypothetical
**+17.65R** (net of the 44 losses, before costs). Doing nothing = 0R. So on
simulated price-only outcomes ZRE is additive — *if* the reconstruction fidelity
holds (§7) and *if* spread/slippage don't eat the thin edge (they are **not**
modeled here — see caveats).

**vs. existing post-SL SL-RE (`manage_sl_reentry`):** I searched the live
`logs/trades.json` (501 recorded trades) for SL-RE / pending-LIMIT / Post-SL /
ZRE / RNG tags — **zero matches**, and 0 rows mention "LIMIT". SL-RE is
**reactive** (fires only in the 30-min window *after* a real SL close, RR≥2,
one-per-side), so it structurally produces far fewer setups than ZRE's
**proactive per-bar zone scan**. ZRE would be a large increase in setup frequency
versus a path that has effectively contributed ~no logged entries. (Caveat:
trades.json may log only filled market positions; pending-LIMIT history could
live elsewhere — but the frequency contrast stands.)

---

## 6. The 4060 case (2026-07-15) — trace

Documented miss: price rejected **4060** during **14:13–16:11 UTC** but the bot
never took the SELL (NO_TRADE at 14:xx, then NEWS_GATE / slot blocks at 15:15 /
16:11). **Would ZRE v2 have caught it?**

**Replayed placements 2026-07-14…16:**

| H1 close (UTC) | Side | Zone | cur | score/grade | D1 | fast-move | Result |
|---|---|---|---|---|---|---|---|
| 07-14 17:00 | SELL | 4091.43 | 4076.6 | 80 / A | BEARISH | +93 | **WIN +2.0R** |
| 07-15 07:00 | SELL | 4034.00 | 4031.3 | 94 / A | BEARISH | +53 | LOSS −1R (broke up) |
| 07-15 18:00 | SELL | 4062.05 | 4060.5 | 78 / A | BEARISH | −1424 | EXPIRED (censored) |
| 07-15 20:00 | SELL | 4034.00 | 4033.7 | 96 / A | BEARISH | +104 | LOSS −1R |

**Answer: No — not during the 14:13–16:11 window.** At those H1 closes there was
**no grade-A/B, score≥78 resistance zone within 0.4% of ~4060**. Cross-checked
against the bot's *live* sr_meta snapshot in `logs/spec_shadow.jsonl` @14:12: the
scored resistance ladder was 4080 / 4103 / 4120 / 4138 / 4180 / 4202 — **nothing
at 4060**. The 4060 level was an *intraday* rejection point that had not yet
crystallised into a scored swing zone. ZRE only placed a SELL at **4062.05 at
18:00**, ~2–4h *after* the documented window, once that swing high had formed and
scored 78 (and even then it didn't resolve before data end).

**Interpretation:** ZRE v2 is a **lagging zone-confirmation** system, not an
intraday reversal catcher. It partially/indirectly addresses the 4060 miss (it
does fade that region once the zone is established) but it does **not** solve the
specific 14:xx NO_TRADE / 15:15 NEWS_GATE parts — which is consistent with the
design doc, where drafts (ก) NEWS-dampener and (ข) scalp-fade target those parts.

---

## 7. Fidelity caveats (read before trusting the numbers)

1. **Offline sr_meta scores diverge from live.** The reconstruction uses the real
   scoring functions but rebuilds D1/W1 confluence levels and (in live) a forming
   bar; individual zone scores drift **±10–25 points** vs the live snapshot.
   Concrete: at 2026-07-15 14:12 the live bot scored H4 **4103.99 = 66/B**, my
   reconstruction scored it **90/A**. The zone *ladder* matches; exact crossings
   of the **78** threshold do not. **⇒ Trigger counts are indicative, not exact,
   and the thin edge lives inside this noise band.**
2. **No spread / commission / slippage modeled.** Gold spread (~$0.20–0.40 per
   round trip) applied to 73 fills erodes the +17.65R materially. Real edge < sim.
3. **M15-granularity fills.** Sub-15-min ordering of TP vs SL within a bar is
   unknown; ties resolved as LOSS (conservative).
4. **counter_spike** only computable from 2026-02-11 (M15 start) — it defines the
   window rather than limiting it.
5. **Censoring:** 1 order (07-15 18:00) unresolved at data end.

---

## 8. Recommendation

**SAFE TO ENABLE: NOT YET. Recommended next step: SHADOW (flag-OFF data capture).**

Evidence:
- **Positive but thin & fragile:** +0.245R/trade, +17.65R/91 trades — a ~4-point
  win-rate drop or realistic spread flips it toward breakeven.
- **Regime-concentrated:** all the edge is in trending D1 (DOWNTREND +11.5R,
  UPTREND +6.7R); **SIDEWAYS is net-negative (−0.6R)** even after the D1-counter
  guard. The BUY lane (+2.1R) is nearly flat.
- **High false-bounce rate (61%)**, including on grade-A/high-score zones —
  survivable only via 2.2R winners; not robust to a worse fill distribution.
- **Fidelity gap:** the offline score reconstruction (§7-1) is large enough that
  exact trigger counts and the sign of the edge cannot be trusted for live money.

Concrete asks before ENABLED:
1. **Run SHADOW** (the design's own gate #4) so triggers use the bot's *live*
   sr_meta scores — this removes the §7-1 reconstruction gap, the single biggest
   uncertainty.
2. **Test a SIDEWAYS suppression** / require D1 trend ≠ NEUTRAL (trend-align
   only). In this replay that removes the −0.6R losing bucket and lifts total R
   without touching the winning trending lanes.
3. **Re-run with spread/slippage** to confirm the edge survives costs.
4. Keep the gate-integration audit (design gate #3) — the caps held (slot/daily
   never hit), and D1-counter + counter_spike did the heavy filtering as intended.

**Bounded-risk positives:** caps were never breached, hold times are mostly
<24h (93%), and 20% never-filled orders cost nothing — so ZRE v2 is *contained*.
It is the **edge quality**, not runaway frequency, that blocks a live enable.
