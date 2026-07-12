# AUDIT — Full-System Code Review & Bug Hunt (v0.4.0)

> Written by: auditor · Run: 2026-07-12 · Scope: whole trading path
> Method: 4 parallel tracer-agents, each reading full functions and tracing
> real numbers (balance $2000, SL 1500pts, conf 65%). CONFIRMED is kept
> strictly separate from NEEDS-VERIFICATION. No code was changed by this audit.
> Files read in full: main.py, config.py, agents/{decision_maker, analyst,
> market_advisor, chart_watcher, swing_manager, position_guardian, accountant,
> news_gatherer, news_cache, news_impact, trading_graph, pending_manager}.py,
> connectors/{mt5_connector, web_news}.py, db/{reader, writer, connection, sync}.py,
> reporter.py. Cross-checked: ml/train_filter.py, utils/market_clock.py, schema.sql.

## Reconciliation of the prompt's "known unfixed bugs" — 3 of 4 are stale

| Stated "known unfixed" bug | Verdict |
|---|---|
| `_partial_stage` never cleaned up (mt5:~497) | ❌ **Refuted** — the var is `_partial_state` and it *is* pruned (mt5_connector.py:1272/1192). The genuine uncleaned dict is elsewhere → **B3** |
| weekly pending uses local time (main:~521) | ✅ **Confirmed** → **B4** (real line 622) |
| analyst naive-vs-aware datetime (~124) | ❌ **Refuted as active** — calendar `timestamp_iso` is tz-aware on the live ForexFactory path (web_news.py:85/87), so no TypeError and `pending_events` populates. Latent gap only → **B7** (real line 206) |
| news_cache `task_type` lowercase (~202) | ❌ **Refuted** — uppercase everywhere already (news_cache.py:306/364/394); line 202 is unrelated prompt code |

Lesson reinforced: two of these were re-tests of the prior false-positive class —
disproven by reading the guard clause / the actual data path.

## Bug / Defect Table (ranked by real-money exposure)

"Money?" = can it directly move the account balance. Sev in parentheses notes the
condition under which it activates.

| # | Finding | file:line | Severity | Verified | Money? |
|---|---|---|---|---|---|
| **B1** | **`RISK_PER_TRADE=0.50` = 50%/trade.** Inert today only because `MIN_LOT=MAX_LOT=0.01` clamps every lot to 0.01. Raise `MAX_LOT` without lowering risk → ~32% single-trade risk (0.50×0.65×$2000=$650 target). Non-NNLB path has no max-loss-% cap (unlike NNLB's `NNLB_MAX_LOSS_PCT`). *Found independently by 2 agents.* | config.py:53 → mt5_connector.py:85-88 | **High (latent)** | CONFIRMED (intent = user's call) | ✅ if `MAX_LOT` raised |
| **B2** | **Daily-loss circuit breaker defanged at default.** `max_daily_loss=1.00` (=100%) → gate 1 effectively never fires unless `.env` overrides it. | config.py:54 | **High (latent)** | CONFIRMED (intent = user's call) | ✅ removes safety net |
| **B3** | **`_tp_ext_count`/`_tp_ext_last_time` never pruned** — the *real* ticket-reuse leak. Every other state dict prunes closed tickets (`_partial_state`:1272, `_be_pending`:938/954, `_zone_state`:1577); `manage_dynamic_tp` has no prune. Reused ticket → new position sees `ext_done≥TP_EXT_MAX` → Dynamic-TP never extends + phantom cooldown; slow memory growth. | mt5_connector.py:1377-1378, 1749-1794 | Med (DYNAMIC_TP only) | CONFIRMED | ⚠️ caps winners |
| **B4** | **Weekly straddle fires on LOCAL date, not UTC.** Only clock in the trading path not on UTC. Never fully misses/double-fires (dedupe + live-order guard), but drifts by the host UTC offset — on a US/UTC VM the Monday straddle lands hours into the week. | main.py:622 | Med | CONFIRMED | ⚠️ degrades entry timing |
| **B5** | **EMA_PULLBACK hard-blocked normally but synthesized & traded LLM-unreviewed in NNLB.** Normal path blocks it (`EMA_PULLBACK_BLOCK`, WR31%/−594); NNLB sets `entry_type="EMA_PULLBACK"`, returns at 476 before the block, and with `NNLB_FASTPATH=true` opens the order at 761-786 without Claude. | decision_maker.py:410-414, 476, 655-657 | Med (NNLB only) | CONFIRMED | ✅ trades a toxic setup if NNLB on |
| **B6** | **Claude's `out_direction` not re-asserted vs the gate-validated direction.** All anti-fade/HTF gates validate the *gate* direction; execution then trusts Claude's `result.direction` and re-selects SL by it, with no `out_direction==gate["direction"]` check. Structured output makes a flip low-probability but nothing enforces it. | decision_maker.py:895-896, 908-911 | Med (low prob, high consequence) | NEEDS-VERIFICATION | ✅ if a flip ever occurs |
| **B7** | **Only unguarded `fromisoformat` on a calendar timestamp** in the repo (no `tzinfo is None` guard, unlike scripts/update_regime.py:193 and decision_maker.py:294). Dormant today; if any cached/alt source ever emits naive time, the bare `except: pass` silently drops the event and `nearest_event_minutes` stays 9999 (feeds `_effective_min_rr` + No-TP-on-event). | analyst.py:206, 212-213 | Low-Med | CONFIRMED (latent) | ⚠️ silently mishandles events |
| **B8** | **Two clock conventions for `mt5.history_deals_get`** — SL-reentry uses aware-UTC 30-min window; daily-cap/reporter use naive-local. On a broker-server-time mismatch the *tight* 30-min window can systematically exclude fresh SL closes → Post-SL re-entry silently finds nothing (fail-safe direction). Wide-window callers tolerate the drift. | pending_manager.py:839-841 vs mt5_connector.py:736-737 | Med | NEEDS-VERIFICATION (inconsistency confirmed; runtime miss needs a 1-line broker-tz probe) | ⚠️ under-delivers |
| **B9** | **No per-cycle deadline; agent LLM clients have no `timeout`/`max_retries`** (SDK default ~600s×2). Protective management (BE/trailing/`ensure_sl_protection`) sits *downstream* of the 4-call LLM chain in the full path → an API stall leaves open positions unmanaged (Guardian is default-off). `DEFAULT_INTERVAL=300` is only the post-cycle sleep, not a cap. | main.py:409; decision_maker.py:13, market_advisor.py:9, analyst.py:11, chart_watcher.py:15 | Med | CONFIRMED | ⚠️ no protection during stall |
| **B10** | **`swing_manager.py` MT5 calls bypass `_mt5_lock`** — unserialized concurrent access with the guardian thread (MT5 binding not thread-safe). The lock-wrap loop (mt5_connector.py:1969-1976) wraps the connector's own fns but not `manage_swing_campaign`. Bites only when `SWING_ENABLED`+`GUARDIAN_ENABLED` both on. | swing_manager.py:63/91/107/216-233 | Med (both flags on) | CONFIRMED | ⚠️ order corruption risk |
| **B11** | **`open_order` retry sleeps ≤1s under `_mt5_lock`**, blocking the guardian; retry path also skips the stops-level re-clamp (523-541) + RR re-check (552-557) → possible hard reject. Worst case fails cleanly (no naked/oversized order). | mt5_connector.py:598-623 | Low | CONFIRMED | ❌ fails cleanly |
| **B12** | **5 decision-snapshot columns written but never read** (`planned_sl_pips, entry_score, atr_h4, momentum, htf_zone_tf`) — same class as the old `strategy_version` bug. Worse: `ml/train_filter.py:48-51` re-derives `sl_pips` from the *final* mutated `sl` → reintroduces the outcome leakage `planned_sl_pips` was added to prevent. | writer.py:91-95; reader.py:39-45; ml/train_filter.py:48-51 | Low-Med | NEEDS-VERIFICATION (may be staged for a v2 trainer) | ❌ ML quality only |
| **B13** | **`pa_patterns`/`manual_reason`/`manual_analysis` mapped on read but never in schema/write** → always blank when a trade row comes from DB vs JSON. (`pa_zone`/`pa_level` same JSON-only status.) | reader.py:74-78 | Low | CONFIRMED | ❌ display/analytics |
| **B14** | **Bare `except: pass` in `_get_close_times`** swallows MT5 history errors with no log → close metadata silently degrades to `now()`/`UNKNOWN` (PnL still recovered separately). | reporter.py:221-222 | Low | CONFIRMED | ❌ metadata only |
| **B15** | **`news_gatherer` `asyncio.gather` without `return_exceptions=True`** — if the twitter fetch raises, the cycle loses calendar + articles too (the web fetchers catch internally and return []). | news_gatherer.py:19-23 | Low-Med | NEEDS-VERIFICATION | ❌ data availability |

### Intentional-but-worth-recording (not bugs)
- **Dynamic min-RR floor is 1.5, not the advertised 2.0.** `_effective_min_rr` (decision_maker.py:218-248) returns 1.5/1.7/1.8 in hot conditions and is the real floor used at TP-scaling (947) and `open_order(min_rr=…)` (969). Intentional & documented, but "RR 2.0" does **not** hold system-wide — the enforced floor is 1.5.

## Concrete cycle trace (conf 65%, RR 2.0, 3-loss streak, event 20 min away)

Aligned BUY, BULLISH trend, at SUPPORT, active hour, `NNLB_MODE=false`: all 12 gates
pass; streak=3 (<max 5) applies `streak_scale=0.60`; `eff_rr` relaxes to ~1.7-1.8 (event
≤30min → hot), RR 2.0 clears; **No-TP-on-event fires** (`nearest_mins=20 ≤ NO_TP_EVENT_MINS=20`
→ `effective_tp=0`); TP-scaling correctly skipped by the `effective_tp>0` guard. **Outcome:**
trade allowed (subject to Claude SKIP), sized 0.60×, opened **with no TP into the event** — only
the SL bounds it. Self-consistent; the strategy stance (ride the event rather than block a fresh
entry) is a design choice, see Opinion O-A.

## Areas verified CLEAN (checked, not invented into bugs)
- pip_value still 0.01 — not regressed (`_calc_pip_value`:100, gold $1/point/lot).
- Breakeven direction correct (manage_breakeven:1030, force-BE:1329, partial-1R:1238) — not inverted; backward-move guards present.
- `_partial_state` cleanup present (1272/1192); EMA NaN seed OK (`_ema_np`:1381); accountant div-guards OK (`total_in>0`).
- position_guardian fail-soft, lock-wrapped calls; NNLB path has a real max-loss cap.
- `strategy_version` traced end-to-end write→schema→select→map→consume (writer.py:96 → schema:39 → reader.py:44/79 → reporter.py:665/786). The past field-loss bug is genuinely fixed.
- News cache TTL: units (seconds) + tz (UTC throughout) consistent, TTL expires; price-move invalidation exists (`force_fresh` via analyst.py:115-117 → COUNTER_SPIKE_PIPS).
- JSON↔DB integrity: `get_trades` returns `None` (not `[]`) on error → reporter falls back to trades.json; startup reconciliation via sync.py (skips existing tickets). No empty-list-as-truth on the money path (open-trade gates read MT5 directly).
- All LLM/agent failure paths default to **no-trade / neutral** (analyst NEUTRAL conf 0; market_advisor SIDEWAYS/NEUTRAL; decision_maker SKIP/NONE). No path defaults to "trade anyway."
- Gate threshold ladder internally consistent: 62 universal floor → 65/70/72/75/80 for riskier setups (not the "62 vs 80 contradiction" the prompt suspected). Streak-5 consistent across NNLB + normal. No two gates double-block the same setup.
- Module-level state (`_cycle`, `_last_chart_data`, …) reassigned in place, never appended — bounded, no memory growth. LangGraph compiled with no checkpointer → stateless per cycle.
- news_impact.py parse/aggregate/snapshot: fail-soft, atomic writes (tmp+os.replace), F-10 empty-overwrite guard present.

## Optimization Table (ranked by ROI)

| # | Proposal | Effort | Impact | Priority |
|---|---|---|---|---|
| **O1** | Remove `cache_control: ephemeral` from market_advisor + decision_maker system prompts (or confirm cycles <5min). Analyst already removed it with evidence ("205 calls, cache_read=0, paying 1.25× write premium for nothing"); the other two still pay it every cycle. | S | Cost — kills a 1.25× write premium on 2 agents/cycle | **High** |
| **O2** | Batch Gemini embeds (`contents=[...]`) + bulk-insert on cache MISS. ~23 items each fire a separate `embed_content` + insert; free tier (~25/day) can exhaust in ~1 MISS. | M | Cost + quota — biggest token/quota win | **High** |
| **O3** | Add `timeout≈30-45s, max_retries=1` to the 4 agent LLM clients (also caps B9's stall). | S | Stability + latency cap | **High** |
| **O4** | Bound the MT5 reconnect loop (main.py:512-516) — retries every 10s forever, no alert. Add a failure counter → WARN + backoff after N. | S | Robustness — surfaces a dead broker | Med |
| **O5** | Single `_broker_now()`/`_broker_window()` helper for every `history_deals_get` caller (fixes B8 permanently). | M | Correctness | Med |
| **O6** | Bulk `agent_usage` insert per cycle (writer.py:127-143 loops one insert/agent) + window/cache the unbounded accounting scans (reader.py:106-178 full-table scan + Python sum on every dashboard load). | S+M | Speed — dashboard + DB load | Med |
| **O7** | Cache the M15 momentum result per cycle — `_is_momentum_strong` recomputes 4 EMAs+RSI on 55 bars for each of dynamic-TP / momentum-exit / post-event-TP, all under the MT5 lock. | S | Latency (under lock) | Low |
| **O8** | Consider moving protective management (`ensure_sl_protection`/`manage_breakeven`) ahead of the LLM chain in the graph, or default `GUARDIAN_ENABLED=on` for the live VM. **Graph-routing / money change → architect + user approval.** | M | Safety — protects during AI stalls | Med |

## Opinions (labeled — strategy soundness, not defects)
- **O-A (add gate?):** No event-blackout gate on *entries* — a fresh entry is permitted 20 min before a high-impact event and the no-TP logic encourages holding through it. Decide explicitly: keep "ride the event" or add a `nearest_event_minutes ≤ X` entry block.
- **O-B (reconcile):** Resolve the EMA_PULLBACK contradiction (B5) — pick one philosophy across normal and NNLB paths.
- **O-C (config safety):** B1 + B2 defaults should be revisited for the live micro-account.

## Postmortem — recurring root-cause patterns + prevention checklist

**Patterns (past bugs + this audit):**
1. **Constants trusted without real-world verification** — the original 10× `pip_value`. Today's analogue: B1/B2 — code-correct but real-world-dangerous defaults, masked by an unrelated clamp/override. A number that only bites when a *second* knob changes.
2. **Fields that don't survive write→read→consume** — the old `strategy_version`. Today: B12/B13 — orphaned columns keep sprouting.
3. **One subsystem on a different clock** — B4/B8/B7. Project standardized on UTC everywhere *except* three unmigrated spots. Timezone drift is this codebase's most persistent bug family.
4. **Silent `except: pass` hiding decision-gating state** — B7/B14/B15. Fail-safe *direction* has prevented money loss, but destroys observability.
5. **Two code paths, one philosophy not enforced across both** — B5 (EMA_PULLBACK), B6 (gate vs execution direction).

**Prevention checklist — before merging any change:**
- [ ] **Financial constant?** Verify against the live broker AND name the *other* knob (MAX_LOT/MIN_LOT/env) currently masking it. A safe default must be safe *without* the mask.
- [ ] **New DB field?** Trace write → schema → select → map → consume in the same PR. If nothing reads it, don't write it.
- [ ] **Any `datetime`?** Use `datetime.now(timezone.utc)`; guard every `fromisoformat` with `if dt.tzinfo is None`. Never `date.today()`/naive `now()` in the trading path.
- [ ] **`except` clause?** Name the exception type + `logger.debug/warning`. No bare `except: pass` on anything feeding a gate.
- [ ] **New module-level dict keyed by ticket?** Add the same prune (`{t:v for … if t in active}`) the other managers use, same PR.
- [ ] **Second code path (NNLB/swing/hedge)?** Re-apply every block/lock the normal path has, or document why it's exempt.
- [ ] **New LLM client?** Set `timeout` + `max_retries`; decide `cache_control` on the *measured* cycle interval, not by default.

**Same-class risk still latent (masked, not fixed):** B1 (lot clamp), B2 (env override), B8 (Bangkok dev-box tz), B12 (v2 trainer not live). Each is one config/deploy change from activating.

## Fix tasks filed (see docs/TASKS.md)
The auditor reports only; fixes are new tasks. Safe / no-approval-needed: B3, B7,
B14, B15, O1, O3. Requires user approval (money-management / gate / graph): B1, B2,
B5, B6, B8, B10, O8. NEEDS-VERIFICATION probes first: B6, B8, B12, B15.

---
---

# ARCHIVED — previous cycle audit (superseded by the 2026-07-12 full-system audit above)

# AUDIT — News & Event Impact Analysis (M0-M6, batches A-G)

> Written by: auditor · Last run: 2026-07-05 06:38-07:05 (+0700)
> Cycle commits: df8cd6d (M0+M1) → c0a9dc5 (M2) → 65055e4 (M3) → 27eba74 (M4) → 248272d (M5+M6). Baseline = a60af40.
> Test command: `& $PY tests\test_all.py` (./CLAUDE.md) · Suite result: **21 passed / 8 failed (2 FAIL + 6 ERROR) — identical to the previous cycle's audited baseline set, 0 new**
>
> Suite evidence: all 8 failures are the SAME set the 2026-07-04 audit recorded — 6 ERROR
> in `TestMomentumFastPath` (TypeError at `agents/decision_maker.py:568`, `7 <= _utc_hour`
> vs MagicMock) + 2 FAIL in `TestStreakGate` (quiet-session floor active at run time 06:38
> +0700 = 23:38 UTC Sat — time-of-day dependent per CLAUDE.md). Neither file was touched
> this cycle: `git log a60af40..HEAD -- agents/decision_maker.py tests/` → **empty**.
> Failure set unchanged → no new failures attributable to this cycle; no worktree baseline needed.

## Per-Item Results

| Task | Criterion | Verdict | Evidence (file:line / command output) |
|------|-----------|---------|----------------------------------------|
| A1 | Delta $ line, arithmetically consistent with prior % | PASS | `index.html:4214-4215` `upDelta = px*avg_up_pct/100`, `dnDelta = px*abs(avg_down_pct)/100`; rendered `:4224` as `▲ +$…  ▼ −$…` with `(prior)` label. Display-only, no new fetch |
| A1 | No matched event → card unchanged; no console error | PASS (code) | `:4224` ternary renders '' when either delta is null; unmatched events keep `extra=''` path (`:4202`). Live-browser check pending dashboard restart (see User Actions) |
| B1 | `normalize_posts` / `is_gold_relevant` / `content_hash` / `prefilter_and_dedupe` per contract | PASS | `agents/news_impact.py:176-291`; keyword set module constant `:46-163` (word-boundary, case-insensitive `:166-169`); 8-char sha256 hash `:237-246`; stats dict exact `{raw,kept,filter_rate_pct}` `:286-290`. Synthetic harness run: case/whitespace duplicate deduped, irrelevant posts dropped, gold headlines kept (auditor run, output logged in this audit session) |
| B1 | node_news measurement wired, try/except, never raises | PASS | `agents/trading_graph.py:138-146` — inner try/except around normalize+prefilter+`log.info("[news_impact] filter %s")`; outer node try `:134-151` unchanged |
| B1 | ≥70% filter rate on real traffic, 1-2 day spot-check | PENDING-VERIFY | `logs/system.log` is 688 bytes (rotated 05:53 today) and contains 0 `[news_impact]` lines; `data/news_impact.json` + `data/news_scores_cache.json` do not exist → the running bot predates this code. Verify after bot restart + 1-2 days |
| B1 | Token cost unchanged; test baseline unaffected | PASS | M1 is pure code (no LLM import in news_impact.py — file has no anthropic/network); suite failure set identical to baseline (header) |
| C1 | Sign table = §4.5 exact, frozen values | PASS | `data/event_sign_table.json` — 8 keys + note, values match PLAN Q1 exactly (UNEMPLOYMENT `hot_gold_up`, FOMC `hawkish_gold_down`) |
| C1 | Builder output validates against §4.2 for CPI/NFP/FOMC; directions from sign table | PASS | `data/event_scenarios.json` keys = {ok,updated,window,min_n,scenarios{sign,hot{dir,magnitude_pct,provenance,n},cool{…},surprise_curve}} — exact §4.2. Directions: CPI/NFP hot→down cool→up, FOMC hot→down cool→up = sign table via `_direction_for_sign` (`build_event_scenarios.py:64-77`) |
| C1 | Rubric magnitudes = two-sided priors | PASS | On-disk 0.699/0.79 (CPI), 0.92/0.87 (NFP), 0.814/0.955 (FOMC) == `data/event_stats.json` avg_down/avg_up exactly (auditor dump: CPI 0.79/−0.699, NFP 0.87/−0.92, FOMC 0.955/−0.814) |
| C1 | Atomic write; reproducible | PASS | `build_event_scenarios.py:397-412` tmp+`os.replace`; sandbox re-run reproduced committed file byte-equal except `updated` (`REPRODUCIBLE: True`) |
| C1 | `/api/event-scenario` mirrors `/api/burn`; missing file → `_empty` ok:true, never 500 | PASS | `dashboard/app.py:1175-1188` — `_empty` per §4.2; `except FileNotFoundError` + generic `except Exception` both return `_empty` (a parse error also cannot 500) |
| C2 | Conditional hot/cool line, $ from px, provenance+n label; fallback to prior card | PASS | `index.html:4160-4177` `renderScenarioLine` — returns '' when no scenario entry, no px, or forecast empty/'—' (`:4163-4165`); both sides colored/signed from `hs.dir`; `$ = px*magnitude_pct/100` (`:4169`); label `(${s.hot.provenance} · n=${s.hot.n})` (`:4172`). Minor: label shows only the hot cell's provenance/n for both sides (cool n differs, e.g. CPI 1 vs 173) — cosmetic, noted for a later polish |
| C2 | Empty endpoint → no crash | PASS | `:4161` `(_eventScenarios && _eventScenarios.scenarios) || {}` and fetch wrapped in try/catch setting `_eventScenarios = null` (`:3717-3719`) |
| D1 | No new call, no model change, cap 12 | PASS | Scoring merged into the ONE existing Haiku call `_summarize_with_haiku` (`agents/news_cache.py:177-297`, model `claude-haiku-4-5-20251001` `:18` unchanged); cap `kept_posts[:12]` `:447`; HIT path reads cached scores with **no LLM** (`:457-465`); MISS path = the same single `messages.create` `:267-271` |
| D1 | **Analyst summary contract unchanged** | **PASS (verified hard)** | (1) Return shape identical: `news_cache.py:522-528` `{summary, relevant_items, cache_id, from_cache, token_estimate}`. (2) `agents/analyst.py` untouched (`git diff a60af40..HEAD` — not in stat); `analyst.py:119` still reads `news_context["summary"]`. (3) Summary is still the 5-bullet plain string: bullets extracted before the SCORES block `news_cache.py:275-286`; no-scoring path returns raw as before `:284-286` |
| D1 | Whole path fail-soft — score failure cannot break summary or raise into bot | PASS | Prefilter guarded `:443-449`; `parse_scores` returns [] on ANY failure (`news_impact.py:319-375`, outer `except Exception: return []`) and its import+call is itself guarded (`news_cache.py:291-295`); aggregate+snapshot block guarded (`:486-508`); scores-cache read/write guarded (`:117-170`); `write_snapshot` never raises (`news_impact.py:535-550`). Haiku failure falls into the PRE-EXISTING stale-cache fallback (`:475-484`) with `scores=[]` |
| D1 | Scores cached so cache HIT keeps scores | PASS (deviation noted) | Implemented as side-car file `data/news_scores_cache.json` keyed by content_hash (`news_cache.py:23-26,117-170`) instead of the Supabase `news_cache` row (ARCH §2/D2) — avoids a DB schema change; stale-reuse handled via the row's own `content_hash` (`:462-463`). Functionally equivalent; architect should log the amendment |
| D1 | Cost: calls/cycle unchanged, THB/day ≤10% rise, 150-250฿ | PENDING-VERIFY | Structurally 0 new calls (above). `max_tokens` 300→700 when scoring (`news_cache.py:237`) + larger prompt = output/input token growth inside the same call. No runtime yet (code deployed 06:12 today, bot not restarted) — measure via burn card over 1-2 days after restart |
| D1 | `data/news_impact.json` validates §4.1 | PENDING (shape verified in code) | File not yet produced (no scored cycle has run). `write_snapshot` emits exactly the §4.1 keys incl. per-post `reason` + `provenance:"rubric"` (`news_impact.py:480-533`); will re-verify on first live snapshot |
| D2 | `/api/news-impact` mirrors burn; `_empty` per §4.1 | PASS | `dashboard/app.py:1191-1214` — `_empty` matches §4.1 verbatim; FileNotFoundError + generic Exception → `_empty`, never 500 |
| D2 | Card: aggregate+label, n, provenance badge, top posts w/ reason; empty → placeholder | PASS | `index.html:3404-3493` — score/label `:3415-3424`, `provenance · n` `:3430`, per-post `(rubric)` label `:3475,3482`, tier/conf/half-life/reason `:3481-3485`, empty-state "No scored posts yet" `:3455-3457`; section header carries "(rubric — not yet validated)" `:1846` |
| E1 | Guarded MT5 init, standalone, no shutdown of live bot | PASS | `scripts/realized_move_logger.py:64-85` — `terminal_info()` check, no `mt5.shutdown()`, per §D5 |
| E1 | §4.4 shape, atomic append, partial moves, realized_dir/flat rule, idempotent | PASS | Record shape `:335-344` = §4.4 (+informational `move_abs`); atomic save `:282-298`; filled horizon never overwritten `:371-373`; `realized_dir` from 60-min sign, flat < 0.05% `:405-413` (FLAT_THRESHOLD_PCT `:50`) |
| E1 | Store-only, asserts no magnitude, no AI | PASS | grep anthropic/claude/openai over all 3 new scripts → 0 matches; economic anchors carry `pred.magnitude_tier: None` `:257`; script writes only realized_moves.json `:19` |
| E1 | `price_at` per §3.4 — timezone correct, None when bar unavailable | **FAIL → F-06** | Two deviations: (1) `:145-146` clamps `i = len(bars)-1` when target is past the last bar — §3.4 mandates **None → horizon unfilled, retried**; with idempotency `:371-373` a too-early price is then frozen permanently. (2) `:118-119` broker offset = `tick.time − time.time()` from the LIVE tick with **no staleness guard** — when the market is closed (weekend/holiday, exactly when Friday-evening horizons mature) the last tick is hours-to-days old, the offset is garbage, and (1) turns that into a permanently wrong logged price. Also noted: `bisect_right` `:144` skips a bar whose open == target exactly (uses the NEXT bar) — this matches §3.4's own pseudocode but contradicts its "first bar at/after" comment; anchor & horizons shift consistently so the +5/15/60 deltas survive, architect to rule (bisect_left) |
| E1 | Spot-check `price_at` vs known past minute | NOT VERIFIABLE TODAY | Market closed (Sat 23:xx UTC); a live check now would itself hit the F-06 stale-tick condition. Must be re-run on a trading day after F-06 |
| F1 | min-n=30 gate; provenance flips ONLY at n≥30; below → rubric magnitude preserved | **PASS — the core honesty rule holds** | `build_event_scenarios.py:43` `_MIN_N_CALIBRATED = 30`; `apply_m5` `:379-383` flips + replaces magnitude only at n≥30; `:385-390` below threshold keeps the rubric magnitude and provenance, updates n only. Verified against on-disk output: all 6 cells `provenance:"rubric"`, and every `magnitude_pct` equals the event_stats prior exactly (no seed-derived magnitude leaked) |
| F1 | Reproducible from one script | PASS | Sandbox re-run → `REPRODUCIBLE: True` (identical except `updated`) |
| F1 | Consensus seed §4.6, CPI+NFP+FOMC only, real verified rows | **FAIL → F-07** | `data/consensus_seed.json:18-40` contains 3 rows explicitly marked `"_note": "EXAMPLE ROW — verify … before relying"` — i.e. **unverified/guessed values**, violating the file's own rule (`:13` "do NOT guess values"). They do not alter any magnitude (above), but they DO produce the displayed `surprise_curve` entries (n=1, e.g. CPI medium 4.04%) and the n=1 cell counts. Spot-check acceptance ("magnitude direction match reality") cannot be satisfied against unverified rows |
| F1 | n label semantics | NOTE | After the overlay, `n` means "calibration progress count" on seeded cells (CPI hot n=1) but "prior sample count" on untouched cells (CPI cool n=173), both labeled `rubric`. Conservative direction (understates backing), but the card reads ambiguously — architect may want a split field (`n_prior`/`n_calib`) in a future contract rev |
| G1 | Per-tier hit-rate with n; §4.3 shape; atomic; gate n≥30; status calibrated only when EVERY tier ≥30 | PASS | `review_calibration.py:44` MIN_N=30; hit_rate null until n≥30 `:157-160`; `all(...)` gate `:171`; bands = §4.3 `:48-52`; atomic `:59-67`. Current output: all tiers n=0, `status:"collecting"` — the honest state on empty data. Sandbox re-run → `CAL REPRODUCIBLE: True` |
| G1 | `/api/impact-calibration` empty-safe | PASS | `dashboard/app.py:1217-1243` mirrors burn; `_empty` = §4.3 (+`mean_realized_abs_move_pct` — see deviation below) |
| G1 | Badge: `rubric — ยังไม่ validate` while collecting, `calibrated (n=…)` when proven | PASS | `index.html:3529-3531` per-tier `collecting (n=…)` vs `calibrated · n=…`; status badge `:3538-3542` shows `rubric — ยังไม่ validate (collecting)` unless status=="calibrated" |
| ALL | continue.md logging per code edit (CLAUDE.md Override #2, TASKS.md footer) | **FAIL → F-08** | `.claude/context/continue.md` has ZERO entries for this cycle (grep `news-event|news_impact|realized_move|Haiku call|scoring` → only the backlog idea line 30 and old-cycle text). Cycle commits ran 07-04 21:52 → 07-05 06:36; latest continue.md entry is the unrelated Manual Range fix |

## Magnitude-Honesty Verdict (the cycle's core discipline) — **PASS**

- **No number anywhere is presented as "calibrated".** All 6 scenario cells: `provenance:"rubric"`
  (data/event_scenarios.json). Calibration file: `status:"collecting"`, all hit_rate null, n=0.
  Every per-post score: `provenance:"rubric"` (`news_impact.py:519`), aggregate too (`:460`).
- **The n≥30 gate exists in code, not convention:** `build_event_scenarios.py:43,379` and
  `review_calibration.py:44,159,171`. Below the gate the rubric magnitude is *preserved*, not
  replaced (verified numerically against event_stats priors — zero drift).
- **Cards label everything:** provenance+n on the scenario line (`index.html:4172`), on the
  aggregate (`:3430`), per post (`:3482`), and the M6 badge defaults to
  "rubric — ยังไม่ validate (collecting)" (`:3542`). Section header hard-codes "(rubric)" (`:1822,1846`).
- Residual risk: the unverified example seed rows (F-07) put n=1 *curve points* on display.
  They are honestly labeled (n=1) but the underlying data is guessed — remove/verify before
  anyone reads the curve.

## D1-Safety Verdict (highest-risk change) — **PASS**

Contract unchanged and hard-verified: `get_news_context` returns the same 5-key dict
(`news_cache.py:522-528`); `summary` is still the plain 5-bullet string (bullet extraction
`:275-283`; non-scoring path byte-identical behavior `:284-286`); `agents/analyst.py` is not
in the cycle diff and still consumes `news_context["summary"]` at `analyst.py:119`. Every new
code path (prefilter `:443`, parse `:291` + `parse_scores` internal catch-all, scores cache
`:117-170`, snapshot `:486-508`) is try/except-guarded — a score-parse failure yields `scores=[]`
and the summary flows exactly as pre-M3. Haiku-failure fallback path (`:475-484`) is the
pre-existing one, untouched except `scores=[]`.

Two low-severity robustness gaps filed (not contract breaks): F-09 (missing `SUMMARY:` header
→ raw response incl. SCORES JSON becomes the summary — token noise into Sonnet, no crash),
F-10 (cache HIT after scores-cache prune overwrites a populated snapshot with an empty one —
§3.1 wanted the stale snapshot kept).

## Governance Verdict (display-only + no-gate-touch) — **PASS**

- `git diff a60af40..HEAD --stat`: **nothing** under `agents/prompts/`; `agents/analyst.py`,
  `agents/decision_maker.py`, `agents/market_advisor.py`, money management, `_run_gates`,
  confidence thresholds all untouched. agents/ changes = `news_impact.py` (new),
  `news_cache.py` (D1), `trading_graph.py` (+9, the guarded M1 measurement block only),
  plus `pending_manager.py` — which is the **separate, non-pipeline commit 74c44c0**
  (manual-range auto-expire, user-driven, itself touches no gate/decision logic).
- Display-only proven by consumer grep: `news_impact.json` / `event_scenarios.json` /
  `impact_calibration.json` are read ONLY by dashboard/app.py endpoints and the cycle's own
  scripts — no agent, no prompt, no gate reads any score or scenario.
- Per-commit file lists all fall inside each task's whitelist (df8cd6d=A1+B1, c0a9dc5=C1+C2,
  65055e4=D1+D2, 27eba74=E1, 248272d=F1+G1; docs/ files are pipeline-owned).
- D1 approval gate: TASKS.md records "implemented per user instruction" (D2 bundling note),
  but there is no continue.md record of the approval → included in F-08 backfill.

## Cost Verdict — **PASS (structural) / runtime measurement PENDING**

- **0 new AI calls/cycle:** scoring rides the one existing Haiku call; cache HIT path has no
  LLM; the 3 new scripts + 3 endpoints have zero AI imports (grep verified).
- Token creep guards in place: gold-factor prefilter + dedupe before the prompt, hard cap 12
  posts/batch (`news_cache.py:447`), scores cached across HITs.
- Expected growth: `max_tokens` 300→700 on scoring calls + the scored-posts block (~12×140
  chars input). Within design, but the ≤10% THB/day acceptance CANNOT be measured yet — the
  bot has not run this code (snapshot/scores-cache files absent, log rotated). **Measure via
  the burn card 1-2 days after restart; if >10%, cut the cap/window per ARCH §9.**
- Minor cleanup note: prefilter now runs twice per cycle (node_news measurement + inside
  get_news_context) — zero token cost, trivial CPU; retire the node_news copy once M1's
  filter-rate evidence is collected.

## Code-Style Findings (global standards)

- No function fails the one-read test; the new modules are heavily commented with WHY notes.
- No O(n²)+ on unbounded input: filter is one compiled-regex pass; aggregates are single
  loops; `_get_realized_move_from_log` is O(seed×records) on small bounded files.
- No unbenchmarked optimizations claimed. Atomic-write helpers duplicated in 3 files
  (news_impact/builder/review) — acceptable now, candidate for a shared util later.

## Integration Gate

| Check | Result | Evidence |
|---|---|---|
| Build/imports OK | PASS | All new modules import and run (synthetic harness + 2 sandbox script runs) |
| Test suite vs baseline | PASS | Identical 8-failure set, all in files untouched this cycle |
| Frozen contracts §4.1-4.6 | PASS w/ 2 additive deviations | §4.3+endpoint add `mean_realized_abs_move_pct` (informational, mutually consistent); §4.4 adds `move_abs`. No key missing/renamed anywhere; architect to log both |
| Endpoints never-500 | PASS | All 3 catch FileNotFoundError + Exception → `_empty` ok:true (app.py:1175-1243) |
| Scope whitelists | PASS | Per-commit stat matches task whitelists; forbidden files untouched |
| Magnitude honesty | PASS | See verdict above |
| Ground-truth quality (M4) | **BLOCKED on F-06** | price_at last-bar clamp + stale-tick offset can permanently poison realized_moves.json |

**GATE: OPEN for display activation (M0-M3, M6 badge) — user may restart dashboard+bot.**
**GATE: CLOSED for scheduling `realized_move_logger.py` (M4) until F-06 is fixed** — wrong
ground truth here silently corrupts every future calibration, the exact failure mode this
cycle was designed to prevent. F-07 must be resolved before anyone reads the surprise_curve.

## Fix Tasks Filed (docs/TASKS.md)

- **F-06** (HIGH) — price_at: return None past-last-bar (remove clamp) + stale-tick/market-closed guard; architect ruling on bisect_right-vs-left.
- **F-07** (MED) — consensus_seed: remove or user-verify the 3 EXAMPLE rows; rebuild scenarios.
- **F-08** (MED, process) — backfill continue.md for the whole cycle incl. the D1 approval record.
- **F-09** (LOW) — news_cache summary extraction: strip SCORES block even without `SUMMARY:` header.
- **F-10** (LOW) — don't overwrite a populated news_impact.json with an empty aggregate on a scores-cache miss.

## User Action Items

1. **Restart the bot + dashboard** (user-controlled) to activate: M1 filter logging, the D1
   scoring merge, `/api/event-scenario|news-impact|impact-calibration`, and all new cards.
2. **Populate `data/consensus_seed.json` with real verified rows** (CPI+NFP+FOMC actual vs
   consensus) and delete the 3 EXAMPLE rows — nothing calibrates until this is real (F-07).
3. **Do NOT schedule `realized_move_logger.py` yet** — wait for F-06.
4. After restart, **watch the burn card for 1-2 days** — D1 acceptance requires THB/day rise
   ≤10% and total within 150-250฿ (ARCH §9 says cut the cap/window if exceeded).
5. Calibration takes time by design: badges stay "rubric — ยังไม่ validate" until n≥30 per
   cell/tier accumulates in realized_moves.json. That is correct behavior, not a bug.

---
---

# AUDIT — Cycle #12 · Regime Auto-Enrichment & Shift Detector (H1/H2/I1/I2/J1)

> Written by: auditor · Run: 2026-07-08 13:54–14:00 (+0700)
> Design of record: ARCHITECTURE.md "Cycle #12" (C12-§2/§3/§4 FROZEN). Code = working-tree
> diff vs HEAD bfec5c7 (uncommitted). Test command: `& $PY tests\test_all.py`.
> Audit method: static diff review + isolated function harness (AV fetch STUBBED — no quota
> spent; state writes redirected to scratchpad; 34/35 checks) + one real `--dry-run`
> (writes nothing, 3 AV series calls) + live `GET /api/regime-state` on the running dashboard.

## Test suite vs baseline

**PASS — zero new failures.** Suite: 29 tests → **2 FAIL + 6 ERROR, the exact known
pre-existing set** (2× `TestStreakGate` quiet-session assertion — run at 13:54+0700 = 06:54
UTC, inside the 0–7 UTC Asian gate; 6× `TestMomentumFastPath` ERROR, TypeError
`agents/decision_maker.py:607` `7 <= _utc_hour` vs MagicMock). `git diff` touches NO file
under `agents/` or `tests/` → failure set cannot be attributed to this cycle.

## Per-Item Results

| Task | Criterion | Verdict | Evidence (file:line / run output) |
|------|-----------|---------|-----------------------------------|
| H1 | CATALYSTS line: frozen grammar, ≤2 nearest matched High-impact USD events, dirs verbatim from event_scenarios.json | PASS | `scripts/update_regime.py:163-228`; harness C1/C6: `- CATALYSTS (auto 2026-07-08): CPI 07-09 (hot->down / cool->up); NFP 07-10 (hot->down / cool->up)` matches frozen regex; same-key dedupe, non-USD/Medium/past events excluded (C4/C5). Real `--dry-run`: `- CATALYSTS (auto 2026-07-08): FOMC 07-08 (hot->down / cool->up)`, dirs match `data/event_scenarios.json` FOMC cell |
| H1 | CATALYSTS fail-soft: FF error / scenarios missing / no match ⇒ line omitted, exit 0 | PASS | harness C2/C3/C4 all return `None`; each path guarded `update_regime.py:167-181`; dry-run exit 0 |
| H1 | Sentiment line TAG-ONLY — NO directional verb | PASS (code) | `update_regime.py:311-316` prints only `{tag} — AV & news_impact agree (AV %+.2f, ni %+d)`; harness S1 regex + forbidden-word scan (`bullish|bearish|up|down|buy|sell|long|short`) → no hit. Tag vocabulary exactly {`risk-bid geopolitics`,`macro tone`} (`:309-310`); internal direction never printed (`:305` comment + code) |
| H1 | Agreement gate: emit iff av_dir == ni_dir ∈ {bullish,bearish}, else omit | PASS | `:253-303`; harness S1 (agree→emit), S3 (disagree→omit), S4 (AV neutral→omit), S5 (ni neutral→omit **before** the AV call — quota saved), S8 (gold proxy absent→omit, no `overall_sentiment_score` fallback per C12-§4.4), thresholds ±0.15 AV / ±10 ni per contract |
| H1 | Kill-switch `REGIME_SENTIMENT_ENABLED=0` ⇒ no AV call, no line | PASS | `:244-245`; harness S11: env=0 → `(neutral, None)`, stubbed AV fetch invoked 0 times |
| H1 | Fail-soft: AV quota/network/Information, missing/malformed news_impact.json ⇒ line omitted, never crash | PASS | `_av_fetch_fail_soft` `:150-160` returns None on any error (never sys.exit); `:283-284` handles `Information`/`Note`; harness S6/S7/S9/S10 all omit cleanly |
| H1 | **Sentiment line actually emits when sources agree — on THIS machine** | **FAIL → F-11** | `update_regime.py:249` `open(NEWS_IMPACT_PATH)` without `encoding="utf-8"`. Windows locale = cp874; `data/news_impact.json` is UTF-8 with non-ASCII (written `ensure_ascii=False`, `agents/news_impact.py:551-552`) → `UnicodeDecodeError` (byte 0x9c) swallowed by `except Exception` → returns `(neutral, None)`. Harness S12 probe with the REAL production file (aggregate.score=+69 bullish, stub AV agreeing): line silently omitted. The sentiment feature is functionally dead on the production machine, and `sentiment_tilt` is pinned `neutral` (also disables H2 `sentiment_tilt_flip`). Same latent hole at `:177` (event_scenarios — ASCII today by luck) and `:352` (regime_state — ASCII, safe today). Worker's continue.md note "AV rate-limited → line omitted (fail-soft verified)" misdiagnosed this: the omission fires BEFORE the AV call |
| H1 | Block order frozen: DATA → inflation → WATCH → CATALYSTS → sentiment, inside markers only | PASS | `build_block()` `:495-505` appends in exactly that order; markers via existing `re.sub` unchanged; dry-run output shows correct order |
| H1 | `agents/prompts/macro_regime.md` not corrupted | PASS | File intact: markers at `macro_regime.md:17,21`, DATA line `:18` (still auto 2026-06-27 — no live run yet), human narrative above (`:15`) and below (`:22-34`) untouched; file absent from `git diff` |
| H1 | Token budget: two lines ≲40 input tokens | PARTIAL (estimate over) | Frozen-grammar worst case = 97+95 = 192 chars ≈ **55–70 tokens both-lines** (> the ≈30–40 frozen estimate; worker's ≈33 estimate optimistic). Single-line typical (CATALYSTS only, today's reality) ≈ 30–35 ✓. Cost ceiling ≈ 2 THB/day at 288 cycles — immaterial vs 150–250฿ budget, but the before/after `get_accounting` measurement (acceptance #3) is still PENDING live cycles. Grammar itself is frozen, so this is a doc-estimate gap, not an implementation deviation |
| H1 | Shadow R1 test (analyst bias WITH vs WITHOUT lines) | **NOT VERIFIABLE STATICALLY** | Requires the live Sonnet analyst on a captured cycle. Not run — see R1 verdict below |
| H1 | Live AV gold-proxy tag (GLD) confirmation | PENDING (blocked by F-11) | The dry-run never reached the AV NEWS_SENTIMENT call (encoding failure aborts earlier). Must re-verify after F-11 on a budget-available day (C12-§2 warning stands) |
| H2 | `regime_state.json` exact C12-§3 schema, atomic write | PASS | `update_regime.py:323-429`; harness H2a: key set == {ok,updated,fed_dir,real_rate_sign,sentiment_tilt,cpi_yoy,fed_funds,real_rate,shift,history}; atomic tmp+`Path.replace` (=os.replace) `:419-421` |
| H2 | Seed: no prior ⇒ active=false, kind=[], from=null | PASS | harness H2a on empty dir |
| H2 | Flip fires once, unchanged re-run clears (no chatter) | PASS | harness H2b (fed_dir flip → active, kind=["fed_dir_flip"], correct from/to, history+1) + H2c (re-run → active=false, history kept) |
| H2 | Real-rate dead-band ±0.1 carries prior sign | PASS | `:337-341,357-362`; harness H2d: real_rate −0.6→+0.05 ⇒ sign stays "negative", no flip; H2e: →+0.5 ⇒ `real_rate_sign_flip` fires |
| H2 | Sentiment debounce: flip only when NEW tilt non-neutral | PASS | `:371-373`; harness H2f (neutral→bullish counts) + H2g (bullish→neutral does NOT) |
| H2 | history[] cap 10 | PASS | `:393`; harness H2h: 12 flips → len 10 |
| H2 | Fail-soft: bad input ⇒ warn, prior file byte-identical | PASS | whole body in try/except `:331-429`; harness H2i |
| H2 | dry-run writes nothing | PASS | `main()` `:534-536` returns before both writes; dry-run printed "regime_state.json NOT written"; `data/regime_state.json` does not exist (Test-Path False) |
| I1 | `/api/regime-state` mirrors `/api/burn`, `_empty` per C12-§3, never 500 | PASS | `dashboard/app.py:1265-1289` — identical structure to `api_burn` `:1165-1174` (try open+jsonify / except FileNotFoundError / except Exception → `_empty`); `_empty` field-for-field == C12-§3 frozen shape. **Live check:** `GET http://localhost:5050/api/regime-state` with file absent → HTTP 200, exact `_empty`, `ok:true` |
| I2 | Pill on shift.active (kind+since+hint); muted stable line; empty payload ⇒ render nothing | PASS (code) | `index.html:1252` (bar, initial display:none), `:3805-3861` `loadRegimeState()`: `!ok || !updated` → hide; active → `⚠ REGIME SHIFT — {kind}` + `since` + youtube-to-knowhow hint; else `regime stable · Fed {fed_dir} · real-rate {sign} · tilt {tilt}`; catch → hide. Wired in `_bootstrap` `:4896` + hourly poll `:4908` mirroring loadBurn. Worker's Flask-test-client + Jinja-parse evidence in continue.md; active-pill visual not re-driven live (file doesn't exist yet — empty path IS today's real path, verified live above) |
| J1 | Scheduler weekly → daily | PASS (code) / PENDING (ops) + **F-13 process** | `setup_vm_regime.ps1:54` `New-ScheduledTaskTrigger -Daily -At $Time` (was `-Weekly -DaysOfWeek Monday`); dry-run still succeeds ✓. BUT: TASKS.md J1 still `[ ]` and continue.md has no J1 entry — code landed without status/log (override #2). Actual re-registration on the VM = user ops step, not yet done |

## Scope / iron-rules check

| Check | Result | Evidence |
|---|---|---|
| Only whitelisted files changed | PASS (with 2 noted non-cycle items) | `git diff --stat`: code changes ONLY in the 4 whitelisted files + docs. Noted: (1) `index.html:4370-4386` SL/TP-shown-as-price + label edit in `renderVerdict` — separate user-driven display edit, logged in continue.md "2026-07-08 (m)", NOT part of cycle #12, display-only, no task entry (pre-existing pipeline-process gap, not a cycle #12 violation); (2) `data/*.json` modifications + untracked `news_gate.json`/`news_scores_cache.json` = runtime artifacts of already-committed producers (`scripts/report_news_gate.py:27`, `agents/news_cache.py:25`), not worker edits |
| No touch: `agents/prompts/*.json`, `_run_gates`, decision_maker, money mgmt, SL/TP, confidence thresholds, analyst.py | PASS | `git diff` contains zero files under `agents/`; `macro_regime.md` (the only prompts-adjacent surface) unchanged on disk |
| Workers stayed inside task scopes H1/H2/I1/I2/J1 | PASS | Diff hunks map 1:1 to the four whitelisted files; update_regime.py edits are `build_block` + new helpers + `main()` tail, exactly per task scope |
| continue.md logging (override #2) | PASS for H1/H2/I1/I2; **gap for J1** (→ F-13) | Entries "2026-07-08 (n)" and "2026-07-08 H3" cover H1/H2/I1/I2 with tests; no J1 entry |

## Code-style (global CLAUDE.md auditor additions)

- `_sentiment_line_and_tilt` (~90 lines) and `_write_regime_state` (~105 lines) exceed the
  ~40-line guideline but are linear, single-purpose, and readable in one pass — noted, no fix
  task. No optimization without WHY; no O(n²) on unbounded input (geo scan is ≤posts×7 keywords,
  posts bounded by the snapshot cap).

## R1 verdict — should REGIME_SENTIMENT_ENABLED default to ON?

**What was verified statically:** tag-only grammar enforced by construction (no directional
token can reach the formatted string — harness forbidden-word scan PASS); emission double-gated
(cross-source agreement AND both non-neutral); lowest-authority last line; kill-switch works
(S11); every failure path degrades to "line absent" (S3–S10) — i.e., the worst static outcome
is the pre-cycle status quo.

**What CANNOT be verified here:** how the live Sonnet analyst's `sentiment/bias/confidence`
actually responds to the added lines (the C12-§6 R1 shadow test needs a captured cycle replayed
through the live analyst) — and that test has NOT been run by anyone. The token before/after
measurement is equally pending.

**Recommendation: default OFF until shadowed.** Two reasons beyond the un-run shadow test:
(1) F-11 means the sentiment line has never once been exercised end-to-end — enabling by
default ships a zero-live-evidence feature into the analyst's authoritative block the moment
F-11 is fixed; (2) `news_impact` scoring is known-overconfident from this project's own
calibration (R6). Cheapest safe path: user sets `REGIME_SENTIMENT_ENABLED=0` on the VM today
(zero code change), OR architect flips the code default at `update_regime.py:244` to "0"
(one-line, needs user approval since it inverts a frozen env semantic). Flip to ON only after
F-11 is fixed AND one R1 shadow comparison on a regime day shows no spurious bias flip.
The CATALYSTS line (factual dates + frozen sign-table dirs) may stay on as shipped.

## Integration Gate — Cycle #12

| Check | Result | Evidence |
|---|---|---|
| Build / imports | PASS | update_regime imports + full dry-run exit 0; dashboard serving new endpoint live |
| Test suite vs baseline | PASS | Identical 2F+6E pre-existing set; no `agents/`/`tests/` files in diff |
| Frozen contracts C12-§2/§3/§4 | PASS | Line grammar, agreement rule, tag vocabulary, env names, regime_state schema, endpoint `_empty` all match (table above) |
| Endpoint never-500 / empty-shape | PASS | Live HTTP 200 `_empty` with file absent |
| Scope whitelist | PASS | See scope table |
| Sentiment feature live-functional | **FAIL (F-11)** | cp874 decode kills the line before the AV call on the production machine |

**GATE: OPEN for J1 ops (register the daily task) and for continued dashboard use** — the
shipped CATALYSTS/H2/I1/I2 paths are contract-clean and fail-soft, and the next real
`update_regime.py` run cannot harm `macro_regime.md` (worst case: auto lines absent).
**GATE: CLOSED for relying on the sentiment line / sentiment_tilt shift detection until F-11
is fixed**, and **the R1 shadow test remains a precondition for trusting the enriched block on
a regime day** (recommend sentiment default-off until then, above).

## Fix Tasks Filed (docs/TASKS.md — Cycle #12)

- **F-11** (MED, functional) — add `encoding="utf-8"` to the three `open()` reads in
  `update_regime.py` (`:177`, `:249`, `:352`); sentiment line is silently dead on cp874 Windows.
- **F-12** (decision, R1) — default `REGIME_SENTIMENT_ENABLED` to OFF until F-11 + live shadow
  bias test pass; user decision required.
- **F-13** (LOW, process) — J1 code landed with TASKS.md still `[ ]` and no continue.md entry;
  reconcile status + log; user re-runs `setup_vm_regime.ps1` on the VM to actually register daily.

## User Action Items (Cycle #12)

1. Decide F-12 now (cheapest: set `REGIME_SENTIMENT_ENABLED=0` in the VM env until shadowed).
2. After F-11 is fixed: run `update_regime.py` on a budget-available day to confirm the live AV
   GLD proxy tag (C12-§2 warning) and produce the first real `regime_state.json`.
3. Re-run `scripts/setup_vm_regime.ps1` on the VM to register the DAILY schedule (J1 ops half).
4. After the first enriched live run: measure analyst tokens before/after via `get_accounting`
   (H1 acceptance #3) and run the R1 shadow comparison on the next CPI/NFP/FOMC day.
