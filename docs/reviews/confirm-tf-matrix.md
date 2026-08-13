# Confirm-TF matrix — algo ไหนเหมาะแท่งปิด TF ไหน (2026-08-13)

confirm = เข้าเฉพาะเมื่อแท่งปิดของ **confirm-TF** ยืนยันทิศ (mode ต่อ algo: cont=momentum/trend, rev=fade). Δexp_R = exp_R(confirm) − exp_R(OFF) เฉลี่ยข้ามคู่ (นับเฉพาะคู่ที่ confirm เก็บไม้ ≥30%).

## สรุปต่อ algo

| algo | mode | signal TF | **แท่งปิดที่ confirm ดีสุด** | Δexp_R | M15 | H1 | H4 | D1 |
|------|------|-----------|------------------------------|--------|-----|----|----|----|
| cdc_zone | cont | D1 | **D1** | +0.137 | -0.005 | +0.043 | +0.053 | +0.137 |
| regime_momentum_fvg | cont | H1 | **D1** | +0.057 | +0.004 | +0.010 | -0.004 | +0.057 |
| regime_momentum | cont | H1 | **D1** | +0.048 | +0.003 | +0.005 | +0.004 | +0.048 |
| sweep_reversal | rev | H1 | **H4** | +0.033 | -0.011 | -0.004 | +0.033 | · |
| tsmom_d1 | cont | D1 | **D1** | +0.016 | -0.010 | -0.020 | +0.013 | +0.016 |
| macro_momentum | cont | H4 | **D1** | +0.004 | +0.001 | -0.018 | +0.001 | +0.004 |
| mean_reversion | rev | H1 | **M15** | -0.009 | -0.009 | -0.171 | · | · |

> Δexp_R > 0 = แท่งปิด TF นั้นช่วยกรอง noise ของ algo · `·` = ตัดไม้เยอะเกิน (n<30%) ไม่นับ

## รายละเอียดต่อคู่ (Δexp_R ต่อ confirm-TF)

| algo | คู่ | base exp_R | M15 | H1 | H4 | D1 |
|---|---|---|---|---|---|---|
| cdc_zone | AUDUSD | -0.114 | -0.011 | -0.033 | +0.006 | -0.045 |
| cdc_zone | BTCUSD | +3.070 | +0.008 | +0.110 | +0.184 | +0.621 |
| cdc_zone | EURUSD | +0.131 | +0.008 | -0.006 | +0.039 | +0.035 |
| cdc_zone | GBPUSD | -0.121 | -0.047 | -0.045 | -0.002 | -0.081 |
| cdc_zone | USDCHF | -0.238 | -0.003 | +0.084 | +0.065 | +0.081 |
| cdc_zone | USDJPY | +0.212 | +0.001 | +0.013 | +0.024 | +0.115 |
| cdc_zone | WTIUSD | +0.213 | +0.041 | +0.072 | +0.084 | +0.165 |
| cdc_zone | XAGUSD | +0.249 | +0.010 | +0.033 | +0.038 | +0.059 |
| cdc_zone | XAUEUR | +1.007 | -0.060 | +0.143 | +0.186 | +0.305 |
| cdc_zone | XAUUSD | +0.992 | +0.003 | +0.064 | -0.088 | +0.113 |
| macro_momentum | AUDUSD | -0.077 | -0.006 | -0.021 | -0.005 | +0.046 |
| macro_momentum | BTCUSD | +0.070 | -0.026 | -0.082 | -0.011 | +0.010 |
| macro_momentum | EURUSD | -0.061 | -0.007 | -0.015 | -0.004 | +0.001 |
| macro_momentum | GBPUSD | -0.063 | +0.003 | -0.009 | -0.006 | +0.017 |
| macro_momentum | USDCHF | -0.016 | +0.029 | -0.034 | +0.019 | -0.095 |
| macro_momentum | USDJPY | -0.058 | +0.005 | +0.017 | +0.015 | +0.029 |
| macro_momentum | WTIUSD | -0.041 | +0.013 | +0.006 | +0.011 | +0.023 |
| macro_momentum | XAGUSD | -0.118 | -0.015 | -0.021 | +0.004 | +0.015 |
| macro_momentum | XAUEUR | +0.120 | +0.005 | +0.028 | -0.009 | +0.027 |
| macro_momentum | XAUJPY | — | · | · | · | · |
| macro_momentum | XAUUSD | +0.121 | +0.010 | -0.045 | -0.005 | -0.035 |
| mean_reversion | AUDUSD | -0.135 | -0.009 | -0.006 | +0.022 | -0.016 |
| mean_reversion | BTCUSD | -0.125 | -0.009 | +0.049 | +0.135 | +0.020 |
| mean_reversion | EURUSD | -0.067 | +0.005 | -0.020 | -0.009 | +0.110 |
| mean_reversion | GBPUSD | -0.080 | -0.006 | +0.007 | -0.119 | -0.066 |
| mean_reversion | USDCHF | -0.105 | -0.006 | -0.039 | +0.089 | -0.020 |
| mean_reversion | USDJPY | -0.074 | -0.009 | -0.037 | -0.049 | +0.005 |
| mean_reversion | WTIUSD | -0.115 | -0.007 | -0.095 | +0.143 | -0.003 |
| mean_reversion | XAGUSD | -0.440 | -0.021 | -0.014 | +0.039 | -0.034 |
| mean_reversion | XAUEUR | -0.139 | -0.020 | -0.031 | +0.019 | +0.084 |
| mean_reversion | XAUJPY | -0.023 | -0.039 | -0.171 | · | · |
| mean_reversion | XAUUSD | -0.086 | -0.009 | -0.128 | +0.003 | -0.035 |
| regime_momentum | AUDUSD | -0.098 | -0.002 | -0.018 | -0.004 | -0.010 |
| regime_momentum | BTCUSD | -0.040 | -0.008 | -0.005 | -0.013 | +0.057 |
| regime_momentum | EURUSD | -0.107 | +0.007 | +0.005 | +0.013 | +0.057 |
| regime_momentum | GBPUSD | -0.110 | +0.001 | -0.016 | +0.003 | +0.041 |
| regime_momentum | USDCHF | -0.184 | -0.021 | +0.002 | -0.033 | +0.060 |
| regime_momentum | USDJPY | -0.074 | +0.009 | +0.012 | +0.018 | +0.012 |
| regime_momentum | WTIUSD | -0.079 | +0.010 | +0.007 | +0.024 | +0.004 |
| regime_momentum | XAGUSD | -0.365 | -0.046 | -0.005 | -0.006 | +0.000 |
| regime_momentum | XAUEUR | -0.045 | -0.002 | +0.006 | +0.032 | +0.005 |
| regime_momentum | XAUJPY | +0.245 | +0.076 | +0.062 | -0.008 | +0.259 |
| regime_momentum | XAUUSD | +0.020 | +0.004 | +0.008 | +0.015 | +0.046 |
| regime_momentum_fvg | AUDUSD | -0.158 | +0.001 | -0.027 | +0.019 | -0.020 |
| regime_momentum_fvg | BTCUSD | -0.055 | -0.016 | -0.007 | -0.011 | +0.047 |
| regime_momentum_fvg | EURUSD | -0.145 | +0.011 | +0.004 | +0.002 | +0.056 |
| regime_momentum_fvg | GBPUSD | -0.081 | +0.008 | -0.012 | -0.007 | +0.049 |
| regime_momentum_fvg | USDCHF | -0.232 | -0.024 | +0.004 | -0.022 | +0.082 |
| regime_momentum_fvg | USDJPY | -0.063 | +0.007 | +0.006 | +0.013 | +0.013 |
| regime_momentum_fvg | WTIUSD | -0.109 | +0.017 | +0.009 | -0.001 | -0.014 |
| regime_momentum_fvg | XAGUSD | -0.319 | -0.036 | +0.004 | -0.012 | -0.013 |
| regime_momentum_fvg | XAUEUR | -0.082 | +0.007 | +0.002 | +0.020 | +0.009 |
| regime_momentum_fvg | XAUJPY | +0.283 | +0.055 | +0.099 | -0.040 | +0.365 |
| regime_momentum_fvg | XAUUSD | +0.040 | +0.010 | +0.026 | -0.009 | +0.058 |
| sweep_reversal | AUDUSD | -0.085 | -0.019 | +0.023 | +0.046 | -0.128 |
| sweep_reversal | BTCUSD | +0.031 | -0.006 | -0.034 | +0.022 | -0.099 |
| sweep_reversal | EURUSD | -0.107 | +0.000 | +0.025 | -0.048 | +0.120 |
| sweep_reversal | GBPUSD | -0.135 | -0.008 | -0.077 | +0.063 | +0.095 |
| sweep_reversal | USDCHF | -0.171 | +0.014 | -0.002 | -0.005 | +0.175 |
| sweep_reversal | USDJPY | -0.164 | -0.007 | -0.015 | +0.033 | -0.290 |
| sweep_reversal | WTIUSD | -0.039 | -0.011 | -0.041 | +0.061 | -0.053 |
| sweep_reversal | XAGUSD | -0.462 | -0.070 | +0.036 | -0.002 | -0.231 |
| sweep_reversal | XAUEUR | -0.148 | -0.004 | -0.025 | +0.063 | -0.275 |
| sweep_reversal | XAUJPY | -0.024 | +0.026 | +0.073 | +0.103 | · |
| sweep_reversal | XAUUSD | -0.041 | +0.003 | -0.007 | +0.017 | +0.192 |
| tsmom_d1 | AUDUSD | -0.034 | +0.004 | -0.043 | -0.014 | -0.003 |
| tsmom_d1 | BTCUSD | +0.844 | -0.004 | -0.076 | +0.030 | +0.185 |
| tsmom_d1 | EURUSD | +0.110 | -0.011 | +0.014 | +0.087 | +0.026 |
| tsmom_d1 | GBPUSD | -0.009 | -0.007 | +0.042 | +0.023 | +0.002 |
| tsmom_d1 | USDCHF | -0.042 | +0.002 | -0.048 | -0.039 | +0.011 |
| tsmom_d1 | USDJPY | -0.006 | -0.001 | -0.009 | +0.055 | +0.014 |
| tsmom_d1 | WTIUSD | +0.141 | -0.059 | +0.015 | -0.023 | -0.049 |
| tsmom_d1 | XAGUSD | -0.058 | -0.008 | -0.036 | -0.011 | +0.004 |
| tsmom_d1 | XAUEUR | +0.098 | -0.009 | -0.011 | +0.008 | -0.024 |
| tsmom_d1 | XAUUSD | +0.159 | -0.003 | -0.053 | +0.011 | -0.007 |
