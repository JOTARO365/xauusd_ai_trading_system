# Confirmation Gate (close-strength) — evaluation (2026-08-13)

gate: confirm ต่อ algo (cont=แท่งปิดแข็งตาม move · rev=pin กลับตัวที่ปลาย). clv_thr = `0.5`

เกณฑ์เปิด live: gated `exp_R>0 · OOS≥0 · t≥2 · n≥80 · exp_R_on≥exp_R_off · n_on≥0.30·n_off`

| ✓ | algo | mode | คู่ | TF | OFF exp_R/t/n | ON exp_R/t/n | Δexp_R | verdict |
|---|------|------|-----|----|----|----|----|----|
|  | cdc_zone | cont | AUDUSD | D1 | -0.114/-0.80/54 | -0.159/-0.93/49 | -0.045 | n_on 49<80 |
|  | cdc_zone | cont | BTCUSD | D1 | +3.070/+2.04/47 | +3.691/+2.12/41 | +0.621 | n_on 41<80 |
|  | cdc_zone | cont | EURUSD | D1 | +0.131/+0.52/54 | +0.165/+0.61/46 | +0.035 | n_on 46<80 |
|  | cdc_zone | cont | GBPUSD | D1 | -0.122/-0.83/56 | -0.202/-1.45/51 | -0.081 | n_on 51<80 |
|  | cdc_zone | cont | USDCHF | D1 | -0.238/-2.06/68 | -0.157/-1.20/52 | +0.081 | n_on 52<80 |
|  | cdc_zone | cont | USDJPY | D1 | +0.212/+0.76/55 | +0.327/+1.00/47 | +0.115 | n_on 47<80 |
|  | cdc_zone | cont | WTIUSD | D1 | +0.213/+0.84/55 | +0.378/+1.20/44 | +0.165 | n_on 44<80 |
|  | cdc_zone | cont | XAGUSD | D1 | +0.249/+0.59/66 | +0.308/+0.63/57 | +0.059 | n_on 57<80 |
|  | cdc_zone | cont | XAUEUR | D1 | +1.007/+1.89/44 | +1.312/+2.05/36 | +0.305 | n_on 36<80 |
|  | cdc_zone | cont | XAUUSD | D1 | +0.992/+2.08/47 | +1.106/+2.28/40 | +0.113 | n_on 40<80 |
|  | confluence_15m | cont | AUDUSD | M15 | -0.284/-2.99/226 | -0.334/-3.46/213 | -0.050 | exp_R_on -0.3342≤0 |
|  | confluence_15m | cont | BTCUSD | M15 | +0.057/+0.38/99 | +0.087/+0.57/94 | +0.030 | t_on 0.57<2 |
|  | confluence_15m | cont | EURUSD | M15 | -0.217/-2.68/295 | -0.203/-2.43/276 | +0.013 | exp_R_on -0.2034≤0 |
|  | confluence_15m | cont | GBPUSD | M15 | -0.190/-2.09/250 | -0.208/-2.24/239 | -0.018 | exp_R_on -0.2085≤0 |
|  | confluence_15m | cont | USDCHF | M15 | -0.387/-1.81/42 | -0.387/-1.74/39 | +0.000 | n_on 39<80 |
|  | confluence_15m | cont | USDJPY | M15 | -0.420/-2.97/85 | -0.397/-2.76/83 | +0.023 | exp_R_on -0.3973≤0 |
|  | confluence_15m | cont | WTIUSD | M15 | -0.321/-2.71/137 | -0.335/-2.79/132 | -0.014 | exp_R_on -0.3347≤0 |
|  | confluence_15m | cont | XAGUSD | M15 | -0.266/-2.69/221 | -0.263/-2.57/204 | +0.003 | exp_R_on -0.2625≤0 |
|  | confluence_15m | cont | XAUEUR | M15 | +0.035/+0.21/77 | +0.083/+0.48/74 | +0.048 | n_on 74<80 |
|  | confluence_15m | cont | XAUJPY | M15 | +0.092/+0.46/54 | +0.113/+0.56/53 | +0.022 | n_on 53<80 |
|  | confluence_15m | cont | XAUUSD | M15 | +0.147/+1.51/229 | +0.106/+1.07/219 | -0.041 | t_on 1.07<2 |
|  | macro_momentum | cont | AUDUSD | H4 | -0.077/-1.21/486 | -0.082/-1.28/479 | -0.005 | exp_R_on -0.0817≤0 |
|  | macro_momentum | cont | BTCUSD | H4 | +0.070/+0.77/362 | +0.059/+0.65/349 | -0.011 | t_on 0.65<2 |
|  | macro_momentum | cont | EURUSD | H4 | -0.061/-1.50/1197 | -0.065/-1.60/1168 | -0.004 | exp_R_on -0.0654≤0 |
|  | macro_momentum | cont | GBPUSD | H4 | -0.065/-1.48/1033 | -0.071/-1.61/1012 | -0.006 | exp_R_on -0.071≤0 |
|  | macro_momentum | cont | USDCHF | H4 | -0.016/-0.17/234 | +0.003/+0.03/224 | +0.019 | OOS_on -0.1197<0 |
|  | macro_momentum | cont | USDJPY | H4 | -0.058/-0.95/537 | -0.043/-0.69/517 | +0.015 | exp_R_on -0.043≤0 |
|  | macro_momentum | cont | WTIUSD | H4 | -0.041/-0.62/463 | -0.030/-0.44/449 | +0.011 | exp_R_on -0.0297≤0 |
|  | macro_momentum | cont | XAGUSD | H4 | -0.118/-1.67/412 | -0.114/-1.59/399 | +0.004 | exp_R_on -0.1144≤0 |
|  | macro_momentum | cont | XAUEUR | H4 | +0.120/+1.36/278 | +0.111/+1.25/275 | -0.009 | t_on 1.25<2 |
|  | macro_momentum | cont | XAUJPY | H4 | — | — | — | no data |
|  | macro_momentum | cont | XAUUSD | H4 | +0.121/+1.76/451 | +0.116/+1.65/432 | -0.005 | t_on 1.65<2 |
|  | mean_reversion | rev | AUDUSD | H1 | -0.135/-6.42/1542 | -0.141/-3.37/427 | -0.006 | confirm ตัดเยอะเกิน (n 1542→427) |
|  | mean_reversion | rev | BTCUSD | H1 | -0.125/-5.88/1414 | -0.076/-1.85/411 | +0.050 | confirm ตัดเยอะเกิน (n 1414→411) |
|  | mean_reversion | rev | EURUSD | H1 | -0.067/-3.12/1472 | -0.087/-1.96/362 | -0.020 | confirm ตัดเยอะเกิน (n 1472→362) |
|  | mean_reversion | rev | GBPUSD | H1 | -0.084/-4.05/1523 | -0.077/-1.85/414 | +0.007 | confirm ตัดเยอะเกิน (n 1523→414) |
|  | mean_reversion | rev | USDCHF | H1 | -0.105/-5.51/1723 | -0.144/-3.74/455 | -0.039 | confirm ตัดเยอะเกิน (n 1723→455) |
|  | mean_reversion | rev | USDJPY | H1 | -0.074/-3.52/1471 | -0.111/-2.63/410 | -0.037 | confirm ตัดเยอะเกิน (n 1471→410) |
|  | mean_reversion | rev | WTIUSD | H1 | -0.115/-4.96/1333 | -0.210/-4.48/336 | -0.095 | confirm ตัดเยอะเกิน (n 1333→336) |
|  | mean_reversion | rev | XAGUSD | H1 | -0.440/-20.41/1467 | -0.454/-9.72/371 | -0.014 | confirm ตัดเยอะเกิน (n 1467→371) |
|  | mean_reversion | rev | XAUEUR | H1 | -0.139/-6.75/1541 | -0.170/-4.01/401 | -0.031 | confirm ตัดเยอะเกิน (n 1541→401) |
|  | mean_reversion | rev | XAUJPY | H1 | -0.023/-0.33/130 | -0.196/-1.55/41 | -0.172 | n_on 41<80 |
|  | mean_reversion | rev | XAUUSD | H1 | -0.086/-4.06/1397 | -0.214/-5.26/396 | -0.128 | confirm ตัดเยอะเกิน (n 1397→396) |
|  | regime_momentum | cont | AUDUSD | H1 | -0.098/-1.69/593 | -0.115/-1.97/576 | -0.018 | exp_R_on -0.1154≤0 |
|  | regime_momentum | cont | BTCUSD | H1 | -0.040/-0.65/528 | -0.046/-0.72/507 | -0.005 | exp_R_on -0.0457≤0 |
|  | regime_momentum | cont | EURUSD | H1 | -0.107/-1.88/602 | -0.101/-1.75/583 | +0.005 | exp_R_on -0.1014≤0 |
|  | regime_momentum | cont | GBPUSD | H1 | -0.114/-2.01/616 | -0.130/-2.28/598 | -0.016 | exp_R_on -0.13≤0 |
|  | regime_momentum | cont | USDCHF | H1 | -0.184/-3.16/562 | -0.182/-3.06/541 | +0.002 | exp_R_on -0.182≤0 |
|  | regime_momentum | cont | USDJPY | H1 | -0.074/-1.32/637 | -0.063/-1.09/612 | +0.012 | exp_R_on -0.0626≤0 |
|  | regime_momentum | cont | WTIUSD | H1 | -0.079/-1.46/678 | -0.072/-1.29/649 | +0.008 | exp_R_on -0.0717≤0 |
|  | regime_momentum | cont | XAGUSD | H1 | -0.365/-6.11/577 | -0.370/-6.06/558 | -0.005 | exp_R_on -0.3699≤0 |
|  | regime_momentum | cont | XAUEUR | H1 | -0.045/-0.70/510 | -0.039/-0.60/493 | +0.006 | exp_R_on -0.039≤0 |
|  | regime_momentum | cont | XAUJPY | H1 | +0.245/+1.26/59 | +0.307/+1.50/54 | +0.062 | n_on 54<80 |
|  | regime_momentum | cont | XAUUSD | H1 | +0.020/+0.32/515 | +0.028/+0.44/500 | +0.008 | t_on 0.44<2 |
|  | regime_momentum_fvg | cont | AUDUSD | H1 | -0.158/-2.58/515 | -0.184/-2.98/497 | -0.027 | exp_R_on -0.1845≤0 |
|  | regime_momentum_fvg | cont | BTCUSD | H1 | -0.055/-0.85/477 | -0.062/-0.94/456 | -0.007 | exp_R_on -0.0619≤0 |
|  | regime_momentum_fvg | cont | EURUSD | H1 | -0.145/-2.44/539 | -0.142/-2.32/514 | +0.004 | exp_R_on -0.1416≤0 |
|  | regime_momentum_fvg | cont | GBPUSD | H1 | -0.085/-1.41/554 | -0.097/-1.58/536 | -0.012 | exp_R_on -0.0965≤0 |
|  | regime_momentum_fvg | cont | USDCHF | H1 | -0.232/-3.85/510 | -0.228/-3.69/487 | +0.004 | exp_R_on -0.2279≤0 |
|  | regime_momentum_fvg | cont | USDJPY | H1 | -0.063/-1.08/589 | -0.057/-0.95/562 | +0.006 | exp_R_on -0.057≤0 |
|  | regime_momentum_fvg | cont | WTIUSD | H1 | -0.109/-1.92/615 | -0.100/-1.73/588 | +0.009 | exp_R_on -0.1002≤0 |
|  | regime_momentum_fvg | cont | XAGUSD | H1 | -0.319/-4.91/500 | -0.315/-4.71/480 | +0.004 | exp_R_on -0.3149≤0 |
|  | regime_momentum_fvg | cont | XAUEUR | H1 | -0.082/-1.25/468 | -0.080/-1.19/449 | +0.002 | exp_R_on -0.0801≤0 |
|  | regime_momentum_fvg | cont | XAUJPY | H1 | +0.283/+1.40/55 | +0.382/+1.77/49 | +0.099 | n_on 49<80 |
|  | regime_momentum_fvg | cont | XAUUSD | H1 | +0.040/+0.60/467 | +0.066/+0.96/448 | +0.026 | t_on 0.96<2 |
|  | sweep_reversal | rev | AUDUSD | H1 | -0.085/-2.67/1493 | -0.063/-1.30/650 | +0.023 | exp_R_on -0.0626≤0 |
|  | sweep_reversal | rev | BTCUSD | H1 | +0.031/+0.89/1327 | -0.004/-0.07/595 | -0.034 | exp_R_on -0.0035≤0 |
|  | sweep_reversal | rev | EURUSD | H1 | -0.107/-3.32/1421 | -0.082/-1.69/629 | +0.025 | exp_R_on -0.0824≤0 |
|  | sweep_reversal | rev | GBPUSD | H1 | -0.140/-4.29/1412 | -0.216/-4.49/616 | -0.076 | exp_R_on -0.2161≤0 |
|  | sweep_reversal | rev | USDCHF | H1 | -0.171/-5.41/1486 | -0.173/-3.69/668 | -0.002 | exp_R_on -0.1729≤0 |
|  | sweep_reversal | rev | USDJPY | H1 | -0.164/-4.92/1323 | -0.178/-3.58/584 | -0.014 | exp_R_on -0.1782≤0 |
|  | sweep_reversal | rev | WTIUSD | H1 | -0.039/-1.17/1395 | -0.080/-1.64/632 | -0.041 | exp_R_on -0.0799≤0 |
|  | sweep_reversal | rev | XAGUSD | H1 | -0.462/-13.67/1393 | -0.425/-8.83/676 | +0.037 | exp_R_on -0.4255≤0 |
|  | sweep_reversal | rev | XAUEUR | H1 | -0.148/-4.62/1465 | -0.173/-3.68/658 | -0.026 | exp_R_on -0.1735≤0 |
|  | sweep_reversal | rev | XAUJPY | H1 | -0.024/-0.23/132 | +0.049/+0.32/65 | +0.073 | n_on 65<80 |
|  | sweep_reversal | rev | XAUUSD | H1 | -0.041/-1.21/1340 | -0.048/-0.98/622 | -0.007 | exp_R_on -0.0479≤0 |

**เปิด live 0 combo:** (ไม่มี combo ผ่าน)

## Aggregate (75 combo มีผล)

- Δexp_R > 0 (ดีขึ้น): **39** · < 0 (แย่ลง): **35** · ~เท่าเดิม: 1
- Δexp_R เฉลี่ยทั้งพอร์ต: **+0.0137 R**
- flip เป็น +EV เพราะ confirm: sweep_reversal|XAUJPY, macro_momentum|USDCHF
- หลุด +EV เพราะ confirm: sweep_reversal|BTCUSD
