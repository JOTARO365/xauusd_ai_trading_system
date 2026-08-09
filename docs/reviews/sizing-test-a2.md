# A2 — Volatility-target / fixed-fractional sizing

`scripts/sizing_test.py` · gold momentum (bt_momentum config, ATR SL 1.5, RR2, trend-gate) · n=256.

| sizing | start | final | ret% | maxDD% | Sharpe* |
|--------|-------|-------|------|--------|---------|
| fixed lot 0.02 (live) | 44k | 70,093 | +59 | 23.7 | 1.19 |
| fixed-fractional 1% | 44k | 56,381 | +28 | 15.3 | 0.94 |
| fixed lot 0.02 | 3k | 29,093 | — | 90.5 | 2.06 |
| fixed-fractional 1% | 3k | 16,046 | — | 58.0 | 1.79 |

## Read
- Fixed-fractional cuts max drawdown materially (24→15% at 44k; **90→58% at 3k** — the difference
  between near-ruin and survivable). That is the A2 goal: constant % risk per trade.
- It gives up return in a bull sample (fixed lot 0.02 bets bigger → more return AND more DD). The
  higher fixed-lot Sharpe here is a bull-sample artifact (bigger bets rewarded on the way up), not a
  real edge of fixed sizing.
- Caveat: this test used a tight ATR SL, so FF floors to min-lot at higher equity. The real FF
  benefit is larger against the LIVE **structural** SL (wide, $30–90): fixed lot there swings risk
  1,984–5,950฿/trade (3×), while FF holds it constant.

## Recommendation
Switch live sizing from fixed-lot to **fixed-fractional (risk % of equity, on the actual SL
distance)** — trades some bull-market upside for much lower drawdown, especially on small accounts,
and composes with the capital-affordability gate. This is a money-management change (iron rule):
needs explicit approval + staged rollout (shadow → one algo → all), not a silent flip.
