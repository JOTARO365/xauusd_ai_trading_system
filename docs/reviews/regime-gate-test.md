# A1 — Regime-gate momentum test (REFUTED)

`scripts/regime_gate_test.py` · gold H1 Donchian(48) breakout, RR2, structural SL, causal.
Hypothesis: gate momentum ON only in trending regime (Hurst>0.5) improves exp_R.

| bucket | n | exp_R | WR% | t |
|--------|---|-------|-----|---|
| ALL (ungated) | 1424 | 0.250 | 51.1 | 7.92 |
| Hurst>0.5 (trend, gated) | 377 | 0.191 | 47.7 | 3.01 |
| Hurst≤0.5 (chop) | 1047 | 0.272 | 52.3 | 7.46 |
| high-vol | 712 | 0.241 | 51.0 | 5.49 |
| trend + high-vol | 214 | 0.117 | 44.9 | 1.47 |

**Result: gate lift = −0.059 (worse).** Restricting momentum to Hurst>0.5 *lowers* exp_R; the
chop bucket is actually slightly better. Vol-gating doesn't help either.

**Why:** a breakout is already a trend signal, so conditioning on Hurst double-counts trend and
adds noise; intraday Hurst is not separable from noise near 0.5 (the exact caveat in the
quant-systematic-trading skill). Do NOT build a Hurst/vol regime gate on momentum.

Caveat: the absolute exp_R (0.25, t 7.92) here exceeds live regime_momentum (0.038) because the
config differs (Donchian48 + fixed RR2 + structural SL + re-entry, cost 0.30). Trust the *relative*
regime comparison (same config), not the absolute number, until run through the full validation harness.

**Next:** since adding a signal filter doesn't help, improvement should target RISK not signal —
A2 volatility-target sizing (cut the 46–83% drawdowns from constant-lot over-risk) and A3
MFE/MAE-based exits — rather than more entry conditions.

## Correction & config-gap resolution

Re-ran at the **exact live backtest config** (`backtest_all.bt_momentum`: brk20, sl_atr1.5, RR2,
non-overlapping `i=ei+1`, real cost) with the trend gate ON vs OFF:

| | n | exp_R | WR | t |
|--|---|-------|----|---|
| trend-GATE ON (live) | 256 | 0.125 | 37.5 | 1.37 |
| trend-GATE OFF | 817 | 0.020 | 34.0 | 0.41 |

**Two corrections to the A1 conclusion:**
1. The earlier ungated 0.25 (t 7.92) was inflated by **overlapping re-entry** (`i+=1` every bar →
   correlated trades all riding one trend). Honest non-overlapping exp_R is 0.02–0.13; the live
   0.038 (full history) is in this range — **no suppressed edge**, live config is not the problem.
2. A regime gate DOES help — but via **efficiency-ratio/ADX/vol** (`detect_regime`), not Hurst. The
   ER/ADX gate lifts exp_R 6× (0.020→0.125); Hurst (my A1) was the wrong, noisy metric. **The system
   already ships the correct gate** in `bt_momentum`/regime routing — nothing to add.

**Net:** live regime_momentum config (ER/ADX trend gate + ATR SL) is already the better choice; the
edge is genuinely thin (t~1.4) and gating captures what's there. Do not over-tune params
(multiple-testing). Improvement must come from risk/exit (A2/A3), not entry signal.
