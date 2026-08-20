# S/R Entry Gate — evaluation (2026-08-20)

params (lookback,pivot,block_atr,min_touches,cluster_atr) = `(60, 3, 0.5, 2, 0.3)`

เกณฑ์เปิด live: gated `exp_R>0 · OOS≥0 · t≥2 · n≥80 · exp_R_on≥exp_R_off · n_on≥0.15·n_off`

| ✓ | algo | คู่ | TF | OFF exp_R/t/n | ON exp_R/t/n | Δexp_R | verdict |
|---|------|-----|----|----|----|----|----|
| ✓ | macro_momentum | XAUUSD | H4 | +0.235/+2.08/354 | +0.254/+2.21/349 | +0.018 | ผ่าน (gate ช่วย + robust) |
|  | confluence_15m | AUDUSD | M15 | -0.306/-3.24/227 | -0.303/-3.11/214 | +0.003 | exp_R_on -0.303≤0 |
|  | confluence_15m | BTCUSD | M15 | +0.071/+0.48/100 | +0.020/+0.13/94 | -0.051 | t_on 0.13<2 |
|  | confluence_15m | EURUSD | M15 | -0.230/-2.86/295 | -0.249/-3.08/290 | -0.019 | exp_R_on -0.2495≤0 |
|  | confluence_15m | GBPUSD | M15 | -0.117/-1.29/251 | -0.100/-1.08/242 | +0.017 | exp_R_on -0.0997≤0 |
|  | confluence_15m | USDCHF | M15 | -0.474/-2.34/44 | -0.504/-2.46/42 | -0.031 | n_on 42<80 |
|  | confluence_15m | USDJPY | M15 | -0.390/-2.73/84 | -0.414/-2.90/83 | -0.025 | exp_R_on -0.4142≤0 |
|  | confluence_15m | WTIUSD | M15 | -0.357/-3.04/136 | -0.350/-2.88/128 | +0.007 | exp_R_on -0.3498≤0 |
|  | confluence_15m | XAGUSD | M15 | -0.250/-2.52/217 | -0.237/-2.36/214 | +0.013 | exp_R_on -0.237≤0 |
|  | confluence_15m | XAUEUR | M15 | +0.035/+0.21/77 | +0.057/+0.33/73 | +0.022 | n_on 73<80 |
|  | confluence_15m | XAUJPY | M15 | +0.085/+0.43/57 | +0.105/+0.53/56 | +0.020 | n_on 56<80 |
|  | confluence_15m | XAUUSD | M15 | +0.139/+1.43/228 | +0.128/+1.30/220 | -0.011 | t_on 1.3<2 |
|  | macro_momentum | AUDUSD | H4 | -0.079/-1.25/487 | -0.055/-0.85/478 | +0.024 | exp_R_on -0.0547≤0 |
|  | macro_momentum | BTCUSD | H4 | +0.071/+0.79/364 | +0.046/+0.50/354 | -0.025 | t_on 0.5<2 |
|  | macro_momentum | EURUSD | H4 | -0.060/-1.48/1199 | -0.046/-1.12/1158 | +0.013 | exp_R_on -0.0463≤0 |
|  | macro_momentum | GBPUSD | H4 | -0.052/-1.18/1033 | -0.047/-1.07/1013 | +0.004 | exp_R_on -0.0472≤0 |
|  | macro_momentum | USDCHF | H4 | -0.013/-0.14/234 | -0.021/-0.21/218 | -0.007 | exp_R_on -0.0207≤0 |
|  | macro_momentum | USDJPY | H4 | -0.052/-0.85/535 | -0.046/-0.75/523 | +0.005 | exp_R_on -0.0463≤0 |
|  | macro_momentum | WTIUSD | H4 | -0.040/-0.61/464 | -0.058/-0.88/454 | -0.018 | exp_R_on -0.0578≤0 |
|  | macro_momentum | XAGUSD | H4 | -0.117/-1.66/413 | -0.099/-1.38/404 | +0.018 | exp_R_on -0.099≤0 |
|  | macro_momentum | XAUEUR | H4 | +0.158/+1.10/217 | +0.146/+1.02/215 | -0.012 | t_on 1.02<2 |
|  | macro_momentum | XAUJPY | H4 | — | — | — | no data |
|  | mean_reversion | AUDUSD | H1 | -0.135/-6.41/1545 | -0.132/-6.17/1514 | +0.004 | exp_R_on -0.1316≤0 |
|  | mean_reversion | BTCUSD | H1 | -0.122/-5.74/1416 | -0.119/-5.57/1394 | +0.003 | exp_R_on -0.1195≤0 |
|  | mean_reversion | EURUSD | H1 | -0.067/-3.14/1475 | -0.062/-2.87/1453 | +0.005 | exp_R_on -0.062≤0 |
|  | mean_reversion | GBPUSD | H1 | -0.051/-2.46/1525 | -0.051/-2.46/1506 | -0.000 | exp_R_on -0.0513≤0 |
|  | mean_reversion | USDCHF | H1 | -0.098/-5.12/1727 | -0.094/-4.87/1686 | +0.003 | exp_R_on -0.0942≤0 |
|  | mean_reversion | USDJPY | H1 | -0.065/-3.09/1469 | -0.064/-3.05/1449 | +0.000 | exp_R_on -0.0643≤0 |
|  | mean_reversion | WTIUSD | H1 | -0.114/-4.89/1329 | -0.109/-4.62/1295 | +0.005 | exp_R_on -0.1088≤0 |
|  | mean_reversion | XAGUSD | H1 | -0.434/-20.25/1469 | -0.429/-19.73/1439 | +0.005 | exp_R_on -0.4295≤0 |
|  | mean_reversion | XAUEUR | H1 | -0.141/-6.83/1544 | -0.141/-6.80/1521 | -0.000 | exp_R_on -0.141≤0 |
|  | mean_reversion | XAUJPY | H1 | -0.035/-0.49/131 | -0.034/-0.46/127 | +0.002 | exp_R_on -0.0338≤0 |
|  | mean_reversion | XAUUSD | H1 | -0.087/-4.08/1399 | -0.086/-3.98/1368 | +0.001 | exp_R_on -0.0861≤0 |
|  | regime_momentum | AUDUSD | H1 | -0.101/-1.75/595 | -0.108/-1.87/593 | -0.007 | exp_R_on -0.108≤0 |
|  | regime_momentum | BTCUSD | H1 | -0.040/-0.64/528 | -0.034/-0.55/525 | +0.006 | exp_R_on -0.0342≤0 |
|  | regime_momentum | EURUSD | H1 | -0.100/-1.76/604 | -0.096/-1.67/601 | +0.005 | exp_R_on -0.0956≤0 |
|  | regime_momentum | GBPUSD | H1 | -0.085/-1.50/614 | -0.089/-1.56/604 | -0.004 | exp_R_on -0.0888≤0 |
|  | regime_momentum | USDCHF | H1 | -0.177/-3.03/558 | -0.175/-2.96/550 | +0.002 | exp_R_on -0.1749≤0 |
|  | regime_momentum | USDJPY | H1 | -0.068/-1.21/640 | -0.063/-1.13/637 | +0.005 | exp_R_on -0.0632≤0 |
|  | regime_momentum | WTIUSD | H1 | -0.083/-1.53/679 | -0.072/-1.32/669 | +0.010 | exp_R_on -0.0723≤0 |
|  | regime_momentum | XAGUSD | H1 | -0.361/-6.07/578 | -0.352/-5.86/572 | +0.010 | exp_R_on -0.3517≤0 |
|  | regime_momentum | XAUEUR | H1 | -0.045/-0.70/510 | -0.051/-0.80/510 | -0.006 | exp_R_on -0.0507≤0 |
|  | regime_momentum | XAUJPY | H1 | +0.224/+1.16/60 | +0.224/+1.16/60 | +0.000 | n_on 60<80 |
|  | regime_momentum | XAUUSD | H1 | +0.021/+0.32/515 | +0.025/+0.39/510 | +0.005 | t_on 0.39<2 |
|  | regime_momentum_fvg | AUDUSD | H1 | -0.162/-2.65/517 | -0.170/-2.78/515 | -0.008 | exp_R_on -0.1696≤0 |
|  | regime_momentum_fvg | BTCUSD | H1 | -0.052/-0.80/476 | -0.046/-0.70/473 | +0.006 | exp_R_on -0.0457≤0 |
|  | regime_momentum_fvg | EURUSD | H1 | -0.138/-2.32/541 | -0.135/-2.26/539 | +0.003 | exp_R_on -0.1347≤0 |
|  | regime_momentum_fvg | GBPUSD | H1 | -0.057/-0.94/552 | -0.058/-0.96/541 | -0.002 | exp_R_on -0.0584≤0 |
|  | regime_momentum_fvg | USDCHF | H1 | -0.225/-3.72/506 | -0.213/-3.48/499 | +0.012 | exp_R_on -0.213≤0 |
|  | regime_momentum_fvg | USDJPY | H1 | -0.058/-0.99/591 | -0.054/-0.93/589 | +0.003 | exp_R_on -0.0544≤0 |
|  | regime_momentum_fvg | WTIUSD | H1 | -0.113/-2.00/616 | -0.103/-1.81/607 | +0.009 | exp_R_on -0.1034≤0 |
|  | regime_momentum_fvg | XAGUSD | H1 | -0.312/-4.81/502 | -0.302/-4.63/497 | +0.010 | exp_R_on -0.3021≤0 |
|  | regime_momentum_fvg | XAUEUR | H1 | -0.082/-1.25/468 | -0.086/-1.31/467 | -0.004 | exp_R_on -0.0864≤0 |
|  | regime_momentum_fvg | XAUJPY | H1 | +0.260/+1.30/56 | +0.260/+1.30/56 | +0.000 | n_on 56<80 |
|  | regime_momentum_fvg | XAUUSD | H1 | +0.040/+0.60/467 | +0.046/+0.68/462 | +0.005 | t_on 0.68<2 |
|  | sweep_reversal | AUDUSD | H1 | -0.088/-2.77/1495 | -0.085/-2.66/1496 | +0.003 | exp_R_on -0.0849≤0 |
|  | sweep_reversal | BTCUSD | H1 | +0.027/+0.78/1332 | +0.015/+0.44/1316 | -0.012 | t_on 0.44<2 |
|  | sweep_reversal | EURUSD | H1 | -0.106/-3.29/1419 | -0.115/-3.56/1418 | -0.009 | exp_R_on -0.1151≤0 |
|  | sweep_reversal | GBPUSD | H1 | -0.099/-3.05/1407 | -0.095/-2.91/1395 | +0.004 | exp_R_on -0.0952≤0 |
|  | sweep_reversal | USDCHF | H1 | -0.168/-5.34/1490 | -0.157/-4.95/1478 | +0.011 | exp_R_on -0.1569≤0 |
|  | sweep_reversal | USDJPY | H1 | -0.151/-4.52/1319 | -0.158/-4.73/1313 | -0.007 | exp_R_on -0.158≤0 |
|  | sweep_reversal | WTIUSD | H1 | -0.040/-1.20/1402 | -0.043/-1.30/1389 | -0.003 | exp_R_on -0.043≤0 |
|  | sweep_reversal | XAGUSD | H1 | -0.454/-13.37/1382 | -0.454/-13.30/1367 | -0.000 | exp_R_on -0.4538≤0 |
|  | sweep_reversal | XAUEUR | H1 | -0.147/-4.61/1466 | -0.149/-4.65/1462 | -0.001 | exp_R_on -0.1489≤0 |
|  | sweep_reversal | XAUJPY | H1 | -0.032/-0.30/138 | -0.032/-0.31/138 | -0.000 | exp_R_on -0.032≤0 |
|  | sweep_reversal | XAUUSD | H1 | -0.041/-1.22/1343 | -0.036/-1.09/1339 | +0.005 | exp_R_on -0.0365≤0 |

**เปิด live 1 combo:** macro_momentum|XAUUSD

## Global gate aggregate (65 combo มีผล)

- Δexp_R > 0 (ดีขึ้น): **38** · < 0 (แย่ลง): **20** · ~เท่าเดิม: 7
- Δexp_R เฉลี่ยทั้งพอร์ต: **+0.0007 R**
- flip เป็น +EV เพราะ gate: (ไม่มี)
- หลุด +EV เพราะ gate: (ไม่มี)
