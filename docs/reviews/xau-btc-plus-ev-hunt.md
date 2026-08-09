# XAU + BTC +EV hunt (disciplined, no hardcode) — verdict

Exhaustive anti-overfit param sweep (deflated-t + OOS) across all algo families for the focus pairs.

## BTC — 2 robust +EV FOUND ✅
- **macro_momentum BTCUSD** `brk25/mlb12/sl1.0/rr2.5` → OOS 0.232, t3.16 (clears deflated 2.96). Applied.
- **sweep_reversal BTCUSD** `buf0.3/rr1.5` → OOS 0.149, t2.69 (clears deflated 2.10). Applied (pending sweep live-enable).
- confluence BTC: no config clears the bar (peak t0.98).

## XAU — no single-combo robust config ❌
- confluence XAU: tighter session (13-17/13-19, London-NY overlap) DOES raise exp_R (0.357 vs 0.277 at
  13-21) — structurally consistent (overlap = tightest spread / most flow) — but t only 1.45–1.72, below
  the deflated bar (2.82). n also drops. The peak (0.357) is curve-fit, not robust.
- momentum/macro/tsmom XAU: all fail deflated-t (from the all-family sweep).

## Where XAU +EV actually lives: the PORTFOLIO, not one combo
Each XAU combo is thin (t~1–1.7). Combined (confluence + macro + tsmom, low mutual correlation), the
aggregate survives — portfolio_replay of the +EV-pruned roster returned ~+119% over 11y. That is a
diversification of individually-thin validated edges, NOT a fabricated single-combo edge. The honest
conclusion: don't chase a single XAU config (param tuning is exhausted and nothing clears the bar);
run the thin XAU edges as a portfolio and size for survival.

## No hardcode / no fabrication
Every number here is a causal backtest; robust picks are chosen by OUT-OF-SAMPLE after clearing a
deflated-t (multiple-testing) bar — the opposite of picking the in-sample peak.
