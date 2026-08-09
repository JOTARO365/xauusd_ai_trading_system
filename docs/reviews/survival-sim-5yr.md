# Survival Simulation — 5-Year Monte-Carlo (gold directional core)

`scripts/survival_sim.py` · 600 paths/tier · block-bootstrap real gold returns + scenario
drift/vol overlay · sentiment-gated direction (62% acc) · THB money model (min-lot floor,
structural SL, margin/stop-out ruin, force-close<20k, fixed-fractional 0.5%).

## Scenarios (2026 consensus, gold-centric, 5-yr)
soft_landing 35% · recession 20% · stagflation 12% · yield_spike 13% · chop_range 15% · tail_crisis 5%

## Result

| start | survive% | ruin% | median฿ | p10 | p90 | med DD | median ruin yr |
|-------|----------|-------|---------|-----|-----|--------|----------------|
| 1,000 | 10% | 90% | 0 | 0 | 18k | 55% | 0.04 |
| 3,000 | 20% | 80% | 0 | 0 | 182k | 83% | 0.07 |
| 20,000 | 69% | 31% | 133k | 0 | 350k | 75% | 0.48 |
| 50,000 | 93% | 7% | 197k | 67k | 398k | 46% | 1.23 |

Realized edge (50k tier): exp_R 0.110 · WR 47% — matches live backtest range (0.04–0.16).

## Findings
1. **1,000 THB does not survive**: 90% ruin, median death ~2 weeks. One losing gold trade
   (min-lot 0.01 × structural SL ~$36 = ~1,190 THB) exceeds the whole account.
2. **min-lot forces ~2.4% risk/trade** at any capital ≤50k (can't size below 0.01 lot with a
   wide structural SL until ~240k equity) → this is why median DD stays 46–83% even when funded.
3. **20,000** (the force-close floor) → 69% survival; **50,000** → 93%. Consistent with the
   min-lot economics computed independently.

## Scope / caveats
Gold directional sleeves only (the capital-survival driver). BTC / single FX / XAU-XAG pairs
excluded (add trade count / reduce risk but don't drive ruin). Synthetic paths, not a price
forecast — a statistical stress test of money mechanics + thin edge against 5-yr tails.
