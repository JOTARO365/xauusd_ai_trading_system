# DESIGN — Specialist Agents (ZoneMapper / TrendSpecialist / RangeSpecialist)

> Status: **APPROVED 2026-07-14 — §5 frozen. Requirement: multi-TF entries (more entry
> candidates) BUT cap=6/day + conf floor=62 UNCHANGED (user chose "คง guard"). 0 iron-rule
> change. Ships flag-OFF. Next: create Layer-B subagents → implement Layer-A.**
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

### 2.4 Routing — PER-TIMEFRAME lanes (multi-TF entries)

The router runs **per timeframe lane** (H1, H4, D1 — W1 informs bias only). Each lane gets its own
deterministic regime → exactly ONE specialist owns that lane that cycle. Because different TFs can be
in different regimes at once, a single cycle can surface **multiple entry candidates** (e.g. H1 lane =
Range edge-buy while H4 lane = Trend pullback) — this is how "more entries" happens WITHOUT loosening
any bar.

| Lane regime (deterministic per TF) | Owner specialist | Dormant in that lane |
|---|---|---|
| trend(TF) = BULLISH | TrendSpecialist · UPTREND | RangeSpecialist, DOWNTREND |
| trend(TF) = BEARISH | TrendSpecialist · DOWNTREND | RangeSpecialist, UPTREND |
| trend(TF) = SIDEWAYS | RangeSpecialist | TrendSpecialist |
| TRANSITION (that TF only) | that lane stands down | — (other lanes still trade) |

- **Router source (FROZEN §5.1):** deterministic per-TF trend (H1/H4/D1) — free, replay-able, aligned
  with gates 4/5. `advisor.regime` is an optional cross-check logged on disagreement, never the sole router.
- **All candidates funnel through the SAME `decision_maker` gates + the shared daily cap = 6 + conf
  floor = 62.** Multi-TF adds *candidates*, not looser thresholds; the cap is the backstop that keeps
  "more entries" from becoming "overtrading" (replay: trade #7+ = −411). Log the winning lane + why,
  and log candidates that were capped out (zero token).
- **Dormancy rule (per lane):** within a lane, only the owning specialist's triggers may evaluate True.

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

## 5. Decisions — FROZEN 2026-07-14 (user approved)

1. **Router source:** ✅ deterministic **per-TF trend (H1/H4/D1)**, `advisor.regime` = logged cross-check
   only. (Revised from single-H4 to per-TF to enable multi-TF entries.)
2. **Scope of the regime rule:** ✅ **market-order path first** (flag-OFF). Duplicating into the 3 bypass
   paths (pending/zone-reentry/swing) is a possible phase-2, not now.
3. **TRANSITION regime:** ✅ **per-lane stand-down** — a TF in TRANSITION doesn't trade, but other TFs in
   a clear regime still can (supports "more entries" without forcing a whole-cycle stop).
4. **ZoneMapper location:** ✅ **new graph node after `chart`**.
5. **`sr_meta` promotion:** ✅ **promote** to a real input (still 0 new LLM calls). MUST log in continue.md
   that `sr_meta` is no longer display-only.
6. **Entry frequency vs guards (added requirement):** ✅ **cap=6/day + conf floor=62 UNCHANGED.** Multi-TF
   adds candidates that still pass every existing gate; NO iron-rule / money-management change. If a future
   step wants a higher cap or lower floor, that is a SEPARATE approval requiring a replay backtest first.

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
