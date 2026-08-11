# S/R Entry Gate — evaluation (2026-08-11)

params (lookback,pivot,block_atr,min_touches,cluster_atr) = `(60, 3, 0.5, 2, 0.3)`

เกณฑ์เปิด live: gated `exp_R>0 · OOS≥0 · t≥2 · n≥80 · exp_R_on≥exp_R_off · n_on≥0.15·n_off`

| ✓ | algo | คู่ | TF | OFF exp_R/t/n | ON exp_R/t/n | Δexp_R | verdict |
|---|------|-----|----|----|----|----|----|
| ✓ | macro_momentum | XAUUSD | H4 | +0.114/+1.91/595 | +0.120/+2.00/589 | +0.006 | ผ่าน (gate ช่วย + robust) |
|  | confluence_15m | AUDUSD | M15 | -0.279/-2.92/225 | -0.274/-2.78/212 | +0.005 | exp_R_on -0.2737≤0 |
|  | confluence_15m | BTCUSD | M15 | +0.083/+0.56/97 | +0.051/+0.33/92 | -0.032 | t_on 0.33<2 |
|  | confluence_15m | EURUSD | M15 | -0.256/-3.23/302 | -0.279/-3.50/295 | -0.024 | exp_R_on -0.2794≤0 |
|  | confluence_15m | GBPUSD | M15 | -0.104/-1.16/255 | -0.093/-1.01/247 | +0.011 | exp_R_on -0.0926≤0 |
|  | confluence_15m | USDCHF | M15 | -0.276/-1.27/43 | -0.342/-1.53/40 | -0.066 | n_on 40<80 |
|  | confluence_15m | USDJPY | M15 | -0.398/-2.78/84 | -0.390/-2.69/83 | +0.009 | exp_R_on -0.3896≤0 |
|  | confluence_15m | WTIUSD | M15 | -0.293/-2.50/142 | -0.297/-2.46/133 | -0.004 | exp_R_on -0.297≤0 |
|  | confluence_15m | XAGUSD | M15 | -0.244/-2.46/221 | -0.231/-2.31/218 | +0.013 | exp_R_on -0.2311≤0 |
|  | confluence_15m | XAUEUR | M15 | +0.081/+0.47/74 | +0.106/+0.60/70 | +0.025 | n_on 70<80 |
|  | confluence_15m | XAUJPY | M15 | +0.139/+0.67/52 | +0.162/+0.77/51 | +0.023 | n_on 51<80 |
|  | confluence_15m | XAUUSD | M15 | +0.126/+1.31/233 | +0.109/+1.12/226 | -0.017 | t_on 1.12<2 |
|  | macro_momentum | AUDUSD | H4 | -0.068/-1.37/794 | -0.050/-0.98/779 | +0.019 | exp_R_on -0.0495≤0 |
|  | macro_momentum | BTCUSD | H4 | +0.070/+0.77/362 | +0.054/+0.60/352 | -0.015 | t_on 0.6<2 |
|  | macro_momentum | EURUSD | H4 | -0.087/-1.95/963 | -0.081/-1.77/934 | +0.007 | exp_R_on -0.0806≤0 |
|  | macro_momentum | GBPUSD | H4 | +0.029/+0.58/823 | +0.024/+0.47/810 | -0.005 | OOS_on -0.0721<0 |
|  | macro_momentum | USDCHF | H4 | -0.023/-0.23/200 | -0.017/-0.16/190 | +0.006 | exp_R_on -0.0165≤0 |
|  | macro_momentum | USDJPY | H4 | -0.080/-1.17/417 | -0.079/-1.14/407 | +0.002 | exp_R_on -0.0788≤0 |
|  | macro_momentum | WTIUSD | H4 | -0.042/-0.63/463 | -0.059/-0.90/453 | -0.018 | exp_R_on -0.0593≤0 |
|  | macro_momentum | XAGUSD | H4 | -0.152/-2.26/456 | -0.136/-2.00/447 | +0.016 | exp_R_on -0.136≤0 |
|  | macro_momentum | XAUEUR | H4 | +0.120/+1.36/278 | +0.122/+1.37/275 | +0.002 | t_on 1.37<2 |
|  | macro_momentum | XAUJPY | H4 | — | — | — | no data |
|  | mean_reversion | AUDUSD | H1 | -0.135/-6.38/1537 | -0.132/-6.20/1505 | +0.002 | exp_R_on -0.1324≤0 |
|  | mean_reversion | BTCUSD | H1 | -0.123/-5.78/1410 | -0.121/-5.64/1388 | +0.002 | exp_R_on -0.1213≤0 |
|  | mean_reversion | EURUSD | H1 | -0.067/-3.10/1469 | -0.062/-2.87/1447 | +0.004 | exp_R_on -0.0622≤0 |
|  | mean_reversion | GBPUSD | H1 | -0.051/-2.44/1508 | -0.053/-2.51/1487 | -0.002 | exp_R_on -0.0527≤0 |
|  | mean_reversion | USDCHF | H1 | -0.103/-5.37/1717 | -0.098/-5.05/1681 | +0.005 | exp_R_on -0.0977≤0 |
|  | mean_reversion | USDJPY | H1 | -0.072/-3.47/1476 | -0.071/-3.37/1454 | +0.002 | exp_R_on -0.0706≤0 |
|  | mean_reversion | WTIUSD | H1 | -0.114/-4.91/1333 | -0.110/-4.67/1300 | +0.004 | exp_R_on -0.1097≤0 |
|  | mean_reversion | XAGUSD | H1 | -0.433/-19.95/1449 | -0.427/-19.39/1418 | +0.006 | exp_R_on -0.4269≤0 |
|  | mean_reversion | XAUEUR | H1 | -0.140/-6.81/1540 | -0.141/-6.82/1519 | -0.001 | exp_R_on -0.1415≤0 |
|  | mean_reversion | XAUJPY | H1 | -0.041/-0.57/127 | -0.039/-0.53/123 | +0.001 | exp_R_on -0.0393≤0 |
|  | mean_reversion | XAUUSD | H1 | -0.088/-4.11/1392 | -0.087/-4.02/1362 | +0.001 | exp_R_on -0.0868≤0 |
|  | regime_momentum | AUDUSD | H1 | -0.104/-1.81/597 | -0.111/-1.93/595 | -0.007 | exp_R_on -0.111≤0 |
|  | regime_momentum | BTCUSD | H1 | -0.035/-0.56/526 | -0.029/-0.47/523 | +0.006 | exp_R_on -0.0291≤0 |
|  | regime_momentum | EURUSD | H1 | -0.100/-1.76/604 | -0.095/-1.67/601 | +0.005 | exp_R_on -0.0952≤0 |
|  | regime_momentum | GBPUSD | H1 | -0.073/-1.29/613 | -0.077/-1.35/603 | -0.004 | exp_R_on -0.0772≤0 |
|  | regime_momentum | USDCHF | H1 | -0.175/-3.00/563 | -0.171/-2.90/554 | +0.004 | exp_R_on -0.1713≤0 |
|  | regime_momentum | USDJPY | H1 | -0.046/-0.81/631 | -0.041/-0.72/628 | +0.005 | exp_R_on -0.0412≤0 |
|  | regime_momentum | WTIUSD | H1 | -0.081/-1.49/679 | -0.070/-1.28/669 | +0.011 | exp_R_on -0.0701≤0 |
|  | regime_momentum | XAGUSD | H1 | -0.369/-6.20/583 | -0.358/-5.97/577 | +0.011 | exp_R_on -0.3577≤0 |
|  | regime_momentum | XAUEUR | H1 | -0.041/-0.65/511 | -0.047/-0.74/511 | -0.006 | exp_R_on -0.047≤0 |
|  | regime_momentum | XAUJPY | H1 | +0.245/+1.26/59 | +0.245/+1.26/59 | +0.000 | n_on 59<80 |
|  | regime_momentum | XAUUSD | H1 | +0.025/+0.40/518 | +0.030/+0.47/513 | +0.005 | t_on 0.47<2 |
|  | regime_momentum_fvg | AUDUSD | H1 | -0.157/-2.58/518 | -0.165/-2.71/516 | -0.008 | exp_R_on -0.1651≤0 |
|  | regime_momentum_fvg | BTCUSD | H1 | -0.043/-0.66/475 | -0.037/-0.56/472 | +0.006 | exp_R_on -0.0366≤0 |
|  | regime_momentum_fvg | EURUSD | H1 | -0.141/-2.37/543 | -0.138/-2.31/541 | +0.003 | exp_R_on -0.1377≤0 |
|  | regime_momentum_fvg | GBPUSD | H1 | -0.049/-0.82/554 | -0.051/-0.84/543 | -0.002 | exp_R_on -0.0511≤0 |
|  | regime_momentum_fvg | USDCHF | H1 | -0.218/-3.61/512 | -0.204/-3.33/504 | +0.014 | exp_R_on -0.204≤0 |
|  | regime_momentum_fvg | USDJPY | H1 | -0.035/-0.59/584 | -0.031/-0.53/582 | +0.004 | exp_R_on -0.0312≤0 |
|  | regime_momentum_fvg | WTIUSD | H1 | -0.110/-1.95/616 | -0.101/-1.77/607 | +0.009 | exp_R_on -0.1011≤0 |
|  | regime_momentum_fvg | XAGUSD | H1 | -0.326/-5.05/507 | -0.315/-4.84/502 | +0.011 | exp_R_on -0.3146≤0 |
|  | regime_momentum_fvg | XAUEUR | H1 | -0.078/-1.19/469 | -0.082/-1.25/468 | -0.004 | exp_R_on -0.0824≤0 |
|  | regime_momentum_fvg | XAUJPY | H1 | +0.284/+1.40/55 | +0.284/+1.40/55 | +0.000 | n_on 55<80 |
|  | regime_momentum_fvg | XAUUSD | H1 | +0.046/+0.69/470 | +0.051/+0.76/465 | +0.005 | t_on 0.76<2 |
|  | sweep_reversal | AUDUSD | H1 | -0.094/-2.95/1492 | -0.090/-2.81/1492 | +0.004 | exp_R_on -0.0897≤0 |
|  | sweep_reversal | BTCUSD | H1 | +0.032/+0.92/1332 | +0.019/+0.55/1317 | -0.013 | t_on 0.55<2 |
|  | sweep_reversal | EURUSD | H1 | -0.108/-3.33/1416 | -0.119/-3.67/1413 | -0.011 | exp_R_on -0.1186≤0 |
|  | sweep_reversal | GBPUSD | H1 | -0.096/-2.96/1409 | -0.097/-2.97/1401 | -0.001 | exp_R_on -0.097≤0 |
|  | sweep_reversal | USDCHF | H1 | -0.168/-5.31/1483 | -0.159/-4.99/1467 | +0.009 | exp_R_on -0.1586≤0 |
|  | sweep_reversal | USDJPY | H1 | -0.163/-4.90/1318 | -0.175/-5.26/1313 | -0.012 | exp_R_on -0.1751≤0 |
|  | sweep_reversal | WTIUSD | H1 | -0.039/-1.17/1395 | -0.042/-1.27/1382 | -0.003 | exp_R_on -0.0421≤0 |
|  | sweep_reversal | XAGUSD | H1 | -0.456/-13.28/1361 | -0.458/-13.27/1346 | -0.002 | exp_R_on -0.4584≤0 |
|  | sweep_reversal | XAUEUR | H1 | -0.150/-4.69/1465 | -0.151/-4.72/1461 | -0.002 | exp_R_on -0.1514≤0 |
|  | sweep_reversal | XAUJPY | H1 | -0.026/-0.24/131 | -0.026/-0.24/131 | -0.000 | exp_R_on -0.0261≤0 |
|  | sweep_reversal | XAUUSD | H1 | -0.049/-1.46/1339 | -0.045/-1.33/1335 | +0.005 | exp_R_on -0.0446≤0 |

**เปิด live 1 combo:** macro_momentum|XAUUSD
