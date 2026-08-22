# ARCHITECTURE — Pipeline Rewrite (mental-model alignment)

Date: 2026-08-22 · Author: architect (design only — no source touched)
Status: **DRAFT FOR OWNER APPROVAL** — nothing here is implemented until approved and
decomposed tasks are picked up by workers per `docs/TASKS_pipeline_rewrite.md`.

**Primary inputs (source of truth):**
- `docs/reviews/mental-model-gap-audit.md` (Sections A–D)
- `docs/reviews/algo-loss-diagnosis.md` (loss anatomy + filter designs)
- Owner's target pipeline (8 stages) + the hard constraints supplied with this task.

**Doc-naming note:** written to `ARCHITECTURE_pipeline_rewrite.md` /
`TASKS_pipeline_rewrite.md` (not the existing 48KB `ARCHITECTURE.md` / 52KB `TASKS.md`) to
avoid destroying prior tracked pipeline state. This matches the repo's namespaced-doc
convention (`ARCHITECTURE_batchB.md`, `DESIGN_*.md`).

---

## 0. The honest ceiling (read this first — it constrains every design choice)

The owner's 8-stage pipeline is being made *real*, but "real" is bounded by validated fact,
not by the mental model. Restated so implementation targets only the achievable:

| Stage | Can it add directional edge? | What the rewrite makes it deliver |
|---|---|---|
| 1 pull news | No | Robustness (Nitter fallback), unchanged role |
| 2 analyze news | No | Unchanged; input to stage 3 |
| 3 ONE sentiment number | **No** (it is a drift restatement — ingests COT/momentum) | **Correctness**: one number, not three; used as veto/size only |
| 4 event statistics | No (direction-of-day at best, n≈173–181) | **Risk-shaping**: PRE-event flat + POST counter-block on *all* paths; magnitude→size scaler |
| 5 inverse asset (DXY) | No (lead-lag probed empty) | **Risk-shaping**: keep binary alignment filter; computed-move = shadow-only |
| 6 demand/supply zones | No as entry source (falsified 3×) | **Risk-shaping**: block-only causal gate + exit/select/display |
| 7 select algo | No (price-regime is deterministic; LLM selection = shadow) | **Correctness**: roster matches code intent, no drift, no double-engine |
| 8 buy/sell/both config | n/a | **Correctness**: already works; harden against silent mutation |

**What the rewrite CANNOT deliver and no wiring will:** directional alpha on gold. ~15 null
backtests converge; the sentiment score is a correlated copy of the trend, event stats and DXY
lead-lag are empty/underpowered. **The achievable outcome is: capture gold drift while it
lasts, with fewer self-inflicted losses and smaller blow-ups.** The confirmed live damage
(−3,191 normalized on 20 SYSTEM trades; worst single loss −6,248 an *un-stopped* SELL) was
100% addressable by risk-shaping (SL enforcement, long-only, event/sentiment veto) — 0% by
better prediction. **Every design element below is therefore tagged
`[correctness]` / `[risk-shaping]` / `[shadow-only-alpha]`. No `[shadow-only-alpha]` element
may authorize live money without passing the standing gate (t>2, OOS>0, n≥100, cost-adjusted,
drift-null, drop-best-k, quant-auditor refute).**

---

## 1. Target data flow — 8 stages mapped to concrete modules

```
                         ┌─────────────────────────────────────────────┐
 STAGE 1  pull news      │ connectors/web_news.py  (FF calendar, RSS)   │
                         │ connectors/twitter_client.py (Nitter mirrors)│  [correctness: fallback]
                         │ agents/news_gatherer.py (concurrent gather)  │
                         └───────────────┬─────────────────────────────┘
                                         ▼
 STAGE 2  analyze        agents/news_impact.py + agents/news_cache.py (per-post LLM score)
                         agents/sentiment_score.py (gold strategist LLM distils all context)
                                         ▼
 STAGE 3  ONE number ────►  sentiment_score.get_score() → {score −100..+100}      [correctness]
                           (news_impact aggregate + macro_quant.gold_macro_score
                            DEMOTED to inputs/display — see §5)
                                         │
 STAGE 4  event stats ───► agents/event_engine.py .evaluate()/.bias()            [risk-shaping]
                           (PRE flat / POST counter-block / magnitude→size)       [HIGH gap]
                                         │
 STAGE 5  inverse asset ─► regime_lib.macro_for (EURUSD/DXY sign) → dxy_align     [risk-shaping]
                           (binary alignment only; drv_*.json = display/research)
                                         │
                                         ▼
                    ┌──────────────────────────────────────────────┐
                    │  agents/market_state.py  (NEW)                │  §4  FROZEN
                    │  build() → MarketState  (sentiment+event+     │
                    │  dxy+regime, one causal snapshot per cycle)   │
                    └───────────────┬──────────────────────────────┘
                                    │  selects ALGO (via regime) + dir-mode/risk-shape
                                    │  — NEVER entry direction by prediction (CORE INVARIANT)
                                    ▼
 STAGE 6  zones ─────────► agents/chart_watcher.py  _build_sr_meta (rich: exit/select/display)
                           agents/sr_entry_gate.py  (causal block-only gate)      [risk-shaping]
                           (zones = price OHLC only; sentiment/event/DXY DO NOT enter — §6)
                                    │
 STAGE 7  select algo ───► scripts/regime_lib.detect_regime (LIVE, deterministic)
                           agents/algo_router_llm.py (SHADOW-only; promote blocked) [shadow-alpha]
                           agents/roster_guard.py (NEW) LIVE_ALLOWLIST assertion    [correctness]
                                    │
                                    ▼
                    ┌──────────────────────────────────────────────┐
                    │  agents/entry_gate.py  (NEW)  §7  FROZEN      │
                    │  check(EntryContext) → GateResult            │
                    │  ONE veto stack, called by EVERY live path   │
                    └───────────────┬──────────────────────────────┘
                                    ▼  (block-only, fail-open, journaled, 0 token)
 STAGE 8  buy/sell/both ─► agents/algo_dir.py (mode) + LONG_ONLY_ALL/METALS_LONG_ONLY choke
                           at connectors/mt5_connector.open_order (single choke point)
                                    ▼
                    connectors/mt5_connector.open_order / place_pending_order
                    (+ SL-enforce refuse-to-open + reconcile sweep — §8)          [correctness]
```

**Live order paths the stack MUST cover (today they each assemble a different subset — the
central defect):**

| Path | File | Has today | MISSING today |
|---|---|---|---|
| regime_tick (main gold H1) | `agents/regime_tick.py` | sentiment, SR-gate, structural-SL | **event blackout** |
| tsmom_manager (gold D1) | `agents/tsmom_manager.py` | sentiment | **event, SR-gate** |
| MSE `_maybe_enter` | `agents/multi_symbol_executor.py` | event, SR-gate, confirm, dir | **sentiment** |
| regime_executor / regime_pending | `agents/regime_executor.py`, `regime_pending.py` | partial | **uniform stack** |

After the rewrite **all four call `entry_gate.check()` and get the identical stack.**

---

## 2. Design principles (non-negotiable, derived from the constraints)

1. **CORE INVARIANT — entry is computed from price data, never predicted.** Sentiment / news /
   event / DXY / LLM select *which algo runs* and *risk-shape* (veto / shrink / delay) — they
   never originate or aim an entry. `[correctness]`
2. **One implementation, all paths.** Every live order path calls the same `entry_gate.check()`.
   No path may re-implement a subset of vetoes. `[correctness]`
3. **Block-only, fail-open, config-gated, journaled, 0 token.** Every veto can only *remove* a
   trade; on any error it lets the trade through (never blocks money on a bug); each veto has
   its own flag defaulting OFF; each decision is journaled with a reason; all computed in code.
4. **Causality is mandatory for any entry-affecting signal.** Any higher-TF / zone / event
   input feeding a lower-TF entry uses only closed/published bars. Backtest and live call the
   *same* function (parity). The intra-bar leak (loss-diag Z1(c): the forming bar's high/low
   leaking into ATR/pivot windows; the t=8.33→−4.2 collapse) is the exact failure to prevent —
   every gate verifies its last bar is closed. `[correctness]`
5. **Shadow-first for anything claiming edge.** `[shadow-only-alpha]` items log a "would-block /
   would-enter" tag and touch no live order until they clear the standing validation gate.
6. **LLM never auto-authorizes live money.** Roster-drift is the #1 historical loss mechanism
   (08-20 memory). LIVE status is granted only by a frozen code-side allowlist + owner action,
   asserted every cycle. `[correctness]`
7. **Reversibility.** Every change has a kill switch; every new file is additive; wiring changes
   preserve prior per-path behavior when the new vetoes are OFF (parity requirement).
8. **Iron rules respected.** Confidence thresholds, SL/TP defaults, anti-fade guards, and any
   demotion of a *currently-live-trading* algo are **owner-approval items** — flagged
   `[NEEDS OWNER APPROVAL]`, never changed silently by this design or by workers.

---

## 3. Component inventory (reuse vs new)

**Reused as-is (frozen interfaces — see §11):** `sentiment_score.get_score`,
`event_engine.evaluate/bias`, `sentiment_bias.compute`, `sr_entry_gate.blocks_live /
blocks_live_gold / blocks_at`, `algo_dir.allowed / mode_of`, `shadow_switches.state_of /
gold_state`, `regime_lib.detect_regime / macro_for`, `chart_watcher._build_sr_meta`,
`mt5_connector.open_order / place_pending_order`.

**New modules:**
| File | Responsibility | Tag |
|---|---|---|
| `agents/market_state.py` | Build the single causal `MarketState` snapshot per cycle (§4) | correctness |
| `agents/entry_gate.py` | The single veto stack `check(EntryContext)→GateResult` (§7) | correctness |
| `agents/roster_guard.py` | `LIVE_ALLOWLIST` + per-cycle assertion, force-demote drift (§7) | correctness |
| `agents/trend_align.py` | Deterministic drift-alignment veto + kill-switch (§7 veto 5) | risk-shaping |
| `agents/sl_enforce.py` | Refuse-to-open validator + reconcile sweep (§8) | correctness |
| `agents/zone_stamp.py` | Stamp zone/sentiment/event context on every order record (§9) | correctness (instrumentation) |

**Modified (wiring only, behind flags):** `regime_tick.py`, `tsmom_manager.py`,
`multi_symbol_executor.py`, `regime_executor.py`, `regime_pending.py`, `mt5_connector.py`
(SL-enforce hooks + drop double-engine gold from MSE loop), `decision_maker.py` (remove dead
NEWS_GATE or rewire), `dashboard/app.py` (label macro_quant as display), `main.py` /
`trading_graph.py` (call `roster_guard`, `sl_enforce` sweep; fix stale comment).

---

## 4. FROZEN INTERFACE — `MarketState` (the unified sentiment/event/DXY object)

Built once per cycle by `agents/market_state.py::build()`. It is a **read model**: pure data,
no side effects, fail-soft (every field degrades to neutral). It **selects algo (via regime) and
dir-mode/risk-shape (sentiment/event/DXY)** — it never returns an entry direction.

```python
# agents/market_state.py  — FROZEN v1
@dataclass(frozen=True)
class Sentiment:
    score: int          # −100..+100 ; THE single number (sentiment_score.get_score)
    asof: str | None
    ok: bool            # False → treated as neutral (score forced 0 by consumers)

@dataclass(frozen=True)
class EventState:
    phase: str          # "PRE" | "POST" | "NONE"
    key: str | None     # "NFP" | "CPI" | "FOMC" | ...
    bias_dir: str | None  # "BUY" | "SELL" | "FLAT" | None   (POST rubric / PRE=FLAT)
    in_min: float | None      # PRE: minutes until event
    age_min: float | None     # POST: minutes since release
    magnitude_pct: float | None
    n: int | None
    blackout: bool      # True inside calendar blackout window (N1)  [risk-shaping]

@dataclass(frozen=True)
class DxyAlign:
    sign: int           # +1 supports gold up, −1 supports gold down, 0 unknown/neutral
    source: str         # "EURUSD_H4" etc.  (binary alignment only — NOT a computed move)

@dataclass(frozen=True)
class Regime:
    label: str          # "TREND" | "RANGE" | "NEUTRAL"   (price-derived, deterministic)
    adx: float | None
    vol_pct: float | None

@dataclass(frozen=True)
class MarketState:
    ts: str                 # UTC iso, build time
    sentiment: Sentiment
    event: EventState
    dxy: DxyAlign
    regime: Regime
    drift_up: bool          # deterministic D1 drift sign (close>EMA200-type) — feeds trend_align
    ok: bool                # False → consumers treat all sub-fields as neutral

def build(symbol: str = "XAUUSD", now=None) -> MarketState: ...
```

**Causal computation contract:** every sub-field is derived from data available *before* the
current decision instant — `sentiment` from the last cached LLM call, `event` from the
published calendar (schedule precedes event by construction), `dxy` from the last *closed*
EURUSD H4 bar, `regime`/`drift_up` from the last *closed* gold bar. `build()` MUST NOT read a
forming bar. `[correctness]`

**Selection contract (what MarketState is allowed to influence):**
- `regime.label` → **live algo selection** (deterministic router, existing). ✅
- `sentiment` + `event` → **entry_gate vetoes** (block / shrink / delay). ✅
- `dxy.sign` → **selection/confirm filter** (already live in macro_momentum/confluence_15m as a
  binary agreement check) + display. ✅
- `event.magnitude_pct`/`n` → **size scaler** (risk-shaping, §7 note). ✅
- **FORBIDDEN:** none of these may set the traded direction. The traded direction always comes
  from the algo's price computation. Enforced by code review + the CORE INVARIANT test.

---

## 5. Stage 3 — unifying the three sentiment numbers `[correctness]`

Today three numbers exist (gap-audit Stage 3 / §C-5):
- `sentiment_score.get_score().score` — **used** (veto/shrink).
- `news_impact` aggregate — used only by the **dead** NEWS_GATE + as LLM context.
- `macro_quant.gold_macro_score` — docstring says "for SELECTION", **consumed only by dashboard**.

**Decision:** `sentiment_score.get_score().score` is the **single consumable number**.
Rationale: it is the only one already wired into live veto paths, and it already ingests
news_impact/COT/macro as inputs — so it *is* the aggregate, and keeping two more parallel
"scores" invites exactly the kind of drift/ambiguity this rewrite removes. Considered: promote
`macro_quant.gold_macro_score` (it is a cleaner deterministic composite) — rejected because it
is unvalidated as a live consumable and switching the live number is a behavior change on a
live path (owner-approval, higher risk) for no proven benefit.

**Actions:** (a) `news_impact` aggregate → demoted to an *input* of the sentiment LLM only
(no direct consumer). (b) `macro_quant.gold_macro_score` → explicitly labeled **display-only**
in code + dashboard. (c) NEWS_GATE: it is dead on the live path (lives in the REGIME_LIVE-skipped
decision_maker). **Remove it, or** rewire its opposition-block intent into the entry_gate as a
shadow-tagged veto (N2 in loss-diag — but N2 has *no admissible history*, so it ships
shadow-only). Default recommendation: **remove the dead flag**, and if the opposition-block is
wanted, it enters as `[shadow-only-alpha]` veto in Batch 4, not as a revived dead gate.

---

## 6. Stage 6 — zone construction (causality + what may inform it)

**Two zone systems, roles frozen:**
- Rich `sr_meta` (`chart_watcher._build_sr_meta`): strength/touches/bounce_pct/n_tests/score/
  grade. **Role: exit/TP, selection context, display.** May inform algo selection and exits.
- Causal swing-pivot gate (`sr_entry_gate`): **Role: block-only hard entry gate.** Backtest and
  live share `blocks_at` → parity. This is the only zone system allowed to gate a live entry.

**Do sentiment/event/DXY enter zone construction?** Today: no. **Recommendation: keep it that
way — zones are built from price OHLC only.** Rationale:
1. **Causality/parity.** The gate's whole value is that `blocks_at` is a pure function of closed
   OHLC, giving exact backtest↔live parity. Injecting sentiment/event/DXY (which have their own
   timing, caching, and revision semantics) would break parity and re-open look-ahead risk.
2. **Drift contamination.** Sentiment is a restatement of the trend (loss-diag N3). Folding it
   into the one causally-clean gate would smuggle the drift factor into what is currently the
   cleanest risk-shaping lever, and double-count it against trend_align.
3. **They already act at the right layer.** Sentiment/event/DXY act as *separate* vetoes in the
   stack (§7) and as *selection/display* context. That is the correct separation of concerns:
   zones = price structure; market-state = context; the stack composes them.

So: **zones stay price-only for any hard gate; rich sr_meta informs selection/exit/display;
sentiment/event/DXY never enter zone math.** `[risk-shaping]`

**Look-ahead prohibition (mandatory):** `sr_entry_gate.blocks_live` evaluates at
`i = len(c)−1`. Because `regime_tick` runs intra-bar, the caller MUST pass an array whose last
element is a **closed** bar (or the gate must drop the forming bar). This is an explicit
acceptance criterion on every gate-wiring task (loss-diag Z1(c)/Z2(c)).

**Zone-anchored ENTRY ("buy at demand"):** `[shadow-only-alpha]` — Batch 4 only. Standalone
zone-reaction entry was falsified 3× (sr_fade t −4..−22, zone_reaction mining, zone-scalp
t=8.33→−4.2). The *only* admissible framing is **LIMIT-at-zone execution of an already-validated
signal** (execution-price improvement, not a new signal), and even that ships shadow-only until
a replay proves the fill improvement beats the missed-runner cost.

---

## 7. FROZEN INTERFACE — the single entry-veto stack `agents/entry_gate.py`

```python
# agents/entry_gate.py — FROZEN v1
@dataclass(frozen=True)
class EntryContext:
    symbol: str
    direction: str            # "BUY" | "SELL"  (from the ALGO's price computation)
    algo_id: str
    price: float
    atr: float
    tf: str = "H1"
    bars: tuple | None = None # (high[], low[], close[]) closed bars, newest last; or None → gate fetches
    market_state: "MarketState | None" = None   # None → check() builds it
    sl_pips: float | None = None                 # for the SL-validity precondition

@dataclass(frozen=True)
class GateResult:
    block: bool               # True → do not enter
    reason: str               # human-readable, journaled
    lot_mult: float = 1.0     # ≤1 size shrink (sentiment soft-counter)
    extra_margin_atr: float = 0.0  # break-by-more requirement (sentiment soft-counter)
    tags: dict = field(default_factory=dict)  # per-veto verdicts, for shadow-tag journaling

def check(ctx: EntryContext) -> GateResult: ...
```

**Frozen order of checks** (task spec: SL-enforce → event-blackout → sentiment/dir-mode →
causal zone/trend). Each is independently flag-gated; a disabled veto is a pass-through:

| # | Veto | Source | Flag | Tag | Live default |
|---|---|---|---|---|---|
| 0 | **SL validity** — refuse if `sl_pips` is None/≤ `SL_MIN_PIPS` | `sl_enforce.valid()` | (always on) | correctness | ON |
| 1 | **Event blackout** — PRE → block; calendar window (N1) → block | `event_engine` + calendar | `EVENT_BLACKOUT` | risk-shaping | OFF→shadow→ON |
| 2 | **Event POST counter** — POST rubric dir opposite → block | `event_engine.bias()` | `EVENT_ENGINE_LIVE` | risk-shaping | (existing) |
| 3 | **dir-mode** — `algo_dir.allowed(algo_id, dir)` false → block | `algo_dir` | (per-algo) | correctness | ON |
| 4 | **Sentiment** — strong counter → block; soft counter → lot_mult/extra_margin | `sentiment_bias.compute` | `SENTIMENT_BIAS` | risk-shaping | ON |
| 5 | **Trend-alignment** — counter-drift entry → block (symmetric, kill-switched) | `trend_align` (new) | `TREND_ALIGN_VETO` | risk-shaping | OFF→shadow→ON |
| 6 | **Causal zone gate** — per-combo allowlist, closed-bar | `sr_entry_gate.blocks_live[_gold]` | `SR_ENTRY_GATE` | risk-shaping | (existing allowlist) |

**Composition rules:**
- **Block short-circuits** in listed order; the first blocking veto sets `reason`.
- **Soft results accumulate:** `lot_mult` = product of soft mults; `extra_margin_atr` = max.
- **Shadow-tag mode** (`ENTRY_GATE_SHADOW=true`, the initial default): `check()` computes every
  veto and records verdicts in `tags` + journal, but returns `block=False` — collecting the
  forward causal dataset without touching live money. Flip per-veto to enforcing after its
  backtest-gate passes.
- **Fail-open:** any exception in a veto → that veto passes, logged at debug.
- **0 token.** No veto calls the LLM at trade time; `sentiment.score` comes from cache.

**trend_align veto (new, veto 5) — the one defensible lever, honestly labeled:** deterministic
"no counter-drift entry" (e.g. block SELL when D1 close > EMA200-type drift measure; symmetric
for BUY in a downtrend). It is **beta/drift-harvesting, not alpha** — it works only while gold
drifts. Mandatory kill condition: when the D1 drift measure flips, the veto **auto-disables and
alerts** rather than silently starting to veto the newly-correct side. Direction-symmetric by
default. `[risk-shaping]`

**roster_guard (Stage 7 backbone):** `agents/roster_guard.py` holds a frozen code-side
`LIVE_ALLOWLIST: set[str]` of validated `"algo_id:symbol"` combos. Every cycle (and at
startup): any combo whose `shadow_switches.state_of == LIVE` but is **not** in `LIVE_ALLOWLIST`
→ force-demote to SHADOW + loud alert + journal. This closes the door `ALGO_ROUTER_ALLOW_PROMOTE`
was meant to close but that `regime_momentum_fvg:XAUUSD` walked through. `LIVE_ALLOWLIST` is
**not** dashboard- or LLM-editable. `[correctness]`

---

## 8. SL enforcement — the −6,248 un-stopped SELL class `[correctness]`

`open_order` already computes `sl = price ± sl_pips*point` (mt5_connector `_order_setup`:693/699,
`_open_order_fine`:790) — so a market order *with valid sl_pips* is stopped. The failure class is
(a) an order opened with `sl_pips` 0/None/absent, or (b) a position whose broker-side SL never
got attached / was dropped. Two-part fix in `agents/sl_enforce.py`:

```python
# agents/sl_enforce.py — FROZEN v1
def valid(sl_pips: float | None, symbol: str) -> tuple[bool, str]:
    """False → refuse to open. Enforced inside open_order / place_pending_order."""

def reconcile(positions=None) -> list[dict]:
    """Every open position across ALL magics (system, MSE, manual) lacking a broker SL →
    attach a backstop SL (reuse existing AUTO_SL_PIPS / default_sl_pips logic,
    mt5_connector ~:1400). Journaled + alerted. Idempotent, fail-soft. Runs every cycle."""
```

- (a) **Refuse-to-open:** `open_order` and `place_pending_order` call `valid()`; an invalid SL
  returns `{"success": False, "error": "SL-ENFORCE: missing/invalid stop"}`. `SL_MIN_PIPS`
  config, sane default. This is a hard safety floor, **not** a change to SL/TP *defaults*
  (those stay owner-controlled) — so it is `[correctness]`, not an iron-rule change. If the
  chosen `SL_MIN_PIPS` would alter behavior of a live algo, that specific value is
  `[NEEDS OWNER APPROVAL]`.
- (b) **Reconcile sweep:** covers the exact hole — a live position with no stop — on every path
  including manual and MSE. Backstop SL only attaches when *none* exists; never tightens or
  moves an existing owner/algo SL.

---

## 9. Zone-stamping (instrumentation, ships first) `[correctness]`

`agents/zone_stamp.py::snapshot(symbol, price) -> dict` returns, at order time, the sr_meta
context (`sr_zone`, `sr_strength`, `score`, `grade`, `dist_to_zone_atr`) **plus** the
`MarketState` snapshot (sentiment score, event phase, dxy sign, regime). Stamped onto every
trade record on every path. Today real trades carry only `None`/`"NONE"` (loss-diag §1), which
makes it *impossible* to attribute losses to zone/sentiment context or to validate any filter on
live data. This is pure measurement (no veto), causally clean (stamp what was on file at order
time, never recompute), and is the enabler for every future `[shadow-only-alpha]` validation.

---

## 10. Rollout safety

1. **Flags default OFF.** Every new veto and the whole `entry_gate` ship with
   `ENTRY_GATE_SHADOW=true` (compute + journal, block nothing).
2. **Shadow-first ordering:** instrumentation (Batch 0) → safe correctness (Batch 1) → unified
   gate in shadow-tag (Batch 2) → risk-shaping vetoes flipped on one at a time behind their
   backtest-gate (Batch 3) → `[shadow-only-alpha]` (Batch 4, never live without the standing
   gate).
3. **Kill switches:** each veto individually disable-able; `entry_gate` as a whole disable-able
   (falls back to each path's prior behavior — guaranteed by the parity acceptance criterion).
   `trend_align` self-disables on drift flip.
4. **Fail-open everywhere.** A bug never blocks a legitimate trade nor opens an unstopped one
   (SL-enforce is the one *fail-closed* guard, deliberately — refusing to open is the safe side).
5. **Reversibility:** new files are additive; wiring is a single `check()` call per path,
   removable by reverting one line + the flag.
6. **`.env.example` + README sync** (project structural-change rule): every new flag
   (`ENTRY_GATE_SHADOW`, `EVENT_BLACKOUT`, `TREND_ALIGN_VETO`, `SL_MIN_PIPS`, `EVENT_BLACKOUT_*`)
   added to `.env.example` with default + comment; README documents each veto + its kill switch.
7. **Auditor integration gate between every batch** (per global CLAUDE.md): build passes,
   contracts match, no scope violations, parity holds.

---

## 11. Frozen shared interfaces (change requires a new architect pass, logged here)

| # | Interface | File | Kind |
|---|---|---|---|
| F1 | `MarketState` + sub-dataclasses; `build(symbol, now)` | `agents/market_state.py` | NEW |
| F2 | `EntryContext`, `GateResult`, `check(ctx)` | `agents/entry_gate.py` | NEW |
| F3 | `roster_guard.LIVE_ALLOWLIST` (frozen set) + `assert_roster()` | `agents/roster_guard.py` | NEW |
| F4 | `sl_enforce.valid()`, `sl_enforce.reconcile()` | `agents/sl_enforce.py` | NEW |
| F5 | `trend_align.veto(direction, market_state) -> (block, reason)` | `agents/trend_align.py` | NEW |
| F6 | `zone_stamp.snapshot(symbol, price) -> dict` | `agents/zone_stamp.py` | NEW |
| F7 | `sentiment_score.get_score() -> {ok,score,reason,asof,ts}` | existing | FROZEN (the one number) |
| F8 | `event_engine.evaluate()/bias()` return shapes | existing | FROZEN |
| F9 | `sentiment_bias.compute(direction,score) -> {aligned,block,lot_mult,extra_margin_atr,score}` | existing | FROZEN |
| F10 | `sr_entry_gate.blocks_live/blocks_live_gold/blocks_at` (causal contract) | existing | FROZEN |
| F11 | `algo_dir.allowed/mode_of`; `shadow_switches.state_of/gold_state` | existing | FROZEN |
| F12 | trade-record zone/context fields (F6 output keys) | trade writer | NEW/FROZEN |

Workers build against F1–F12. Any change to a frozen interface = `[BLOCKED]` → architect pass.

---

## 12. Owner-approval gates (iron rules — flagged, not decided here)

These are **not** changed by this design; they are surfaced for the owner to approve before the
relevant task runs:

1. **Demoting a currently-live algo** (`regime_momentum` live-tick full-history −0.133;
   `tsmom_d1` t=0.94 believe:false) per loss-diag §4 #2 — changes live money exposure.
   `[NEEDS OWNER APPROVAL]`
2. **`SL_MIN_PIPS` value** if it would alter any live algo's behavior. `[NEEDS OWNER APPROVAL]`
3. **Flipping any risk-shaping veto from shadow to enforcing** (event blackout, trend_align) —
   each only after its backtest-gate passes AND owner signs off. `[NEEDS OWNER APPROVAL]`
4. **Any `[shadow-only-alpha]` item going live** — requires the full standing gate + quant-auditor
   refute + owner. Prior is that they will not pass. `[NEEDS OWNER APPROVAL]`

Not touched at all: confidence thresholds, SL/TP *defaults*, anti-fade `_run_gates` logic,
DecisionMaker bypass structure. Prompt edits (if any) are to `.json`, never `.md`.
```
