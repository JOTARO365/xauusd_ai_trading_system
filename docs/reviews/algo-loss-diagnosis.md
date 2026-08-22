# Algo Loss Diagnosis — zones / OI / news as LOSS FILTERS (not alpha)

**Date:** 2026-08-22 · **Author:** quant-analyst subagent (read-only pass; no code/config touched)
**Sources:** `data/backtest_results.json` (2026-08-12 matrix, causal · SL-first · cost-adj · OOS 70/30),
`docs/reports/shadow_backtest.json` (full-history 16–25y replays), `logs/trades.json` (510 closed real trades),
`agents/algo_registry.py`, `agents/sr_entry_gate.py`, `agents/decision_maker.py`, `data/cot.json`,
`data/news_impact.json`, `data/sentiment_score.json`, live `.env` flags, `data/algo_router_journal.jsonl`.

**Standing facts this report is built on (do not relitigate):**

1. Gold has **no directional/timing edge** — proven across D1/H1/M1/tick, all TP/SL shapes, fade & momentum
   & breakout. Every apparent edge decomposed into (a) up-drift beta (+12% window) or (b) look-ahead.
2. The correct null is **drift-null / matched-random-null**, never zero-null. `exp_R > 0` on a drifting
   asset is not evidence.
3. Causality: any HTF signal (zone, COT, OI, news) mapped to an LTF entry must be fully closed/published
   before entry time. A zone-scalp showed t=8.33 from one not-yet-closed H1 bar; fixed → −4.2.
4. Confirmed real loss cause: bot SHORTED gold 17/20 SYSTEM trades into the up-drift.
5. Nothing goes live without causal backtest + drift-null + drop-best-k + OOS + quant-auditor refute.

Everything proposed below is a **FILTER** (removes a losing sub-population from an existing entry stream).
Nothing here is claimed alpha. Where a proposal risks quietly *becoming* directional alpha (sentiment,
COT tilt), that risk is flagged explicitly.

---

## 0. Live wiring snapshot (what can actually lose money today)

| Path | Flag (now) | Algo | Goes through DecisionMaker gates? | S/R gate? | Sentiment gate? |
|---|---|---|---|---|---|
| `regime_tick.py` | `REGIME_LIVE=true`, `REGIME_LIVE_TICK=true` | regime_momentum (gold H1) | **NO — bypasses** | only if combo allowlisted (it is NOT: allowlist = `macro_momentum\|XAUUSD` only) | **NO** |
| `tsmom_manager.py` | `TSMOM_LIVE=true` | tsmom_d1 (gold) | **NO — bypasses** | not allowlisted | yes (inside evaluate, gold) |
| MSE (`multi_symbol_executor`) | `MSE_MAX_POSITIONS=1` | regime_momentum:WTIUSD (per memory) | **NO** | not allowlisted | n/a |
| pending / ZRE / swing | ZRE on, trend-align-only | re-entry paths | **NO — bypass** | no | no |
| LLM pipeline (Analyst → DecisionMaker) | running | discretionary/cockpit | yes (HTF block, anti-fade, NEWS_GATE floor) | n/a | yes |
| algo_router (LLM promote) | `ALGO_ROUTER_LIVE=false`, demote-only guard | — | n/a | n/a | n/a |

**Structural finding #1:** every gate the system has built (HTF direction block, anti-fade, NEWS_GATE
conf-floor, S/R rich-zone gate) lives on paths that the actual live order flow **bypasses**. The 20
SYSTEM trades in `logs/trades.json` were produced by regime_tick / tsmom_manager, which see none of the
news gate and (except the single allowlisted combo) none of the S/R gate. Filters cannot cut losses on
paths they are not wired into. This is the cheapest fix in the whole report.

---

## 1. Real-money loss anatomy (`logs/trades.json`, 510 closed trades, lot-normalized to 0.01)

Re-derived 2026-08-22 with `Python311` (numbers below are ฿ per 0.01 lot):

**SYSTEM (n=20):** sum **−3,191**, mean −159.5, WR 15%.
- SELL: n=17, sum −2,257, WR 18% → the confirmed counter-drift shorts (guardrail #4).
- BUY: n=3 (all 2026-08-20, a pullback day), sum −933, WR 0% → **trend-alignment alone did not save
  these** — being long-only is beta, not protection; timing/stop placement still loses on red days.
- Recurring 01:02 timestamps (07-30, 07-31, 08-04, 08-05, 08-20) = the daily D1-close path
  (tsmom_manager); the rest intraday = regime_tick. Note lot escalation to 0.02 on 08-06/08-07 doubled
  the worst losses (−596.7, −602.9 raw).

**MANUAL (n=478):** sum +7,544. BUY +14,471 (WR 52%) vs SELL **−6,927** (WR 41%). Same asymmetry as
SYSTEM: the entire book's loss concentrates in shorting an up-drifting asset.

**Month split:** 2026-07 = +15,764 (both sides won — strong clean trend). 2026-08 = **−11,411**, and
within August, SELL alone = **−15,591** (n=211, WR 35%). August BUY was still +4,181. The losing slice
is precise: *August shorts*.

**Pipeline-vs-manual confound (be honest):** trades tagged `sr_zone="NONE"`/`conf=0` (n=163 — the
bot-pipeline population) split into BUY +13.6/trade vs SELL **−92.2/trade (WR 27%)**. Tempting to read
as "no-zone entries lose" — but `sr_zone` only takes values `None` (MT5-detected manual) and `"NONE"`
(pipeline), so this segmentation is *pipeline vs manual*, not *zone vs no-zone*. No real trade in the log
carries an actual zone label. **Conclusion: the current trade log cannot validate zone filters; zone
context must start being stamped on every order before any zone filter can be judged on live data.**

**Concentration:** worst 10 trades = −7,775 (14% of gross losses); best 10 = +19,334 (33% of gross
wins). P&L is tail-driven in both directions — any filter that clips entries must be checked against the
*winning* tail it also removes (`exp_R_on ≥ exp_R_off` criterion, as the sr_gate harness already does).

---

## 2. Per-algo diagnosis

Notation: `bt` = `backtest_results.json` (recent-window, cost-adj), `sh` = `shadow_backtest.json`
(full-history). All gold combos are SHADOW in `bt`; live exposure is via the paths in §0.

### 2.1 regime_momentum (H1 Donchian breakout, TREND-gated) — **LIVE on gold via regime_tick**

- **What:** Donchian momentum-breakout only when regime = TREND (`regime_shadow` → `regime_lib`).
  Direction-agnostic: sells breakdowns as readily as it buys breakouts.
- **Loss cause: no edge + window bias + counter-drift shorts.**
  - bt XAUUSD: exp_R +0.0255, **t = 0.40**, n=518 — statistically zero. Under a drift-null, a strategy
    that is long ~half the time in a +12% window *should* show ≈ this; the +0.03 is drift residue.
  - sh XAUUSD (25.1y, n=926): exp_R **−0.133**, sum −123.4R, WR 35.7% — over full history it is
    plainly −EV. The recent-window "+EV" grouping is exactly the backtest-window bias documented in
    memory (2026-07-25).
  - Other pairs: −EV nearly everywhere (silver −0.369 t=−6.2; USDCHF −0.18 t=−3.1; sh WTI is the lone
    big positive, +1.02 — which is why MSE trades only WTI).
  - Live: regime_tick is the source of most of the 17 counter-drift SELLs. TREND-regime detection says
    "market is moving", not "which way the drift is" — in an up-drift, every pullback that trips a
    breakdown gets shorted. This is the single largest documented live loss mechanism.
- **Cost:** 28 pips/trade embedded; at WR 35.7 / RR 2 the gross margin is a rounding error — cost eats it.

### 2.2 regime_momentum_fvg (breakout + FVG confluence) — SHADOW only

- **What:** same as 2.1 plus a 3-bar Fair-Value-Gap must support the direction within 6 bars.
- **Loss cause: filter adds nothing — no edge to filter.** bt XAUUSD +0.0457 t=0.69, **OOS +0.0014**
  (i.e., OOS ≈ exactly zero); on 7 of 11 pairs the FVG version is *worse* than plain momentum (e.g.,
  AUDUSD −0.163 vs −0.110). The registry docstring already concedes: in-sample improvement did not
  survive OOS. An SMC confluence layer on a signal with no edge just resamples noise.

### 2.3 mean_reversion (RANGE z-score fade) — SHADOW (cut from live earlier, P2 −EV OOS)

- **What:** fade z-score extremes when regime = RANGE.
- **Loss cause: structurally −EV everywhere + over-trading + cost.** bt: −EV on **all 11 pairs**
  (XAUUSD −0.087 t=−4.08 n=1392; silver −0.433 **t=−19.9**; sh silver sum −692R). Highest trade counts
  in the book (1,300–3,100 per pair) at the highest relative costs (silver 53 pips, XAUEUR 60 pips) —
  it grinds cost with no gross edge. On gold specifically, "fade the top of the range" = short into
  drift, a small persistent negative bias on top. 45% of sh outcomes are TIMEOUT — trades that just sat
  in noise paying spread.

### 2.4 sweep_reversal (prior-day H/L sweep fade, NEUTRAL/RANGE only) — SHADOW

- **What:** fade a sweep of prior-day high/low that closes back inside.
- **Loss cause: fading continuation, −EV.** −EV on 10/11 pairs (XAUUSD −0.0498 OOS −0.0691; silver
  −0.456 t=−13.3). Registry note is accurate: high-WR/low-RR trap, fade eats the cascade when the sweep
  is real. BTC +0.030 t=0.89 is noise-level. Nothing here to rescue with filters; the entry premise
  (reversal at liquidity levels) is the same family already killed twice (`sr_fade` cut 08-07,
  `zone_reaction` mining dead 08-17).

### 2.5 tsmom_d1 (D1 ensemble 21/63/126 + confirm-21, exit-on-flip) — **LIVE on gold via tsmom_manager**

- **What:** time-series momentum vote, no TP, disaster SL 3×ATR. Gold runs through `tsmom_manager`
  (TSMOM_LIVE=true); other pairs via MSE shadow.
- **Loss cause: drift-harvesting misread as edge + whipsaw on the confirm leg.**
  - bt XAUUSD +0.154 **t=0.94** OOS +0.64 — sub-significant, and TSMOM-long on an asset that rose 12%
    *is* the drift; a matched-null (random entries, same long/short mix, same exit-on-flip horizon)
    would very likely absorb the whole 0.154. sh XAUUSD: t=1.36, `believe: false` (correctly).
  - Live behavior: the 01:02 SYSTEM entries include SELLs on 07-30→08-05 (short-lookback leg flipped
    bearish in the pullback) — i.e., during chop the 21-day confirm whipsaws the ensemble into exactly
    the counter-drift shorts the strategy exists to avoid, then exit-on-flip realizes each whip as a
    full loss. The 08-20 BUY (−784) is the same whipsaw on the other side.
  - Cross-pairs: silver REJECT (memory: t=−2.89 on the frozen port), USDCHF −0.126 t=−2.3; BTC is the
    only combo with t>2 in bt (0.846, t=2.06, n=80) and even that halves OOS (0.33) with IS 5.9 → OOS
    0.49 in sh = regime-dependence, not edge.

### 2.6 macro_momentum (H4 Donchian + EURUSD/DXY-proxy confirm + sentiment gate) — SHADOW; best-validated gold combo

- **What:** breakout only when the pair's structural USD driver moved the same way over 24 H4 bars;
  gold adds the LLM sentiment block.
- **Status vs loss:** bt XAUUSD +0.114, **t=1.91**, OOS +0.19, n=595 — the only gold combo close to
  significance, and the only combo that passed the S/R-gate validation harness
  (`data/sr_gate_combos.json`: gate lifts t 1.91→2.00). Honest read: t=1.91 across an 11-pair × 9-algo
  search grid (~90 tests) is **below any multiple-testing bar** (drop-best-k would need t≳3), and the
  DXY-confirm largely proxies "don't short when USD is falling" = a drift-alignment filter, not alpha.
  −EV on 7 other pairs (silver −0.151 t=−2.25) says the mechanism is not general.
- **Loss cause (where it loses):** breakouts against no macro support are already filtered; residual
  losses are breakout-failures inside chop — the classic 62%-loser stream at WR 38 that only survives
  if the RR-2 winners keep landing, i.e., only while trends persist.

### 2.7 confluence_15m (M15 breakout + H1+H4+macro+volume-surge + session filter) — SHADOW

- **What:** most-filtered scalp: 5 conditions incl. tick-volume surge, gold session window 13–21 UTC.
- **Loss cause: overfit-by-construction; cost-fragile.** bt XAUUSD +0.129 t=1.34 n=235 — but the
  session filter is *documented in memory as overfit* (07-25: "session gate overfit อย่าเปิด"), the
  volume-surge band (1.5–2.0×median, excluding >2× "news spikes") is a two-sided tuned window, and 5
  stacked conditions on M15 is a textbook selection surface. −EV on 8 of 10 other pairs (AUDUSD −0.297
  t=−3.1, USDJPY −0.396 t=−2.8). M15 gold at 28-pip cost needs a large gross edge just to reach zero;
  nothing suggests it has one. Expected to fail drift-null + drop-best-k.

### 2.8 cdc_zone (CDC Action Zone D1, long-only, exit-on-flip) — SHADOW (router correctly refused promote)

- **What:** EMA12/26 zone trend-following, long-only by config, hold-until-flip.
- **Loss cause: none visible in-window — because it IS the drift.** bt XAUUSD exp_R 0.983 t=2.05 n=47;
  OOS +2.48. A long-only, always-in trend follower on an asset that rose 12% in the sample is a
  leveraged bet *on the sample's drift*; the OOS segment being even better than IS just says the drift
  accelerated late in the window. n=47 fails every min-N bar. The router journal (08-22) flagged it
  "สูงผิดปกติ (อาจ overfitted)" — correct instinct. Its true risk profile is the one CDC always has:
  −38% WR with occasional deep flip-losses; in a drift reversal this algo converts the whole prior
  "edge" into drawdown. **Validation that matters here is purely the drift-null:** random long entries
  with the same time-in-market and same exit-on-flip mechanics on the same window — CDC must beat
  *that*, not zero. It almost certainly will not.

### 2.9 pullback_buy (H1 dip-buy in D1 uptrend, long-only) — SHADOW

- **What:** buy EMA20 reclaim when D1 > EMA, structural swing-low SL, RR 3.
- **Loss cause: same as cdc_zone — conditional beta.** OOS t=3.88 looks strong but IS is weak and the
  registry admits the edge is "กระจุก gold-bull" (concentrated in the gold bull leg). "Buy dips while
  it drifts up" is definitionally profitable *while it drifts up*. It is the codified version of what
  the MANUAL book did right (+14.5k on BUYs) — legitimate as drift-harvesting with controlled risk,
  but it must carry a **regime kill-switch** (see §4), because its entire P&L is one macro state.
  Note: this algo is correctly **excluded** from the S/R gate (gate blocked profitable dip entries).

### 2.10 Dead/cut (for completeness)

- **sr_fade** — cut 08-07: −EV every pair/variant (t −4…−22). Confirms naive zone-fade has no edge.
- **xau_xag_pairs** — stat-arb: exp_R −6.62 t=−4.91, cointegration failed split-half. Rejected.
- Both matter for §3: they are prior evidence that *zones/spread-reversion as ALPHA is dead*. Only the
  block-filter use of zones has any surviving evidence.

### Summary table

| Algo | Live exposure | Recent bt (XAU) | Full-history / OOS reality | Primary loss cause |
|---|---|---|---|---|
| regime_momentum | **YES (tick)** | +0.026 t=0.4 | 25y: −0.133 (−123R) | counter-drift shorts; no edge; window bias |
| regime_momentum_fvg | no | +0.046 t=0.69 | OOS ≈ 0 | confluence on no-edge = noise |
| mean_reversion | no | −0.087 t=−4.1 | −EV all 11 pairs | structural −EV fade + cost + over-trading |
| sweep_reversal | no | −0.050 | −EV 10/11 pairs | fading real cascades |
| tsmom_d1 | **YES (gold mgr)** | +0.154 t=0.94 | believe:false; whipsaw SELLs live | drift beta + confirm-leg whipsaw |
| macro_momentum | no (router wanted) | +0.114 t=1.91 | best combo; still < multiple-testing bar | breakout-failure chop; USD-confirm = drift proxy |
| confluence_15m | no | +0.129 t=1.34 | session param known-overfit | overfit stack; M15 cost |
| cdc_zone | no | +0.98 t=2.05 n=47 | pure drift beta, n tiny | IS the drift |
| pullback_buy | no | OOS t=3.9, IS weak | edge = gold-bull only | conditional beta, needs kill-switch |

---

## 3. Filter designs: demand/supply zones · OI/COT · news

Design rules applied to every proposal: **(a)** exact rule, **(b)** filter vs claimed-alpha, **(c)**
causal/look-ahead check, **(d)** matched-null validation, **(e)** losing slice it targets. Shared
validation harness: the existing `scripts/sr_gate_backtest` criteria
(`exp_R_on ≥ exp_R_off · n_on ≥ 0.15·n_off · t ≥ 2 · n ≥ 80`) generalized to any block-signal, **plus**
a random-block null: block the same *fraction* of entries uniformly at random (1,000 draws) and require
the real filter's exp_R improvement to beat ≥95% of random blocks. This is the filter-world analogue of
matched-random-null and is mandatory — without it, any filter that shrinks n on a noisy stream can look
good by luck.

### 3.1 Demand/supply zones (rich sr_meta: strength/touches/bounce_pct/n_tests/score/grade)

**Z1 — Extend the rich-zone entry gate per-combo (the already-validated mechanism).**
- (a) For each (algo, pair): block BUY within `0.5×ATR` under a rich resistance
  (touches ≥ 2, causal bounce_pct ≥ 55, n_tests ≥ 3); block SELL within `0.5×ATR` above a rich support.
  Exactly `sr_entry_gate.blocks_at(..., rich=(55,3))` — no new math; new *allowlist entries only*.
- (b) Pure filter (block-only, momentum-aware — never generates or flips a signal).
- (c) Causal by construction: pivots confirmed ≥`pivot` bars before i; bounce stats only from windows
  fully resolved before i (`kmax = i − fwd − 1`). The one live risk: `blocks_live` evaluates at
  `i = len(c) − 1`; **verify the fetched last bar is closed** (regime_tick runs intra-bar — if the
  array's last element is the forming bar, its high/low leak intra-bar information into ATR/pivot
  windows; this is the exact class of bug in guardrail #3). Audit that before extending the allowlist.
- (d) Per-combo run of the sr_gate harness + the random-block null above, on full paginated history
  (25y gold, not the 3.4y bull window). Drop-best-k across the combo grid.
- (e) Slice removed: breakout/fade entries fired directly into a statistically-bouncing wall — the
  "no room to run" losers. Evidence it can work: macro_momentum|XAUUSD t 1.91→2.00 passed. Evidence to
  stay humble: it was **1 of ~90 combos** that passed; expect most extensions to fail, and pullback_buy
  proves the gate can *destroy* a working entry. Extend only where the harness passes; never blanket-on
  (`SR_GATE_ALL=true` without per-combo evidence would be a config-level violation of the harness).

**Z2 — SELL-specific demand-zone ledge check for the bypass paths (regime_tick / tsmom_manager).**
- (a) Before any live SELL on gold from a bypass path: call `blocks_live_gold(algo_id, "SELL", px, atr)`
  with the rich-zone params — i.e., wire the *existing* gold wrapper into the two paths that currently
  skip it, gated per-combo like Z1.
- (b) Filter.
- (c) Same as Z1, plus: `blocks_live_gold` fetches its own bars — confirm it slices to the last *closed*
  bar for the tf it fetches.
- (d) Replay regime_tick's historical entry stream (its journal + parity backtest already exist for
  `sr_entry_gate`) with/without the block; random-block null; then the drift-null variant: apply the
  same filter to matched random SELLs — if the filter "improves" random shorts as much as real ones,
  it's just deleting shorts (i.e., rediscovering drift), and it should be labeled a de-facto
  short-throttle, not a zone effect. **This decomposition is the honest test: zone-effect vs
  short-deletion-effect.**
- (e) Slice: the 17/20 counter-drift live shorts — many were sells into well-tested demand during an
  uptrend. Expected outcome stated in advance: a good chunk of the improvement will turn out to be
  short-deletion, not zone information. That is acceptable *if declared* — but then §4.1 (trend-align)
  achieves it more directly and cheaply.

**Z3 — Zone-stamping on every order (instrumentation, not a filter).**
- (a) At order time, stamp `sr_zone`/`sr_strength`/`score/grade` + distance-to-nearest-zone-in-ATR from
  `chart_watcher`'s sr_meta onto the trade record for **all** paths (today real trades carry only
  `None`/`"NONE"` — §1).
- (b) Neither — measurement. (c) sr_meta is built from closed bars; stamp whatever was on file at order
  time, never recompute retroactively. (d) None needed to ship; it *enables* all future zone-filter
  validation on live data. (e) Removes no losses directly; removes the current impossibility of
  attributing losses to zone context.

**What will FAIL in the zone family (say it now):** any *entry-generating* use of zones (bounce-trade,
zone re-entry as signal, "grade-A zone → take the trade") — already falsified three separate times
(sr_fade, zone_reaction mining, zone-scalp t=8.33→−4.2 look-ahead collapse). Zones in this system have
exactly one evidenced role: **vetoing entries into walls.**

### 3.2 Open Interest / COT positioning

Available now: `data/cot.json` = weekly legacy COT (non-comm long/short/net + weekly change; currently
net +222K, near-crowded-long). To pull (flagged, not needed for design): AlphaVantage
`HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` (real daily futures OI) — note free-tier 25 req/day.

**O1 — COT crowding brake (position-size/frequency throttle, not a direction signal).**
- (a) When non-comm net-long is above its own 90th percentile (rolling 3y) **and** weekly change is
  negative (longs liquidating), halve max concurrent positions / block *adds* in the drift direction
  for all long-side algos (cdc_zone, pullback_buy, tsmom-long). Mirror-image for extreme net-short.
- (b) Filter (throttle). The moment it picks direction ("crowded long → short it") it becomes
  claimed-alpha — and with 52 independent observations/year it can never reach n≥100 significance on
  gold within a usable horizon. **Do not build the directional version.**
- (c) Causality is the classic COT trap: report_date is Tuesday, publication is Friday ~20:30 UTC. Any
  backtest must lag ≥3 trading days from report_date (use publication timestamp, never `report_date`).
  `data/cot.json` stores only report_date — the join key for backtests must be
  `report_date + 3 business days` at minimum.
- (d) Matched-null: replay the throttle over the long-side algos' historical entry streams vs 1,000
  random throttles of equal total blocked-exposure. Also test on the pre-2024 window where gold chopped
  — a crowding brake that only helps in the bull window is itself drift-fit.
- (e) Slice: drawdown clusters where crowded longs unwind (the −784 type of day, 08-20). Honest prior:
  **underpowered — likely unprovable at p<0.05 with weekly data.** Recommend building it as a *risk
  overlay* (size, not entry) where the burden of proof is drawdown reduction, not exp_R, and
  acknowledging it may never clear the significance bar.

**O2 — OI-confirmation veto on breakouts (needs the AlphaVantage pull).**
- (a) For H4/D1 breakout algos (macro_momentum, tsmom_d1, cdc entries): if the breakout day's futures
  OI *declined* vs prior day (short-covering rally / long-liquidation break rather than new
  participation), veto the entry. Classic futures-market reading: price↑+OI↑ = new money (let it
  through); price↑+OI↓ = covering (veto).
- (b) Filter. (c) CME OI is **preliminary next morning, final T+1** — a D1 entry at 01:02 broker time
  can only use OI from **two days prior**. Any backtest joining same-day OI to same-day entry is
  look-ahead; flag this in the script header. AlphaVantage timestamps must be checked for
  publication-lag semantics before trusting them.
- (d) Same harness: exp_R_on ≥ exp_R_off + random-veto null + drop-best-k (the up/down×price/OI grid is
  4 cells = a small search space, good). n is adequate here (daily data, ~600 breakout entries on gold).
- (e) Slice: failed breakouts without participation. Prior: plausible-but-unproven; this is the one
  OI idea with enough n to actually be testable. Rank it behind the news/zone items only because it
  needs a new data feed.

**What will FAIL in the OI family:** COT-extreme *fade* (claimed-alpha, n≈52/yr, drift-confounded);
any same-day OI join (look-ahead); "OI proves smart money is buying" narratives (the LLM sentiment
prompt already ingests COT — see N3 — do not double-count it).

### 3.3 News / sentiment

Available: `data/news_impact.json` (windowed scored posts → aggregate, feeds NEWS_GATE conf-floor on
the LLM path only), `data/sentiment_score.json` (LLM 0–100 gold score, gates tsmom/macro/cdc inside
evaluate()), `data/ff_calendar_raw.json` (ForexFactory calendar — **exists already**, currently unused
for entry gating).

**N1 — Calendar event blackout on ALL order paths (highest-confidence news filter).**
- (a) Block *new* entries on gold from any path within [−15 min, +30 min] of a red-folder USD/gold
  event (NFP, CPI, FOMC, PCE) from `ff_calendar_raw.json`; widen to [−60, +60] for FOMC. Manage open
  positions unchanged (no panic-close — that's a different, unvalidated feature).
- (b) Pure filter, and the *only* one here whose information is available with certainty in advance
  (event schedule is published days ahead → zero look-ahead risk by construction).
- (c) Causal: trivially — the calendar timestamp precedes the event. One check: use scheduled time, not
  the revised/actual-release row that gets rewritten after the fact.
- (d) Matched-null: tag every historical trade (real + shadow streams) in/out of event windows; compare
  per-trade R in-window vs out-of-window with the same side/exit distribution; then random-blackout
  null (block equal total minutes at random times-of-day, 1,000 draws). Event-window losses must be
  worse than random-window losses at p<0.05. `docs/reviews/event-edge-test.md` exists — reconcile with
  whatever it already found before re-deriving.
- (e) Slice: spread-blowout + spike-whipsaw entries around releases (M15/H1 scalps are most exposed:
  regime_tick, confluence_15m). Expected effect honest-sized: gold's events are few; this trims tails,
  it will not flip any −EV algo positive.

**N2 — Wire the existing NEWS_GATE floor to the bypass paths.**
- (a) The `news_impact` aggregate → conf-floor logic exists in `decision_maker._news_gate` but only the
  LLM path sees it. For algo paths (which have no confidence), reduce it to a binary: aggregate score
  strongly *opposing* the entry direction (|score| ≥ 40, n_scored ≥ 3, age ≤ 60 min) → block the entry.
- (b) Filter (block-only, opposition-only — never "news supports → take more trades", which is the
  alpha version and is banned here).
- (c) **Serious look-ahead hazard in validation:** there is no archived history of `news_impact.json`
  aggregates. Re-scoring old headlines with an LLM today is contaminated (the model knows what gold
  did). Therefore this filter **cannot be causally backtested yet**. The only clean path: start
  journaling the aggregate every cycle now (append-only log with timestamps), run the filter in
  SHADOW-tag mode (log would-have-blocked, block nothing), and evaluate after ≥100 tagged entries.
- (d) Forward matched-null on the accumulated journal: blocked-tag entries vs random tags of equal
  frequency. No retro-backtest is admissible.
- (e) Slice: entries opened directly against fresh one-sided news flow. Prior: modest; sentiment flow
  on gold is mostly a *lagging* narrative of price (see N3), so opposition-block ≈ another partial
  trend-align proxy. Cheap to run in shadow; let the data decide.

**N3 — Sentiment-score honesty audit (a warning, not a feature).**
The LLM sentiment score currently gating tsmom/macro/cdc reads: *"…ทองกำลังทำ weekly gain ที่ 3
ติดต่อกัน…"* — the score explicitly ingests **price momentum and COT** as inputs. It is therefore
substantially a re-statement of drift: when gold rises, sentiment reads bullish, which blocks shorts,
which looks like skill in an up-window. Consequences: (1) never validate sentiment gating on the same
window that formed the sentiment — only forward-collected scores (they exist: `sentiment_score.json` is
journaled per call — confirm retention) against later trades; (2) never stack sentiment-block + COT
crowding brake + trend-align as if independent — they are one correlated drift factor measured three
ways; count them as one filter in any combined validation, or a joint model will double-credit the same
avoided shorts. (3) If a future test shows sentiment-block ≈ trend-align-block in overlap, keep the
cheaper deterministic one (trend-align costs 0 tokens).

---

## 4. Cross-algo synthesis — top 3 changes, ranked by expected loss reduction per unit of validation risk

### #1 — One shared entry-veto stack, wired into EVERY order path (kills the bypass problem)

**Change:** a single `entry_vetoes(symbol, direction, algo_id, price, atr)` module called by
regime_tick, tsmom_manager, MSE, pending/ZRE/swing, and the LLM path alike, containing (initial set):
trend-alignment veto (no counter-drift shorts: D1 close < EMA200-type deterministic rule), calendar
blackout (N1), and the per-combo-allowlisted rich-zone gate (Z1/Z2). Config-gated per veto, block-only,
fail-open, journaled with reasons (0 tokens, computed in code).

**Why #1:** the confirmed live loss (−3,191 normalized, 17 shorts) happened on paths that bypass every
existing protection. Trend-alignment is the *one defensible lever found* — and it must be shipped with
its own honesty label: **it is beta/drift-harvesting, works only while gold drifts up, and needs an
explicit kill condition** (e.g., veto auto-disables and alerts when the D1 drift measure flips, rather
than silently starting to veto longs in a downtrend — direction-symmetric application is the correct
default, with the awareness that its measured benefit is window-specific).

**Validation plan:** replay the veto stack over (i) full 25y H1 gold history on each algo's entry
stream, (ii) the real 20-trade SYSTEM stream, (iii) matched random entries with the same side/exit
distribution. Required: exp_R_on ≥ exp_R_off, random-block null p<0.05 per veto *separately* (no
credit-sharing), drop-best-k over veto parameterizations, correlated-factor accounting per N3, then
quant-auditor refute pass. Expected result stated in advance: trend-align will pass on the recent
window and look weaker on 2013–2018 chop — report both; ship only with the kill condition.

### #2 — Demote/kill the proven −EV and drift-only combos (loss reduction by subtraction)

**Change (proposals, user decision):** (i) regime_momentum gold live-tick — the full-history number is
−0.133 over 25 years and it produced the live damage; either turn `REGIME_LIVE_TICK` off or subordinate
it to the #1 veto stack and re-earn live status through the promotion bar. (ii) tsmom_d1 gold
(TSMOM_LIVE) — t=0.94, believe:false, live whipsaw losses; same treatment. (iii) Freeze mean_reversion
and sweep_reversal shadows on the pairs where t<−4 (silver, USDCHF, USDJPY…) — they burn compute to
re-confirm a settled answer; keep one reference pair each. (iv) cdc_zone/pullback_buy: label as
"drift-harvest, conditional-beta" in the registry and require the drift-null (not zero-null) in their
promotion criteria explicitly.

**Why #2:** no filter can rescue a −EV entry stream (filters shrink n; they cannot manufacture gross
edge). The cheapest loss to cut is the trade never taken. This is also the only item with *zero*
validation risk — the evidence already exists in the two backtest files.

### #3 — Zone-stamping + veto-shadow journaling now; per-combo zone-gate extension as the data matures

**Change:** Z3 (stamp zone context on every order) + run every §3 filter in shadow-tag mode on all
paths (log would-block + reason + zone/OI/news snapshot at decision time), building the forward,
causally-clean dataset that none of the news/sentiment filters currently have. Extend the rich-zone
allowlist combo-by-combo strictly through the existing harness (Z1) as replays pass.

**Why #3:** §1 showed the live log cannot even attribute losses to zone context; N2/N3 showed the news
filters have no admissible history at all. The single highest-leverage act for *future* loss reduction
is making today's decisions auditable. This costs nothing at trade time and converts every subsequent
trade into validation data.

### Explicit expectations — what will likely FAIL validation vs what should survive

**Likely FAIL (don't be surprised, don't ship on a lucky window):**
- Any directional use of COT/OI/sentiment (alpha claims on a no-alpha asset; COT additionally
  underpowered at n≈52/yr).
- confluence_15m's session/volume stack under drop-best-k (documented overfit lineage).
- cdc_zone / tsmom-long / pullback_buy against a proper drift-null (they *are* the drift; they may
  still be run deliberately as risk-controlled beta, but must be labeled and killed on regime flip).
- Zone-gate extension to most combos (1/~90 passed so far; the harness exists precisely to say no).
- Retro-backtests of LLM-scored news (contaminated by hindsight — inadmissible, not just weak).

**Sound risk-reduction filters (the defensible short-list):**
- Trend-alignment veto on all paths — with beta label + kill condition (#1).
- Calendar event blackout — causally airtight, tail-trimming (N1).
- Rich-zone block gate where the per-combo harness passes — currently exactly macro_momentum|XAUUSD (Z1).
- OI-declining-breakout veto — testable with adequate n once the feed is pulled and lagged correctly (O2).
- Subtraction of −EV combos (#2) — not a filter, but the largest guaranteed loss reduction available.

---

*Report ends. No code, config, or live files were modified; this file is the only write.*
