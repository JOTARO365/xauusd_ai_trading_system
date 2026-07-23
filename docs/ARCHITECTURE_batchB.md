# ARCHITECTURE — Batch B: Multi-Pair Shadow Engine

Status: **DRAFT — awaiting user approval. No code until approved.**
Extends `docs/DESIGN_multipair.md` (Phase 3–5). Grounded in a code audit of existing
machinery (see §2). Live-money system → everything ships **flag-OFF, SHADOW-only, 0 orders, 0 token**.

---

## 1. Goal & scope

**Goal:** start accumulating per-`(algo, pair)` **shadow evidence today**, so that after 4–8 weeks
we have a net-of-cost track record per pair and can promote combos to LIVE one at a time — instead of
designing pair algos on assumptions (which repeated the EMA_PULLBACK failure: WR 31%, −$594).

**In scope (this batch):**
- A symbol-parameterized shadow engine that runs a **validated** algo on every pair, logs virtual
  entries, and resolves them against real bars (SL-first, no look-ahead), net of **measured** per-pair cost.
- An algo registry (starts with the ONE validated algo).
- A per-`(algo,pair)` switch store (`SHADOW`/`LIVE`/`OFF`), hot-reloaded, dashboard-editable later.
- An attribution matrix report + one read-only dashboard endpoint.

**Non-goals (explicitly deferred):**
- **No new algo.** v1 registry = only `regime_momentum` (the existing validated momentum-breakout router).
  A new non-XAUUSD algo is Batch D (DESIGN_multipair.md), only after shadow proves out.
- **No LIVE multi-pair orders.** Nothing calls `open_order` for a non-XAUUSD pair in this batch. The
  cluster-risk cap (`portfolio_risk.py`) is **stubbed** — it only matters once a combo is promoted LIVE.
- **No change to the XAUUSD live pipeline.** `algo_journal.py`, `regime_executor.py`, gates, money mgmt — untouched.
- **No DB schema migration in v1** (see Decision D1) — reuse the proven file-journal pattern first.

---

## 2. Reuse map (from code audit — what already exists)

| Capability | Existing asset | Reuse decision |
|---|---|---|
| Signal compute (ER/ADX/vol → regime → algo) | `regime_shadow.compute_shadow_signal(high,low,close,times)` — **symbol-agnostic** (operates on arrays) | **Reuse as-is.** |
| Algo rules | `scripts/regime_lib.py` `algo_momentum_breakout` → `{algo,dir,sl_pips,tp_pips}`; `route()`; only `TREND`→momentum wired | **Reuse as-is.** Only `POINT=0.01` is gold-specific. |
| Bars per symbol | `price_feed.get_ohlcv(symbol=…, timeframe, count)` — **already symbol-param** | **Reuse.** `regime_shadow._bars_from_feed` is XAUUSD-hardcoded → write a 1-line symbol-param twin. |
| Resolve (SL-first, MFE/MAE, timeout, cost_R) | `algo_journal._resolve` — proven, but `POINT`/`COST_PIPS` gold-hardcoded, no `symbol` field | **Extract pure fn**, parameterize `(point, cost_pips, max_hold)`. Leave `algo_journal` untouched. |
| Per-symbol pip value | `mt5_connector._calc_pip_value(symbol)` (via `order_calc_profit`, currency-aware) | **Reuse** for $-P&L if needed. |
| Measured per-symbol spread | `data/pairs/spread_log.jsonl` `{ts,sym,spread_pts,…}` (all 8 pairs) | **Reuse** → median spread = real cost, replaces flat `COST_PIPS=30`. |
| Enable/disable switch store | `regime_adaptive.disabled_strategies()` — reads `data/regime_strategy_state.json`, 60 s TTL cache, fail-soft | **Reuse the idiom** for the `(algo,pair)` switch matrix. |
| Every-cycle hook | `trading_graph.node_position_mgmt` (skip_ai + full), fail-soft per hook; `journal_tick` at end | **Slot `shadow_engine.tick()` right after `journal_tick`.** |
| Dashboard endpoint | `_cached(key, fn, ttl)` SWR + `/api/algo-journal` template; `/api/pair-context` file+staleness template | **Reuse both patterns.** |
| DB symbol support | `writer.write_trade(symbol=…)`, `reader.get_trades(symbol=…)` + `_ALIASES` | Available if we choose DB (Decision D1). |

**Bottom line:** ~70% exists. New code = engine loop + registry + switch store + matrix report + one endpoint.

---

## 3. Component architecture & data flow

```
                        ┌─────────────────── every cycle (node_position_mgmt) ──────────────────┐
                        │                                                                        │
  data/algo_switches.json ──(TTL cache)──► shadow_switches.combos_in("SHADOW")                   │
                        │                              │                                         │
                        │                   for each (algo_id, symbol):                          │
                        │                              │                                         │
   price_feed.get_ohlcv(symbol,H1,600) ──► _bars(symbol) ─► ALGO_REGISTRY[algo_id].evaluate(     │
                        │                                        symbol, bars, ctx) ─► VirtualOrder│
                        │                              │                                         │
                        │                     append OPEN record  ──►  logs/shadow/<algo>__<sym>.jsonl
                        │                              │                                         │
                        │                     resolve OPEN records (SL-first, per-symbol cost)   │
                        │                              └──► mutate outcome in place ─────────────┘
                        │
  logs/shadow/*.jsonl ──► scripts/shadow_matrix.py ──► /api/shadow-matrix ──► dashboard tab
                                                        (LIVE vs SHADOW matrices, never merged)
```

**Cost model per symbol** (`shadow_cost.py`): `cost_pips(symbol)` = `median(spread_log[sym].spread_pts)`
(fallback to a config default). Optional `+ swap_pips(symbol, bars_held)` from a measured/config table
(default OFF in v1, flagged as a known gap in the matrix — see Decision D3). This is a real upgrade over
`algo_journal`'s flat `COST_PIPS=30`.

**Signal dedup:** momentum signal only changes on H1 bar-close → one OPEN record per `(algo,symbol,bar_ts)`
(same guard as `algo_journal`: skip if `bar_ts` already logged for that combo). Resolve runs every tick.

**Bars source:** fetched fresh via `get_ohlcv(symbol,H1,600)` — **NOT** the bounded `data/pairs/*.json`
(those hold only 500 H1 bars; the router needs ≥520). Shadow is thus independent of the collector.

---

## 4. Frozen interfaces (architect-frozen — workers must not change)

### 4.1 `VirtualOrder` (what an algo emits)
```python
VirtualOrder = {
    "algo_id":  str,      # registry key, e.g. "regime_momentum"
    "symbol":   str,      # logical symbol, e.g. "XAGUSD"
    "dir":      "BUY" | "SELL",
    "entry":    float,    # signal-bar close (paper entry)
    "sl_pips":  int,
    "tp_pips":  int,
    "regime":   str,      # TREND/RANGE/... (context, from router)
    "bar_ts":   str,      # ISO ts of the signal (closed) bar — dedup key
    "klass":    "scalp" | "swing",   # promotion-rule threshold selector (n≥100 vs ≥20)
}
```
`None` = stand-down (no signal this bar). No `$` price levels invented by any model — `entry` is a real bar close, SL/TP are pip offsets. **CORE INVARIANT preserved.**

### 4.2 `AlgoSpec` / registry (`agents/algo_registry.py`)
```python
class Algo:
    algo_id: str
    version: int
    klass:   str                     # "scalp" | "swing"
    eligible_pairs: list[str]        # logical symbols
    def evaluate(self, symbol, bars, ctx) -> dict | None:   # returns VirtualOrder | None; deterministic, no LLM
        ...

ALGO_REGISTRY: dict[str, Algo] = { "regime_momentum": RegimeMomentumAlgo() }
```
v1 `RegimeMomentumAlgo.evaluate` = thin wrapper: `compute_shadow_signal(*bars)` → if `signal.algo=="momentum_breakout"` build a `VirtualOrder`, else `None`. `eligible_pairs` = the 8-pair universe.

### 4.3 Shadow journal record (`logs/shadow/<algo_id>__<symbol>.jsonl`)
Superset of `algo_journal`'s signal record, **plus** `algo_id`, `symbol`, `klass`:
```
{ algo_id, symbol, klass, kind:"signal", logged_at, bar_ts, regime, dir,
  entry, sl, tp, sl_pips, tp_pips, cost_pips,          # cost_pips = measured at log time
  outcome: { result: OPEN|TP|SL|TIMEOUT, realized_R, realized_R_gross,
             bars_held, mfe_R, mae_R, exit_px, exit_ts, resolved_at } }
```
One file per combo → cheap whole-file rewrite on outcome mutation (same as `algo_journal`), naturally
partitioned, "never pool shadow+live" satisfied by construction (these files are shadow-only).

### 4.4 Switch store (`data/algo_switches.json`)
```json
{ "regime_momentum:XAUUSD": "SHADOW",
  "regime_momentum:XAGUSD": "SHADOW",
  "…": "…" }
```
- States: `SHADOW` (log+resolve, 0 orders) · `LIVE` (reserved; **rejected in v1** — no live multi-pair path) · `OFF` (skip).
- **Missing key for an eligible combo ⇒ defaults to `SHADOW`.** Read each cycle with 60 s TTL cache (regime_adaptive idiom), fail-soft to all-SHADOW.
- v1 hard rule: `shadow_engine` treats `LIVE` as `SHADOW` and logs a warning (no non-XAU live path exists yet). Promotion to real LIVE is Batch D + explicit approval.

### 4.5 Resolve function (`agents/shadow_resolve.py` — pure, unit-testable)
```python
def resolve_signal(rec: dict, high, low, close, times,
                   point: float, cost_pips: float, max_hold_bars: int) -> dict | None:
    """Return updated `outcome` dict, or None if the signal bar is out of window (stay OPEN).
    SL-first on ambiguous bars; resolve only from bar AFTER entry; TIMEOUT marks-to-market.
    realized_R = r_gross − cost_pips/sl_pips.  (Lifted 1:1 from algo_journal._resolve, parameterized.)"""
```
**Parity gate:** a unit test must show `resolve_signal(..., point=0.01, cost_pips=30, max_hold=48)`
reproduces `algo_journal._resolve` bit-for-bit on the same XAUUSD records (de-risks the extraction).

---

## 5. File layout & config

**New files:**
- `agents/algo_registry.py` — registry + `RegimeMomentumAlgo`.
- `agents/shadow_engine.py` — `tick()` (the cycle loop), `_bars(symbol)`, per-combo log+resolve.
- `agents/shadow_resolve.py` — pure `resolve_signal` (+ its parity test data).
- `agents/shadow_switches.py` — `state_of(algo,sym)`, `combos_in(state)`, TTL cache.
- `agents/shadow_cost.py` — `cost_pips(symbol)` from `spread_log.jsonl` (median, cached); optional swap.
- `scripts/shadow_matrix.py` — read journals → matrix rows + readiness badges.
- `data/algo_switches.json` — seed all universe combos = `SHADOW`.
- `tests/test_shadow_resolve.py` — parity + edge tests (SL-first, timeout, out-of-window).

**Touched files (add-only, fail-soft):**
- `agents/trading_graph.py` — 3 lines: `from agents.shadow_engine import tick as shadow_tick` + call after `journal_tick`, own try/except.
- `config.py` — `SHADOW_ENGINE` flag (default **OFF**), `SHADOW_UNIVERSE` (default the 8 pairs),
  `SHADOW_MAX_HOLD_BARS` (default 48), `SHADOW_SWAP` (default OFF). Registered in `reload_config()`.
- `dashboard/app.py` — one `/api/shadow-matrix` route (`_cached` + `shadow_matrix.build()`), plus a
  small tab (display-only, can be its own task).

**Kill switch:** `SHADOW_ENGINE=false` (live-reload) → engine no-ops. Nothing it does can touch orders.

---

## 6. Task decomposition (sequential — each ships + is verified before the next)

```
Batch B — sequential (shared interfaces §4 frozen before T-01):

[DONE] T-01 | agent: worker | scope: agents/shadow_resolve.py, tests/test_shadow_resolve.py
         | output: pure resolve_signal() + parity test vs algo_journal._resolve (XAUUSD, must match)
         | gate: pytest parity passes → then T-02
         | RESULT 2026-07-23: 10/10 parity PASS (bit-for-bit vs algo_journal._resolve, resolved_at excluded);
         |   symbol-general EURUSD (point 1e-5) verified. `python tests/test_shadow_resolve.py`.

[DONE] T-02 | agent: worker | scope: agents/algo_registry.py
         | input: §4.1/§4.2 interfaces + regime_shadow.compute_shadow_signal
         | output: ALGO_REGISTRY with RegimeMomentumAlgo.evaluate(symbol,bars,ctx)->VirtualOrder|None
         | RESULT 2026-07-23: VirtualOrder shape == §4.1 (9 keys); all 8 pairs fetch+evaluate OK via
         |   broker map (symbol-param end-to-end); non-momentum/stand-down → None. `python agents/algo_registry.py`.

[DONE] T-03 | agent: worker | scope: agents/shadow_switches.py, agents/shadow_cost.py, data/algo_switches.json (gitignored runtime), .gitignore
         | output: TTL-cached switch store (regime_adaptive idiom) + measured per-symbol cost_pips;
         |         seed switches = all 8 combos SHADOW
         | RESULT 2026-07-23: switches combos_in/state_of/set_state OK, missing→SHADOW default, toggle verified.
         |   cost_pips measured/pair: XAUUSD 30 (==old flat const ✓), XAUJPY 97, XAUEUR 60, XAG 51, EUR 19, ...
         |   → per-pair cost is load-bearing (flat-30 badly under-costs XAU-crosses). switches file is runtime
         |   (dashboard-edited, gitignored); shadow works without it (missing combo ⇒ SHADOW).

[ ] T-04 | agent: worker | scope: agents/shadow_engine.py
         | input: T-01..T-03 + get_ohlcv(symbol) + node hook contract
         | output: tick(): per-SHADOW-combo eval→log→resolve into logs/shadow/<algo>__<sym>.jsonl;
         |         per-(combo,bar_ts) dedup; fail-soft; 0 orders; LIVE-state downgraded to SHADOW+warn

[ ] T-05 | agent: worker | scope: config.py, agents/trading_graph.py
         | output: SHADOW_ENGINE flag (default OFF) + reload_config; wire shadow_tick after journal_tick
         | gate: auditor integration check — bot runs with flag OFF (no-op) AND ON (writes shadow logs, 0 orders)

[ ] T-06 | agent: worker | scope: scripts/shadow_matrix.py, dashboard/app.py (+ 1 tab in templates)
         | output: matrix {n, WR, exp_R net, sumR, maxDD, mfe/mae, badge} per (algo,pair),
         |         LIVE vs SHADOW separated; /api/shadow-matrix (_cached); promotion-readiness badge

Gate: auditor — flag-OFF no-op verified; flag-ON writes only shadow logs; 0 MT5 orders; 0 token; parity test green.
```

**Promotion readiness (matrix badge, Phase-5 rule):** `◐ready` when shadow `n ≥ 100` (scalp) / `≥ 20`
(swing) **AND** net `exp_R > +0.05R` **AND** window spans ≥ 2 regimes; `○collecting` otherwise; `✗dying`
if rolling-50 WR < breakeven. **Promotion to LIVE stays 100% manual** (user flips the switch after Batch D
adds a non-XAU live path). No auto-promote-to-live, ever.

---

## 7. Decisions — LOCKED (user sign-off 2026-07-23)

- **D1 — Storage = FILES.** `logs/shadow/<algo_id>__<symbol>.jsonl` (reuse `algo_journal` pattern, zero
  migration risk, shadow/live separated by construction). DB deferred; the latent `account_login`-not-on-`trades`
  schema gap is thereby avoided, not inherited.
- **D2 — Universe = ALL 8.** XAU/XAG/XAUEUR/XAUJPY/AUD/EUR/CHF/JPY. Shadow eval is free; keeps an unbroken
  record for any later toggle.
- **D3 — Cost = SPREAD-ONLY (measured median) + explicit gap flag.** `cost_pips(symbol)` = median of that
  symbol's `spread_log.jsonl`. **Swap NOT modelled in v1**; the matrix must render a visible "net of spread
  only — swap excluded" flag. A measured swap table is a prerequisite before ANY combo is promoted to LIVE
  (tracked as a Batch-D blocker, not this batch).

---

## 8. Invariant & risk compliance

- **CORE INVARIANT:** every algo is deterministic (Donchian/ER/ADX on arrays); no model invents a price;
  entry = a real bar close; SL/TP = pip math. ✅
- **Cost discipline:** 0 token (pure Python), 0 new LLM calls; per-cycle work = 8× `get_ohlcv` + small file
  rewrites. ✅
- **Live-money safety:** flag-OFF by default; SHADOW sends **nothing** to MT5 (no `open_order` call in any
  path); XAUUSD live pipeline and `algo_journal` untouched; kill switch = `SHADOW_ENGINE=false`. ✅
- **Validation honesty (skill):** shadow record is the unbiased forward log (features-at-decision → forward
  outcome, SL-first pessimistic, net of measured cost); matrix separates shadow vs live and never pools them;
  promotion gated on min-N + net-EV + ≥2 regimes. This is exactly the "collect → validate → shadow → enable
  one segment" discipline. ✅
- **Main risk:** `resolve_signal` extraction diverging from the tested `algo_journal._resolve` → mitigated by
  the **bit-for-bit parity test** (T-01 gate). Secondary: per-cycle latency from 8× bar fetches → mitigated by
  H1-bar-close dedup (eval only on new bars; resolve is cheap array walks).
```
