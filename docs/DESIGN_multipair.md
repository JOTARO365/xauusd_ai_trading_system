# DESIGN — Gold-Complex Multi-Pair Ecosystem (Phase 2–5)

Status: **DRAFT — awaiting user approval.** No code until approved.
Extends the existing single-symbol XAUUSD system; does not replace it.
Phase-1 universe decision (07-23): **trade XAUUSD only; collect all pairs; per-pair toggle.**

## Guiding invariants (this repo)
- Real-money system: every phase ships flag-gated, **default OFF/SHADOW**. XAUUSD LLM pipeline stays as-is.
- **Zero new LLM calls/cycle** for the multi-pair layer (all pure-Python, `news_impact` precedent).
- Broker truth over assumptions: pip value per pair via `order_calc_profit` (measured in Phase 1).
- Reuse the existing symbol-aware machinery; build only the single-symbol bottlenecks (see map below).

## Reuse vs Build (from architecture audit)
**Reuse as-is:** DB `symbol` column on trades/agent_usage/cycles + `strategy_version`; `db/reader.get_trades(symbol,)` + `_ALIASES`; `db/writer` symbol passthrough; `price_feed.get_ohlcv(symbol=)`/`get_current_price(symbol=)` (already symbol-safe); flag idiom + `reload_config()` hot-reload; JSONL/`open_order(shadow=True)` shadow patterns; `scripts/export_drivers.py` multi-symbol collector template.
**Build new:** per-pair OHLC collector loop; algo registry; shadow engine (virtual fill + resolve); `is_shadow`/`algo_id` columns; per-(algo,pair) switch store; correlation-aware cluster cap; attribution journal. **Do NOT** refactor `SYMBOL` global / LangGraph `TradingState` yet — the multi-pair layer runs *beside* the XAUUSD pipeline on explicit `symbol` params, not through it.

---

## PHASE 2 — Data collection layer (ships first, runs for weeks)

**Goal:** unbiased per-pair OHLC + spread history for the whole universe, before any algo is designed.

- **`connectors/pair_collector.py`** (new) — generalizes the `export_drivers.py` loop. Each cycle (or every N cycles), for every symbol in the universe registry: `mt5.symbol_select(sym)` → `get_ohlcv(sym, tf, count)` for M15/H1/H4/D1 → append to `data/pairs/<sym>_<tf>.json`, plus a **spread snapshot** `{ts, sym, spread_pts, bid, ask}` → `data/pairs/spread_log.jsonl`. Free (no AI). Symbols validated against `mt5.symbol_info` (avoid the `drv_xag`=`Hexagon` mis-resolution — validate resolved name, never assume the key).
- **Cross-pair context signals (pure Python, 0 token), offered to the existing XAUUSD pipeline as context only:**
  - **Gold-complex breadth**: of {XAUUSD, XAGUSD, XAUEUR, XAUJPY}, how many confirm the current gold move sign → a −1..+1 breadth score.
  - **USD-leg decomposition**: XAU move vs its EUR/JPY-denominated moves + the FX cluster → classify the current gold move as *gold-driven* vs *USD-driven* (XAU↑ & EUR↑ = gold story; XAU↑ & EUR↓ = USD story).
  - **Gold/silver ratio**: level + z-score vs its own history (RV context).
  - Written to `data/pair_context.json`; consumed by the dashboard + optionally passed to the analyst as read-only context (no new call). Precedent: `news_impact`.
- **DB persistence:** shadow/real trades already key by `symbol`; the collector's raw bars stay in files (like `data/xau_*`). Context snapshots to `data/`.
- **Gate:** collect **≥ 4–8 weeks** before any pair-specific algo is designed. Algos designed on assumptions repeat the EMA_PULLBACK failure (WR 31%, −$594, hard-blocked).

---

## PHASE 3 — Algo registry + correlation-aware risk

- **`agents/algo_registry.py`** (new) — `ALGO_REGISTRY: dict[algo_id, AlgoSpec]` where
  `AlgoSpec = {algo_id, version, eligible_pairs: list[str], klass, params: dict}`.
  Each algo is a rule-based class implementing one interface:
  ```
  class Algo:
      def evaluate(self, symbol, bars, ctx) -> VirtualOrder | None   # deterministic; no LLM
  VirtualOrder = {symbol, algo_id, dir, entry, sl, tp, risk_pct, class: "scalp"|"swing"}
  ```
  The LLM layer stays XAUUSD-only until an (algo,pair) combo earns a live slot (cost discipline).
- **Per-(algo,pair) design must state** (in a follow-up doc when a real algo is proposed): why the algo fits the pair's character (trend/range stats, session, spread budget), **net-of-cost expectancy math** (spread+swap measured), and its risk budget drawn from the cluster cap.
- **Correlation-aware portfolio cap** — `agents/portfolio_risk.py` (new):
  - Clusters (from Phase-1 corr): `GOLD = {XAUUSD, XAGUSD, XAUEUR, XAUJPY}`, `USD = {AUDUSD, EURUSD, USDCHF, USDJPY}`.
  - Rule: **Σ open risk within a cluster ≤ CLUSTER_RISK_CAP (e.g. 2%)** regardless of how many pairs signal — this is what stops "5 pairs = one 5× trade". `MAX_DAILY_LOSS` stays global and unchanged.
  - A LIVE entry is rejected (or downsized) if it would breach its cluster cap. Enforced before `open_order`.

---

## PHASE 4 — Enable/disable + SHADOW engine (the key requirement)

- **Per-(algo,pair) switch:** state ∈ `{LIVE, SHADOW, OFF}`, stored in **`data/algo_switches.json`** `{"<algo_id>:<symbol>": "SHADOW"}`, **hot-reloaded each cycle** (same pattern as `reload_config()` `.env` reload) and editable from the dashboard. Every combo **starts SHADOW**. `OFF` only for delisted/broken instruments — **data collection continues even when OFF**.
- **`agents/shadow_engine.py`** (new) — each cycle, for every combo in SHADOW (and LIVE, for parity logging):
  1. run `algo.evaluate(symbol, bars, ctx)` → `VirtualOrder`.
  2. record the virtual entry/SL/TP with `is_shadow=true, algo_id, symbol, entry_ts`.
  3. **resolve** open virtual orders against subsequent real bars using the documented convention: **SL-first on ambiguous bars** (if a bar's range spans both SL and TP, count SL) — identical to the backtest harness, pessimistic, no look-ahead (resolve from the bar *after* entry).
  4. sends **nothing to MT5**.
- **Storage:** same trades store, flagged `is_shadow=true` + `algo_id` + `symbol`. Follows the `strategy_version` discipline: **write → schema → select → map → consume in ONE change**, and **never pool shadow and live stats in one number**.
- **Promotion → LIVE:** requires the evidence bar (Phase 5). **Demotion → SHADOW is automatic** on kill-switch (rolling-50 WR < breakeven+buffer, or cluster DD breach) + alert.

### Schema changes (migration `db/migration_add_shadow_algo.sql`)
```sql
ALTER TABLE trades ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS algo_id   TEXT;
-- live trades keep on_conflict (ticket, account_login); shadow rows have ticket=0,
-- so shadow uniqueness = (algo_id, symbol, entry_ts). add a partial unique index:
CREATE UNIQUE INDEX IF NOT EXISTS ux_shadow ON trades (algo_id, symbol, entry_ts)
  WHERE is_shadow = true;
```
`db/reader._ALIASES` and `accountant._norm_symbol` (the two alias tables) unified before adding pairs. New symbols added to both.

---

## PHASE 5 — Attribution journal (which algo works where)

- **Performance matrix** — dashboard tab + `scripts/algo_matrix_report.py`: rows = algos, cols = pairs, cell = `{n, WR, net_PnL, expectancy_R, max_DD, badge:live|shadow}`. **Separate matrices for LIVE vs SHADOW — never merged.**
- **Promotion rule (mechanical):** shadow `n ≥ 100` (scalp-class) or `≥ 20` (swing-class) **AND** net expectancy `> +0.05R` after real costs (spread+swap) **AND** window spans **≥ 2 market regimes**. Demotion: rolling-50 WR below breakeven+buffer, or cluster DD breach → auto-SHADOW + alert.
- **Cost drag** per combo: `spread + swap + tokens` — a combo gross-profitable but net-negative after its costs is a **losing** combo and the journal says so explicitly.
- Answers per month, one screen: which combos earn their slot, which are dying, which shadow combos are promotion-ready, and total cost drag per combo.

### Dashboard matrix mock
```
LIVE                                  SHADOW
        XAUUSD                               XAUUSD   XAGUSD
regime  n=520 WR54% +0.11R DD8%  ●live  ...  n=0      n=87 WR51% +0.06R  ◐ready
tsmom   n=12  WR33% -0.20R DD5%  ●live  ...  ratio_rv  -       n=140 WR55% +0.09R ◐ready
                                             breakout  n=44 WR48% -0.02R ○collecting
cost drag/combo: regime 31p+swap  |  ratio_rv 0.6% spread ...
```

---

## Implementation plan (sequenced — each a separate approved batch)

1. **Batch A — Data collection** (lowest risk, runs weeks in background):
   `pair_collector.py` + universe registry + `data/pairs/` storage + cross-pair context signals + dashboard "gold-complex context" strip. No trades, no schema-critical change. Ship, let it accumulate 4–8 weeks.
2. **Batch B — Shadow engine + registry + switch**: schema migration (`is_shadow`,`algo_id`), `algo_registry.py`, `shadow_engine.py`, `algo_switches.json` + dashboard toggle, `portfolio_risk.py` cluster cap (enforced only when a LIVE combo exists). Everything SHADOW. Auditor integration check.
3. **Batch C — Attribution journal**: `algo_matrix_report.py` + dashboard matrix tab (live/shadow separated, cost drag).
4. **Batch D — First non-XAUUSD algo** (LAST): only after Batch A data + Batch B shadow prove out; a concrete (algo,pair) proposal with net-of-cost expectancy, validated on collected data, starts SHADOW, promoted only by the Phase-5 rule.

## Open questions for user (before Batch A)
1. Collection cadence — every cycle (~5s, heavier) vs every N min (lighter)? (recommend: OHLC on bar-close, spread snapshot every ~1 min.)
2. `CLUSTER_RISK_CAP` value (recommend 2% gold-cluster, matching current single-XAU risk posture).
3. Which pairs collect from day 1 — the full 7 (XAGUSD/XAUEUR/XAUJPY/AUDUSD/EURUSD/USDCHF/USDJPY) or the recommended 3 (XAGUSD/AUDUSD/EURUSD)? (recommend all 7 — collection is free and keeps the record unbroken for later toggles.)
