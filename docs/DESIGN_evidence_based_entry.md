# DESIGN — Evidence-Based Order-Entry Decision Layer (dip-buy vs falling-knife)

**Status: DESIGN PROPOSAL ONLY. Flag-OFF. Nothing here is wired into the live pipeline.**
Reference implementation: `docs/proposals/evidence_entry_reference.py` (standalone, imported by nothing).

**Author:** research/quant pass (read-only). No file was modified, no gate/money-management/SL/TP/prompt was
touched, no order path was changed. This document proposes a *replacement discriminator* for one specific
heuristic — the `counter_spike` guess — and specifies how it must be **fitted and validated before any use.**

**Iron rules this design commits to (unchanged):** RR ≥ 2 (`MONEY_MANAGEMENT["min_rr_ratio"]=2.0`), fixed SL,
NO averaging / martingale, every existing gate stays in place, flag-OFF until user approval **and** a passing
replay. This model can only ever be an *additional* discriminator *inside* the counter-spike branch; it never
loosens `_htf_direction_reason`, `_run_gates`, streak, daily-loss, or slot logic.

---

## 0. TL;DR

**Architecture vision (the frame for everything below): the AI/model SELECTS the entry *algorithm*, it does not
guess a price.** Instead of a magnitude threshold deciding "block or not," the decision layer is a
**regime-router over a LIBRARY of deterministic, math-defined entry algorithms** — each algorithm carries
explicit preconditions and a fixed entry/SL/TP formula (support-bounce-at-graded-zone, momentum-breakout,
range-fade, trend-pullback/EMA, mean-reversion-on-divergence). The model's only job is to **classify the current
market state → pick the one algorithm whose preconditions are met AND whose expected value is highest → that
algorithm computes the deterministic entry.** If *no* algorithm's preconditions hold, the answer is **stand down**
— which is exactly what a falling knife is. This is not a new subsystem: it *builds on* the project's existing
`entry_type` taxonomy (`SR_ZONE` / `EMA_PULLBACK` / `MOMENTUM_BREAKOUT` / `TREND_CONT`) and the already-scaffolded
`agents/specialist_router.py` (regime → per-TF specialist candidates, ranked A/B/C). See §1.5.

`decision_maker._counter_spike_reason()` blocks a BUY whenever `abs(fast_move_pips) >= 500` on a fast drop, on
the stated assumption *"น่าจะข่าว (probably news)"*. In the selector frame the real question is **"is this a valid
`support-bounce` algorithm setup, or is no algorithm valid (→ falling knife → stand down)?"** — not "is the drop
big?" We answer it with a transparent, calibratable **Bayesian log-odds model of P(bounce)** that serves as the
**precondition + EV scorer for the support-bounce algorithm**, built from signals the bot already computes (news
score + freshness, `reversal_confirm`, m15/h1 momentum alignment, the zone's empirical `bounce_pct` vs
`break_pct`, `fast_move` as **one** feature, RR). The rule is `select support-bounce iff P(bounce) ≥ τ AND RR ≥ 2`;
otherwise the **stand-down / falling-knife veto** fires — *only* when the evidence actually converges on a knife
(real adverse news **AND** no reversal confirm **AND** momentum still adverse **AND** low empirical bounce prior).
Weights and τ are **fitted from the labelled counter-spike replay**, not chosen by hand.

**Intellectual-honesty clause, stated once and binding on the whole document:** a "smarter" model that is not
validated on history is *just a new guess with more parameters*. The crude guard exists because replay proved
that fading fast drops lost money. This model MUST be shown, on the same replay, to **beat** the crude guard on
net-R and tail risk **before** it is enabled. Until fitted, the reference code defaults to behaving **no looser
than the crude guard** (§8, §9).

---

## 1. Problem framing — why the current `fast_move` heuristic is statistically weak

The live guard (`agents/decision_maker.py:114`):

```python
if abs(fast) < _cfg.COUNTER_SPIKE_PIPS:      # 500 pips
    return None
if fast < 0 and direction == "BUY":
    return "Counter-spike: ราคาดิ่งลง ... (น่าจะข่าว) — ห้าม BUY สวนการร่วง"
```

**Evidence from the bot's own block log** (`logs/gate_blocks.jsonl`, 917 rows, 2026-06-28 → 2026-07-14;
`counter_spike` = 146 blocks):

| Cut | Count | Reading |
|---|---:|---|
| `counter_spike` blocks total | 146 | |
| …of which **BUY** (dip-buy) | **107 (73%)** | the guard is overwhelmingly a *dip-buy* killer |
| …at **SUPPORT** zone | **103 (71%)** | it blocks buys *exactly where mean-reversion is most likely* |
| …at **conf ≥ 62** (passed every other gate) | **136 (93%)** | it kills otherwise-qualified, high-confidence setups |
| …with `d1_trend` recorded | 13 (all BEARISH) | most blocks predate richer logging → guard acts blind |

Four concrete statistical weaknesses:

1. **Single feature, hard threshold.** The decision is a step function of one variable, `|fast_move|`, with a
   round-number cut (500) that was *chosen*, not *fitted*. No measured precision/recall, no ROC, no EV curve
   backs the 500.
2. **It is a proxy for a signal the bot already measures directly.** The stated purpose is "there is news."
   But `data/news_impact.json` carries a *scored, directional* news aggregate (`score ∈ [-100,+100]`, `n_scored`,
   `updated`). Using magnitude as a proxy for "news happened" while a real news signal sits unread is the textbook
   definition of a weak feature.
3. **Base-rate / zone-context neglect.** A −600p drop *into a grade-A support that has bounced 100% of 7 tests*
   and a −600p drop *through a worn support in a fresh D1 downtrend* get the identical block. The guard cannot
   tell a support bounce from a breakdown because it never looks at `sr_meta[].bounce_pct/break_pct`.
4. **Low discriminative power of the lone feature.** Drop magnitude correlates with **both** genuine knives
   **and** sharp-but-recoverable dips (a news-driven overshoot that snaps back). A feature that rises under both
   classes has poor single-feature separation; magnitude only becomes informative *conditioned on* news polarity,
   reversal state, and the zone prior — which is exactly what a multi-feature model supplies.

**What we keep.** The guard's *instinct* is sound and replay-proven: fading a real, unconfirmed, into-the-trend
knife loses money. We are not discarding that. We are replacing the *test for "is this a knife?"* from
"magnitude ≥ 500" to "the evidence says knife."

---

## 1.5. Architecture — AI as algorithm-selector over a deterministic library (build on what exists)

The design principle is **separation of *selection* (uncertain, model's job) from *execution* (deterministic,
formula's job).** The AI never invents a price; it picks *which* pre-defined algorithm applies, and that
algorithm computes the entry/SL/TP by fixed rule.

**The library (each = preconditions + deterministic formula).** This is a *catalogue of the algorithms the bot
already expresses as `entry_type`*, made explicit — not a new set of strategies:

| Algorithm (id) | Existing `entry_type` / owner | Preconditions (regime + state) | Deterministic entry / SL / TP |
|---|---|---|---|
| `support-bounce` | `SR_ZONE` (BUY) / `range_specialist` | at graded S-zone, bounce-prior high, reversal/PA turning, not a knife | entry at zone; SL = wick-SL beyond zone; TP = RR·SL (RR≥2) |
| `resistance-fade` | `SR_ZONE` (SELL) | at graded R-zone in ≤SIDEWAYS/BEARISH, no up-breakout | mirror of above |
| `momentum-breakout` | `MOMENTUM_BREAKOUT` | range-edge break + m15 STRONG aligned | breakout close; SL = ATR-based; TP = RR·SL |
| `trend-pullback` | `EMA_PULLBACK` / `TREND_CONT` / `trend_specialist` | H1+H4 EMA stack aligned, price at EMA20 pullback | pullback entry; SL = ATR; TP = RR·SL |
| `mean-reversion-divergence` | (candidate, not yet built) | momentum divergence at extreme | reversion entry; fixed SL/TP |
| `STAND-DOWN` | — (the `_fail` path) | **no** algorithm's preconditions hold, or knife-veto | no order |

**The selector = a two-stage router** that *reuses `agents/specialist_router.py`*:
1. **Classify state → eligible algorithms.** `specialist_router.route()` already turns `chart_data` + the zone map
   into per-TF regime lanes (`h1/h4/d1 ∈ {BULLISH,BEARISH,SIDEWAYS}`) and emits ranked candidates with a quality
   grade (A/B/C) — this *is* the "which algorithms' preconditions are met" step. We do not reinvent it; the
   evidence model plugs in as the **precondition + EV score for the `support-bounce` candidate** (and, by
   symmetry, `resistance-fade`), replacing the router/gate's current reliance on the crude magnitude veto.
2. **Rank eligible algorithms by EV, pick the top or STAND-DOWN.** `route()` already ranks by `(quality, tf)`.
   We refine the ranking key so a candidate's rank is its **calibrated EV** = `P(success)·R − (1−P(success))·1`
   (with RR = R), and add an absolute floor: if the top candidate's EV ≤ 0 (or `P < τ`), the selector returns
   **STAND-DOWN** — the principled, evidence-based version of "counter_spike blocked it."

**Re-reading the counter_spike problem in this frame:** a fast −600p drop is not "big move → block." It is a
*state* that must be classified: *is `support-bounce`'s precondition set satisfied?* (graded S-zone with high
bounce prior, reversal confirming, news not adverse, momentum turning) → **select support-bounce, deterministic
entry**. If instead the state matches *no* algorithm (news adverse, momentum still down, worn/absent zone) →
**STAND-DOWN**. The magnitude of the drop is one input to that classification (F6), never the classifier.

**Boundary (unchanged):** the selector emits *at most one selected algorithm*; the chosen algorithm's
deterministic output still flows through the **unchanged** downstream gates (`_htf_direction_reason`,
counter-trend, SIDEWAYS, session, min-conf, streak, slot, SL-range) and the shared daily cap. Selection can only
*remove a false STAND-DOWN* or *choose among already-eligible algorithms*; it can never bypass a gate, change
RR≥2, alter fixed SL, or place an order itself.

---

## 2. Feature set (all from fields the bot already produces)

Shapes verified against the live `logs/bot_status.json` and `data/news_impact.json`. For a candidate of a given
`direction` (focus: `BUY` into a drop), define the trade-frame sign convention: a feature is **supportive** when
it argues the dip will bounce *in the trade's direction*, **adverse** when it argues falling-knife.

| # | Feature | Source field | Extraction | Role |
|---|---|---|---|---|
| F1 | `news_adverse` | `news_impact.aggregate.score`, `.n_scored`, `.updated` | sign of score vs direction; only trust if `n_scored ≥ 3`, `|score| ≥ NEWS_GATE_OPPOSE(40)`, and fresh (`age_min ≤ window_min`) | **primary knife evidence** — real bearish news under a BUY |
| F2 | `news_fresh` | `news_impact.updated`, `.window_min` | `age_min = now − updated`; decay weight `exp(−age/half_life)` | stale news ≠ current driver → down-weight F1 |
| F3 | `reversal_confirm` | `signals.reversal_confirm.{status,direction}` | `+1` if `status=="confirmed" and direction==trade dir`; `−1` if confirmed *against*; `0` else | **primary dip evidence** — PA says the drop is turning |
| F4 | `mom_align` | `momentum_tf.m15`, `.h1` `{direction,strength}` | weighted vote: m15 STRONG same-dir = strong support, m15/h1 still adverse = knife | is price *still* falling or curling up? |
| F5 | `zone_bounce_prior` | nearest `sr_meta[]` entry: `bounce_pct`, `break_pct`, `n_tests`, `grade`, `bars_since_touch` | **Beta-smoothed** empirical bounce rate (§3) | the calibrated **prior** P(bounce) at *this* level |
| F6 | `fast_move` | `fast_move_pips` | signed, scaled (e.g. `tanh(fast/500)`) — **one feature, not the gate** | overshoot magnitude, now *conditioned* on F1–F5 |
| F7 | `vol_tilt` | `volume_profile.tilt` (tick-vol proxy) | `+1` supportive / `−1` adverse; **low weight** (proxy, not real volume) | weak corroborator only |
| — | `RR` | `plan.tp_pips / plan.sl_pips` | **hard constraint**, not scored: reject if `< 2.0` | iron rule |

Notes:
- F5 is the statistical heart. `sr_meta[].bounce_pct` is an *empirical frequency* the bot already computes in
  `chart_watcher._touch_recency_bounce` / `_score_zone`; it is a real, per-level bounce prior — exactly the
  base-rate the crude guard ignores.
- Everything is **computed-in-code from existing outputs** — **zero new Claude calls, zero new API cost.**

---

## 3. The zone bounce prior (F5) — Beta smoothing, not raw percentage

Raw `bounce_pct` is unreliable at low `n_tests` (a zone touched once with `bounce_pct=null`, or 2 tests reading
100%). Use a **Beta-Binomial** posterior with a weak informative prior:

```
bounces  = round(bounce_pct/100 * n_tests)          # reconstruct successes
p_bounce = (bounces + α) / (n_tests + α + β)          # posterior mean, Beta(α,β) prior
```

Default `α = β = 1` (uniform Beta(1,1) → Laplace rule of succession). If desired, set the prior mean to the
*global* historical support-bounce rate `p0` measured on the trade DB, with prior strength `k`:
`α = k·p0`, `β = k·(1−p0)`. This shrinks thin zones toward the global base rate and lets proven zones
(high `n_tests`) speak for themselves. A recency taper (`bars_since_touch`) and `grade` can adjust `k`.

The prior enters the model as **log-odds**: `logit(p_bounce) = ln(p_bounce / (1 − p_bounce))`.

---

## 4. The model — Bayesian log-odds (interpretable, calibratable)

*Role in the architecture (§1.5): this model is the **precondition + EV scorer for the `support-bounce`
algorithm**. Its `P(bounce)` becomes that algorithm's `P(success)`, which the selector turns into EV
(`P·R − (1−P)·1`) to rank it against the other algorithms or STAND-DOWN. Each other algorithm gets its own
analogous scorer; this document works `support-bounce` end-to-end as the template because it is the one the
`counter_spike` guess currently mishandles.*

We model the probability that a dip resolves as a **bounce in the trade direction** as a logistic function whose
*intercept is the zone prior* and whose evidence terms are additive log-likelihood-ratio contributions:

```
logit P(bounce) = logit(p_bounce_zone)                     # F5 — empirical prior (the intercept)
                + w_news   · f_news(F1, F2)                 # adverse news pushes DOWN
                + w_rev    · F3                             # reversal_confirm pushes UP
                + w_mom    · F4                             # momentum alignment
                + w_fast   · f_fast(F6)                     # overshoot, signed & bounded
                + w_vol    · F7                             # weak corroborator
                + b0                                        # global calibration offset

P(bounce) = 1 / (1 + exp(−logit))
```

This is **logistic regression with an offset** (the zone prior is an *offset* term, not a free intercept — it is
already a probability, so we trust it and let the other weights be *corrections* to it). Properties that make it
the right choice here:

- **Interpretable.** Each `w_i · f_i` is an additive shift in *log-odds* — you can read, per decision, exactly
  how many "bounce-points" news removed and reversal added. This is auditable in a way no black-box is.
- **Calibratable.** Logistic output is a probability; it can be checked against realized bounce frequency with a
  reliability diagram and, if needed, Platt/isotonic recalibrated. "P=0.7" must *mean* 70%.
- **Monotone & bounded evidence.** `f_fast = tanh(fast/s)` bounds the overshoot term so a 5000p spike cannot
  dominate; `f_news` is gated on freshness/`n_scored` so stale or thin news contributes ~0.
- **Reduces to sanity at the corners.** No news + no reversal + adverse momentum + low prior → `logit` collapses
  well below 0 → the veto fires. Bullish-flip evidence at a proven support → `logit` rises above τ → allow.

### Decision rule

```
if RR < 2.0:                      SKIP        # iron rule, unchanged
elif P(bounce) ≥ τ:               ALLOW dip-buy (hand back to the remaining gates)
else:                             BLOCK  "falling-knife: <which evidence convicted it>"
```

### The falling-knife veto (the explicit replacement for the guess)

Blocking must be *evidence-convicted*, not magnitude-convicted. Beyond the probabilistic `P < τ`, we define a
high-precision **AND veto** that names the exact condition the crude guard was *trying* to approximate:

```
falling_knife  ⟺  news_adverse_confirmed          # F1 fresh, |score|≥40, n≥3, against the trade
             AND  reversal_confirm not in favour   # F3 ≤ 0
             AND  momentum still adverse            # F4 adverse (m15/h1 not turned)
             AND  zone_bounce_prior low             # F5 posterior below global base rate
```

- **All four must hold** → this is a real knife → BLOCK (this is where the guard *should* fire, and now does so
  for a *reason*, logged with the convicting evidence).
- **Any one fails** and `P ≥ τ` → ALLOW: e.g. a −600p drop into grade-A support (bounce prior 0.9) with
  `reversal_confirm` = BUY and bullish news is a **dip**, not a knife — the crude guard blocked it, this model
  passes it back to the normal gates.

This is precisely the user's principle operationalised: *block a counter-trend dip-buy ONLY when evidence says
falling-knife, else allow.*

---

## 5. Thresholds DERIVED from data (weights `w_i`, offset `b0`, threshold `τ`)

**Nothing above is a number until it is fitted.** The fitting recipe:

### 5.1 Labels — from the counter-spike replay (the label source)

The counter-spike replay running in parallel is the label generator. For each historically **blocked-BUY**
counter-spike event, it assigns the counterfactual outcome from forward price:

```
label = WIN(1)   if price bounced ≥ +1R (TP-distance) before hitting −1R (fixed SL)
label = LOSS(0)  if it fell −1R first  (a true knife — the guard was right)
```

This yields a supervised dataset `{ (F1..F7, p_bounce_zone), label }`. **Crucially**, the label is defined on
the *same* RR/SL the live system uses, so "beating the guard" is measured in the currency that matters (net R).

### 5.2 Fit

- Standardise features; fit `w_i, b0` by **L2-regularised logistic regression** (ridge; small dataset → shrink
  to avoid over-fitting the 100–200 events). Keep the zone prior as a fixed **offset**, so the fit only learns
  *corrections* to the empirical prior — this is both more data-efficient and more interpretable.
- Report each weight with a bootstrap CI. A weight whose CI straddles 0 is dropped (Occam / audit rule: no
  feature without evidence it separates the classes).
- **Calibrate:** reliability diagram on held-out folds; if mis-calibrated, Platt-scale. Target: predicted P
  within ±0.1 of realized frequency across deciles.

### 5.3 Choose τ from the EV/cost curve, not by hand

RR fixes the breakeven win rate: with reward `R` and risk `1` unit, `EV > 0 ⟺ P(win) > 1/(1+R)`. For RR = 2,
breakeven `P = 1/3`. So **τ ≥ 1/3 is a hard floor** — never allow a dip-buy the model itself rates below the
mathematical breakeven. The *operating* τ is then swept on the validation set to maximise realized net-R (or a
chosen precision on the ALLOW class), with a margin above 1/3 for estimation error. τ is **read off the curve**,
reported with the confusion matrix at that point — it is not an opinion.

### 5.4 Minimum sample gate (honesty)

Fitting on < ~100 labelled blocked-BUY events, or with the class heavily imbalanced, is **not** a fit — it is
noise with weights. Below the minimum-N bar (to be set in the validation plan, §7), the model stays OFF and the
crude guard remains authoritative. See §9.

---

## 6. How this specifically replaces the `counter_spike` guess

| Aspect | Current `_counter_spike_reason` | Proposed evidence layer |
|---|---|---|
| Trigger to consider blocking | `abs(fast_move) ≥ 500` | same *entry point* (only evaluate inside the counter-spike branch — cheap, no scope creep) |
| Basis of the block | magnitude only ("น่าจะข่าว") | `P(bounce) < τ` **and/or** the 4-way evidence veto |
| Uses real news? | No | Yes — `news_impact.json` score/freshness (F1,F2) |
| Uses the zone's empirical bounce history? | No | Yes — Beta-smoothed `bounce_pct` prior (F5) |
| Uses PA reversal / momentum? | No | Yes — `reversal_confirm` (F3), m15/h1 (F4) |
| Behaviour on a proven-support bounce with bullish news + confirmed reversal | **BLOCK** (false negative) | **ALLOW** → back to normal gates |
| Behaviour on a real bearish-news knife, no reversal, momentum down, worn support | BLOCK (right, by luck of magnitude) | **BLOCK** (right, by evidence — and logged with the reason) |
| Threshold provenance | round guess (500) | fitted `w_i`, τ from EV curve |

**Integration stance (proposal, not wiring):** the evidence layer would sit *only* inside the existing
counter-spike decision point and would return one of `{BLOCK, ALLOW}`. `ALLOW` does **not** mean "trade" — it
hands the candidate back to the *unchanged* downstream gates (`_htf_direction_reason`, counter-trend, SIDEWAYS,
session, min-conf, streak, slot, SL-range). It can only *remove* a false block; it can never bypass another gate.

---

## 7. Validation plan (echoes the project's rollout gate; mirrors `docs/reviews/replay-validation.md`)

**Precedent honoured:** `docs/reviews/replay-validation.md` already established this project's standard — *"0
entries looks safe" is an artifact of missing data, not safety.* The same rigour binds this proposal.

### 7.0 The P1 enabler — a queryable per-decision snapshot → outcome table (must close first)

**The single biggest missing piece for fitting the selector from DATA is a labelled
`(features-at-decision → eventual bounce / PnL)` table that is not selection-biased.** Fitting weights, τ, and
per-algorithm EV without it is impossible — and any model shipped without it is, by this document's own standard,
just a more elaborate guess. Three concrete gaps in the current persistence, each verified in the repo:

| Source | Has decision-time features? | Has outcome? | Fatal flaw for fitting |
|---|---|---|---|
| DB `trades` (+ `_decision_snapshot`) | partial | **yes** (PnL) | **Selection bias** — only *TAKEN* trades. The algorithm the selector must learn to *avoid* (blocked knives) never appears → the model can't learn the negative class from here. |
| `logs/gate_blocks.jsonl` | thin slice | **NO outcome** | Has the blocked-signal context (the negative-class *candidates*) but **no forward price path** → cannot be labelled WIN/LOSS. |
| `trades.planned_sl_pips / entry_score / atr_h4 / momentum / htf_zone_tf` | yes (5 cols) | via join | **WRITE-ONLY.** `reporter._decision_snapshot` + `db/writer.py` persist them, but `db/reader.py` never `SELECT`s them and `ml/train_filter.py` doesn't use them as features → captured, then ignored. |

**Phase 0 (P1) work — the enabler, all flag-OFF / shadow-only:**
1. **Persist an append-only per-decision snapshot** at the selection point (both TAKEN *and* STAND-DOWN/blocked
   candidates), carrying the full feature vector `{F1..F7, p_bounce_zone, chosen_algorithm|STAND-DOWN, direction,
   entry_price, RR, timestamp}`. This closes the selection-bias hole: the *negative* class (blocked knives) gets
   recorded with features, not just the positives that were taken.
2. **Forward-bar outcome join** — label each snapshot WIN/LOSS by whether price reached +1R (TP-distance) before
   −1R (fixed SL), so the label is in net-R terms (§5.1).
3. **Make the write-only columns readable** — have `reader` select the `_decision_snapshot` columns and let the
   fitter (and `ml/train_filter`) consume them, so the 5 already-captured fields stop being dead data.
4. **Interim label source:** until the append-only table has accumulated, the **counter-spike replay running in
   parallel** is the interim labeller for *blocked BUYs* specifically (blocked-BUY → bounced(WIN)/fell(LOSS)) —
   enough to fit the `support-bounce` vs STAND-DOWN discriminator, not the full multi-algorithm selector.

This is the same class of blocking gap the specialist replay hit (`docs/reviews/replay-validation.md`): without
the per-cycle full-contract time-series + forward bars, "0 blocks looks safe" and "the selector picks well" are
both **unfalsifiable artifacts of missing data**, not properties of the model. Close the gap first.

### 7.1 Acceptance criteria (all must pass before any live use)

1. **Sample:** ≥ ~100 labelled blocked-BUY events (and a healthy LOSS/WIN mix), stated up front like the
   specialist replay's "sample size up front" table. Under-sample → **NOT YET**, stays OFF.
2. **Beats the guard on net-R:** on held-out replay, `Σ R(model)` > `Σ R(crude guard)`. The guard's number is
   the counterfactual "block everything ≥500" P&L; the model's is its ALLOW/BLOCK P&L. Model must win *net*,
   not just allow more winners.
3. **No fatter knife tail:** the model must **not** increase the count or magnitude of −1R knife losses beyond
   the crude guard's. (It is allowed to add small wins; it is *not* allowed to reintroduce the tail the guard
   was built to stop.) Report the loss distribution, not just the mean.
4. **Calibrated:** reliability diagram within ±0.1 across deciles; τ ≥ 1/3 (RR=2 breakeven) with margin.
5. **Ablation:** each retained feature improves held-out log-loss; any feature that doesn't is dropped.

### 7.2 Shadow phase (before flip)

Run the model flag-OFF in production, logging `P(bounce)`, the decision it *would* make, and the crude guard's
actual decision, side by side, for **2–4 weeks**. Weekly, compare would-have outcomes. Flip only after: (a) §7.1
passes on the accumulated shadow data, and (b) the **auditor** signs off per the project pipeline (Audit stage).
Any single-week regression in the knife tail reverts to OFF automatically (kill-switch = the flag).

---

## 8. Risk analysis & failure modes

| Failure mode | Mitigation (built into the design) |
|---|---|
| **Model is a new guess** (unfitted / under-sampled) | Reference code ships with **placeholder weights** and defaults to the **conservative veto** → behaves *no looser than the crude guard* until real weights are loaded (§9). Minimum-N gate blocks premature enabling. |
| **Reintroduces the knife losses the guard prevented** | Acceptance criterion §7.1(3): model may not enlarge the −1R tail. Veto retained as a hard subset. It only ever *removes* blocks that the evidence exonerates. |
| **Stale / missing news** (F1,F2) | Fail-safe: missing or stale news ⇒ treat adverse-news evidence as *present-and-uncertain* (conservative), never as "all clear." Freshness decay → 0 contribution, not spurious support. |
| **Missing zone data** (F5) | Fall back to global base rate `p0` (or a low prior), never to "high bounce." Thin `n_tests` shrunk by Beta smoothing. |
| **Over-fitting 100–200 events** | L2 shrinkage, bootstrap CIs, drop non-separating features, keep zone prior as fixed offset (fewer free params). |
| **Feature leakage** (a field computed using forward info) | All F1–F7 are decision-time fields already emitted before the order; label uses only forward OHLC. Audit the capture for leakage before fitting. |
| **Scope creep into other gates** | Hard design boundary: layer lives *only* in the counter-spike branch, returns BLOCK/ALLOW, cannot touch HTF-direction, counter-trend, money-management, SL, TP, or prompts. RR≥2 and fixed SL are external and unchanged. |
| **Tick-volume proxy (F7) misleads** | Lowest weight by construction; drop entirely if ablation (§7.1-5) shows it doesn't separate. |

**Why it cannot, by construction, be *looser* than the guard before it is proven:** until a validated weight
file is loaded, `decide()` returns the **veto result** (equivalent to the crude block on adverse setups) and only
switches to the probabilistic ALLOW path when `weights.fitted == True`. No fit → no new allows.

---

## 9. Ship-state of the reference code

`docs/proposals/evidence_entry_reference.py` is **standalone, imported by nothing, flag-OFF**. It contains: pure
feature-extraction functions over a `bot_status`-shaped dict, the Beta-smoothed zone prior, the log-odds scorer,
the decision function with the falling-knife veto, and a `__main__` demo on a synthetic input. Its weights are
**explicitly labelled `ILLUSTRATIVE — NOT FITTED`**; with `fitted=False` the module deliberately falls back to
the conservative veto so that, copied as-is, it can only ever *block*, never *allow more than the crude guard*.
The plug-in points for the fitted `w_i`, `b0`, `τ`, and `p0` are a single `EvidenceWeights` dataclass so the
validation output (§5, §7) drops straight in.

---

## 10. One-line restatement of the honesty requirement

Deriving weights and τ from the labelled counter-spike replay is the entire point. **A model we merely *believe*
is smarter, but have not shown beats the guard on the same replay in net-R and tail risk, does not get enabled —
it is only a more elaborate guess.** Derive, don't assume.
