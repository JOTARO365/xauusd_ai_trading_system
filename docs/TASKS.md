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

### C1 — Frozen sign table + scenario builder (rubric) + endpoint
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

### C2 — Conditional scenario line on the event card
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
- **agent:** worker (single) — **BLOCKED until user approves ARCHITECTURE §7 D1**
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
- **agent:** worker (single) — after D1 (needs the snapshot shape)
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

### E1 — `scripts/realized_move_logger.py` (+ `price_at` helper)
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

### F1 — Consensus seed + calibrated scenario magnitudes
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

### G1 — `scripts/review_calibration.py` + endpoint + card badge
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

## Cross-batch integration gate (auditor)

- After every batch: `& $PY tests\test_all.py` compared to a **baseline** run (some tests are
  time-of-day dependent — see CLAUDE.md; use the `git stash` baseline trick before blaming a change).
- **After D (M3):** verify AI-calls/cycle unchanged and THB/day ≤10% over baseline via
  `db.reader.get_accounting` / `scripts/report_burn.py` — this is the hard cost gate.
- **All new `/api/*`:** confirm empty-shape on missing file returns `ok:true` (never 500).
- **No diff** may touch `agents/prompts/*.json`, `_run_gates`, money management, or confidence
  thresholds. Any worker hitting such a need marks the task **[BLOCKED]** and escalates (do not diverge).
- Every code edit / bug / fix also logged in `.claude/context/continue.md` (CLAUDE.md override #2).
