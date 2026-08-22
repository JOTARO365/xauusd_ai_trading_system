# Mental-Model Gap Audit — what the owner believes vs. what the code does

Date: 2026-08-22 · Auditor: read-only code audit (no code/config modified)
Scope: every stage of the owner's understood pipeline + every algo in `ALGO_REGISTRY`,
mapped against the actual live wiring (`.env` flags as of today, `data/algo_switches.json`,
`data/algo_dir_mode.json`).

**Live context used as ground truth (not re-litigated here):** gold has no proven causal
directional edge at any TF; the live gold algo enters on Donchian breakout at close;
`sr_meta` rich zones are exit/advisory/display; `ALGO_ROUTER_LIVE=false`;
`REGIME_LIVE=true` makes `decision_maker` SKIP (agents/decision_maker.py:782-786), so the
LLM gates there do not touch the live algo paths.

**Live flag snapshot (.env):** `REGIME_LIVE=true`, `REGIME_LIVE_TICK=true`,
`TSMOM_LIVE=true`, `TSMOM_COEXIST=true`, `MULTI_SYMBOL_LIVE=true`,
`SENTIMENT_BIAS=true` (`SENTIMENT_BLOCK_ABOVE=60`), `EVENT_ENGINE_LIVE=true`,
`LOSS_ADAPTIVE_LIVE=true`, `ALGO_ROUTER_ENABLE=true` / `ALGO_ROUTER_LIVE=false` /
`ALGO_ROUTER_ALLOW_PROMOTE=false`, `NEWS_GATE=true` (dead — see Stage 4),
`REGIME_PENDING=false` / `REGIME_PENDING_FADE=true`, `SR_GATE_ALL=true`,
`SR_RICH_ZONE=true`, `LONG_ONLY_ALL=true`, `METALS_LONG_ONLY=true`,
`PAIRS_LIVE=false`, `PAIRS_SHADOW=false`.

---

## Section A — Pipeline stage gaps

| # | Owner's stage | Exists? | Works as understood? | Actual behavior | Evidence (file:line) | Gap severity |
|---|---|---|---|---|---|---|
| 1 | LLM pulls news | YES (but code pulls, not LLM) | Mostly | Deterministic code fetches: ForexFactory weekly calendar JSON + Investing.com RSS (`connectors/web_news.py:19,26-29`), tweets via free **Nitter RSS mirrors**, not the X API (`connectors/twitter_client.py:9-14`), gathered concurrently in `agents/news_gatherer.py:16-33`. The LLM never "pulls" anything — it reads what code fetched. | web_news.py:19; twitter_client.py:9-14; news_gatherer.py:23-28 | LOW (semantic). Real risk: Nitter mirrors are flaky free proxies — the tweet leg silently degrades to `[]` (news_gatherer.py:29-33). |
| 2 | LLM analyzes the news | YES | Yes (two layers) | (a) Per-post scoring: prefilter/dedupe in code (`agents/news_impact.py`), LLM scores parsed by `parse_scores` and aggregated → `data/news_impact.json` (`agents/news_cache.py:290-297, 438-510`). (b) Gold strategist LLM distils worldmonitor + news_impact + calendar + **econ actuals + macro_strip (DXY/10Y/real-yield) + COT** + macro_regime.md → one number (`agents/sentiment_score.py:91-158`). | news_cache.py:290-510; sentiment_score.py:91-158 | LOW-MED. Caveat (established): inputs include COT/momentum ⇒ the score is heavily a **drift restatement**, one factor not an independent signal. |
| 3 | Produces a sentiment NUMBER | YES | Partly | `sentiment_score.get_score()` → −100..+100, cached 30 min (`sentiment_score.py:161-174`; `config.py:301`). But there are **three parallel numbers**: sentiment_score, the news_impact aggregate score, and `macro_quant.gold_macro_score` (composite "for SELECTION" per its own docstring but consumed **only by the dashboard**, `dashboard/app.py:1913-1918`). The number is used only as a **veto/size-shrink** (`agents/sentiment_bias.py:25-33`): hard block only at \|score\|≥60, below that lot-shrink + wider break requirement. It never *chooses* a direction or an algo. | sentiment_score.py:161-174; sentiment_bias.py:12-33; macro_quant.py:1-9; dashboard/app.py:1913-1918 | MEDIUM. Number exists; role is a brake, not the driver the owner imagines. And 2 of the live gold entry paths never read it (see Stage 7 note + Section B). |
| 4 | Per-event STATISTICS applied to the sentiment | PARTIAL | **No** | Stats ARE computed offline: `scripts/event_reaction_stats.py` → `data/event_stats.json`; `scripts/build_event_scenarios.py` → `event_scenarios.json` (hot/cool dir + magnitude_pct + n); `scripts/review_calibration.py` → `impact_calibration.json`. Applied live via `event_engine.bias()` (`agents/event_engine.py:104-192`, EVENT_ENGINE_LIVE=true): PRE-event = block new entries, POST-event = block entries against the rubric direction — **but only on the MSE path for XAU symbols** (`agents/multi_symbol_executor.py:653-665`). The main gold engine `regime_tick` has **no event check at all** — it will enter a breakout during the NFP minute (`agents/regime_tick.py` — no event_engine reference). `magnitude_pct`/`n` are journaled but never used numerically (no sizing/threshold scaling — event_engine.py:129-133 carries them as payload only). Nothing ever multiplies event statistics into the sentiment number. `analyst.py:55-65` injects event-stat priors into an LLM whose trade decision is skipped under REGIME_LIVE (decision_maker.py:782-786); NEWS_GATE=true adjusts a conf floor in the same skipped decision_maker (decision_maker.py:304-347) ⇒ **NEWS_GATE is dead on the live path**. `impact_calibration.json` = dashboard-only (`dashboard/app.py:2770-2789`). | event_engine.py:104-192; multi_symbol_executor.py:653-665; decision_maker.py:304-347, 782-786; dashboard/app.py:2770 | **HIGH**. Stats exist but are (a) direction-only, never magnitude-applied, (b) absent from the largest live gold path, (c) partly wired into a dead LLM path. |
| 5 | Inverse-asset moves computed (DXY→gold) | PARTIAL | Partly | Live use is a **binary agreement filter, not a computed move**: `macro_momentum` requires its H4 Donchian breakout to agree with EURUSD (DXY-inverse proxy) momentum, per-pair sign via `regime_lib.macro_for` (`agents/algo_registry.py:363-403`); `confluence_15m` requires M15 EURUSD momentum agreement (+H1/H4/volume) (`algo_registry.py:441-511`). Both fetch EURUSD live from MT5. No beta, no magnitude, no lead-lag translation of a DXY move into an expected gold move. All the "computed" artifacts the owner sees are research/display: `drv_*.json` = offline exports (`scripts/export_drivers.py:3,86`), `cointegration.json` = dashboard background scan (`dashboard/app.py:2344-2361`), `macro_strip.json` = dashboard + sentiment-LLM context (`sentiment_score.py:107-114`). Lead-lag was probed (`scripts/probe_gold_lead.py`) and found nothing tradable; XAU/XAG stat-arb is OFF (ADF −2.14 not cointegrated, .env note 08-22). | algo_registry.py:395-403,461-511; export_drivers.py:86; dashboard/app.py:2344-2361 | MEDIUM. The concept exists in 2 of ~5 live gold-entry paths as a yes/no filter; the "compute the implied move" part does not exist anywhere, and evidence says it wouldn't validate. |
| 6 | Demand/supply ZONES built from all the above | EXISTS but **not from the above, and not the entry anchor** | **No** | Zones are built from **price OHLC only** — sentiment/event/DXY numbers never enter zone construction. Two zone systems: (a) rich `sr_meta` (`agents/chart_watcher.py:1017-1059`) — code says explicitly "sr_meta = display" (:900, :933, :1023); (b) causal swing-pivot clusters in `agents/sr_entry_gate.py:20-48`. Live uses: **block-only entry gate** (BUY blocked near strong overhead resistance / SELL near support; `sr_entry_gate.py:78-112`; SR_GATE_ALL=true, rich bounce-stat mode SR_RICH_ZONE=true; wired at regime_tick.py:170-176 and multi_symbol_executor.py:666-674); **exit/TP + trailing** (`algo_exit.sr_tp_pips`, regime_tick.py:167,177; REGIME_SR_EXIT=true); and exactly **one zone-anchored entry path**: RANGE-regime fade BUY_LIMIT **at** sr_meta support (`agents/regime_pending.py:66-76 (_sr_view consumes bot_status sr_meta), :171-172, :247-249`; live via REGIME_PENDING_FADE=true) — whose own header warns "RANGE-fade ยังไม่ผ่าน validation (naive fade −EV)" (:7). SELL_LIMIT at resistance is choked by long-only (`connectors/mt5_connector.py:1024-1028`). The dominant live entry (TREND) is the **opposite** of zone entry: it buys the break *above* the zone. | chart_watcher.py:900,933,1023,1017-1059; sr_entry_gate.py:1-112; regime_pending.py:7,66-76,171-172,247-249; mt5_connector.py:1024-1028 | **HIGH** — largest single gap. Zones exist and are good; they gate, exit, and display — they do not source entries (except the unvalidated RANGE fade), and they are not informed by sentiment/events/DXY. |
| 7 | Sentiment/state SELECTS the algo | PARTIAL | **No** | Three selection mechanisms, none sentiment→live: (a) deterministic **price-regime** router — TREND→momentum breakout, RANGE→fade/stand-down (`scripts/regime_lib.py detect_regime`; regime_tick.py:55-65) — price-derived, not news-derived; (b) the LLM router *does* read sentiment + events + regime + backtest EV (`agents/algo_router_llm.py:62-113`) but with ALGO_ROUTER_LIVE=false every swap is journal-only (`:169-190` — `wrote = live and not promote_blocked` is always False), and promotes are separately blocked (ALLOW_PROMOTE=false); (c) `loss_adaptive` (LIVE=true) is **reactive**: ≥3 consecutive losses → force-refresh sentiment → widen `algo_dir` to "both" or demote combo to SHADOW (`agents/loss_adaptive.py:120-137`) — after-the-fact damage control, not proactive selection. The actual live roster is the **static human-set** `data/algo_switches.json`. | algo_router_llm.py:169-190; loss_adaptive.py:120-137; shadow_switches.py:44-66; data/algo_switches.json | **HIGH** (by design — the roster-drift guard is intentional and correct). The owner's "system picks the algo from sentiment" runs only on paper. |
| 8 | Orders per buy-only / sell-only / both config | YES | **Yes** (best-implemented stage) | Three enforcement layers: (1) global choke at the single order function — `LONG_ONLY_ALL` / `METALS_LONG_ONLY` block every SELL market order (`connectors/mt5_connector.py:883-892`) and every SELL pending (`:1024-1028`), both `true`; (2) per-algo `algo_dir` long/short/both, dashboard-editable, enforced on every live entry path — regime_tick.py:103-107, multi_symbol_executor.py:647-652, tsmom_manager.py:227-232 (SELL→FLAT), regime_executor.py:133; current file = everything "long" (`data/algo_dir_mode.json`); (3) `CDC_DIR_MODE=long` inside cdc_zone (`algo_registry.py:540-551`). | mt5_connector.py:883-892,1024-1028; algo_dir.py:53-59; data/algo_dir_mode.json | LOW. One caveat: `loss_adaptive` (LIVE) can silently widen an algo's mode to "both" (`loss_adaptive.py:126`) — owner-set dir modes are not immutable. LONG_ONLY_ALL still backstops actual SELLs, so today the mutation is inert, but flip that flag off and modes can drift without the owner acting. |

### Cross-stage findings not in the mental model (correctness issues found during mapping)

1. **Roster drift instance, live right now:** `regime_momentum_fvg:XAUUSD` = **LIVE** in
   `data/algo_switches.json`, while its own code declares "⚠️ SHADOW-ONLY … ไม่มี edge
   พิสูจน์แล้ว … ไม่ live" (`agents/algo_registry.py:241-242`).
2. **Gold double-engine overlap:** `regime_momentum:XAUUSD` = LIVE runs through **two
   engines simultaneously** — `regime_tick` (magic base, comment `ALGO-mom`) and the MSE
   loop (magic = SYSTEM_MAGIC+1, comment `MSE-*`), because MSE iterates every LIVE combo
   with no gold exclusion (`multi_symbol_executor.py:763-764,797`) and
   `data/mse_state.json` shows `regime_momentum:XAUUSD last_bar_ts 2026-08-21T09:00` —
   it has fired. The two engines count stacks separately (regime_tick counts only
   `ALGO-mom` comments, regime_tick.py:116-119; MSE counts its own magic,
   :812-813), so the same breakout family can hold 2 concurrent gold positions.
   The comment at `trading_graph.py:373-374` ("MSE = symbol อื่น … ทองไม่กระทบ") is stale
   and false.
3. **Sentiment-gate coverage holes on live gold:** `confluence_15m` and
   `regime_momentum_fvg` evaluate() have **no sentiment check**, and the MSE entry
   wrapper `_maybe_enter` adds none (multi_symbol_executor.py:638-720 — dir-mode, event,
   SR, confirm gates only). So 2 of the LIVE gold combos ignore the sentiment number
   entirely; only regime_tick, tsmom_manager, macro_momentum, (cdc_zone if promoted)
   respect it.
4. **PRE-news pause does not cover the main engine:** event_engine PRE/POST gating lives
   only in MSE (`multi_symbol_executor.py:653-665`). regime_tick and tsmom_manager trade
   through high-impact release windows.

---

## Section B — Per-algo gaps

Live state from `data/algo_switches.json` + `data/algo_dir_mode.json` (all dir modes =
"long" unless noted). "Zone?" = does the zone *source* the entry (gate/exit use noted
separately).

| Algo | How it ACTUALLY enters | Zone-anchored entry? | Sentiment / dir-mode respected? | Live or shadow? | Gap vs mental model |
|---|---|---|---|---|---|
| `regime_momentum` | Donchian N-bar breakout in TREND regime — BUY when price breaks above the N-bar high (`scripts/regime_lib.py:178 algo_momentum_breakout`; live per-tick vs cached levels, regime_tick.py:97-102) | **No** — zones only block (SR gate, regime_tick.py:170-176) and set TP/trailing (:167,177) | Sentiment: YES on regime_tick (block ≥60 / lot-shrink + extra-margin below, :144-165,182-183). **NO on its MSE clone.** dir-mode: yes (:103-107) = long | **LIVE** XAUUSD via regime_tick **and** MSE (double engine, finding A.2); SHADOW all other pairs | Chases the breakout **above** the zone — the exact opposite of "enter at demand." Core live behavior ≠ mental model. |
| `regime_momentum_fvg` | Same Donchian breakout + requires a Fair-Value-Gap in the last 6 bars supporting the direction (`algo_registry.py:249-270`) | No | Sentiment: **NO** (evaluate has none, MSE adds none). dir-mode: yes (long) | **LIVE XAUUSD** — contradicting its own SHADOW-ONLY docstring (:241-242) | Live against code intent; no proven OOS edge per its own comment. Roster-drift case. |
| `mean_reversion` | RANGE-regime z-score fade of price vs mean (`regime_lib.py:206`; algo_registry.py:102-125) | No (statistical stretch, not a mapped zone) | Sentiment: NO. dir-mode: default both (not in dir file) — moot in SHADOW; LONG_ONLY would choke SELLs if ever promoted | SHADOW everywhere (cut from live: −EV OOS, :95-96) | Closest in *spirit* to "buy low" but uses z-score, not the owner's zones; correctly parked in shadow. |
| `tsmom_d1` | D1 time-series momentum: majority vote of sign(close−close[−L]) L=21/63/126 + short-term confirm (`algo_registry.py:177-233`; gold engine `tsmom_manager._signal` + :213-255) | No | Sentiment: YES — gold engine blocks new opens vs strong score (tsmom_manager.py:237-246); registry clone gates only XAU-prefixed symbols (:208-217). dir-mode: yes — long ⇒ SELL signal → FLAT (tsmom_manager.py:227-232) | **LIVE** XAUUSD (tsmom_manager) + **LIVE WTIUSD** (MSE); SHADOW others | Pure trend-following (drift capture). No news/zone input to entry; sentiment is a veto only. |
| `macro_momentum` | H4 Donchian breakout **and** DXY-proxy (EURUSD) momentum must agree + seasonal + sentiment gates (`algo_registry.py:377-421`) | No (breakout) | Sentiment: YES (:406-412). dir-mode: yes (long) | **LIVE** XAUUSD, XAUEUR, BTCUSD (via MSE) | The one algo that genuinely implements stage 5 — but as a binary agreement filter, not a computed inverse move; still enters on breakout, not zone. |
| `confluence_15m` | M15 Donchian breakout + H1 & H4 EMA-slope + EURUSD momentum + tick-volume surge all aligned + session 13-21 UTC (`algo_registry.py:474-522`) | No | Sentiment: **NO**. dir-mode: yes (long) | **LIVE** XAUUSD (MSE); SHADOW others | Most-filtered breakout chaser; ignores the sentiment number entirely despite being live on gold. |
| `sweep_reversal` | Fades a prior-day H/L liquidity sweep that closed back inside, NEUTRAL/RANGE only (`algo_registry.py:304-343`) | Partial (prior-day extreme = a level, causally computed) | Sentiment: NO. dir-mode: "both" in file — SELL leg would be choked by LONG_ONLY anyway | SHADOW everywhere (−EV backtest, :278-279) | Reversal-at-level exists — but only on paper, and its own backtest says the idea loses. |
| `cdc_zone` | EMA12/26 "Action Zone" trend-follow, enter on pullback within bull zone, exit-on-flip (`algo_registry.py:544-585`) | **No — "zone" here means EMA color zone, a name collision with the owner's demand/supply zones** | Sentiment: YES for gold (:564-571). dir-mode: long (CDC_DIR_MODE=long) | SHADOW XAUUSD/XAUEUR; **LIVE BTCUSD** | Not a supply/demand algo at all despite the name. |
| `pullback_buy` | BUY-only dip: H1 close reclaims EMA20 after dipping, D1 must be uptrend, SL under swing low (`algo_registry.py:628-664`) | No (EMA reclaim, not a mapped zone) | Sentiment: NO. dir-mode: BUY-only by construction; **excluded from SR gate** (SR_GATE_EXCLUDE, config.py:392) | SHADOW (absent from switches ⇒ default SHADOW, shadow_switches.py:44-47) | Closest live-code relative of "buy the dip near demand" — but anchored on an EMA, in shadow, and its IS evidence is weak (docstring :593). |
| *(path, not an algo)* `regime_pending` RANGE fade | BUY_LIMIT placed **at sr_meta support** when H1 regime=RANGE, HTF-trend gated, vol/momentum cancel gate (`regime_pending.py:171-172,218-249`) | **YES — the only zone-anchored entry in the system** | dir: SELL_LIMIT choked by long-only (mt5_connector.py:1024-1028). No sentiment gate. | LIVE-flagged (REGIME_PENDING_FADE=true) but fires only in RANGE regime | Matches the owner's mental model most closely — and is the one path whose own header says it never passed validation (:7). |

---

## Section C — The rewrite work-list (ranked)

Legend: **[risk-shaping/correctness]** = safe, does not claim predictive edge, testable as
variance/exposure reduction. **[claims-alpha]** = implicitly asserts a directional edge —
per this repo's own ~15 null backtests it will fail honest validation; do not wire to
live without passing the standard gate (t>2, OOS>0, n≥100, cost-adjusted).

1. **Close the sentiment-gate coverage holes** — add the same `sentiment_bias` block/shrink
   used by regime_tick into `multi_symbol_executor._maybe_enter` (covers
   `confluence_15m`, `regime_momentum_fvg`, and the MSE clone of `regime_momentum` on
   gold). One call site, uniform behavior. **[risk-shaping]** — safe; it only vetoes.
2. **Extend event_engine PRE-event flat to regime_tick and tsmom_manager** — today the
   biggest gold engine trades through NFP. Small guard call mirroring
   multi_symbol_executor.py:653-665. **[risk-shaping]** — safe, bounded, matches the
   owner's stage-4 intent.
3. **Fix the roster drift:** demote `regime_momentum_fvg:XAUUSD` → SHADOW (its own code
   says shadow-only), and add a startup assertion that any switch=LIVE combo must be on a
   code-side allowlist of validated combos — the exact failure `ALGO_ROUTER_ALLOW_PROMOTE`
   was built to prevent happened anyway via a different door. **[correctness]**.
4. **Resolve the gold double-engine:** either exclude `("regime_momentum","XAUUSD")` from
   the MSE loop (regime_tick owns it) or make both engines count each other's positions
   in the stack cap. Today the same breakout can open two positions. **[correctness]**.
5. **Unify the three sentiment numbers** — `sentiment_score` (used), `news_impact`
   aggregate (used only by dead NEWS_GATE + as LLM context), `macro_quant.gold_macro_score`
   (dashboard-only despite "for SELECTION" docstring). Pick one consumable value, delete or
   demote the rest to inputs. Also either remove NEWS_GATE or rewire it to a live path —
   as-is `NEWS_GATE=true` does nothing. **[correctness]**.
6. **Apply event magnitude statistics as a size/pause scaler** (e.g. reduce lot or widen
   stops when `magnitude_pct` × n says the release historically moves > SL distance).
   Direction-neutral use of the stats the owner already computed. **[risk-shaping]** —
   validate on the journal first (`data/event_engine_journal.jsonl` exists for this).
7. **Zone-anchored entry ("buy at demand")** — restructure an *existing validated signal*
   to fill via LIMIT at the nearest sr_meta support instead of market-chasing the break.
   As **execution-price improvement on an unchanged signal** this is testable and safe to
   frame; as a *standalone* zone-reaction entry it is **[claims-alpha]** — already mined
   and rejected twice (`scripts/zone_reaction_backtest.py` BUY-support exp_R negative;
   `sr_fade` cut with t −4..−22, algo_registry.py:672-674). Expect the LIMIT variant to
   trade less often and miss runners; demand a replay proving net improvement before live.
8. **DXY "computed move" → gold entry** (beta/lead-lag translation): **[claims-alpha —
   will fail validation]**. `probe_gold_lead.py` and `cointegration_scan` already found
   nothing tradable; keep the inverse relationship as the binary alignment filter it is
   (already live in macro_momentum/confluence_15m).
9. **Sentiment-driven algo selection live:** turning on `ALGO_ROUTER_LIVE` in
   **demote-only** form (promote still blocked) is **[risk-shaping]** and consistent with
   the existing guard; letting the LLM promote combos is **[claims-alpha]** and re-opens
   the exact roster-drift hole documented on 08-20.
10. **Docs/comment hygiene:** fix `trading_graph.py:373-374` ("MSE never touches gold" —
    false), and soften the "sr_meta = display" comments (chart_watcher.py:900,1023) —
    regime_pending/tsmom_manager consume sr_meta for live pending placement, so
    "display-only" is no longer literally true. **[correctness/docs]**.
11. **Guard `loss_adaptive`'s silent dir-mode widening** (loss_adaptive.py:126) with a
    journal notification and/or require dashboard confirmation — today an automated
    process can overwrite an owner-set direction restriction. Inert while LONG_ONLY_ALL
    is on; a landmine the day it's turned off. **[correctness]**.

---

## Section D — Honest verdict

**The pipeline the owner describes half-exists — as scaffolding around a breakout
trend-follower, not as the driver of entries.** News is pulled (by code), analyzed (by
LLM), condensed to a number, event stats are computed, DXY alignment is checked, zones
are built — and then the actual live entries are: price broke an N-bar high, buy. The
sentiment number can veto, shrink, or delay that entry; it never originates or aims one.
Zones block and exit trades; only one unvalidated RANGE-fade path enters at them. The
LLM never selects the live algo (by deliberate, correct design). The one stage that works
exactly as understood is the buy-only/sell-only config — enforced at three layers,
including a single choke point every order passes through.

**What a rewrite toward the mental model CAN deliver:**

- **Correctness** — one sentiment number instead of three, gates applied uniformly instead
  of per-path accidents, no double-engine gold entries, a roster that matches code intent,
  documentation that matches wiring. Real, measurable, and worth doing.
- **Risk-shaping / loss-reduction** — no entries into NFP/CPI windows on any path, fewer
  counter-sentiment entries, event-magnitude-aware sizing, zone-gated entries near strong
  opposing levels (already live and validated as a gate for macro_momentum). The DB
  evidence supports exactly this: the gold book is ≈ +423 net decomposed as BUY +1992 /
  SELL −1569, with the single worst loss (−6,248) an **un-stopped** SELL — an
  operational SL failure plus shorts fighting an uptrend. Every dollar of that damage was
  addressable by risk-shaping (long-only, SL enforcement, sentiment veto), none of it by
  better prediction.
- **Better fills, maybe** — LIMIT-at-zone execution of existing signals, *if* replay
  proves the price improvement beats the missed-runner cost. Provable either way.

**What the rewrite CANNOT deliver, and no wiring change will:**

- **Directional alpha on gold.** ~15 backtests across D1/H1/M1/tick, every TP/SL
  structure, plus the UHAS signal-mining sweep and the zone/fair-value candidates, all
  converge: no causal directional edge; apparent edges were drift or look-ahead. The
  sentiment score is substantially a restatement of the same drift (COT/momentum inputs),
  so "wiring sentiment deeper into entries" adds a correlated copy of the trend filter,
  not new information. Event stats give direction-of-day at best, with n≈173-181 and no
  demonstrated post-cost tradability. DXY lead-lag was probed and is empty.
- Therefore the honest ceiling of the fully-rewired mental-model system is: **capture the
  gold drift while it lasts, with fewer self-inflicted losses and smaller blowups.** Its
  P&L will still be dominated by whether gold keeps trending up — the same exposure the
  long-only flag already encodes. If the regime flips bearish, no stage of this pipeline
  detects that with an edge; the protection is the kill switches (`LONG_ONLY_ALL=false`
  is a manual decision), not the sentiment machinery.
- Any proposal from this rewrite that promises entry-timing profit from news, zones, or
  DXY must clear the standing validation gate (t>2, OOS>0, n≥100, cost-adjusted) before
  touching live — and based on everything already mined in this repo, the prior is that
  it won't.
