# Algo Tune — all families (anti-overfit sweep)

Robust pick = clears deflated-t (√(2·lnN)) AND OOS>0, ranked by OOS. Not the in-sample peak.


## regime_momentum (H1)
- **momentum AUDUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk30/sl1.5/rr2.0` t=0.49 OOS=-0.105 = overfit
- **momentum BTCUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk15/sl1.5/rr2.5` t=0.59 OOS=0.049 = overfit
- **momentum EURUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk15/sl1.5/rr2.0` t=-0.55 OOS=-0.000 = overfit
- **momentum GBPUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk30/sl2.0/rr1.5` t=-0.72 OOS=0.076 = overfit
- **momentum USDCHF**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk10/sl2.0/rr1.5` t=-1.34 OOS=0.036 = overfit
- **momentum USDJPY**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk25/sl2.0/rr1.5` t=1.64 OOS=-0.039 = overfit
- **momentum WTIUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk30/sl1.0/rr2.5` t=1.34 OOS=-0.039 = overfit
- **momentum XAGUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk10/sl2.0/rr2.5` t=0.15 OOS=0.237 = overfit
- **momentum XAUEUR**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk20/sl1.5/rr2.5` t=0.59 OOS=0.186 = overfit
- **momentum XAUJPY**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk10/sl1.0/rr2.5` t=1.93 OOS=0.132 = overfit
- **momentum XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk20/sl1.0/rr1.5` t=1.93 OOS=0.071 = overfit

## macro_momentum (H4)
- **macro XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.96 + OOS>0). peak `brk25/mlb36/sl1.5/rr2.0` t=1.29 OOS=0.254 = overfit
- **macro XAGUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.96 + OOS>0). peak `brk25/mlb36/sl2.0/rr2.5` t=2.06 OOS=0.057 = overfit
- **macro XAUEUR**: ❌ ไม่มี config ผ่าน (defl-t 2.96 + OOS>0). peak `brk15/mlb24/sl2.0/rr1.5` t=1.58 OOS=0.339 = overfit
- **macro XAUJPY**: ไม่มีไม้พอ
- **macro BTCUSD**: ✅ ROBUST `brk25/mlb12/sl1.0/rr2.5` OOS=0.231 t=3.16 (defl 2.96) — peak in-sample `brk25/mlb12/sl2.0/rr2.5` 0.440

## tsmom_d1 (D1)
- **tsmom AUDUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb5-20-40/cf21/sl2.0` t=0.27 OOS=-0.175 = overfit
- **tsmom BTCUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb21-63-126/cf10/sl2.0` t=1.90 OOS=0.504 = overfit
- **tsmom EURUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb30-90-180/cf10/sl2.0` t=1.27 OOS=-0.298 = overfit
- **tsmom GBPUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb30-90-180/cf10/sl2.0` t=0.63 OOS=-0.172 = overfit
- **tsmom USDCHF**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb21-63-126/cf21/sl4.0` t=-0.80 OOS=-0.022 = overfit
- **tsmom USDJPY**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb21-63-126/cf10/sl2.0` t=0.50 OOS=0.006 = overfit
- **tsmom WTIUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb10-30-60/cf21/sl2.0` t=0.79 OOS=0.407 = overfit
- **tsmom XAGUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb10-30-60/cf10/sl2.0` t=0.03 OOS=0.235 = overfit
- **tsmom XAUEUR**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb10-30-60/cf10/sl4.0` t=-1.18 OOS=0.212 = overfit
- **tsmom XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb30-90-180/cf21/sl2.0` t=0.49 OOS=3.198 = overfit

## sweep_reversal (H1)
- **sweep AUDUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.8/rr1.5` t=0.90 OOS=0.073 = overfit
- **sweep BTCUSD**: ✅ ROBUST `buf0.3/rr1.5` OOS=0.150 t=2.69 (defl 2.10) — peak in-sample `buf0.3/rr1.5` 0.110
- **sweep EURUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.3/rr1.0` t=-0.62 OOS=-0.053 = overfit
- **sweep GBPUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.8/rr1.5` t=0.22 OOS=0.018 = overfit
- **sweep USDCHF**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.8/rr1.0` t=0.86 OOS=-0.042 = overfit
- **sweep USDJPY**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.8/rr1.0` t=-0.73 OOS=-0.079 = overfit
- **sweep WTIUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.5/rr1.5` t=1.86 OOS=-0.030 = overfit
- **sweep XAGUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.8/rr2.0` t=-0.31 OOS=0.109 = overfit
- **sweep XAUEUR**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.8/rr2.0` t=0.53 OOS=-0.101 = overfit
- **sweep XAUJPY**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.8/rr2.0` t=1.00 OOS=0.041 = overfit
- **sweep XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.5/rr1.0` t=1.28 OOS=-0.035 = overfit

## Verdict
ถ้าส่วนใหญ่ ❌ = edge ไม่รอด param validation → เก็บ default, อย่า tune ฝืน (quant-sat ch3).