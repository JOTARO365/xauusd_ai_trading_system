# Cointegration Scan — all pairs (SAT ch10 CADF, numpy)

`scripts/cointegration_scan.py` · H1 · ADF(constant) + Hurst + OU half-life + split-half robustness.
Tradeable ⇔ ADF < −2.86 (5%) AND Hurst<0.5 AND half-life 5–500 bars AND both halves pass ADF.

| pair | ADF full | Hurst | half-life | ADF ½1 | ADF ½2 | tradeable |
|------|----------|-------|-----------|--------|--------|-----------|
| XAUUSD-XAUEUR | −4.00 | 0.49 | 230 | −3.50 | −2.37 | — |
| XAUUSD-XAGUSD (LIVE) | −3.02 | 0.49 | 318 | −2.38 | −2.16 | — |
| XAUUSD-BTCUSD | −2.04 | 0.53 | 475 | −2.50 | −2.79 | — |
| XAUUSD-WTIUSD | −2.06 | 0.49 | 826 | −1.52 | −1.72 | — |
| XAUEUR-XAGUSD | −2.77 | 0.50 | 352 | −1.78 | −2.05 | — |
| others | > −2.86 | ~0.5 | 400–900 | fail | fail | — |

## Verdict: no robustly-cointegrated pair exists in the universe
- The **live XAU-XAG pairs fails**: full-sample ADF (−3.02) looks borderline-cointegrated, but
  neither half passes on its own (−2.38 / −2.16) — the prior "t=1.89 edge" was full-sample
  look-ahead. Same lesson SAT ch10 teaches: test cointegration out-of-sample, not once on all data.
- Half-lives are all 230–900 H1 bars (10–38 days) — even a truly cointegrated spread would revert
  too slowly to beat the two-leg transaction cost.

**Action:** treat the XAU-XAG pairs sleeve like the WTI/BTC edges — not validated; shadow or cut
(`PAIRS_LIVE`), don't add capital to it. Stat-arb is not a real alpha source here. The CADF scanner
did its job: it refuted a strategy that was running live.

## Full universe (55 pairs, log-price) — update

Extended to the full collected universe (11 symbols → 55 pairs) and switched to **log-price**
(raw-price OLS produced scale artifacts, e.g. XAUJPY-USDCHF ADF −295 / β −3.8M — spurious).

Nominal 5% passers (log-price): **GBPUSD-USDJPY** (ADF −3.70, halves −3.01/−3.78, HL 195),
**GBPUSD-WTIUSD** (−3.68, −3.08/−3.00, HL 186), **AUDUSD-WTIUSD** (−3.00, −3.15/−3.15, HL 287).

**Multiple-testing verdict — indistinguishable from noise:**
- 55 pairs tested → ~2.8 false positives expected at 5% by chance. We found exactly 3 → the
  passing count equals the noise rate; it is NOT evidence of real cointegration.
- Bonferroni (α = 0.05/55 → ADF crit ≈ −4.0+): none of the three clear it (best is −3.70).
- Gold-complex pairs (XAU-XAG, XAU-XAUEUR, …) all fail regardless — no gold stat-arb.
- Half-lives 186–287 H1 bars (8–12 days) — slow enough that two-leg cost erodes any thin edge.

**Conclusion:** no pair survives a multiple-testing-honest bar. Only **AUDUSD-WTIUSD** has an
economic rationale (AUD is a commodity currency co-moving with oil) and is worth a *shadow* test
to collect forward OOS — not a live deployment. Stat-arb is not a validated alpha source in this
universe; the live XAU-XAG pairs should be shadowed/cut.
