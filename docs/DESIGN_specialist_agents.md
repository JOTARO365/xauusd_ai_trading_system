# DESIGN — Specialist Agents (ZoneMapper / TrendSpecialist / RangeSpecialist)

> Status: **DRAFT — awaiting user approval. No code written, no subagents created.**
> Written by: architect · Date: 2026-07-14 · Source spec: user (two-layer specialist design)
> Design of record once approved. Per `.claude/CLAUDE.md` explain-before-acting + iron rules,
> nothing in Layer A gets implemented until this doc is approved.

## 0. Goal & non-goals

**Goal.** Restructure the trading judgment into three *regime-scoped* specialist roles so the
logic for each market condition is isolated, testable, and only ONE is active per cycle. Each
specialist is a **deterministic Python module first**; an LLM call is justified only where a rule
genuinely cannot capture the judgment, and it must **ride the existing `decision_maker` Claude
call** — never add a new call.

**Non-goals.** No new AI agent/LLM call. No change to confidence thresholds, SL/TP defaults,
anti-fade guards, or money management (iron rules — would need separate approval). Not a rewrite
of chart_watcher — we *reuse* its primitives.

## 1. What already exists (verified, file:line) — so we reuse, not duplicate

| Need | Already in code | Note |
|---|---|---|
| Per-TF swing ladder H1/H4/D1/W1 | `chart_watcher.find_swing_levels` :202, called :1383-1395 | 4 separate `*_sr` dicts; **no unified ladder object** |
| Rich per-level metadata (strength%, touches, confluence, break/hold) | `sr_meta` via `_build_sr_meta` :861 | **display-only today** — not read by gates/LLM. Ready-made ZoneMapper basis |
| Flat ladder gates/pending actually read | `sr_zones` (H4+H1) :1544 | D1/W1 NOT in it |
| HTF nearest zone | `detect_htf_zone` :309 → `htf_zone` | feeds anti-fade gates |
| Range "box" | **only** on-the-fly in `pending_manager.manage_range_pending` :714-735 | not persisted/shared — ZoneMapper centralizes this |
| Regime (LLM) | `market_advisor` → `regime` ∈ {BULLISH_TREND, BEARISH_TREND, SIDEWAYS, TRANSITION} `schemas.py:34` | **advisory only — NOT a gate today** |
| Trend (deterministic, enforced) | `chart_data["trend"]` (H4 bias) `scan_entry_setups` :962 | gates 4/5 read THIS |
| D1 trend (deterministic, hard block) | `calc_d1_trend` :1319 → `d1_trend` | gate 2e HTF_DIRECTION_BLOCK |
| EMA/PA primitives for TrendSpecialist | `calc_momentum` :589, `_check_h1_structure` :684, `detect_candle_pattern` :453, `detect_sr_action` :647, EMAs in `indicators` :1553 | all present |

## 2. Layer A — runtime specialists (cost tokens; must add ZERO new calls)

### 2.1 ZoneMapper (Stage-1 owner, pure Python)
- **Job:** produce ONE `zone_map` object = the unified 1H/4H/1D/1W ladder + the range box, as the
  single source of truth the other two specialists + pending manager consume.
- **Build from what exists:** merge the four `*_sr` dicts + `sr_meta` strength/confluence + `key_levels`
  + `htf_zone`; lift the box math out of `manage_range_pending` :714-735 (upper=nearest res, lower=
  nearest sup, `range_width_pips`, width/ATR guards) into ZoneMapper so it is computed ONCE and shared.
- **Output:** `zone_map = {ladder:[{level,tf,side,strength,...}], box:{upper,lower,width_pips,valid},
  htf_zone, nearest:{...}}` attached to `chart_data` (so `node_reporter`/pending_manager reach it too).
- **Runs:** new graph node between `chart` and `advisor` (`trading_graph.py:355`), writing `zone_map`
  into `chart_data`/state. Zone math needs no LLM.

### 2.2 TrendSpecialist (owns UPTREND + DOWNTREND)
- **Pure-Python qualification + trigger:** EMA structure (`indicators` EMAs + `calc_momentum` :589),
  PA confirmation at bands (`detect_candle_pattern` :453, `detect_sr_action` :647, `_check_h1_structure`
  :684), consuming `zone_map`.
- **If a judgment call is genuinely needed** (e.g. "clean pullback vs knife-catch"): express it as
  **extra context lines inside the EXISTING `decision_maker` Claude call** (precedent: news_impact
  scoring merged into the Haiku call = 0 new calls). NO new agent call.

### 2.3 RangeSpecialist (owns SIDEWAYS)
- **Pure-Python:** box-width validation, edge-rejection PA, breakout invalidation — all from `zone_map`
  + existing PA detectors. Mirrors today's gate-5 SIDEWAYS logic (`decision_maker.py:581-606`) +
  `manage_range_pending` guards, now centralized. Same rule: no new LLM call.

### 2.4 Routing table (regime → exactly ONE active specialist)

| Regime signal | Active specialist | Dormant (must NOT fire) | Log line |
|---|---|---|---|
| trend = BULLISH (UPTREND) | TrendSpecialist · UPTREND branch | RangeSpecialist, DOWNTREND branch | `[SPEC] TrendUp active — <why>` |
| trend = BEARISH (DOWNTREND) | TrendSpecialist · DOWNTREND branch | RangeSpecialist, UPTREND branch | `[SPEC] TrendDown active — <why>` |
| trend = SIDEWAYS | RangeSpecialist | TrendSpecialist | `[SPEC] Range active — <why>` |
| TRANSITION (advisor) | **none** (conservative: no fresh entry) | all | `[SPEC] Transition — stand down` |

- **Router source (DECISION NEEDED — see §5):** recommend the **deterministic `chart_data["trend"]`**
  (H4, free, already what gates 4/5 enforce) as the primary router, with `advisor.regime` as an
  optional confirm. Using the LLM regime as the sole router would make routing depend on an LLM field
  that is advisory-only today.
- **Dormancy rule:** the classifier selects one; the other two specialists' trigger conditions must
  evaluate False. Log active specialist + reason every cycle (goes to `system.log`, zero token).

### 2.5 Zero-new-LLM-call cost statement  ✅
- ZoneMapper, TrendSpecialist, RangeSpecialist = **pure Python. 0 tokens.**
- Any judgment escalation = **extra context lines on the existing `decision_maker` Sonnet call** —
  same call count, marginally more input tokens (like news_impact rode the Haiku call).
- **Net new LLM calls/cycle = 0.** Net new calls/day = 0. If any future step *requires* a new call,
  STOP and present `calls/day × tokens × price` for approval (hard rule).

## 3. ⚠️ Reality check — the spec's "no path bypasses DecisionMaker" is NOT true today

Recon found **the regime gate placed in `_run_gates` would govern ONLY the live-market-order path.**
Three other order paths already bypass `make_decision`/`_run_gates` and carry their OWN gate logic:

1. **`pending_manager`** — `auto_place_pending_orders` :213, `manage_range_pending` :652,
   `manage_sl_reentry` :858 call `place_pending_order()` directly (run in `node_reporter`), with a
   *separate* filter set (they already duplicate `_d1_counter`). Pending fills become live positions
   without passing `_run_gates`.
2. **`mt5_connector.manage_zone_break_close` :1709** — zone-break re-entry calls `open_order(...,
   "ZONE_REENTRY")` directly from `node_position_mgmt`. Full bypass.
3. **`swing_manager`** — raw `mt5.order_send` :91/:127, own `SWG-` magic. Full bypass.

**Implication for the design (DECISION NEEDED — see §5):** to truly have "one regime rule govern all
entries," the regime check must be applied in ZoneMapper's shared object AND consumed by all four
paths (market gate + the three bypasses), the way `_d1_counter` is already duplicated. Otherwise the
feature governs the market-order path only and the doc must say so honestly.

## 4. Layer B — development specialists (Claude Code subagents, ZERO runtime cost)

Created under `.claude/agents/*.md`, used only while BUILDING. Each: **narrow file whitelist,
read-only except its own report file, and MUST quote file:line for every claim** (this repo has a
documented history of agent false-positive bug reports — unverified claims are the failure mode).

| Dev subagent | Whitelist (read) | Job / output |
|---|---|---|
| `sr-logic-reviewer` | `chart_watcher.py` + new ZoneMapper module | Hand-trace zone-merge math on real XAU ladder examples; hunt off-by-one + unit bugs (pips=0.01 vs points vs price); verify every datetime is UTC-aware. → report file |
| `gate-integration-auditor` | `decision_maker.py` (gates) + pending/zone-reentry/swing order paths | Prove the new regime gate cannot contradict gates 2b–5c (HTF_DIRECTION_BLOCK, anti-fade, counter-trend, SIDEWAYS); produce a **gate-conflict matrix**; enumerate every order path that bypasses DecisionMaker (§3) and whether each got the regime check. → report file |
| `replay-validator` | recent H1/H4 history (MT5 export / logged bars) + the 3 specialist condition sets | Per-regime trigger counts, hypothetical R:R outcomes, false-signal cases. **Feature stays flag-OFF until this report is reviewed.** → report file |

## 5. Decisions the user must make before implementation

1. **Router source:** deterministic `chart_data["trend"]` (recommended) vs `advisor.regime` (LLM) vs
   both-must-agree. Affects how often each specialist activates.
2. **Scope of the regime rule:** market-order path only (simplest, honest), OR duplicate the regime
   check into the 3 bypass paths too (pending/zone-reentry/swing) for true coverage (bigger change,
   touches gate-adjacent code → more approval surface).
3. **TRANSITION regime:** stand down (no entry) — confirm this conservative default.
4. **Where ZoneMapper lives:** new graph node after `chart` (recommended, clean separation) vs folded
   into `node_chart`.
5. **`sr_meta` promotion:** ZoneMapper would make the currently display-only `sr_meta` a real input.
   Confirm that's intended (it changes `sr_meta` from zero-token display to a consumed object — still
   0 new LLM calls, but it now influences logic).

## 6. Non-goals / guardrails restated
- 0 new LLM calls (§2.5). No threshold/SL-TP/anti-fade/money-mgmt change without separate approval.
- Feature ships **flag-OFF** behind a config knob until `replay-validator` report is reviewed.
- continue.md + TASKS.md updated per iron rules once implementation starts.

---
### Proposed next steps (ONLY after approval)
1. User answers §5 decisions.
2. Create the 3 Layer-B dev subagents (`.claude/agents/`).
3. Implement Layer-A modules (ZoneMapper → TrendSpecialist → RangeSpecialist) with the dev subagents
   reviewing each step; unit tests per module; feature flag-OFF.
4. `replay-validator` report → review → decide on enabling.
