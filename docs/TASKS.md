# TASKS — News & Event Impact Analysis

> Written by: architect · Status updates by: workers/auditor
> Design of record: `docs/ARCHITECTURE.md` (all §refs point there). Contracts in §4 are FROZEN.
> Supersedes the previous "Stabilize & Complete" TASKS (closed; git history).
> ⚠️ **Approval gate:** M0/M1/M2 add ZERO AI cost and may start once the design is approved.
> **M3 must NOT start until the user approves D1** (editing the live Haiku prompt in
> `news_cache.py`) — see ARCHITECTURE §7. Workers: update this file + `.claude/context/continue.md`.

## Batch / dependency structure (cheap-first, per PLAN milestones)

```
Batch A (M0)  delta-$ quick win .............. no deps .......... [index.html]
Batch B (M1)  Feature A code-only filter ..... no deps .......... [agents/news_impact.py, trading_graph.py]
Batch C (M2)  Feature B sign scenario ........ deps: A ........... [sign_table, build_event_scenarios, app.py, index.html]
Batch D (M3)  Feature A batch scoring + card .. deps: B (+APPROVAL) [news_cache.py, news_impact.py, app.py, index.html]
Batch E (M4)  Realized-move logger ........... deps: D (post feed) [realized_move_logger.py]
Batch F (M5)  Surprise-magnitude stats ....... deps: C, E ........ [consensus_seed, build_event_scenarios]
Batch G (M6)  Calibration review ............. deps: D, E ........ [review_calibration, app.py, index.html]
```

Sequential where a file is shared to avoid parallel-write conflicts:
**`index.html`** is touched by A, C, D, G and **`dashboard/app.py`** by C, D, G — these batches
run in order, each with ONE owner of the shared file. Within a batch, tasks touching the same
file are bundled into a single task. **A and B are the only pair that can run in parallel**
(disjoint files); everything else is gated by the deps above.

No task genuinely spans 3+ *independent parallel* modules — these are sequential pipelines, not
fan-out — so the sub-agent delegation format is not used. Each task = one worker.

---

## Batch A — M0: delta $ on Event Radar (quick win)  · deps: none

### A1 [DONE] — Add +$/−$ delta line to the event card
- **agent:** worker (single)
- **scope (whitelist):** `dashboard/templates/index.html` (function `renderEventCard`, lines ~3900–3953 only)
- **input contract:** in `renderEventCard`, current price `px = bs.price_info.bid` is in scope;
  matched event stats `s` already provide `avg_up_pct` / `avg_down_pct` / `avg_abs_d0_pct`; each
  event row has `ev.forecast` / `ev.previous` / `ev.actual`.
- **output contract:** render an explicit dollar delta next to the existing % targets, e.g.
  `▲ +$X.X  ▼ −$Y.Y` where `X = px*avg_up_pct/100`, `Y = px*|avg_down_pct|/100`. Display-only,
  no new fetch, no new endpoint. Label stays consistent with the existing prior (source = prior).
- **acceptance:** open dashboard on a day with a matched event (NFP/CPI/FOMC) → delta $ shown and
  arithmetically consistent with the % it is derived from (spot-check `px*pct/100`). No console
  error; days with no matched event render unchanged.

---

## Batch B — M1: Feature A code-only filter (free)  · deps: none (parallel with A)

### B1 [DONE] — `agents/news_impact.py` code-only core + wire measurement into node_news
- **agent:** worker (single)
- **scope (whitelist):** `agents/news_impact.py` (NEW), `agents/trading_graph.py` (`node_news` `:130` only)
- **input contract:** `news_data` dict from `news_gatherer.gather_news()` =
  `{tweets:[{id,text,user,created_at}], calendar:[...], web_articles:[{title,summary,...}]}`.
- **output contract:** implement pure functions (ARCHITECTURE §1, §3.1):
  - `normalize_posts(news_data) -> list[dict]` → unified `{id, source, text, author, ts_utc}`
    (tweets + web_articles; calendar excluded — that's Feature B).
  - `is_gold_relevant(text) -> bool` → keyword filter for Fed / CPI / yields / DXY / war / tariff /
    Trump (case-insensitive, word-boundary). Keep the keyword set as a module constant.
  - `content_hash(text) -> str` → 8-char stable hash (dedupe key).
  - `prefilter_and_dedupe(posts) -> (kept:list, stats:dict)` where
    `stats = {"raw":int,"kept":int,"filter_rate_pct":float}`.
  - In `trading_graph.node_news`: after `gather_news`, call `prefilter_and_dedupe` and
    `log.info("[news_impact] filter %s", stats)`. **Wrap in try/except — must never raise into the
    pipeline** (return/skip on error). No card, no LLM, no behavior change to gate/analyst.
- **acceptance:** run bot (or a unit harness feeding a captured `news_data`) → log shows filter
  rate; on a 1–2 day spot-check ≥70% of raw posts dropped AND no gold-factor headline wrongly
  dropped (manual review of the `kept` list). Token cost unchanged (no LLM added). `tests/test_all.py`
  baseline unaffected.

---

## Batch C — M2: Feature B sign-based scenario  · deps: A (shares index.html)

### C1 [DONE] — Frozen sign table + scenario builder (rubric) + endpoint
- **agent:** worker (single)
- **scope (whitelist):** `data/event_sign_table.json` (NEW, frozen seed), `scripts/build_event_scenarios.py`
  (NEW), `data/event_scenarios.json` (NEW, generated), `dashboard/app.py` (add `/api/event-scenario` only)
- **input contract:** sign table = ARCHITECTURE §4.5 exact JSON (PLAN Q1, FROZEN — do not edit values).
  `scripts/build_event_scenarios.py` reads `data/event_sign_table.json` + `data/event_stats.json`
  (per-event `avg_up_pct`, `avg_down_pct`, `n`, `window`).
- **output contract:**
  - Builder writes `data/event_scenarios.json` in the **exact** §4.2 shape. M2 = rubric only:
    `provenance:"rubric"`, magnitude from the two-sided prior, `surprise_curve:null`, per-cell `n`
    from `event_stats`. Direction from the sign table (hot→sign, cool→opposite; UNEMPLOYMENT/FOMC
    per §4.5). Atomic write (`tmp`+`os.replace`, §D8).
  - `/api/event-scenario` mirrors `/api/burn` EXACTLY (module `_empty` per §4.2; never 500).
- **acceptance:** run builder → `data/event_scenarios.json` validates against §4.2 for CPI/NFP/FOMC;
  `GET /api/event-scenario` returns it; delete the file → endpoint returns `_empty` with `ok:true`
  (no 500). Directions match the frozen sign table.

### C2 [DONE] — Conditional scenario line on the event card (finished by orchestrator หลัง worker C2 ชน session limit กลางคัน)
- **agent:** worker (single) — **runs after C1** (needs the endpoint; shares no file with C1's app.py)
- **scope (whitelist):** `dashboard/templates/index.html` (`renderEventCard` + a fetch of
  `/api/event-scenario` into a global, mirroring how `_eventStats` is loaded)
- **input contract:** `/api/event-scenario` (§4.2); live event `ev.forecast` (consensus) from
  `/api/calendar`; `px = bs.price_info.bid`.
- **output contract:** for a matched event WITH a scenario entry, render one conditional line:
  `hot > forecast → gold {dir} ~{magnitude as $ from px}` | `cool < forecast → gold {dir} ~$…`,
  suffixed with a provenance+n label (e.g. `(rubric · n=173)`). **Fallback:** event with no
  `forecast`/`—` or no scenario entry → render the existing prior card unchanged (§3.2).
- **acceptance:** on an event day the card shows two correctly-signed scenarios + `(rubric · n=…)`;
  an event lacking consensus falls back to the old card; no console error; empty endpoint → no crash.

---

## Batch D — M3: Feature A batch scoring + News Impact card  · deps: B · ⚠️ REQUIRES USER APPROVAL of D1

### D1 — Merge per-post scoring into the Haiku call + cache scores
- **agent:** worker (single) — **[DONE] implemented 2026-07-05**
- **scope (whitelist):** `agents/news_cache.py` (`_summarize_with_haiku` `:108`, `get_news_context`
  `:274`, cache store/read only), `agents/news_impact.py` (add `parse_scores`, `rolling_aggregate`,
  `write_snapshot`)
- **input contract:** the `kept` posts from B1's `prefilter_and_dedupe`; the existing Haiku prompt
  assembly in `_summarize_with_haiku` (already builds `tweet_block` from `tweets[:10]`); Supabase
  `news_cache` row (currently stores `summary`).
- **output contract:**
  - Extend the SAME Haiku call to also return a per-post JSON score array
    `{post_id, direction, confidence, magnitude_tier(1-3), half_life_min, reason}` (§4.1). **No new
    call, no model change** (stays `claude-haiku-4-5`). Cap posts/batch at **12** after
    prefilter+dedupe.
  - Store `{summary, scores}` in the `news_cache` row; on cache HIT read scores back (no LLM).
  - `news_impact.rolling_aggregate(scores, now)` → aggregate with magnitude×freshness (half-life)
    decay (§4.1 `aggregate`). `write_snapshot()` → `data/news_impact.json` (§4.1 exact shape, atomic).
    All new numbers `provenance:"rubric"`.
  - Whole path fail-soft: any error → bot proceeds, stale snapshot kept, no raise.
- **acceptance:** (1) **cost:** AI calls/cycle unchanged vs baseline (`get_accounting`); THB/day
  rises ≤10% and total stays 150–250 ฿/day after a representative run. (2) cache HIT path does NOT
  invoke Haiku yet still refreshes the snapshot. (3) `data/news_impact.json` validates against §4.1
  with per-post `reason` + `provenance:"rubric"`.

### D2 — `/api/news-impact` endpoint + News Impact card
- **agent:** worker (single) — **[DONE] implemented 2026-07-05 (bundled with D1 per user instruction)**
- **scope (whitelist):** `dashboard/app.py` (add `/api/news-impact` only), `dashboard/templates/index.html`
  (new News Impact card, mirroring `loadBurn()` fetch→render)
- **input contract:** `data/news_impact.json` (§4.1).
- **output contract:** `/api/news-impact` mirrors `/api/burn` exactly (`_empty` per §4.1). Card shows
  aggregate score+label, `n`, provenance badge, and top posts (author, snippet, direction,
  confidence, tier, reason). Empty/missing file → card shows a "no data" placeholder, no crash.
- **acceptance:** card renders live snapshot; delete file → placeholder + `ok:true`, no 500; every
  magnitude on the card carries a `rubric` label and an `n`.

---

## Batch E — M4: Realized-move logger  · deps: D (high-tier post feed); economic-event side is independent

### E1 [DONE — ⚠️ AUDIT 2026-07-05: F-06 must be fixed BEFORE this script is scheduled] — `scripts/realized_move_logger.py` (+ `price_at` helper)
- **agent:** worker (single)
- **scope (whitelist):** `scripts/realized_move_logger.py` (NEW), `data/realized_moves.json` (NEW, generated)
- **input contract:** high-tier posts (`magnitude_tier ≥ 2`) from `data/news_impact.json`; released
  economic events (`actual != "pending"`) from the calendar; `connectors.price_feed.get_current_price`;
  MT5 via guarded init `if mt5.terminal_info() is None: mt5.initialize(...)` (§D5).
- **output contract:** implement `price_at(ts_utc) -> float|None` per §3.4 (broker-time offset via
  live `symbol_info_tick().time` vs `utcnow`; `copy_rates_range` M1 + `bisect_right`). For each anchor,
  fill horizons +5/+15/+60 min as they mature; atomic append to `data/realized_moves.json` in the
  **exact** §4.4 shape (partial `moves` allowed; `realized_dir` from 60-min sign, flat if |move|<0.05%).
  Idempotent: re-runs must not duplicate a filled horizon. Store-only — the script asserts NO magnitude.
- **acceptance:** after one high-impact event/post cycle, `data/realized_moves.json` has a record with
  all three horizons filled and correct `move_pct` sign; a manual `price_at` spot-check against a known
  past minute matches MT5 (timezone correct); running the bot is unaffected (separate MT5 process).

---

## Batch F — M5: Feature B surprise-magnitude from real data  · deps: C, E

### F1 [DONE — ⚠️ AUDIT 2026-07-05: seed rows are unverified EXAMPLEs → F-07] — Consensus seed + calibrated scenario magnitudes
- **agent:** worker (single)
- **scope (whitelist):** `data/consensus_seed.json` (NEW, hand-maintained), `scripts/build_event_scenarios.py`
  (extend — same file as C1), `data/event_scenarios.json` (regenerated)
- **input contract:** `data/consensus_seed.json` (§4.6, CPI+NFP+FOMC only — PLAN Q2); historical moves
  from `data/xau_daily.json` (daily) and forward realized moves from `data/realized_moves.json`; window
  = 2012-01-01→present (§8).
- **output contract:** extend the builder to compute the conditional split (hot/cool/inline) and
  `|surprise| → |move|` curve per event → populate `surprise_curve` and replace `magnitude_pct` per cell.
  **Flip `provenance` to `"calibrated"` ONLY where that cell's `n ≥ 30`; otherwise keep `"rubric"`**
  (min-n fallback, §8). Same §4.2 shape (no contract change). Reproducible from the one script.
- **acceptance:** re-running the script reproduces `data/event_scenarios.json`; cells with n≥30 show
  `calibrated` + surprise-curve, cells below show `rubric`; spot-check one real event (e.g. a recent
  NFP miss) — sign + magnitude direction match reality; card (C2) now renders the calibrated numbers.

---

## Batch G — M6: Calibration review  · deps: D, E

### G1 [DONE] — `scripts/review_calibration.py` + endpoint + card badge
- **agent:** worker (single)
- **scope (whitelist):** `scripts/review_calibration.py` (NEW), `data/impact_calibration.json` (NEW,
  generated), `dashboard/app.py` (add `/api/impact-calibration` only), `dashboard/templates/index.html`
  (calibrated/not badge on News Impact + Event cards)
- **input contract:** `data/realized_moves.json` (§4.4) with `pred.magnitude_tier` + realized `moves`.
- **output contract:** compute per-tier hit-rate (realized |move| landed in the tier's assumed band)
  with `n`; write `data/impact_calibration.json` (§4.3, atomic). `/api/impact-calibration` mirrors
  `/api/burn`. Cards read it → badge `rubric — ยังไม่ validate` when `status:"collecting"`, else
  `calibrated (n=…)`. Gate: `status:"calibrated"` only when every tier n≥30.
- **acceptance:** with realized data present, report shows hit-rate per tier + n; below n=30 the badge
  stays "rubric — ยังไม่ validate"; endpoint empty-safe (delete file → `_empty`, no 500); numbers
  reproduce from the one script.

---

## Fix tasks — filed by auditor 2026-07-05 (see docs/AUDIT.md for full evidence)

### F-06 [DONE 2026-07-05] — price_at can permanently log a wrong price (HIGH — blocks scheduling the M4 logger)
- **agent:** worker (single) · **scope (whitelist):** `scripts/realized_move_logger.py` only
- **root cause (two independent holes, same symptom):**
  1. `price_at` (`realized_move_logger.py:145-146`) clamps `i = len(bars)-1` when the target
     is past the last available bar, returning an EARLIER bar's price instead of `None`.
     ARCHITECTURE §3.4 mandates `None → horizon stays unfilled, retried next run`. Because
     `resolve_pending` is idempotent (`:371-373` never overwrites a filled horizon), the
     too-early price is frozen into `data/realized_moves.json` forever.
  2. The broker-time offset (`:118-119`, `tick.time − time.time()`) is computed from the
     live tick with NO staleness guard. When the market is closed (weekend/holiday — exactly
     when Friday-evening +60m horizons mature) the last tick is hours-to-days old, the offset
     is off by that amount, `copy_rates_range` queries the wrong window, and hole 1 converts
     that into a silently wrong permanent record.
- **fix contract:** (a) delete the clamp — if `bisect` lands past the last bar, return `None`;
  (b) skip the entire run (or at least all `price_at` calls) when the tick is stale, e.g.
  `abs(time.time() − tick.time − cached_offset)` heuristic or simply
  `tick.time` older than N minutes vs a *previously persisted* offset — simplest honest rule:
  if `now_utc − tick_time_utc_estimate > 5 min`, log "market closed — deferring" and return.
  (c) escalate to architect: §3.4's pseudocode uses `bisect_right` but its comment says
  "first bar at/after target" — `bisect_left` matches the comment (bar opening exactly at the
  anchor second is currently skipped). Do not change without an architect ruling since §3.4 is frozen.
- **acceptance:** on a trading day, `price_at` spot-check vs a known MT5 minute matches;
  a run while the market is closed fills NOTHING (no record gains a price); re-run after
  reopen fills the deferred horizons correctly; no existing filled horizon changes.

### F-07 [DONE 2026-07-05] — consensus_seed.json contains guessed EXAMPLE rows feeding the displayed surprise_curve (MED)
- **agent:** user + worker · **scope:** `data/consensus_seed.json`, then re-run `scripts/build_event_scenarios.py`
- **root cause:** the F1 worker planted 3 rows marked `"_note": "EXAMPLE ROW — verify"` with
  guessed values, violating the file's own rule (`consensus_seed.json` notes: "do NOT guess
  values. A wrong row is worse than no row"). Magnitudes are NOT affected (audit verified all
  cells kept the rubric prior), but the rows produce the on-card `surprise_curve` points
  (n=1, e.g. CPI medium 4.04%) and the misleading n=1 cell counts.
- **fix contract:** user verifies each row against the real June 2026 releases (or empties
  `records` to `[]`); worker re-runs the builder; card then shows `surprise_curve: null`
  (or verified points) — no other change.
- **acceptance:** every record in `consensus_seed.json` is user-verified (no `_note` EXAMPLE
  markers remain); `data/event_scenarios.json` regenerated and reproducible.

### F-08 [DONE 2026-07-05] — continue.md has zero entries for the entire M0-M6 cycle (MED — process, CLAUDE.md Override #2)
- **agent:** worker (single) · **scope:** `.claude/context/continue.md` only
- **root cause:** all five implementation commits (df8cd6d, c0a9dc5, 65055e4, 27eba74,
  248272d — 2026-07-04 21:52 → 2026-07-05 06:36) skipped the mandatory continue.md log; the
  D1 (live Haiku prompt) approval also has no written record.
- **fix contract:** backfill one dated entry per batch in the prescribed format (files
  changed, what changed, issues), and record when/how the user approved D1 + the D2 bundling
  instruction.
- **acceptance:** continue.md contains entries covering every cycle commit + the D1 approval note.

### F-09 [DONE 2026-07-05] — Haiku response without `SUMMARY:` header leaks the SCORES JSON into the analyst summary (LOW)
- **agent:** worker (single) · **scope:** `agents/news_cache.py` (`_summarize_with_haiku` extraction only)
- **root cause:** `news_cache.py:275` requires BOTH `have_scored` AND `"SUMMARY:" in raw` to
  strip the scores block; if Haiku emits bullets without the header (format drift), the whole
  raw response — including the ```json scores array — becomes `summary` and flows into the
  Sonnet analyst prompt (token noise; no crash, shape unchanged).
- **fix contract:** split on `"SCORES:"` whenever it is present in `raw`, independent of the
  `SUMMARY:` header; keep all other behavior identical.
- **acceptance:** unit check — raw with SCORES but no SUMMARY header yields a summary that
  contains no `SCORES:`/JSON text; existing paths byte-identical.

### F-10 [DONE 2026-07-05] — cache HIT with a pruned scores-cache overwrites a populated snapshot with an empty one (LOW)
- **agent:** worker (single) · **scope:** `agents/news_cache.py` (snapshot block `:486-508`) or `agents/news_impact.py write_snapshot`
- **root cause:** on a cache HIT whose scores-cache entry has been pruned (>2 h) or lost
  (restart), `scores=[]` → `rolling_aggregate` returns the empty aggregate and
  `write_snapshot` replaces a previously populated `data/news_impact.json` with a neutral,
  post-less one. ARCHITECTURE §3.1 says on a no-data path the stale snapshot should remain.
- **fix contract:** skip `write_snapshot` when `scores` is empty AND the existing snapshot
  file has `posts` (preserve stale display); still write when there is genuinely nothing yet.
- **acceptance:** simulate HIT-with-no-scores after a populated snapshot → file unchanged;
  MISS path still refreshes normally.

---

## Cross-batch integration gate (auditor)

- After every batch: `& $PY tests\test_all.py` compared to a **baseline** run (some tests are
  time-of-day dependent — see CLAUDE.md; use the `git stash` baseline trick before blaming a change).
- **After D (M3):** verify AI-calls/cycle unchanged and THB/day ≤10% over baseline via
  `db.reader.get_accounting` / `scripts/report_burn.py` — this is the hard cost gate.
- **All new `/api/*`:** confirm empty-shape on missing file returns `ok:true` (never 500).
- **No diff** may touch `agents/prompts/*.json`, `_run_gates`, money management, or confidence
  thresholds. Any worker hitting such a need marks the task **[BLOCKED]** and escalates (do not diverge).
- Every code edit / bug / fix also logged in `.claude/context/continue.md` (CLAUDE.md override #2).

---
---

# TASKS — Cycle #12 · Regime Auto-Enrichment & Shift Detector

> Written by: architect · 2026-07-08 · Design of record: `docs/ARCHITECTURE.md` §"Cycle #12"
> (C12-§). Contracts in **C12-§4 are FROZEN**.
> ⚠️ **APPROVAL GATE — implementation waits for user approval.** Every task below is `[ ]` NOT
> STARTED. **No worker may begin until the user approves the Cycle #12 architecture** (explain-
> before-acting, live-money iron rule). In particular **Batch H1 edits the regime context the
> Sonnet analyst reads every cycle** (can tilt bias, R1) — same approval class as #10/#11's D1.
> Workers update this file + `.claude/context/continue.md` per CLAUDE.md override #2.

## Batch / dependency structure

```
Batch H1 (Thread 1)  update_regime.py auto CATALYSTS + news_sentiment agreement line
                     · deps: user approval · [scripts/update_regime.py]
Batch H2 (Thread 2)  update_regime.py shift detector → data/regime_state.json
                     · deps: H1 (SAME FILE, sequential) · [scripts/update_regime.py, data/regime_state.json]
Batch H3 (dashboard) parallel — disjoint files, frozen contract C12-§3/§4:
   ├─ I1  /api/regime-state endpoint ........ deps: H2 (sample file) · [dashboard/app.py]
   └─ I2  regime-shift UI indicator ......... deps: I1 contract (frozen) · [dashboard/templates/index.html]
   Gate: auditor integration check → empty-shape ok:true, pill renders on active shift
Batch J1 (ops)       setup_vm_regime.ps1 weekly → daily · deps: H1+H2 landed · [scripts/setup_vm_regime.ps1]
```
`scripts/update_regime.py` is shared by H1 and H2 → **sequential, one owner at a time** (not
parallel). H3's two files are disjoint and build against the frozen `regime_state.json` /
`/api/regime-state` contracts, so I1+I2 may run in parallel with an integration gate after. No
task spans 3+ independent parallel modules → sub-agent delegation format not required.

---

## Batch H1 — Thread 1: MACRO_AUTO enrichment  · deps: USER APPROVAL

### H1 [DONE — ⚠️ AUDIT 2026-07-08: sentiment line silently dead on prod machine (cp874) → F-11; R1 shadow test + token measure still pending] — auto CATALYSTS + news_sentiment agreement line in `update_regime.py`
- **agent:** worker (single)
- **scope (whitelist):** `scripts/update_regime.py` only (`build_block()` + helpers; a small
  self-contained title→scenario-key NEEDLE map + geo-keyword list may be added as module
  constants). MUST NOT touch `agents/prompts/macro_regime.md` by hand (the script rewrites it
  between markers at runtime), `analyst.py`, or any `.json` prompt.
- **input contract:** C12-§2 + C12-§4. Reads `data/event_scenarios.json` (`scenarios[key].hot.dir`
  / `cool.dir`), `data/news_impact.json` (`aggregate.score`, `posts[].text`),
  `connectors.web_news.fetch_forexfactory_calendar(hours_ahead=168, include_all_us=True)`, and
  AlphaVantage `NEWS_SENTIMENT` (topics=economy_monetary,financial_markets; tickers=gold proxy,
  default `GLD`, env `REGIME_SENTIMENT_TICKER`).
- **output contract:** `build_block()` appends, INSIDE the `MACRO_AUTO` markers and in the frozen
  order (DATA → inflation → WATCH → CATALYSTS → sentiment[tag-only]):
  - **CATALYSTS line** (C12-§2 grammar), ≤2 nearest matched high-impact US events, `hot->`/`cool->`
    dirs verbatim from `event_scenarios.json`; no match or calendar fetch fails ⇒ line omitted.
  - **sentiment line — TAG-ONLY** (no directional verb; frozen grammar C12-§2), emitted ONLY when
    `av_dir == ni_dir ∈ {bullish,bearish}` (agreement is the *trigger*, not printed as a direction);
    tag ∈ {`risk-bid geopolitics`,`macro tone`} from the frozen keyword scan; provenance
    `(AV {av:+.2f}, ni {ni:+d})`. Any missing source / disagreement / neutral ⇒ line omitted.
    ⚠️ Confirm the live AV gold-proxy tag (`GLD` default, else `REGIME_SENTIMENT_TICKER`) on a
    budget-available day (25/day AV quota is shared/tight); quota spent ⇒ fail-soft, line omitted.
  - Env `REGIME_SENTIMENT_ENABLED=0` ⇒ skip the AV call + sentiment line entirely.
  - Every new-line path wrapped fail-soft: failure ⇒ that line absent, DATA line + human narrative
    intact, script exits 0.
- **acceptance:** (1) `--dry-run` on a day with an upcoming CPI/NFP prints a correctly-formatted
  CATALYSTS line with dirs matching `event_scenarios.json`. (2) When AV gold-proxy sentiment and
  `news_impact` agree non-neutral → one **tag-only** `sentiment (auto …)` line (NO
  BULLISH/BEARISH/UP/DOWN verb) in the frozen format; when they disagree / either is neutral /
  AV unavailable → NO sentiment line (block otherwise unchanged).
  (3) **Token check:** the two added lines add ≲40 input tokens to the analyst call (measure
  before/after via `db.reader.get_accounting()` / `agent_usage`). (4) **Shadow (R1):** analyst on
  a captured regime-day cycle WITH vs WITHOUT the lines does not spuriously flip `bias` direction.
  (5) `REGIME_SENTIMENT_ENABLED=0` ⇒ no AV sentiment call, no sentiment line; DATA+CATALYSTS still
  written. Emptying the MACRO_AUTO body ⇒ analyst falls back to gold_factors (kill-switch intact).

---

## Batch H2 — Thread 2: regime-shift detector  · deps: H1 (same file)

### H2 [DONE] — shift detection + `data/regime_state.json` writer in `update_regime.py`
- **agent:** worker (single) — runs AFTER H1 (shares `update_regime.py`)
- **scope (whitelist):** `scripts/update_regime.py` (post-`build_block` state logic), `data/regime_state.json` (NEW, generated)
- **input contract:** C12-§3. Current tuple from `build_block`-derived values: `fed_dir`,
  `real_rate_sign` (dead-band |real_rate|<0.1 ⇒ carry previous sign), `sentiment_tilt`
  (bullish/bearish/neutral from H1's agreement result). Previous values from an existing
  `data/regime_state.json`.
- **output contract:** compute `shift.kind` = monitored fields differing from the previous run
  ({fed_dir_flip, real_rate_sign_flip, sentiment_tilt_flip}); **debounce** — count
  `sentiment_tilt_flip` only when the NEW tilt is non-neutral. `shift.active = kind≠[]`. On an
  active flip append `{date, kind}` to `history[]` (cap 10). Write the EXACT C12-§3 schema atomically
  (tmp + `os.replace`). Missing prior state ⇒ `shift.active=false`, `kind=[]`, `from=null` (seed only).
  Fail-soft: any error ⇒ no crash, prior file left intact.
- **acceptance:** fixture a prior `regime_state.json`, flip `fed_dir` → new file has
  `shift.active=true`, `kind=["fed_dir_flip"]`, correct `from`/`to`, and a `history` append; re-run
  with unchanged inputs → `shift.active=false` (no chatter); nudge `real_rate` within ±0.1 of zero
  → no `real_rate_sign_flip`; output validates against C12-§3.

---

## Batch H3 — dashboard (parallel; disjoint files, frozen contract)

### I1 [DONE] — `GET /api/regime-state` pass-through endpoint
- **agent:** worker (single)
- **scope (whitelist):** `dashboard/app.py` (add `/api/regime-state` only)
- **input contract:** `data/regime_state.json` (C12-§3).
- **output contract:** mirror `/api/burn` EXACTLY — module `_empty` per C12-§3; `try open +
  jsonify(json.load(f))`; `except FileNotFoundError/Exception → jsonify(_empty)`. Never 500, never
  wrap the file on success.
- **acceptance:** `GET /api/regime-state` returns the live file; delete the file → returns `_empty`
  with `ok:true` (no 500); shape matches C12-§3.

### I2 [DONE] — regime-shift indicator on the dashboard
- **agent:** worker (single) — builds against I1's frozen contract (parallel-safe; integration gate after)
- **scope (whitelist):** `dashboard/templates/index.html` (new regime-shift indicator + a fetch of
  `/api/regime-state`, mirroring the existing `loadBurn()` fetch→render)
- **input contract:** `/api/regime-state` (C12-§3).
- **output contract:** `shift.active` ⇒ highlighted pill `⚠ REGIME SHIFT — {kind}` + `since` +
  hint "run youtube-to-knowhow to refresh the narrative"; else muted line
  `regime stable · Fed {fed_dir} · real-rate {sign} · tilt {sentiment_tilt}`; empty/missing payload
  ⇒ render nothing (no console error).
- **acceptance:** with `shift.active:true` the pill renders with kind+since; with an inactive/empty
  payload no pill and no crash; no console error.
- **Gate (auditor):** integration check after H3 — endpoint empty-shape returns `ok:true` (never
  500); UI renders correctly for active / inactive / empty payloads.

---

## Batch J1 — ops: daily cadence  · deps: H1+H2 landed

### J1 [WIP — ⚠️ AUDIT 2026-07-08: code change already landed (unlogged, F-13); remaining = VM re-registration (user ops) + continue.md entry] — `setup_vm_regime.ps1` weekly → daily
- **agent:** worker (single)
- **scope (whitelist):** `scripts/setup_vm_regime.ps1` only
- **input contract:** existing weekly scheduled task definition.
- **output contract:** change the schedule trigger weekly → daily (AV budget 4/25/day). No code-path
  change, ops-only.
- **acceptance:** the scheduled task registers as daily; a manual `update_regime.py --dry-run` after
  the change still succeeds.

---

## Fix tasks — filed by auditor 2026-07-08 (see docs/AUDIT.md "Cycle #12" for full evidence)

### F-11 [DONE 2026-07-08] — sentiment line silently dead on the production Windows machine (MED — functional)
- **fix applied:** added `encoding="utf-8"` to all three reads (`:177`, `:249`, `:352`). Verified:
  bare `open()` raises `UnicodeDecodeError` byte 0x9c on the real file; utf-8 read OK; dry-run now
  emits the CATALYSTS line (sentiment still omitted today only because AV quota is spent — fail-soft).
- **agent:** worker (single) · **scope (whitelist):** `scripts/update_regime.py` only
- **root cause:** `_sentiment_line_and_tilt` opens `data/news_impact.json` with a bare
  `open(NEWS_IMPACT_PATH)` (`update_regime.py:249`). Windows default locale is cp874;
  `news_impact.json` is written UTF-8 with non-ASCII (`ensure_ascii=False`,
  `agents/news_impact.py:551-552`). Reading it raises `UnicodeDecodeError` (byte 0x9c), which the
  function's `except Exception` swallows → always returns `(neutral, None)`. **The sentiment line
  never emits on the prod machine even when AV and news_impact agree, and `sentiment_tilt` is
  pinned `neutral`, which also disables H2 `sentiment_tilt_flip`.** Verified by an isolated
  harness reading the REAL production file (aggregate.score=+69 bullish, AV stubbed agreeing) →
  line omitted. The same bare-open latent bug exists at `:177` (event_scenarios — ASCII today by
  luck) and `:352` (regime_state — ASCII, safe today).
- **fix contract:** add `encoding="utf-8"` to all three reads (`:177`, `:249`, `:352`). No logic
  change. (The AV `Information`/`Note`/agreement paths are all correct once the file is readable.)
- **acceptance:** with the real `data/news_impact.json` present and a stubbed/real agreeing AV
  reading, `_sentiment_line_and_tilt` returns a non-None TAG-ONLY line; all fail-soft paths (missing
  / malformed file, AV down/quota, disagreement) still omit cleanly; no directional verb in output.

### F-12 [ ] — REGIME_SENTIMENT_ENABLED should default OFF until R1 shadow test passes (decision — R1 live-money)
- **agent:** user decision + (optional) worker · **scope:** VM env, or `update_regime.py:244` default
- **root cause:** the sentiment line defaults ENABLED (`os.getenv("REGIME_SENTIMENT_ENABLED","1")`)
  and will enter the analyst's authoritative regime block on the first real run after F-11 is
  fixed. The C12-§6 R1 shadow test (analyst bias WITH vs WITHOUT the lines on a regime day) has NOT
  been run by anyone, the token before/after measurement is pending, and `news_impact` scoring is
  known-overconfident (R6). Static mitigations (tag-only, agreement-gated, lowest-authority,
  kill-switch) are sound but do not substitute for one behavioral shadow observation.
- **fix contract:** user either sets `REGIME_SENTIMENT_ENABLED=0` in the VM env (zero code change),
  OR approves flipping the code default at `update_regime.py:244` to `"0"` (inverts a frozen env
  semantic → needs user approval, architect logs it). CATALYSTS + DATA lines stay on. Flip to ON
  only after F-11 fixed AND a regime-day shadow shows no spurious `bias` direction flip.
- **acceptance:** on the VM, the sentiment line + its AV call are disabled until the shadow test is
  recorded; DATA + CATALYSTS still write; documented in continue.md.

### F-13 [ ] — J1 code landed without status/log; VM re-registration outstanding (LOW — process)
- **agent:** worker + user ops · **scope:** `docs/TASKS.md` (J1 status), `.claude/context/continue.md`
- **root cause:** `setup_vm_regime.ps1` was changed weekly→daily (`:54`) but J1 stayed `[ ]` and no
  continue.md entry was written (override #2). The scheduled task on the VM has not been
  re-registered (that is a user ops step).
- **fix contract:** reconcile J1 status, add the continue.md entry (file changed + why), and the
  user re-runs `scripts/setup_vm_regime.ps1` on the VM to register the daily trigger.
- **acceptance:** J1 marked `[DONE]` only after the VM task shows a daily trigger and a post-change
  `update_regime.py --dry-run` succeeds; continue.md has the entry.

---

## Cross-batch integration gate (auditor) — Cycle #12
- After H1: token before/after (`get_accounting`) within budget; shadow analyst on a regime day
  shows no spurious `bias` flip; fail-soft paths verified (AV down / `news_impact.json` missing).
- After H2: shift fixtures (flip fires once, unchanged re-run clears, dead-band holds).
- After H3: all `/api/regime-state` empty-shape returns `ok:true` (never 500); pill renders.
- **No diff** may touch `agents/prompts/*.json`, `analyst.py` decision logic, `_run_gates`, money
  management, SL/TP, confidence thresholds. A worker hitting such a need marks the task
  **[BLOCKED]** and escalates (do not diverge).
- Every code edit / bug / fix also logged in `.claude/context/continue.md` (override #2).
