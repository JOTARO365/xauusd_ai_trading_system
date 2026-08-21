# RICH S/R gate — evaluation (2026-08-21)

params=`(60, 3, 0.5, 2, 0.3)` · rich(min_bounce,min_tests)=`(55.0, 3)`

block เฉพาะโซนที่ **causal bounce_pct ≥ min + tests ≥ min** (ไม่ใช่แค่มี swing)

| ✓ | algo | คู่ | TF | OFF exp_R/t/n | rich-ON exp_R/t/n | Δexp_R | verdict |
|---|------|-----|----|----|----|----|----|
| ✓ | macro_momentum | XAUUSD | H4 | +0.237/+2.09/354 | +0.241/+2.12/353 | +0.004 | ผ่าน (rich gate ช่วย + robust) |
|  | macro_momentum | AUDUSD | H4 | -0.079/-1.25/487 | -0.079/-1.25/487 | +0.000 | exp_R_on -0.0791≤0 |
|  | macro_momentum | BTCUSD | H4 | +0.080/+0.89/365 | +0.064/+0.71/364 | -0.016 | t_on 0.71<2 |
|  | macro_momentum | EURUSD | H4 | -0.057/-1.41/1199 | -0.056/-1.39/1198 | +0.001 | exp_R_on -0.0564≤0 |
|  | macro_momentum | GBPUSD | H4 | -0.048/-1.10/1032 | -0.050/-1.14/1031 | -0.002 | exp_R_on -0.0499≤0 |
|  | macro_momentum | USDCHF | H4 | -0.013/-0.14/234 | -0.013/-0.14/234 | +0.000 | exp_R_on -0.0133≤0 |
|  | macro_momentum | USDJPY | H4 | -0.049/-0.80/535 | -0.045/-0.74/533 | +0.004 | exp_R_on -0.0449≤0 |
|  | macro_momentum | WTIUSD | H4 | -0.038/-0.58/464 | -0.036/-0.54/463 | +0.002 | exp_R_on -0.0357≤0 |
|  | macro_momentum | XAGUSD | H4 | -0.115/-1.63/413 | -0.115/-1.63/413 | +0.000 | exp_R_on -0.1153≤0 |
|  | macro_momentum | XAUEUR | H4 | +0.158/+1.10/217 | +0.158/+1.10/217 | +0.000 | t_on 1.1<2 |
|  | macro_momentum | XAUJPY | H4 | — | — | — | no data |
|  | mean_reversion | AUDUSD | H1 | -0.134/-6.39/1547 | -0.134/-6.39/1547 | +0.000 | exp_R_on -0.1344≤0 |
|  | mean_reversion | BTCUSD | H1 | -0.122/-5.74/1416 | -0.122/-5.74/1416 | +0.000 | exp_R_on -0.122≤0 |
|  | mean_reversion | EURUSD | H1 | -0.061/-2.87/1475 | -0.061/-2.87/1475 | +0.000 | exp_R_on -0.0614≤0 |
|  | mean_reversion | GBPUSD | H1 | -0.048/-2.29/1523 | -0.048/-2.29/1523 | +0.000 | exp_R_on -0.0475≤0 |
|  | mean_reversion | USDCHF | H1 | -0.098/-5.12/1727 | -0.098/-5.14/1726 | -0.001 | exp_R_on -0.0981≤0 |
|  | mean_reversion | USDJPY | H1 | -0.059/-2.84/1468 | -0.059/-2.84/1468 | +0.000 | exp_R_on -0.0595≤0 |
|  | mean_reversion | WTIUSD | H1 | -0.114/-4.89/1329 | -0.114/-4.90/1328 | -0.000 | exp_R_on -0.114≤0 |
|  | mean_reversion | XAGUSD | H1 | -0.434/-20.21/1467 | -0.434/-20.21/1467 | +0.000 | exp_R_on -0.4341≤0 |
|  | mean_reversion | XAUEUR | H1 | -0.141/-6.83/1544 | -0.141/-6.83/1544 | +0.000 | exp_R_on -0.1405≤0 |
|  | mean_reversion | XAUJPY | H1 | -0.035/-0.49/131 | -0.035/-0.49/131 | +0.000 | exp_R_on -0.0349≤0 |
|  | mean_reversion | XAUUSD | H1 | -0.087/-4.08/1399 | -0.087/-4.09/1398 | -0.000 | exp_R_on -0.0873≤0 |
|  | regime_momentum | AUDUSD | H1 | -0.101/-1.75/595 | -0.106/-1.84/595 | -0.005 | exp_R_on -0.1063≤0 |
|  | regime_momentum | BTCUSD | H1 | -0.037/-0.60/527 | -0.035/-0.57/526 | +0.002 | exp_R_on -0.0354≤0 |
|  | regime_momentum | EURUSD | H1 | -0.093/-1.64/603 | -0.093/-1.64/603 | +0.000 | exp_R_on -0.0935≤0 |
|  | regime_momentum | GBPUSD | H1 | -0.081/-1.43/614 | -0.085/-1.49/613 | -0.003 | exp_R_on -0.0845≤0 |
|  | regime_momentum | USDCHF | H1 | -0.176/-2.99/557 | -0.172/-2.93/555 | +0.003 | exp_R_on -0.1722≤0 |
|  | regime_momentum | USDJPY | H1 | -0.065/-1.17/640 | -0.065/-1.17/640 | +0.000 | exp_R_on -0.0654≤0 |
|  | regime_momentum | WTIUSD | H1 | -0.082/-1.51/680 | -0.080/-1.48/679 | +0.002 | exp_R_on -0.0804≤0 |
|  | regime_momentum | XAGUSD | H1 | -0.364/-6.12/579 | -0.360/-6.04/577 | +0.004 | exp_R_on -0.3597≤0 |
|  | regime_momentum | XAUEUR | H1 | -0.050/-0.79/510 | -0.056/-0.88/510 | -0.006 | exp_R_on -0.0562≤0 |
|  | regime_momentum | XAUJPY | H1 | +0.224/+1.17/60 | +0.224/+1.17/60 | +0.000 | n_on 60<80 |
|  | regime_momentum | XAUUSD | H1 | +0.021/+0.32/515 | +0.021/+0.32/515 | +0.000 | t_on 0.32<2 |
|  | regime_momentum_fvg | AUDUSD | H1 | -0.162/-2.65/517 | -0.167/-2.75/517 | -0.006 | exp_R_on -0.1674≤0 |
|  | regime_momentum_fvg | BTCUSD | H1 | -0.052/-0.80/476 | -0.052/-0.80/476 | +0.000 | exp_R_on -0.052≤0 |
|  | regime_momentum_fvg | EURUSD | H1 | -0.131/-2.20/540 | -0.131/-2.20/540 | +0.000 | exp_R_on -0.131≤0 |
|  | regime_momentum_fvg | GBPUSD | H1 | -0.053/-0.88/552 | -0.056/-0.94/551 | -0.004 | exp_R_on -0.0564≤0 |
|  | regime_momentum_fvg | USDCHF | H1 | -0.223/-3.68/505 | -0.222/-3.65/504 | +0.002 | exp_R_on -0.2216≤0 |
|  | regime_momentum_fvg | USDJPY | H1 | -0.053/-0.91/591 | -0.053/-0.91/591 | +0.000 | exp_R_on -0.0532≤0 |
|  | regime_momentum_fvg | WTIUSD | H1 | -0.112/-1.98/617 | -0.110/-1.95/616 | +0.002 | exp_R_on -0.1101≤0 |
|  | regime_momentum_fvg | XAGUSD | H1 | -0.315/-4.87/503 | -0.312/-4.82/502 | +0.003 | exp_R_on -0.3118≤0 |
|  | regime_momentum_fvg | XAUEUR | H1 | -0.088/-1.34/468 | -0.097/-1.48/469 | -0.008 | exp_R_on -0.0967≤0 |
|  | regime_momentum_fvg | XAUJPY | H1 | +0.260/+1.30/56 | +0.260/+1.30/56 | +0.000 | n_on 56<80 |
|  | regime_momentum_fvg | XAUUSD | H1 | +0.040/+0.60/467 | +0.040/+0.60/467 | +0.000 | t_on 0.6<2 |
|  | sweep_reversal | AUDUSD | H1 | -0.089/-2.79/1494 | -0.090/-2.82/1495 | -0.001 | exp_R_on -0.0897≤0 |
|  | sweep_reversal | BTCUSD | H1 | +0.027/+0.78/1331 | +0.027/+0.78/1331 | +0.000 | t_on 0.78<2 |
|  | sweep_reversal | EURUSD | H1 | -0.101/-3.13/1419 | -0.101/-3.13/1419 | +0.000 | exp_R_on -0.1013≤0 |
|  | sweep_reversal | GBPUSD | H1 | -0.094/-2.88/1406 | -0.092/-2.82/1406 | +0.002 | exp_R_on -0.092≤0 |
|  | sweep_reversal | USDCHF | H1 | -0.168/-5.34/1490 | -0.168/-5.34/1490 | +0.000 | exp_R_on -0.1681≤0 |
|  | sweep_reversal | USDJPY | H1 | -0.145/-4.35/1319 | -0.142/-4.25/1320 | +0.003 | exp_R_on -0.1417≤0 |
|  | sweep_reversal | WTIUSD | H1 | -0.040/-1.22/1402 | -0.038/-1.17/1402 | +0.002 | exp_R_on -0.0385≤0 |
|  | sweep_reversal | XAGUSD | H1 | -0.452/-13.32/1380 | -0.452/-13.30/1379 | +0.001 | exp_R_on -0.4519≤0 |
|  | sweep_reversal | XAUEUR | H1 | -0.148/-4.64/1466 | -0.148/-4.64/1466 | +0.000 | exp_R_on -0.1484≤0 |
|  | sweep_reversal | XAUJPY | H1 | -0.031/-0.30/138 | -0.031/-0.30/138 | +0.000 | exp_R_on -0.0314≤0 |
|  | sweep_reversal | XAUUSD | H1 | -0.042/-1.26/1343 | -0.043/-1.29/1342 | -0.001 | exp_R_on -0.0434≤0 |

**เปิด live (rich) 1 combo:** macro_momentum|XAUUSD
