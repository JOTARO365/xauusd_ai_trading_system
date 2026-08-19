# Replay Validation — Specialist Entry Logic

**Verdict: NOT YET — data is insufficient for a faithful historical replay.**
**Recommendation: DO NOT enable the feature flag on the strength of a replay. The replay cannot be run at meaningful sample size on the data this repo persists.**

Modules under test: `agents/zone_mapper.py::build_zone_map`, `agents/specialist_router.py::route`
(→ `trend_specialist.evaluate` + `range_specialist.evaluate`), shared `specialist_common`.

Author: replay-validator (read-only pass — no MT5 connection, no orders, no bot start/stop).
Scripts used (throwaway, re-runnable): `scratchpad/replay_probe.py`, `scratchpad/synth_demo.py`.

---

## 1. Data source, window, sample size — stated up front

| Source | Records | Window | Carries full `chart_data` contract? |
|---|---|---|---|
| `logs/shadow_chart.jsonl` | 831 | 2026-06-29 → 2026-07-03 | **No** — decision I/O only (`signal`,`confidence`, tokens, latency). Zero chart_data keys. |
| `logs/gate_blocks.jsonl` | 873 | 2026-06-28 → 2026-07-14 | **No** — thin slice: `trend`, `sr_zone`, `sr_strength`, `signal`, `price`, `entry_type`, `sentiment_bias`. No ladder, no momentum_tf, no PA. |
| `logs/bot_status.json` | **1** (latest cycle, overwritten each cycle) | 2026-07-08T14:51 (cycle 2, `skip_ai=true`) | **Partial** — richest snapshot but still missing 4 required fields (below). |
| `logs/trades.json` / DB `trades` | 507 | — | **No** — execution records + 5 decision scalars (`_decision_snapshot`: planned_sl_pips, entry_score, atr_h4, momentum, htf_zone_tf). |
| DB `cycles` table | — | — | **No** — cost/ticket accounting only (id, cycle_at, ticket, total_cost_usd). |

**Faithful-replay sample size available: N = 1** (the single `bot_status.json` snapshot).
There is **no time-series of full chart_data anywhere** — `_shadow_chart_call`
(`agents/chart_watcher.py:104-114`) logs only `signal`/`confidence`, and `_write_bot_status`
(`main.py:92-119`) overwrites one snapshot per cycle rather than appending.

### Contract fields vs what the data carries

Required by the modules (per their docstrings): `trend`, `d1_trend`,
`momentum_tf.{h4,h1,m15}.{direction,strength,ema_align}`, `candle_pat.bias`, `sr_actions[]`,
`sr_meta[]`, `sr_zones.{resistance,support}`, `key_levels.{pdh,pdl}`, `htf_zone`,
`indicators.{h4,h1,m15}.{close,atr}`.

Present in the best source (`bot_status.json`) — verified by running `scratchpad/replay_probe.py`:

| Field | Status in bot_status.json |
|---|---|
| `trend`, `d1_trend` | present |
| `momentum_tf.*.direction/strength` | present |
| `momentum_tf.*.ema_align` | **MISSING** — stripped by `main.py:98-101`. Breaks the h1 regime (needs `ema_align==BULL/BEAR`) → h1 always falls to SIDEWAYS. |
| `sr_meta[]` | present (16 entries, full fields) |
| `sr_zones.resistance/support`, `key_levels.pdh/pdl` | present |
| `htf_zone` | present but `null` this cycle → d1 lane has no anchor |
| `candle_pat.bias` | **MISSING** — never persisted. |
| `sr_actions[]` | **MISSING** — never persisted. |
| `indicators.{tf}.{close,atr}` | **MISSING** — no per-TF close (→ no faithful `current`) and no h4 ATR (→ box validity untestable). |

`candle_pat.bias` and `sr_actions[]` are the **two inputs to `pa_confirms()`**, and **every**
trend and range candidate is gated on `pa_confirms()` returning True
(`trend_specialist.py:73`, `range_specialist.py:31`). With both absent from all persisted
data, a data-driven replay can **never** produce a candidate — so a "0 entries, looks safe"
result would be an artifact of missing data, not a property of the feature. This is exactly
the false-positive pattern this repo warns about, so it is called out rather than reported as a pass.

---

## 2. What the N=1 real replay actually shows (`scratchpad/replay_probe.py`)

Fed the real `bot_status.json` snapshot through `build_zone_map` + `route`
(`current` = `price_info.bid` = 4123.77 as a documented proxy, since `indicators.*.close` is absent):

- **`build_zone_map` works on real data:** ladder = 16 zones; nearest R = 4143.97 (H1),
  nearest S = 4121.60 (H4); **box valid** (upper 4143.97 / lower 4121.60, width 2237p ≥ 2000p);
  htf_anchor = None.
- **`route` lanes:** `h1:SIDEWAYS` (forced by missing ema_align), `h4:BEARISH`, `d1:BEARISH`.
- **Candidates: 0.** Log: `[SPEC] 0 cand — lanes h1:SIDE/h4:BEAR/d1:BEAR`.

The 0 here is **not** a safety signal: PA fields that gate every lane are absent, and price sat
at the lower band (support 4121.6) in a bearish trend, so no down-continuation pullback-to-resistance existed anyway.

## 3. Proof the modules DO fire (synthetic complete contract — `scratchpad/synth_demo.py`)

To distinguish "0 because safe" from "0 because data missing," a **synthetic, clearly-labeled**
complete-contract record (bearish trend, price pulled back up to an H4 resistance, bearish PA present)
was run. Result: **3 candidates** — `H4 SELL Q(A)`, `D1 SELL Q(C)`, `H1 SELL Q(C)`,
top = H4 SELL. This confirms (a) the plumbing produces entries when the contract is complete, and
(b) **multi-TF genuinely adds candidates** (one aligned regime → 3 simultaneous candidates across H4/D1/H1).
It does **not** validate real-world win rate — it is a mechanics check on fabricated input.

---

## 4. Items that could NOT be produced (and why)

3. **Per-regime / per-TF trigger counts over history** — not possible. Requires a time-series of
   full chart_data; none is persisted. Only N=1 (real, 0 candidates) + N=1 (synthetic, 3 candidates).
4. **Daily-cap interaction (candidates/day vs cap 6)** — not possible. Needs per-cycle candidate
   counts across days; cannot be derived without the chart_data time-series. Cap enforcement lives in
   decision_maker (out of these modules) and was not exercised.
5. **Hypothetical R:R / win-loss / R distribution** — **not possible.** No source carries
   forward OHLC bars. `shadow_chart.jsonl`/`gate_blocks.jsonl` store no price path, and
   `trades.json` covers only executed (mostly MANUAL) trades, not specialist candidates. Any
   win-rate number here would be fabricated — deliberately not reported.
6. **False-signal examples (lane fired, price reversed)** — **not possible** to source from history:
   zero lane firings exist in the real data (all gated out by missing PA), and there are no forward
   bars to judge a reversal against. No timestamps can be honestly quoted.

---

## 5. Recommendation

**NOT YET — cannot certify SAFE from replay. Blocking gap is instrumentation, not the code.**

The module logic is internally sound (fail-soft on bad input, box/ladder math runs on real data,
lanes compute, multi-TF fan-out works on a complete record). But the repo persists **no historical
corpus that satisfies the input contract**, so the three questions that actually gate a live flip —
how often it fires, whether it stays under the daily cap, and whether its entries win — **cannot be
answered with real numbers.** Enabling on the basis of a replay would be enabling on a replay that
does not exist.

To unblock a real validation, add **decision-time capture of the full chart_data** (append-only, not
the overwritten bot_status.json), specifically including the currently-dropped
`candle_pat`, `sr_actions`, `momentum_tf.*.ema_align`, and `indicators.*.{close,atr}` — then let it
accumulate (the modules are already flag-OFF/unwired, so this can run in shadow). Once ~2–4 weeks of
per-cycle snapshots plus forward bars exist, per-regime trigger counts, cap interaction, and R:R
become answerable. Until then: **keep the flag OFF.**
