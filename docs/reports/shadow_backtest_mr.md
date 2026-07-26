# Shadow Backtest — mean_reversion (RANGE z-score fade), per pair (net of measured spread)

_generated 2026-07-24T06:12Z · H1 · SL-first · zone-SL + OU time-stop max_hold · non-overlapping single-position · fires only in RANGE regime_


| pair | broker | n | trades/yr | WR% | exp_R (net) | exp_R gross | sum_R | maxDD_R | avg hold | TP/SL/TO | cost_pips | span |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|--:|
| **XAUUSD** | GOLD# | 525 | 155.3 | 49.7 | **-0.043** | -0.010 | -22.8 | -29.6 | 3.6 | 129/156/240 | 30.0 | 3.38y |
| **XAGUSD** | SILVER# | 552 | 163.3 | 35.1 | **-0.339** | -0.093 | -187.1 | -188.3 | 3.5 | 121/181/250 | 51.0 | 3.38y |
| **XAUEUR** | XAUEUR# | 572 | 168.7 | 48.3 | **-0.050** | +0.028 | -28.6 | -38.0 | 3.5 | 162/160/250 | 60.0 | 3.39y |
| **XAUJPY** | XAUJPY# | 125 | 147.1 | 51.2 | **-0.008** | +0.015 | -1.0 | -9.6 | 3.5 | 34/36/55 | 96.0 | 0.85y |
| **AUDUSD** | AUDUSD | 651 | 202.2 | 43.5 | **-0.175** | -0.011 | -113.8 | -114.2 | 3.8 | 191/207/253 | 24.0 | 3.22y |
| **EURUSD** | EURUSD | 609 | 189.1 | 46.3 | **-0.113** | +0.007 | -68.9 | -69.4 | 3.6 | 159/176/274 | 20.0 | 3.22y |
| **USDCHF** | USDCHF | 732 | 227.3 | 44.3 | **-0.145** | +0.029 | -106.4 | -108.8 | 3.7 | 183/183/366 | 26.0 | 3.22y |
| **USDJPY** | USDJPY | 566 | 175.8 | 43.5 | **-0.142** | -0.046 | -80.4 | -84.6 | 3.9 | 143/183/240 | 25.0 | 3.22y |
| **BTCUSD** | BTCUSD# | 545 | 239.0 | 47.2 | **-0.073** | -0.034 | -39.6 | -43.8 | 3.7 | 140/171/234 | 2250.0 | 2.28y |
| **WTIUSD** | OILCash# | 523 | 154.3 | 46.8 | **-0.086** | -0.028 | -44.7 | -48.2 | 3.5 | 147/179/197 | 3.0 | 3.39y |

## Read this before trusting any number

- **mean_reversion was CUT from live routing 07-19** (P2 OOS proved −EV, 0/27 combos). This backtest is IN-SAMPLE reference / shadow data-collection only — NOT a case to re-enable it.

- Same caveats as the momentum report: no deflated-Sharpe / OOS / PBO / purge-embargo, swap excluded, in-sample multiple testing. A positive in-sample exp_R here is a hypothesis, not an edge.

- **momentum_bars** column = RANGE bars with a fade signal (overlapping); **n** = non-overlapping trades actually taken. Pairs with few RANGE spells will have small n.
