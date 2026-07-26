# Shadow Backtest — regime momentum-breakout, per pair (net of measured spread)

_generated 2026-07-25T00:24Z · H1 · SL-first · max_hold 48 bars · non-overlapping single-position_


| pair | broker | n | trades/yr | WR% | exp_R (net) | exp_R gross | sum_R | maxDD_R | avg hold | TP/SL/TO | cost_pips | span |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|--:|--:|
| **XAUUSD** | GOLD# | 525 | 155.3 | 49.7 | **-0.043** | -0.043 | -22.8 | -29.6 | 3.6 | 129/156/240 | 30.0 | 3.38y |
| **XAGUSD** | SILVER# | 551 | 163.0 | 35.0 | **-0.341** | -0.341 | -187.7 | -188.3 | 3.5 | 120/181/250 | 51.0 | 3.38y |
| **XAUEUR** | XAUEUR# | 572 | 168.7 | 48.3 | **-0.050** | -0.050 | -28.6 | -38.0 | 3.5 | 162/160/250 | 60.0 | 3.39y |
| **XAUJPY** | XAUJPY# | 125 | 147.1 | 51.2 | **-0.007** | -0.007 | -0.9 | -9.6 | 3.5 | 34/36/55 | 95.0 | 0.85y |
| **AUDUSD** | AUDUSD | 651 | 202.2 | 43.5 | **-0.175** | -0.175 | -113.8 | -114.2 | 3.8 | 191/207/253 | 24.0 | 3.22y |
| **EURUSD** | EURUSD | 609 | 189.1 | 46.3 | **-0.113** | -0.113 | -68.9 | -69.4 | 3.6 | 159/176/274 | 20.0 | 3.22y |
| **USDCHF** | USDCHF | 732 | 227.3 | 44.3 | **-0.144** | -0.144 | -105.7 | -108.0 | 3.7 | 183/183/366 | 26.0 | 3.22y |
| **USDJPY** | USDJPY | 566 | 175.8 | 43.5 | **-0.142** | -0.142 | -80.4 | -84.6 | 3.9 | 143/183/240 | 25.0 | 3.22y |
| **BTCUSD** | BTCUSD# | 545 | 239.0 | 47.2 | **-0.073** | -0.073 | -39.6 | -43.8 | 3.7 | 140/171/234 | 2250.0 | 2.28y |
| **WTIUSD** | OILCash# | 522 | 154.0 | 46.7 | **-0.086** | -0.086 | -45.0 | -48.2 | 3.5 | 147/179/196 | 3.0 | 3.39y |

## Read this before trusting any number

- **In-sample historical replay — NOT validated edge.** No deflated-Sharpe, no OOS/PBO, no purge/embargo. With one strategy across 10 pairs this is 10 trials of multiple testing; the best-looking pair is the most likely to be noise.

- **exp_R (net)** already subtracts each pair's measured median spread (cost_pips). A pair is only interesting if **exp_R net > 0 with a usable sample** (rule of thumb n≥100). exp_R gross shows how much of the edge the spread eats.

- **Swap excluded** (D3). H1 momentum holds ~avg-hold bars; multi-day holds accrue swap (gold ≈ −81/lot/night) — real net is WORSE than shown. A measured swap table is required before LIVE.

- **Prior finding stands:** XAUUSD momentum showed no directional edge OOS. Treat any positive in-sample exp_R here as a hypothesis to be confirmed by forward SHADOW (n≥100, ≥2 regimes), not a green light.

- **momentum_bars** = every bar in a TREND breakout (overlapping); **n** = the non-overlapping trades actually taken (one position at a time). WR/exp_R are on n.
