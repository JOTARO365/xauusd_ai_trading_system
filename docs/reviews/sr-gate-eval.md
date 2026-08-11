# S/R Entry Gate — evaluation (2026-08-11)

params (lookback,pivot,block_atr,min_touches,cluster_atr) = `(60, 3, 0.5, 2, 0.3)`

เกณฑ์เปิด live: gated `exp_R>0 · OOS≥0 · t≥2 · n≥80 · exp_R_on≥exp_R_off · n_on≥0.15·n_off`

| ✓ | algo | คู่ | TF | OFF exp_R/t/n | ON exp_R/t/n | Δexp_R | verdict |
|---|------|-----|----|----|----|----|----|
| ✓ | macro_momentum | XAUUSD | H4 | +0.114/+1.91/595 | +0.120/+2.00/589 | +0.006 | ผ่าน (gate ช่วย + robust) |
|  | confluence_15m | AUDUSD | M15 | -0.279/-2.92/225 | -0.274/-2.78/212 | +0.005 | exp_R_on -0.2737≤0 |
|  | confluence_15m | BTCUSD | M15 | +0.070/+0.47/98 | +0.038/+0.25/93 | -0.033 | t_on 0.25<2 |
|  | confluence_15m | EURUSD | M15 | -0.256/-3.23/302 | -0.279/-3.50/295 | -0.024 | exp_R_on -0.2794≤0 |
|  | confluence_15m | GBPUSD | M15 | -0.198/-2.20/255 | -0.186/-2.03/247 | +0.012 | exp_R_on -0.186≤0 |
|  | confluence_15m | USDCHF | M15 | -0.301/-1.41/44 | -0.367/-1.68/41 | -0.066 | n_on 41<80 |
|  | confluence_15m | USDJPY | M15 | -0.409/-2.85/84 | -0.400/-2.76/83 | +0.009 | exp_R_on -0.4004≤0 |
|  | confluence_15m | WTIUSD | M15 | -0.299/-2.54/140 | -0.304/-2.50/131 | -0.005 | exp_R_on -0.3043≤0 |
|  | confluence_15m | XAGUSD | M15 | -0.248/-2.51/222 | -0.236/-2.36/219 | +0.013 | exp_R_on -0.2357≤0 |
|  | confluence_15m | XAUEUR | M15 | +0.065/+0.38/75 | +0.089/+0.51/71 | +0.024 | n_on 71<80 |
|  | confluence_15m | XAUJPY | M15 | +0.171/+0.83/53 | +0.195/+0.94/52 | +0.023 | n_on 52<80 |
|  | confluence_15m | XAUUSD | M15 | +0.121/+1.26/234 | +0.104/+1.07/227 | -0.017 | t_on 1.07<2 |
|  | macro_momentum | AUDUSD | H4 | -0.068/-1.37/794 | -0.050/-0.98/779 | +0.019 | exp_R_on -0.0495≤0 |
|  | macro_momentum | BTCUSD | H4 | +0.070/+0.77/362 | +0.054/+0.60/352 | -0.015 | t_on 0.6<2 |
|  | macro_momentum | EURUSD | H4 | -0.087/-1.95/963 | -0.081/-1.77/934 | +0.007 | exp_R_on -0.0806≤0 |
|  | macro_momentum | GBPUSD | H4 | +0.016/+0.33/823 | +0.011/+0.22/810 | -0.005 | OOS_on -0.0868<0 |
|  | macro_momentum | USDCHF | H4 | -0.023/-0.23/200 | -0.017/-0.16/190 | +0.006 | exp_R_on -0.0165≤0 |
|  | macro_momentum | USDJPY | H4 | -0.082/-1.20/417 | -0.081/-1.16/407 | +0.002 | exp_R_on -0.0805≤0 |
|  | macro_momentum | WTIUSD | H4 | -0.041/-0.62/463 | -0.058/-0.88/453 | -0.018 | exp_R_on -0.0584≤0 |
|  | macro_momentum | XAGUSD | H4 | -0.151/-2.25/456 | -0.135/-1.99/447 | +0.016 | exp_R_on -0.1354≤0 |
|  | macro_momentum | XAUEUR | H4 | +0.120/+1.36/278 | +0.122/+1.37/275 | +0.002 | t_on 1.37<2 |
|  | macro_momentum | XAUJPY | H4 | — | — | — | no data |
|  | mean_reversion | AUDUSD | H1 | -0.134/-6.34/1540 | -0.131/-6.16/1508 | +0.002 | exp_R_on -0.1314≤0 |
|  | mean_reversion | BTCUSD | H1 | -0.123/-5.78/1410 | -0.121/-5.64/1388 | +0.002 | exp_R_on -0.1213≤0 |
|  | mean_reversion | EURUSD | H1 | -0.067/-3.10/1469 | -0.062/-2.87/1447 | +0.004 | exp_R_on -0.0622≤0 |
|  | mean_reversion | GBPUSD | H1 | -0.083/-3.96/1509 | -0.084/-4.02/1488 | -0.002 | exp_R_on -0.0843≤0 |
|  | mean_reversion | USDCHF | H1 | -0.102/-5.35/1719 | -0.097/-5.03/1683 | +0.005 | exp_R_on -0.0972≤0 |
|  | mean_reversion | USDJPY | H1 | -0.077/-3.72/1475 | -0.076/-3.61/1453 | +0.002 | exp_R_on -0.0759≤0 |
|  | mean_reversion | WTIUSD | H1 | -0.114/-4.91/1333 | -0.110/-4.67/1300 | +0.004 | exp_R_on -0.1097≤0 |
|  | mean_reversion | XAGUSD | H1 | -0.433/-19.95/1449 | -0.427/-19.39/1418 | +0.006 | exp_R_on -0.4269≤0 |
|  | mean_reversion | XAUEUR | H1 | -0.140/-6.81/1540 | -0.141/-6.82/1519 | -0.001 | exp_R_on -0.1415≤0 |
|  | mean_reversion | XAUJPY | H1 | -0.041/-0.57/127 | -0.040/-0.54/123 | +0.001 | exp_R_on -0.0396≤0 |
|  | mean_reversion | XAUUSD | H1 | -0.087/-4.08/1391 | -0.086/-3.98/1361 | +0.001 | exp_R_on -0.0861≤0 |
|  | regime_momentum | AUDUSD | H1 | -0.104/-1.81/597 | -0.111/-1.93/595 | -0.007 | exp_R_on -0.111≤0 |
|  | regime_momentum | BTCUSD | H1 | -0.036/-0.59/526 | -0.031/-0.49/523 | +0.006 | exp_R_on -0.0308≤0 |
|  | regime_momentum | EURUSD | H1 | -0.098/-1.73/603 | -0.094/-1.64/600 | +0.005 | exp_R_on -0.0936≤0 |
|  | regime_momentum | GBPUSD | H1 | -0.104/-1.83/613 | -0.108/-1.88/603 | -0.004 | exp_R_on -0.1077≤0 |
|  | regime_momentum | USDCHF | H1 | -0.175/-3.00/563 | -0.171/-2.90/554 | +0.004 | exp_R_on -0.1713≤0 |
|  | regime_momentum | USDJPY | H1 | -0.051/-0.89/631 | -0.046/-0.80/628 | +0.005 | exp_R_on -0.0457≤0 |
|  | regime_momentum | WTIUSD | H1 | -0.081/-1.49/679 | -0.070/-1.28/669 | +0.011 | exp_R_on -0.0701≤0 |
|  | regime_momentum | XAGUSD | H1 | -0.369/-6.20/583 | -0.358/-5.97/577 | +0.011 | exp_R_on -0.3577≤0 |
|  | regime_momentum | XAUEUR | H1 | -0.047/-0.74/511 | -0.053/-0.83/511 | -0.006 | exp_R_on -0.0529≤0 |
|  | regime_momentum | XAUJPY | H1 | +0.245/+1.26/59 | +0.245/+1.26/59 | +0.000 | n_on 59<80 |
|  | regime_momentum | XAUUSD | H1 | +0.025/+0.40/518 | +0.030/+0.47/513 | +0.005 | t_on 0.47<2 |
|  | regime_momentum_fvg | AUDUSD | H1 | -0.157/-2.58/518 | -0.165/-2.71/516 | -0.008 | exp_R_on -0.1651≤0 |
|  | regime_momentum_fvg | BTCUSD | H1 | -0.045/-0.69/475 | -0.038/-0.59/472 | +0.006 | exp_R_on -0.0384≤0 |
|  | regime_momentum_fvg | EURUSD | H1 | -0.139/-2.34/542 | -0.136/-2.28/540 | +0.003 | exp_R_on -0.136≤0 |
|  | regime_momentum_fvg | GBPUSD | H1 | -0.079/-1.32/554 | -0.081/-1.34/543 | -0.002 | exp_R_on -0.0812≤0 |
|  | regime_momentum_fvg | USDCHF | H1 | -0.218/-3.61/512 | -0.204/-3.33/504 | +0.014 | exp_R_on -0.204≤0 |
|  | regime_momentum_fvg | USDJPY | H1 | -0.039/-0.67/584 | -0.036/-0.60/582 | +0.004 | exp_R_on -0.0358≤0 |
|  | regime_momentum_fvg | WTIUSD | H1 | -0.110/-1.95/616 | -0.101/-1.77/607 | +0.009 | exp_R_on -0.101≤0 |
|  | regime_momentum_fvg | XAGUSD | H1 | -0.326/-5.05/507 | -0.315/-4.84/502 | +0.011 | exp_R_on -0.3146≤0 |
|  | regime_momentum_fvg | XAUEUR | H1 | -0.085/-1.29/469 | -0.089/-1.35/468 | -0.004 | exp_R_on -0.0888≤0 |
|  | regime_momentum_fvg | XAUJPY | H1 | +0.283/+1.40/55 | +0.283/+1.40/55 | +0.000 | n_on 55<80 |
|  | regime_momentum_fvg | XAUUSD | H1 | +0.046/+0.69/470 | +0.051/+0.76/465 | +0.005 | t_on 0.76<2 |
|  | sweep_reversal | AUDUSD | H1 | -0.093/-2.91/1491 | -0.089/-2.78/1491 | +0.004 | exp_R_on -0.0886≤0 |
|  | sweep_reversal | BTCUSD | H1 | +0.031/+0.90/1331 | +0.018/+0.53/1316 | -0.013 | t_on 0.53<2 |
|  | sweep_reversal | EURUSD | H1 | -0.108/-3.33/1417 | -0.119/-3.67/1414 | -0.011 | exp_R_on -0.1186≤0 |
|  | sweep_reversal | GBPUSD | H1 | -0.134/-4.12/1408 | -0.135/-4.13/1400 | -0.001 | exp_R_on -0.1351≤0 |
|  | sweep_reversal | USDCHF | H1 | -0.169/-5.35/1485 | -0.160/-5.03/1469 | +0.009 | exp_R_on -0.1598≤0 |
|  | sweep_reversal | USDJPY | H1 | -0.167/-5.02/1319 | -0.179/-5.38/1314 | -0.012 | exp_R_on -0.1791≤0 |
|  | sweep_reversal | WTIUSD | H1 | -0.039/-1.19/1396 | -0.043/-1.28/1383 | -0.003 | exp_R_on -0.0426≤0 |
|  | sweep_reversal | XAGUSD | H1 | -0.456/-13.28/1361 | -0.458/-13.27/1346 | -0.002 | exp_R_on -0.4584≤0 |
|  | sweep_reversal | XAUEUR | H1 | -0.148/-4.62/1465 | -0.149/-4.66/1461 | -0.002 | exp_R_on -0.1494≤0 |
|  | sweep_reversal | XAUJPY | H1 | -0.028/-0.26/131 | -0.028/-0.26/131 | -0.000 | exp_R_on -0.0278≤0 |
|  | sweep_reversal | XAUUSD | H1 | -0.049/-1.47/1339 | -0.045/-1.33/1335 | +0.005 | exp_R_on -0.0447≤0 |

**เปิด live 1 combo:** macro_momentum|XAUUSD

## Global gate aggregate (65 combo มีผล)

- Δexp_R > 0 (ดีขึ้น): **39** · < 0 (แย่ลง): **23** · ~เท่าเดิม: 3
- Δexp_R เฉลี่ยทั้งพอร์ต: **+0.0004 R**
- flip เป็น +EV เพราะ gate: (ไม่มี)
- หลุด +EV เพราะ gate: (ไม่มี)
