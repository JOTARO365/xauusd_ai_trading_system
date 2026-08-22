# TASKS — Pipeline Rewrite (mental-model alignment)

Date: 2026-08-22 · Author: architect
Design: `docs/ARCHITECTURE_pipeline_rewrite.md` (read it first; §refs below point into it).
Status legend: `[ ]` not started · `[WIP]` · `[DONE]` · `[BLOCKED: reason]`.

**Global rules for every task below:**
- Worker reads only: the two CLAUDE.md files, `ARCHITECTURE_pipeline_rewrite.md`, and its own
  task entry. It touches only its scope whitelist. Shared interfaces F1–F12 are FROZEN.
- **Backtest-gate** (any task that affects entries): must show **(i) parity** — with the new
  veto OFF, the path's live+backtest behavior is byte-identical to today; **(ii) shadow-tag
  run** — collect ≥N would-block tags with reasons, no live effect; **(iii) drift-null /
  matched-random-null** — the veto's exp_R improvement beats ≥95% of random blocks of equal
  blocked-fraction; **(iv) OOS** on full paginated history (25y gold, not the 3.4y bull window).
  A veto that fails (iii)/(iv) ships shadow-only or not at all.
- Live-money iron rule: NOTHING flips from shadow to enforcing without the backtest-gate AND the
  owner-approval gate (ARCHITECTURE §12). Workers implement; they do not enable live.
- Every code edit also logged in `.claude/context/continue.md` (project rule).
- Structural-change rule: new flags → `.env.example` + README in the same task.

---

## Batch 0 — Instrumentation (zero-risk, enables all later validation) · PARALLEL

Gate before Batch 1: auditor confirms stamping present on all paths, no behavior change.

- [ ] **T-01** | agent: instrumentation-worker | scope: `agents/zone_stamp.py` (new),
  `connectors/mt5_connector.py` (order-record write only), `db/writer.py` (trade fields)
  - input: F6, F12, loss-diag §1 / Z3.
  - output: `zone_stamp.snapshot()` + stamped `sr_zone/sr_strength/score/grade/dist_to_zone_atr`
    + market-state context on EVERY order record (all paths).
  - accept: a live+shadow order on each path carries non-null zone+context fields; snapshot uses
    on-file sr_meta at order time (no retro-recompute — causal); fail-soft (missing sr_meta →
    fields = null, order still opens). No backtest-gate (pure measurement). continue.md logged.

- [DONE] **T-02** | agent: instrumentation-worker | scope: `data/entry_gate_journal.jsonl` (new,
  append-only), `agents/entry_gate.py` (journaling scaffold only — no vetoes yet)
  - input: F2, ARCHITECTURE §7 shadow-tag.
  - output: journal writer for `GateResult.tags`; append-only, timestamped, fail-soft.
  - accept: a stub `check()` returning `block=False` writes a well-formed journal line; schema
    documented in the file header. Depends on nothing. continue.md logged.

---

## Batch 1 — Safe correctness / loss-reduction (the PRIORITY) · PARALLEL

Exclusive file ownership; no shared writes. Gate: auditor integration check (build, parity,
no double-fire, roster asserts, SL refuses invalid) before Batch 2.

- [ ] **T-03** | agent: roster-worker | scope: `agents/roster_guard.py` (new),
  `main.py`/`trading_graph.py` (call site only), `data/algo_switches.json` (demote fvg)
  - input: F3, gap-audit §C-3 + cross-finding A.1.
  - output: `LIVE_ALLOWLIST` frozen set (currently validated combos only — e.g.
    `macro_momentum:XAUUSD`, plus whatever the owner confirms live); `assert_roster()` run at
    startup + every cycle → force-demote any LIVE combo not on allowlist + alert + journal.
    Demote `regime_momentum_fvg:XAUUSD` → SHADOW now.
  - accept: unit test — a switches file marking a non-allowlisted combo LIVE is force-demoted to
    SHADOW on the next cycle with a logged alert; allowlist is not writable via dashboard/LLM;
    `regime_momentum_fvg:XAUUSD` shows SHADOW after run. **[NEEDS OWNER APPROVAL]** on the exact
    `LIVE_ALLOWLIST` membership (it defines what may trade live). continue.md logged.

- [DONE] **T-04** | agent: mse-worker | scope: `agents/multi_symbol_executor.py` (loop filter only),
  `agents/trading_graph.py` (stale comment fix :373-374)
  - input: gap-audit §C-4 + cross-finding A.2.
  - output: exclude `("regime_momentum","XAUUSD")` from the MSE combo loop (regime_tick owns it);
    fix the false "MSE never touches gold" comment.
  - accept: with `regime_momentum:XAUUSD`=LIVE, `mse_state.json` no longer advances a `last_bar_ts`
    for that combo; a replay proves the same breakout cannot open two concurrent gold positions
    (one from regime_tick, one from MSE). Parity: non-gold MSE combos unchanged. continue.md logged.

- [ ] **T-05** | agent: risk-worker | scope: `agents/sl_enforce.py` (new),
  `connectors/mt5_connector.py` (`open_order`/`place_pending_order` guard hook + reconcile call),
  `main.py`/position-mgmt node (sweep call site), `.env.example`, `README.md`
  - input: F4, ARCHITECTURE §8, gap-audit §D (−6,248 un-stopped SELL).
  - output: (a) `valid()` refuse-to-open on invalid/missing SL; (b) `reconcile()` cycle sweep
    attaching a backstop SL to any stopless open position across all magics (incl. manual/MSE).
  - accept: unit — `open_order` with `sl_pips=None`/`0` returns success=False with SL-ENFORCE
    error and places no order; integration — a simulated stopless position gets a backstop SL on
    the next sweep, journaled; an existing SL is never moved/tightened. `SL_MIN_PIPS` in
    `.env.example`+README. **[NEEDS OWNER APPROVAL]** if `SL_MIN_PIPS` alters any live algo.
    continue.md logged.

- [WIP] **T-06** | agent: sentiment-worker | scope: `agents/decision_maker.py` (remove/neutralize
  dead NEWS_GATE), `agents/macro_quant.py` (label display-only), `dashboard/app.py` (label),
  `config.py`+`.env.example` (retire `NEWS_GATE` flag), `README.md`
  - input: ARCHITECTURE §5, gap-audit §C-5.
  - output: `sentiment_score.get_score().score` is the single consumable number;
    `news_impact` aggregate = input only; `macro_quant.gold_macro_score` = display-only;
    `NEWS_GATE` removed (its opposition-block, if wanted, is deferred to T-17 shadow-only).
  - accept: grep shows no live consumer of `macro_quant.gold_macro_score` except dashboard;
    `NEWS_GATE=true` no longer sets any live behavior; sentiment number unchanged on live paths
    (parity). continue.md logged.

---

## Batch 2 — The unified entry-gate (correctness core) · SEQUENTIAL then PARALLEL

This spans 3+ paths → decomposed per Sub-Agent Delegation. **2a defines the module; 2b wires it
into each path in parallel (one file per agent).** All ship in **shadow-tag mode**
(`ENTRY_GATE_SHADOW=true`) — no live veto behavior until Batch 3.

### 2a (sequential — must complete before 2b)
- [ ] **T-07** | agent: gate-core-worker | scope: `agents/market_state.py` (new),
  `agents/entry_gate.py` (vetoes 0–6 composed from existing modules), `config.py`+`.env.example`,
  `README.md`
  - input: F1, F2, F7–F11, ARCHITECTURE §4 + §7.
  - output: `MarketState.build()` (causal, fail-soft) + `entry_gate.check()` composing SL-valid,
    event-blackout(stub flag), event-POST, dir-mode, sentiment, trend_align(stub call),
    causal-zone — each flag-gated, shadow-tag by default, journaled (T-02 writer), 0 token.
  - accept: unit — with all veto flags OFF, `check()` returns `block=False` for every input
    (pure pass-through = parity guarantee); with a flag ON in shadow mode, the corresponding tag
    is recorded but `block` stays False; `build()` never reads a forming bar (closed-bar test).
    New flags in `.env.example`+README. continue.md logged.

### 2b (parallel — after T-07; one path per agent, exclusive files)
Gate: auditor parity check per path (behavior identical to pre-wire with gate in shadow mode).

- [ ] **T-08** | agent: regime-tick-worker | scope: `agents/regime_tick.py`
  - input: F2, T-07 output.
  - output: replace the inline sentiment+SR checks with a single `entry_gate.check()` call;
    this ADDS the event-blackout regime_tick lacks today.
  - accept: parity — with new vetoes OFF, entries/skips match today's regime_tick exactly on a
    replay; closed-bar passed to the gate (no intra-bar leak); event-blackout tag appears in
    shadow journal during a historical NFP window. Backtest-gate applies when its vetoes flip
    (Batch 3). continue.md logged.

- [ ] **T-09** | agent: tsmom-worker | scope: `agents/tsmom_manager.py`
  - input: F2, T-07 output.
  - output: route entry through `entry_gate.check()`; ADDS event-blackout + causal-zone tsmom
    lacks today; preserve existing sentiment-block behavior via the gate.
  - accept: parity on D1-close replay with vetoes OFF; sentiment-block still fires identically;
    event/zone tags appear in shadow journal. continue.md logged.

- [ ] **T-10** | agent: mse-gate-worker | scope: `agents/multi_symbol_executor.py`
  (`_maybe_enter` only — must not collide with T-04's loop edit; sequence T-10 after T-04)
  - input: F2, T-07 output.
  - output: replace the ad-hoc event+SR+dir+confirm block with `entry_gate.check()`; ADDS the
    sentiment veto MSE lacks today (closes gap-audit A.3).
  - accept: parity on MSE replay with new vetoes OFF (existing event/SR/dir/confirm behavior
    preserved); sentiment tag now present for gold MSE combos. **Ordering: depends on T-04.**
    continue.md logged.

- [ ] **T-11** | agent: pending-worker | scope: `agents/regime_executor.py`,
  `agents/regime_pending.py`
  - input: F2, T-07 output.
  - output: route both paths' entries through `entry_gate.check()` for uniform coverage.
  - accept: parity with vetoes OFF; RANGE-fade pending placement unchanged in shadow mode
    (note: regime_pending's own header warns it never passed validation — do NOT enable any new
    veto to "fix" it here; that is a separate owner decision). continue.md logged.

---

## Batch 3 — Risk-shaping vetoes (flip on one at a time, each behind its backtest-gate)

Each task: implement the veto in `entry_gate` (module already exists), run the full
backtest-gate, deliver the evidence, leave the flag in shadow. **Flipping to enforcing is a
separate owner-approval step (ARCHITECTURE §12), not part of the task.** These are largely
parallel (different veto modules) but each must be validated independently — no credit-sharing
across correlated drift factors (loss-diag N3).

- [ ] **T-12** | agent: event-blackout-worker | scope: `agents/event_engine.py` (calendar
  blackout window helper), `agents/entry_gate.py` (veto 1 wiring only), `config.py`+`.env.example`
  - input: ARCHITECTURE §7 veto 1, loss-diag N1, `docs/reviews/event-edge-test.md`.
  - output: calendar blackout `[−15,+30]` (FOMC `[−60,+60]`) on ALL paths via the gate;
    manages open positions unchanged (no panic-close).
  - accept (backtest-gate): tag every historical trade in/out of event windows; per-trade R
    in-window vs out-of-window worse at p<0.05; random-blackout null (1,000 draws) beaten;
    reconcile with event-edge-test.md. Ships shadow. `[risk-shaping]` `[NEEDS OWNER APPROVAL to enable]`.
    continue.md logged.

- [ ] **T-13** | agent: trend-align-worker | scope: `agents/trend_align.py` (new),
  `agents/entry_gate.py` (veto 5 wiring only), `config.py`+`.env.example`, `README.md`
  - input: F5, ARCHITECTURE §7 veto 5, loss-diag §4 #1.
  - output: deterministic symmetric drift-alignment veto + auto-disable-on-drift-flip kill
    condition + alert.
  - accept (backtest-gate): replay over (i) 25y H1 gold per-algo stream, (ii) the real 20-trade
    SYSTEM stream, (iii) matched-random entries; **drift-null decomposition** required — report
    how much of the improvement is short-deletion vs signal; must beat random-block p<0.05;
    report 2013–2018 chop window separately; ship ONLY with the kill condition. Beta label in
    registry/README. `[risk-shaping]` `[NEEDS OWNER APPROVAL to enable]`. continue.md logged.

- [ ] **T-14** | agent: event-size-worker | scope: `agents/event_engine.py` (magnitude→scaler),
  `agents/entry_gate.py` (size-scaler hook in GateResult.lot_mult)
  - input: ARCHITECTURE §4 size note, gap-audit §C-6, `data/event_engine_journal.jsonl`.
  - output: when `magnitude_pct × n` says the release historically moves > SL distance, reduce
    lot / widen stop (direction-neutral). Validate on the journal first.
  - accept: journal-based replay shows the scaler reduces variance/drawdown on event days
    without flipping any −EV stream positive (honest expectation); direction-neutral (never sets
    a side). `[risk-shaping]`. continue.md logged.

- [ ] **T-15** | agent: dir-guard-worker | scope: `agents/loss_adaptive.py` (widening guard only)
  - input: gap-audit §C-11.
  - output: `loss_adaptive`'s silent dir-mode widening (`:126`) → require journal notification +
    (config) dashboard confirmation before overwriting an owner-set restriction.
  - accept: unit — a ≥3-loss streak no longer silently flips an algo's mode to "both"; it
    journals/flags and waits for confirmation when the guard flag is on. `[correctness]`.
    continue.md logged.

- [ ] **T-16** | agent: docs-worker | scope: `agents/chart_watcher.py` (comment text only :900,
  :1023), `README.md`
  - input: gap-audit §C-10.
  - output: soften "sr_meta = display" comments (regime_pending/tsmom_manager consume it for live
    pending placement); document the veto stack + every kill switch in README.
  - accept: comments accurate; README documents entry_gate, each veto, each flag default + kill
    switch, and the SL-enforce sweep. No logic change. `[correctness/docs]`. continue.md logged.

---

## Batch 4 — Shadow-only-alpha (LOG, NEVER live without the standing gate) · LAST

These implicitly assert directional edge on a no-edge asset. They ship **shadow-only** (compute
+ journal, zero live authorization). Going live requires t>2, OOS>0, n≥100, cost-adjusted,
drift-null, drop-best-k, AND a quant-auditor refute pass AND owner sign-off (ARCHITECTURE §12).
Prior, from ~15 repo backtests: **they will not pass.** Build them to *collect evidence*, framed
honestly.

- [ ] **T-17** | agent: shadow-alpha-worker | scope: `agents/entry_gate.py` (shadow veto only),
  `data/entry_gate_journal.jsonl`
  - input: gap-audit §C-7, loss-diag §3.1 Z1/N2.
  - output: (a) LIMIT-at-zone execution of an *existing validated signal* (execution-price
    improvement) in shadow — log would-fill-at-zone vs actual market fill; (b) optional
    opposition-only news-impact block (N2) in shadow-tag (no admissible history → forward-collect
    only). NO standalone zone-reaction entry (falsified 3×).
  - accept: shadow journal accumulates ≥100 tagged decisions; a replay report quantifies LIMIT
    fill improvement vs missed-runner cost. **Stays shadow.** `[shadow-only-alpha]`. continue.md logged.

- [ ] **T-18** | agent: shadow-alpha-worker | scope: `agents/market_state.py` (dxy computed-move
  field, shadow), `data/entry_gate_journal.jsonl`
  - input: gap-audit §C-8, loss-diag §3.2.
  - output: compute a DXY→gold implied move (beta/lead-lag) as a *logged* field only; the live
    `dxy.sign` binary alignment is unchanged.
  - accept: field computed causally (closed DXY bars only) and journaled; a validation report
    confirms (as expected) no tradable lead-lag. **Stays shadow.** `[shadow-only-alpha]`. continue.md logged.

- [ ] **T-19** | agent: router-worker | scope: `agents/algo_router_llm.py` (demote-only shadow
  path only), `config.py`+`.env.example`
  - input: gap-audit §C-9, memory roster-drift-llm-promote-fix.
  - output: keep `ALGO_ROUTER_LIVE=false`; document/prepare a **demote-only** shadow evaluation
    (promote stays hard-blocked by `ALGO_ROUTER_ALLOW_PROMOTE=false` AND by roster_guard's
    allowlist). LLM never authorizes live money.
  - accept: with any config, the router cannot promote a combo to LIVE (double-blocked: flag +
    roster_guard); demote-only actions are journal-only in shadow. `[shadow-only-alpha]`
    (promote) — promote path NEVER enabled. continue.md logged.

- [ ] **T-20** | agent: (owner-decision, not auto) | scope: `data/algo_switches.json`
  - input: loss-diag §4 #2, ARCHITECTURE §12.1.
  - output: proposal to demote the proven −EV / drift-only live combos (`regime_momentum`
    live-tick full-history −0.133; `tsmom_d1` t=0.94 believe:false) — subordinate to the veto
    stack and re-earn LIVE via the promotion bar.
  - accept: **[NEEDS OWNER APPROVAL]** — this changes live money exposure; not executed by a
    worker without explicit owner instruction. Evidence already exists in
    `backtest_results.json` + `shadow_backtest.json`. continue.md logged.

---

## Dependency / batch summary

```
Batch 0 (parallel):  T-01  T-02                         → gate: stamping present, no behavior change
Batch 1 (parallel):  T-03  T-04  T-05  T-06             → gate: build, parity, roster asserts, SL refuses
Batch 2a (seq):      T-07                                → gate: pass-through parity, closed-bar
Batch 2b (parallel): T-08  T-09  T-10(after T-04)  T-11 → gate: per-path parity (shadow mode)
Batch 3 (parallel*): T-12  T-13  T-14  T-15  T-16       → gate: each veto's backtest-gate (independent)
Batch 4 (last):      T-17  T-18  T-19  T-20(owner)      → shadow-only; never live w/o standing gate
```
`*` independent files, but each veto validated separately — no credit-sharing across the
correlated drift factors (sentiment ≈ trend-align ≈ COT-brake; loss-diag N3).

**Frozen interfaces this decomposition assumes:** F1–F12 (ARCHITECTURE §11). Any worker needing
to change one → mark `[BLOCKED]` and return to the architect.
