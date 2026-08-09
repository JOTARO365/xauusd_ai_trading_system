# Event-driven edge test (gold, NFP) — no directional edge

`scripts/event_edge_test.py` · XAUUSD H1 · 98 NFP events (first-Friday 13:30 UTC, deterministic —
no need for actual/consensus data).

| variant | n | exp_R | t | WR |
|---------|---|-------|---|-----|
| post-NFP momentum (immediate) | 98 | −0.141 | −1.08 | 31% |
| post-NFP fade | 98 | −0.024 | −0.19 | 38% |
| baseline (random H1) | 294 | −0.101 | −1.70 | 40% |
| delay 3h / hold 6h | 98 | −0.004 | −0.06 | 49% |
| delay 3h / hold 12h | 97 | +0.021 | +0.24 | 47% |
| delay 6h / hold 12h | 97 | +0.034 | +0.30 | 47% |
| pre-NFP drift (12h before) | 98 | +0.053 | +0.39 | 38% |

## Verdict: events are RISK, not a directional edge
Immediate post-NFP momentum is negative (whipsaw — worse than random baseline); waiting out the
whipsaw drifts to flat/noise; pre-NFP drift is noise. Nothing reaches t>2. Gold around NFP is a
volatility/whipsaw event, not a tradeable directional signal.

**Implication:** the existing event_engine's correct role is a RISK GATE (PRE-event flat/pause to
avoid the whipsaw) — which it already does. It should NOT be promoted to a directional edge source.
Only NFP tested (deterministic); FOMC/CPI untested (irregular dates) but the whipsaw pattern is
robust across 98 events. Consistent with the day's theme: directional edge is thin; event windows
are especially whippy. Keep event_engine as an avoid-gate, not alpha.
