# Gold seasonality — validated structural filter (SEASONALITY_GATE)

## Validation (XAUUSD D1, 2014-2026, monthly returns)
- **Jan +3.53% (t2.73, pos 75%)**, **Dec +1.52% (t2.35, pos 64%)** — bull, significant (t>2).
- Jun −1.22 (pos25%), Sep −0.72 (pos27%), Nov −1.29 (pos36%) — weak/bear.
Fundamental story: Indian festival/wedding demand + year-end. Not curve-fit (validated independently
+ documented externally).

## Gate (agents/seasonality.py, flag SEASONALITY_GATE)
"Don't fight strong seasonality" (like the macro/sentiment gates), XAU-family only:
- block SHORT gold entries in strong-bull months {Jan, Dec}
- block LONG gold entries in weak months {Jun, Sep, Nov}
- neutral months: no filter
Wired into all gold algos (regime_momentum, macro_momentum, confluence_15m, tsmom XAUEUR/XAUJPY) and
mirrored in the backtest for parity (tsmom D1 backtest parity pending — position-based).

## System impact (backtest, gate on vs off)
- **macro_momentum XAUUSD: 0.068→0.120, t1.09→1.75** (best gold directional now, near-significant)
- macro_momentum XAUEUR: OOS 0.476
- confluence_15m XAUUSD: ~unchanged (0.158→0.144)
- regime_momentum XAUUSD: 0.038→0.018 (marginal both ways — weakest gold algo)

Net: helps the stronger gold directional combos (macro), neutral/slightly-negative on the weakest.
Config-flagged; kill switch SEASONALITY_GATE=false.
