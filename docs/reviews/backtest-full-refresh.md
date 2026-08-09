# Full backtest refresh + algo bug fix (all 77 combos, incl non-live)

Regenerated `data/backtest_results.json` across all 11 symbols × all algos.

## Headline: no combo is statistically significant
All 11 "+EV" combos have t-stat 0.48–1.89 — **none reach t>2**. The strongest (xau_xag_pairs
t1.89) is the already-refuted look-ahead pair; confluence_15m XAUUSD (t1.87, exp_R 0.162) is the
best genuine gold combo but its OOS drops to 0.072. The system's edge is thin by rigorous standards
— treat "+EV" (exp_R>0 & OOS≥0) as a loose, noise-permissive label, not proof of edge.

## Bug fixed: regime_momentum_fvg was a copy of regime_momentum
`backtest_all.py` ran the same `bt_momentum()` for both, so the FVG variant's numbers were
identical (0.038/t0.50/n367) — the FVG confluence filter (live `MomentumFVGAlgo`) was never applied
in the backtest. Added `bt_momentum_fvg` replicating the live filter (require a bull/bear
fair-value-gap within 6 bars supporting the breakout direction).

After the fix, the variants diverge and reveal:
| pair | regime_momentum | regime_momentum_fvg |
|------|-----------------|---------------------|
| XAUUSD | 0.038 (n367) | 0.024 (n335) ↓ |
| BTCUSD | 0.027 | −0.044 ↓ (now −EV) |
| XAUJPY | 0.193 | 0.246 ↑ (but −EV/small n) |

**The FVG filter ("IMPROVED momentum") mostly hurts** — it drops trades without adding edge on the
pairs that matter (gold, BTC). `regime_momentum_fvg XAUUSD` is LIVE but is strictly worse than plain
`regime_momentum XAUUSD` (same breakout, FVG subtracts). Recommend shadowing it (redundant + worse).

## Audit fixes applied (backtest-vs-live parity) — big honesty corrections

Fixed 4 backtest bugs found by the parity audit; re-ran the matrix. Effect on LIVE combos:

| combo | before | after | cause |
|-------|--------|-------|-------|
| confluence_15m XAUUSD | exp_R 0.162, OOS 0.072 | 0.158, **OOS 0.006** | removed H1/H4 slope **look-ahead** (map to closed HTF bar) + added live **session gate** → OOS collapses; real edge thinner |
| tsmom_d1 XAUUSD | 0.214 | 0.148 | P&L was %-of-final-price, now **R-multiple** (÷3×ATR) + disaster SL |
| tsmom_d1 BTCUSD | 2.064 (+EV) | 0.860, t2.07, **−EV** | units fix; t crosses 2 but n=79 < MIN_N → not trusted |
| tsmom_d1 WTIUSD | 1.023 | 0.141 | units fix → honest thin |
| **xau_xag_pairs** | **+1.64, t1.89, +EV, auto-LIVE** | **−1.813, t−0.89, −EV** | the row was a **hardcoded literal**; a real causal rolling-β z-fade backtest is NEGATIVE |

Fixes: `_htf_slope_map` uses the last *closed* HTF bar (−2 not −1); `bt_conf15m` applies the
`CONF15M_SESSION` gate for XAU; `bt_tsmom` returns R-multiples with a 3×ATR disaster stop; the
pairs row is now computed by a real `bt_pairs` (causal) instead of a static literal.

**Key correction:** the pairs "+1.64 +EV" that was auto-marking itself LIVE was fabricated — the
real causal edge is −1.81. Combined with the cointegration scan (fails split-half), **PAIRS_LIVE
should be set false**. confluence_15m gold, our best combo, has OOS ≈ 0 once the look-ahead is
removed — genuinely marginal, not the 0.16 it appeared. Remaining backtest simplifications
(managed BE/trail exits, macro/tsmom sentiment gates, mean_reversion/sweep divergences) are noted
in the audit for later.

## Remaining audit fixes applied — mean_reversion + sweep_reversal

- **bt_meanrev** rewritten to match `algo_mean_reversion` live: window 20 (was 60), RANGE-only (was
  NEUTRAL+RANGE), OU half-life gate (>10 skip, was absent), zone SL `m∓2.5σ` floored at 1.5×ATR
  (was fixed 1.2×ATR), TP = distance back to mean (was RR=1.0), time-stop 3×half-life (was 120).
  Post-fix: XAUUSD −0.070 (t−2.50), EURUSD −0.049, USDCHF −0.081 — honestly −EV (matches the cut).
- **bt_sweep** SL now = distance beyond the sweep wick + 0.5×ATR (live `SweepReversalAlgo`), was a
  flat 1.0×ATR. Post-fix XAUUSD −0.025, XAGUSD −0.318 — −EV.

All 6 parity-audit findings are now resolved (conf look-ahead + session, tsmom units + disaster SL,
pairs hardcode→causal, mean_reversion 5-divergences, sweep SL). Inherent-only items remain
(managed BE/trail exits, macro/tsmom sentiment gates — no historical series). The backtest now
faithfully reflects live algo logic; no fabricated or hardcoded numbers remain.

## Full-history (50k H1) refresh — the honest +EV/−EV picture

Bumped H1 backtest depth 20k/30k → 50k (full available: XAUUSD back to 2018, ~8y; XAUJPY only
5,240 bars ≈ 11 months — broker recently added it). This removes the recent-bull-window bias.

Result: +EV 11 → **10**. `regime_momentum XAUUSD` fell out (+0.038 on 3.4y → −EV on 8y) —
confirming it was a bull-window artifact (matches the prior finding: gold momentum −0.137 full vs
+0.085 recent). Every surviving +EV combo still has t < 2 (best confluence_15m XAU t1.72).

### Why the −EV combos are −EV (categorised)
1. **Bull-window artifact** — looked +EV on the short recent window, −EV on full history (gold
   momentum). Using full data is the fix; it reveals the truth (−EV), it cannot make it +EV.
2. **n < 80 hard data limit** — XAUJPY (11 months of data only), tsmom BTC (79). Positive exp_R +
   OOS but too few trades to trust. Not fixable in code — needs more history the broker doesn't have.
3. **Wrong-instrument / no edge** — macro_momentum on FX (DXY driver is gold-specific), momentum on
   arbitrary pairs. −EV by construction; correct.

**Conclusion:** −EV cannot be turned +EV without hardcoding or curve-fitting — the edge genuinely
isn't there, and full history confirms it (per quant-sat ch3: use the methods to REJECT, not to
manufacture edge). The disciplined action is to keep −EV combos shadow/off, not force them live.
No fabricated or hardcoded numbers were introduced.

## Structural per-pair macro driver (legit fix, not curve-fit)

macro_momentum used EURUSD (DXY proxy) as the macro confirm for ALL pairs — wrong for non-USD-quoted
gold. Added a structural per-pair map (`regime_lib.MACRO_MAP` / `macro_for`), used by both the live
`MacroMomAlgo` and `bt_macro`:
- USD-quoted (XAU/XAG/WTI/BTC ·USD) → EURUSD (+): EURUSD up = USD weak = asset up.
- XAUJPY → USDJPY (+): JPY weakness lifts gold-in-JPY.
- XAUEUR → EURUSD (−): EUR weakness lifts gold-in-EUR.

This is a currency-structural choice, NOT parameter tuning to a backtest. Result:
- **macro_momentum XAUEUR: −EV → +EV** (exp_R 0.113, t1.42, OOS 0.460, n336) — now the 2nd-strongest
  +EV combo, using the correct EUR-inverted driver.
- macro_momentum XAUUSD unchanged (0.068) — fixing one pair did NOT touch the others (the goal).
- XAUJPY: no result (only 11 months of data — hard limit, unchanged).

+EV total 10 → 11. macro_momentum XAUEUR is now a live-enable candidate. Discipline held: only the
structurally-correct driver was changed per pair; no BRK/SL/RR was tuned per pair (that would be
curve-fitting).
