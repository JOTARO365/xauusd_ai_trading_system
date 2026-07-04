# ARCHITECTURE — News & Event Impact Analysis

> Written by: architect · Last updated: 2026-07-04
> Input: `docs/PLAN.md` (APPROVED) + `CLAUDE.md` + QUICKREF + skill.md
> Supersedes: the previous "Stabilize & Complete" cycle's ARCHITECTURE (closed; in git history)
> Status: **DRAFT — needs user approval before workers start** (explain-before-acting; §7 lists what to approve)

This design covers PLAN Feature A (per-post News Impact scoring), Feature B (event
scenario conditioned on surprise), and the shared Realized-Move Logger. **v1 is
display-only** (การแสดงผลอย่างเดียว) — no output feeds analyst / macro_regime / gate /
money management / anti-fade guards / `agents/prompts/*.json`. Every number rendered
carries provenance (`prior` / `rubric` / `calibrated`) + sample count `n`.

---

## 0. Design principles (บังคับทั้งไฟล์)

- **Reuse the display-only pattern** already proven last cycle: *out-of-band producer
  (bot cycle or scheduled script) → `data/*.json` (atomic write) → pass-through `/api/*`
  endpoint (empty-shape on missing file, never 500) → `index.html` card.* Mirror
  `/api/burn` (`dashboard/app.py:1160`), **not** `/api/event-stats` (which returns
  `ok:false` on error — do not copy).
- **Fail-soft ทุกชั้นใหม่**: ถ้า producer พัง / ไฟล์หาย / รูปแบบเพี้ยน → การ์ดว่างหรือตกกลับพฤติกรรมเดิม,
  ห้ามล้ม bot pipeline และห้าม 500. (PLAN Risk: external source ล่ม.)
- **No new AI call per bot cycle.** Feature A scoring **merges into the existing Haiku
  call** (§2, evidence confirmed). Feature B is **computed-in-code, zero recurring AI cost.**
- **Magnitude honesty is a schema property, not a convention.** `magnitude` numbers
  travel bundled with `{provenance, n}` in every JSON contract (§4). A magnitude with no
  realized-move backing MUST be labelled `"rubric"`; `"calibrated"` is earned only at
  `n ≥ 30` (§8).

---

## 1. File structure — new / changed files and responsibility

### New files (สร้างใหม่)

| File | Responsibility | Milestone |
|---|---|---|
| `agents/news_impact.py` | **Pure code-only lib** for Feature A: normalize posts → gold-factor pre-filter → content-hash dedupe → build Haiku scoring block → parse batch scores → rolling weighted aggregate → atomic snapshot write. No LLM client inside; no side effects except the snapshot writer. | M1 (normalize/filter/dedupe) + M3 (score-parse/aggregate/write) |
| `data/news_impact.json` | Display snapshot written by the bot after each scored news cycle: rolling aggregate + top scored posts. Read by `/api/news-impact`. Fail-soft. | M3 |
| `data/event_sign_table.json` | **FROZEN seed (hand-maintained)** — the confirmed sign table (PLAN Q1). Maps event type → gold direction on a HOT (actual > consensus) surprise. Read by the scenario builder. | M2 |
| `data/event_scenarios.json` | Per-event-type conditional scenarios (sign + two-sided magnitude + provenance + n). Written by `scripts/build_event_scenarios.py`. Read by `/api/event-scenario`. Same file across M2 (rubric) → M5 (calibrated). | M2 (rubric) + M5 (calibrated) |
| `scripts/build_event_scenarios.py` | Scheduled/manual producer. M2: joins sign table + `data/event_stats.json` two-sided priors → rubric scenarios. M5: additionally joins `data/consensus_seed.json` + realized moves → conditional split + \|surprise\|→\|move\| curve, flips provenance to `calibrated` where n≥30. | M2 + M5 |
| `data/consensus_seed.json` | **Hand-maintained history**, CPI + NFP + FOMC only (PLAN Q2): actual-vs-consensus per past release. No scraping, no AlphaVantage. | M5 |
| `scripts/realized_move_logger.py` | **Standalone scheduled script.** Records XAUUSD price at +5/+15/+60 min after (a) high-tier scored posts and (b) released economic events, into `data/realized_moves.json`. Owns the `price_at(ts_utc)` MT5 helper (§3.4). Store-only — asserts no magnitude. | M4 |
| `data/realized_moves.json` | Append-only realized-move log (the ground truth that later calibrates magnitudes). Read by M5 + M6. | M4 |
| `scripts/review_calibration.py` | Compares predicted `magnitude_tier` (from logged post scores) + surprise-curve against `data/realized_moves.json`; writes hit-rate stats. Gate = n≥30. | M6 |
| `data/impact_calibration.json` | Calibration status + hit-rate per tier. Read by `/api/impact-calibration`; drives the `calibrated / not-yet` badge on both cards. | M6 |

### Changed files (แก้ไข — whitelist ต่อ task ใน TASKS.md)

| File | Change | Milestone | Sensitivity |
|---|---|---|---|
| `dashboard/templates/index.html` | M0: delta +$/−$ line in `renderEventCard`. M2: conditional "hot→ / cool→" line + provenance/n label. M3: new **News Impact** card. M6: calibrated/not badge. | M0/M2/M3/M6 | display-only; **single owner per batch** (avoid parallel writes) |
| `dashboard/app.py` | Add 3 pass-through endpoints: `/api/news-impact`, `/api/event-scenario`, `/api/impact-calibration` — each mirroring `/api/burn`. | M2/M3/M6 | display-only; single owner per batch |
| `agents/news_cache.py` | **M3 only** — extend the existing Haiku call `_summarize_with_haiku()` (`:108`, model `claude-haiku-4-5`) to ALSO return a per-post score array in the same call; cache scores alongside `summary` in the `news_cache` row so cache HITs keep scores. | M3 | ⚠️ **LIVE LLM call** — modifies a prompt the bot pays for. Needs explicit user approval (§7). Not a `.json` prompt file, not gate/money logic. |
| `agents/trading_graph.py` | **M1 only** — in `node_news()` (`:130`), call `news_impact.prefilter_and_dedupe()` on `news_data` and log the filter rate. M1 is pure measurement (no card, no cost, no behavior change). | M1 | low; measurement only, must stay fail-soft |

### Explicitly NOT touched (PLAN Non-Goals — ห้ามแตะ)

`agents/prompts/*.json`, `_run_gates` / anti-fade guards, confidence thresholds, money
management, `agents/analyst.py` decision logic, `agents/decision_maker.py`, `agents/market_advisor.py`,
`data/event_stats.json` producer (`scripts/event_reaction_stats.py`) — Feature B **reads** the
existing priors, does not rebuild them.

---

## 2. Feature-A merge decision — CAN scoring merge into an existing news LLM call? **YES**

**Target: `agents/news_cache.py:108 _summarize_with_haiku(news_data)`, model `claude-haiku-4-5`.**

Evidence (from code recon):
1. **Model already Haiku** — PLAN mandates Haiku for scoring; the summarizer is already
   `_HAIKU_MODEL = claude-haiku-4-5` (`news_cache.py:16`). No new call, no model change.
2. **Post list is present at the call site** — `news_data["tweets"]` (full objects:
   `id, text, user, created_at`) is in scope inside `_summarize_with_haiku` (`:110`). The
   prompt already assembles `tweet_block` from `tweets[:10]`. We extend that same prompt to
   emit a per-post JSON score array, and reuse the assembled block.
3. **Do NOT merge into the Sonnet analyst call** (`agents/analyst.py:177`): despite being
   the "sentiment" call it receives only the compressed 5-bullet summary — raw tweets are
   deliberately dropped there (only `len(tweets)` survives). Scoring there would re-inject
   the posts we just compressed out.

**Cache caveat (load-bearing) → design consequence:** the Haiku call is **cache-gated**
(`get_news_context()`, `news_cache.py:274`): hash HIT or ≤10-min stale-reuse skips Haiku,
so it does NOT run every cycle. Therefore **per-post scores are cached in the same
`news_cache` row as `summary`** (the `_hash_news()` key already covers `tweets[:10]`, so
cached scores stay valid exactly as long as the summary). On a cache HIT the bot reads
scores from cache and re-writes `data/news_impact.json` with freshness-decayed weights —
still zero extra LLM cost. **This keeps the "no new AI call per cycle" guarantee intact.**

---

## 3. Data flow

### 3.1 Feature A — per-post News Impact (display-only)

```
bot cycle (main.py run_cycle → trading_graph.node_news)
  │
  ├─ news_gatherer.gather_news()  → news_data{tweets[], calendar[], web_articles[]}   [existing]
  │
  ├─ news_impact.normalize_posts(news_data)        → posts[]  (tweets+web_articles unified)   [M1]
  ├─ news_impact.prefilter_and_dedupe(posts)       → kept[], filter_stats                     [M1]
  │        • gold-factor keyword filter (Fed/CPI/yields/DXY/war/tariff/Trump) — free
  │        • content-hash dedupe (same story across sources counted once)
  │        • log filter_rate (target ≥70% dropped)                                            [M1]
  │
  └─ news_cache.get_news_context()   [existing cache gate]
         │   MISS/force_fresh → _summarize_with_haiku()  [ONE Haiku call, MERGED]             [M3]
         │        returns summary  + scores[] = per-post {direction,confidence,tier,half_life,reason}
         │        store {summary, scores} in news_cache row
         │   HIT → read {summary, scores} from cache row (no LLM)                             [M3]
         │
         └─ news_impact.rolling_aggregate(scores, now)  → aggregate (magnitude×freshness decay) [M3]
                └─ news_impact.write_snapshot()  → data/news_impact.json  (atomic)             [M3]

dashboard:  /api/news-impact → News Impact card  (top posts + aggregate + provenance/n)        [M3]
```

Fail-soft: any exception in the news_impact path is caught, logged, and the bot proceeds
exactly as today (no card update, stale snapshot remains). It never raises into the pipeline.

### 3.2 Feature B — event scenario conditioned on surprise (computed-in-code)

```
scripts/build_event_scenarios.py   [scheduled/manual, NO AI]
  ├─ read data/event_sign_table.json   (FROZEN sign table, PLAN Q1)
  ├─ read data/event_stats.json        (existing two-sided priors: avg_up_pct/avg_down_pct)   [M2]
  ├─ [M5] read data/consensus_seed.json (CPI+NFP+FOMC actual-vs-consensus history)
  │       + realized moves (data/xau_daily.json historical / data/realized_moves.json forward)
  │       → conditional split hot/cool/inline + |surprise|→|move| curve, per cell with n
  └─ write data/event_scenarios.json   (per event type: sign, hot{}, cool{}, provenance, n)   [M2/M5]

dashboard (renderEventCard, index.html):
  ├─ /api/calendar    → upcoming events (already carries `forecast` = consensus, `previous`, `actual`)
  ├─ /api/event-stats → existing prior magnitudes
  ├─ /api/event-scenario → data/event_scenarios.json                                          [M2]
  │
  ├─ M0: delta +$/−$ line   = current bid × (avg_up_pct/avg_down_pct)/100                      [M0]
  └─ M2: conditional line   "ถ้า actual ร้อนกว่า forecast → ทอง {dir} ~{mag} | ถ้าเย็นกว่า → {dir} ~{mag}"
         (direction from sign table; magnitude from scenario entry; label provenance+n)
         fallback: event with no consensus/forecast or no scenario entry → existing prior card
```

### 3.3 Shared — Realized-Move Logger (M4) — the calibration ground truth

```
scripts/realized_move_logger.py   [scheduled, e.g. every 5 min; standalone MT5 process]
  ├─ guarded MT5 init:  if mt5.terminal_info() is None: mt5.initialize(login,pwd,server)   [safe cross-process]
  ├─ collect anchors:
  │     • high-tier posts  ← data/news_impact.json  (magnitude_tier ≥ 2)
  │     • economic events  ← /api/calendar cache / released events (actual != pending)
  ├─ for each anchor not yet complete, for horizon h in {5,15,60} min:
  │     if now ≥ anchor_ts + h:  price = price_at(anchor_ts + h);  record move_pct
  └─ atomic append → data/realized_moves.json
```

`price_at(ts_utc)` (§3.4) is the ONLY new price primitive. Everything else reuses
`connectors.price_feed.get_current_price()` for the anchor/reference price.

### 3.4 `price_at(ts_utc)` — the one new price primitive (M4)

No timestamp-anchored bar accessor exists today. Reuse the proven pattern from
`scripts/score_trend_mode.py:47`:

```
price_at(ts_utc: datetime) -> float | None
  broker_offset = symbol_info_tick(SYMBOL).time_epoch  -  utcnow_epoch     # bar time = BROKER time, not UTC
  target_broker = ts_utc + broker_offset
  bars = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, target_broker-2min, target_broker+2min)
  i = bisect_right([b.time for b in bars], target_broker_epoch)            # first bar at/after target
  return bars[i].open  (or None if unavailable → horizon stays unfilled, retried next run)
```

**⚠️ Timezone is load-bearing:** MT5 bar/tick `time` is **broker server time (≈UTC+2/+3)**,
while post/event timestamps are **UTC**. The offset MUST be computed live per run; getting
this wrong silently logs the wrong price. This is called out here because it is the single
highest-risk correctness bug in the whole cycle.

### 3.5 M6 calibration

```
scripts/review_calibration.py  [manual/scheduled, NO AI]
  ├─ read data/realized_moves.json  (measured moves)
  ├─ per magnitude_tier: hit-rate = (realized |move| landed in tier's assumed band) / n
  ├─ surprise-curve fit check vs realized (Feature B)
  └─ write data/impact_calibration.json {tiers:{...hit_rate,n}, status per event, updated}
cards read /api/impact-calibration → flip badge "rubric — ยังไม่ validate" ↔ "calibrated (n=…)"
```

---

## 4. API contracts — **FROZEN** (endpoints + data schemas)

All new endpoints mirror `/api/burn` exactly: module-level `_empty` dict with `"ok": true`
+ every field the frontend reads (zeroed/empty/null); `try open + jsonify(json.load(f))`;
`except FileNotFoundError / Exception → jsonify(_empty)`. **Never 500, never wrap the file
on success.** Data files on disk MUST already match the endpoint shape. Changing any shape
below after workers start requires a new architect pass, logged here.

### 4.1 `GET /api/news-impact` ← `data/news_impact.json`  (Feature A)

```json
{
  "ok": true,
  "updated": "2026-07-04T13:05:00Z",
  "window_min": 180,
  "aggregate": {
    "score": -37,                 // signed int -100..+100 ; + = bullish GOLD
    "label": "bearish gold",      // bullish|bearish|neutral gold
    "n_scored": 8,                // posts scored in window
    "provenance": "rubric",       // "rubric" until M6; "calibrated" once magnitude proven
    "n": 8                        // sample count backing this aggregate (== n_scored in v1)
  },
  "filter_stats": { "raw": 41, "kept": 9, "filter_rate_pct": 78.0 },   // M1 measurement, surfaced for QA
  "posts": [
    {
      "post_id": "a1b2c3d4",      // 8-char content hash (dedupe key)
      "source": "twitter|forexfactory|investing",
      "author": "zerohedge",
      "text": "…≤160 chars…",
      "ts_utc": "2026-07-04T12:40:00Z",
      "age_min": 25,
      "direction": "bull|bear|neutral",   // toward GOLD
      "confidence": 0,            // 0..100
      "magnitude_tier": 2,        // 1 minor | 2 moderate | 3 major  (RUBRIC assumption)
      "half_life_min": 120,       // freshness decay used in aggregate weight
      "reason": "…≤12 words…",
      "provenance": "rubric"      // per-post magnitude provenance
    }
  ]
}
```
`_empty` = `{"ok": true, "updated": null, "window_min": 180, "aggregate": {"score":0,"label":"neutral gold","n_scored":0,"provenance":"rubric","n":0}, "filter_stats": {"raw":0,"kept":0,"filter_rate_pct":0}, "posts": []}`

### 4.2 `GET /api/event-scenario` ← `data/event_scenarios.json`  (Feature B)

```json
{
  "ok": true,
  "updated": "2026-07-04",
  "window": "2012-01-01..2026-06-30",
  "min_n": 30,
  "scenarios": {
    "CPI": {
      "sign": "hot_gold_down",              // from FROZEN sign table
      "hot":  { "dir": "down", "magnitude_pct": 0.92, "provenance": "rubric",     "n": 173 },
      "cool": { "dir": "up",   "magnitude_pct": 0.87, "provenance": "rubric",     "n": 173 },
      "surprise_curve": null                // M5: [{surprise_bucket, avg_abs_move_pct, n}] or null
    },
    "NFP":  { "sign": "hot_gold_down",  "hot": {...}, "cool": {...}, "surprise_curve": null },
    "FOMC": { "sign": "hawkish_gold_down", "hot": {...}, "cool": {...}, "surprise_curve": null }
  }
}
```
Rules: `provenance` is `"rubric"` in M2 (magnitude = existing two-sided prior). In M5 a cell
flips to `"calibrated"` **only if its n≥30**; otherwise it stays `"rubric"` (min-n fallback).
`magnitude_pct` is a % move of price; the card converts to $ using live bid.
`_empty` = `{"ok": true, "updated": null, "window": null, "min_n": 30, "scenarios": {}}`
(empty `scenarios` → card falls back to the existing prior display for every event).

### 4.3 `GET /api/impact-calibration` ← `data/impact_calibration.json`  (M6)

```json
{
  "ok": true,
  "updated": "2026-07-04",
  "min_n": 30,
  "tiers": {
    "1": { "assumed_band_pct": [0.0, 0.4], "hit_rate_pct": null, "n": 0 },
    "2": { "assumed_band_pct": [0.4, 0.9], "hit_rate_pct": null, "n": 0 },
    "3": { "assumed_band_pct": [0.9, 9.9], "hit_rate_pct": null, "n": 0 }
  },
  "status": "collecting"          // "collecting" (n<30 anywhere) | "calibrated"
}
```
`_empty` = same shape with all `hit_rate_pct: null`, `n: 0`, `status: "collecting"`.

### 4.4 `data/realized_moves.json` (M4 — internal, not an endpoint in v1)

```json
{
  "updated": "2026-07-04T13:10:00Z",
  "records": [
    {
      "anchor_id": "CPI-2026-07-14 | post:a1b2c3d4",
      "kind": "economic|post",
      "subtype": "CPI|NFP|FOMC|tweet",
      "anchor_ts_utc": "2026-07-14T12:30:00Z",
      "anchor_price": 3312.40,
      "moves": {
        "5":  { "price": 3318.1, "move_pct":  0.172, "logged_at": "…Z" },
        "15": { "price": 3325.7, "move_pct":  0.402, "logged_at": "…Z" },
        "60": { "price": 3309.9, "move_pct": -0.076, "logged_at": "…Z" }
      },
      "realized_dir": "up|down|flat",       // sign of the 60-min move (flat if |move|<0.05%)
      "pred": { "magnitude_tier": 2, "direction": "bear", "surprise_pct": null }  // what was predicted, for M6
    }
  ]
}
```
Append-only; a record is written incrementally as each horizon matures (partial `moves` allowed).

### 4.5 `data/event_sign_table.json` (FROZEN seed — PLAN Q1)

```json
{
  "note": "Gold direction when actual is HOTTER than consensus. Hand-maintained. FROZEN.",
  "CPI":          "hot_gold_down",
  "CORE_CPI":     "hot_gold_down",
  "NFP":          "hot_gold_down",
  "PCE":          "hot_gold_down",
  "RETAIL_SALES": "hot_gold_down",
  "GDP":          "hot_gold_down",
  "UNEMPLOYMENT": "hot_gold_up",      // higher-than-consensus unemployment → gold UP
  "FOMC":         "hawkish_gold_down"
}
```

### 4.6 `data/consensus_seed.json` (M5 — hand-maintained, CPI+NFP+FOMC only)

```json
{
  "note": "Manual seed. CPI + NFP + FOMC only. No scraping / no AlphaVantage.",
  "updated": "2026-07-04",
  "records": [
    { "event": "CPI",  "date": "2026-06-11", "consensus": 3.2, "actual": 3.4, "unit": "%yoy" },
    { "event": "NFP",  "date": "2026-06-06", "consensus": 190, "actual": 145, "unit": "k" },
    { "event": "FOMC", "date": "2026-06-18", "stance": "hawkish", "consensus_stance": "neutral" }
  ]
}
```

---

## 5. Notes, code-contradictions & fallbacks (PLAN assumption checks)

1. **Mergeable news LLM call? ✅ YES** — confirmed `_summarize_with_haiku()` (Haiku, has the
   raw post list). No fallback needed. The only nuance is cache-gating → scores cached in the
   `news_cache` row (§2). No new per-cycle call.
2. **ForexFactory consensus field? ✅ YES, named `forecast`** (`connectors/web_news.py:92`,
   surfaced via `/api/calendar`), plus `previous` and `actual`. So the **M2 conditional line
   needs NO manual seed** — it uses the live `forecast` as consensus. Manual seed
   (`consensus_seed.json`) is only for **M5 history** (per PLAN Q2), because ForexFactory gives
   only the upcoming instance, not multi-year history.
3. **No scheduler in repo.** `ecosystem.config.js` runs only `main`/`dashboard`/`auto-deploy`;
   the report scripts (`report_burn.py`, etc.) are NOT in pm2 — they run via Windows Task
   Scheduler / manually. New scripts (`build_event_scenarios.py`, `realized_move_logger.py`,
   `review_calibration.py`) follow the same out-of-band model. **Consequence (design, not a
   blocker):** the dashboard must tolerate stale/absent `data/*.json` — which is exactly why
   the `/api/burn` empty-shape contract is mandatory. Recommend documenting the schedule
   (logger every 5 min; scenario builder daily) in continue.md; actual Task Scheduler setup is
   a user/ops step, out of worker scope.
4. **Non-atomic write in the existing pattern.** `report_burn.py` writes with plain
   `open()+json.dump`. New writers that a scheduled reader or the live dashboard can read
   mid-write MUST write atomically (`tmp` file + `os.replace`) to avoid serving a half-written
   JSON. This tightens (does not contradict) the existing pattern.
5. **`price_at` timezone offset (§3.4)** is the top correctness risk — flagged, not a blocker.
6. **No PLAN scope conflicts found.** Nothing here changes gate/money/prompt logic. If a worker
   discovers they must, they STOP and escalate (do not diverge).

---

## 6. Dependencies

- **No new heavy dependency** (PLAN Non-Goal): no ML framework, no vector DB. Stats = stdlib
  (`statistics`, `bisect`) + existing `numpy` already used by `price_feed`.
- Reuses existing: `anthropic` (Haiku, already in `news_cache.py`), `MetaTrader5`,
  `connectors.price_feed`, `db.reader.get_accounting` (token-budget verify), `db.connection`
  (Supabase `news_cache` row for cached scores), Flask (`dashboard/app.py`).
- Token budget verification path (M3 acceptance): `db.reader.get_accounting()["daily"]` /
  `scripts/report_burn._fetch_daily_cost_usd()` — compare THB/day before vs after M3
  (`≤10%` of current burn, total within 150–250 ฿/day, PLAN Q5).

---

## 7. Decisions (each WITH rationale) — and what needs USER approval

**Needs explicit user approval BEFORE M3 workers start (explain-before-acting, live-money repo):**

- **D1 — Merge scoring into the live Haiku call in `news_cache.py`.** *Because* it is already
  Haiku and already holds the raw posts, so we add scores with zero new call and no model
  change (§2). *Considered* a separate scheduled Haiku scoring script; *rejected because* it
  would double-fetch posts and add a second recurring Haiku cost, and PLAN forbids a new
  per-cycle call. **This edits a prompt the bot pays real money for → user must approve the
  prompt change + the per-post cap before M3.** (M0/M1/M2 do NOT need this approval; they add
  no AI cost.)

**Design decisions (rationale):**

- **D2 — Scores cached in the `news_cache` row, snapshot re-written every cycle.** *Because*
  the Haiku call is cache-gated and would otherwise leave the card stale; caching keeps
  freshness-decay live at zero cost. *Considered* recomputing scores each cycle; *rejected*:
  new cost, violates no-new-call.
- **D3 — Feature B fully computed-in-code, one `data/event_scenarios.json` spanning M2→M5.**
  *Because* a stable contract lets M5 upgrade magnitude in place (rubric→calibrated) without
  re-architecting the card. *Considered* rendering the scenario purely in frontend JS;
  *rejected because* M5 needs a computed history file anyway, so a single data file is cleaner
  and keeps provenance/n honest.
- **D4 — Sign table as a FROZEN committed JSON (`data/event_sign_table.json`), not code
  constant.** *Because* the user confirmed the exact table (PLAN Q1); a committed, auditable
  file makes the frozen contract explicit and lets M5 read it. *Considered* hardcoding in the
  script; *rejected*: less auditable, easy to drift.
- **D5 — Realized-move logger is a standalone MT5 process with a guarded init.** *Because* MT5
  Python is per-process IPC; `if mt5.terminal_info() is None: mt5.initialize(...)` is safe and
  will not disturb the live bot's connection (confirmed via `report_ride_cohort.py:84`).
  *Considered* reusing `price_feed.connect_mt5()`; *rejected*: it unconditionally calls
  `mt5.shutdown()` first — wasteful in a co-running process.
- **D6 — `magnitude_tier` is RUBRIC until M6, provenance travels in every schema.** *Because*
  of the project's reverse-causality scars (hold-time, CHART_SHADOW); asserting magnitude
  before realized-move validation is exactly the failure mode. *No alternative considered* —
  this is a PLAN hard rule.
- **D7 — New endpoints mirror `/api/burn` (empty-shape, `ok:true`), NOT `/api/event-stats`
  (`ok:false` on error).** *Because* display cards must degrade to empty, never error the page.
  *Considered* the `event-stats` form; *rejected*: `ok:false` forces every card to special-case
  errors.
- **D8 — Atomic writes (`tmp`+`os.replace`) for all producer files.** *Because* the live
  dashboard/logger can read mid-write. *Considered* the existing plain-write; *rejected* for
  reader safety.
- **D9 — M1 wires only measurement into `trading_graph.node_news`, no card, no cost.** *Because*
  PLAN sequences the free code-only filter (M1) before the paid scoring (M3) so filter quality
  is verified against real traffic before spending tokens. *Considered* shipping filter+score
  together; *rejected*: couples a free change to a paid one and to user approval.

---

## 8. Calibration window & min-n (PLAN Q4 — architect proposes)

- **min-n = 30 per cell** (PLAN Q4). No `magnitude` renders as `"calibrated"` below this; it
  stays `"rubric"` and the card shows the `n`.
- **Primary window = 2012-01-01 → present** for Feature B surprise-magnitude stats (long base,
  matches `event_stats.json` history depth). *Rationale:* maximizes n before splitting by
  surprise sign/size (the "n too small when split" risk in PLAN).
- **Recent-regime overlay = trailing 3 years**, shown *only* as a secondary number and *only*
  when its own n≥30. *Rationale:* lets the user see regime shift (e.g. post-2022 gold-rate
  decoupling) without asserting a thin-sample number as primary.
- Realized-move horizons frozen at **+5 / +15 / +60 min** (PLAN). 60-min move sign defines
  `realized_dir`; `flat` when |move| < 0.05% (reuses `event_stats.json` flat_threshold).

---

## 9. Cost architecture summary (hard constraint)

| Feature | AI cost | Mechanism |
|---|---|---|
| A — per-post scoring | **0 new calls/cycle** | merged into existing Haiku `_summarize_with_haiku`; scores cached with summary; pre-filter (≥70% dropped) + dedupe + per-batch cap BEFORE the prompt |
| A — verification | — | M3 acceptance compares THB/day before/after via `get_accounting`; ≤10% of burn, total 150–250 ฿/day |
| B — scenarios | **0 (computed-in-code)** | sign table + priors + manual seed + realized moves; scheduled script |
| Shared — realized-move logger | **0 (no AI)** | MT5 M1 bars only |
| M6 — calibration | **0 (no AI)** | pure stats over `realized_moves.json` |

Token creep guard (PLAN Risk): pre-filter + dedupe + **cap posts/batch (default 12)** before
the prompt; if THB/day rises >10% after M3, cut the window / cap immediately.
