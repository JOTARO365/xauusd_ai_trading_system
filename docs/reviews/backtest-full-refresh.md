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
