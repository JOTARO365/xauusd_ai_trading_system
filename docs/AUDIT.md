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
