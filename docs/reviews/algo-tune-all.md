# Algo Tune — all families (anti-overfit sweep)

Robust pick = clears deflated-t (√(2·lnN)) AND OOS>0, ranked by OOS. Not the in-sample peak.


## regime_momentum (H1)
- **momentum XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk20/sl1.0/rr1.5` t=1.93 OOS=0.071 = overfit
- **momentum XAUEUR**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk20/sl1.5/rr2.5` t=0.59 OOS=0.186 = overfit
- **momentum BTCUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk15/sl1.5/rr2.5` t=0.59 OOS=0.049 = overfit
- **momentum WTIUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.76 + OOS>0). peak `brk30/sl1.0/rr2.5` t=1.34 OOS=-0.039 = overfit

## macro_momentum (H4)
- **macro XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.96 + OOS>0). peak `brk25/mlb36/sl1.5/rr2.0` t=1.29 OOS=0.254 = overfit
- **macro XAUEUR**: ❌ ไม่มี config ผ่าน (defl-t 2.96 + OOS>0). peak `brk15/mlb24/sl2.0/rr1.5` t=1.58 OOS=0.339 = overfit
- **macro BTCUSD**: ✅ ROBUST `brk25/mlb12/sl1.0/rr2.5` OOS=0.232 t=3.16 (defl 2.96) — peak in-sample `brk25/mlb12/sl2.0/rr2.5` 0.440

## tsmom_d1 (D1)
- **tsmom XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb30-90-180/cf21/sl2.0` t=0.49 OOS=3.198 = overfit
- **tsmom XAUEUR**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb10-30-60/cf10/sl4.0` t=-1.18 OOS=0.212 = overfit
- **tsmom WTIUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb10-30-60/cf21/sl2.0` t=0.79 OOS=0.407 = overfit
- **tsmom EURUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb30-90-180/cf10/sl2.0` t=1.27 OOS=-0.298 = overfit
- **tsmom BTCUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.52 + OOS>0). peak `lb21-63-126/cf10/sl2.0` t=1.90 OOS=0.504 = overfit

## sweep_reversal (H1)
- **sweep BTCUSD**: ✅ ROBUST `buf0.3/rr1.5` OOS=0.149 t=2.69 (defl 2.10) — peak in-sample `buf0.3/rr1.5` 0.110
- **sweep XAUUSD**: ❌ ไม่มี config ผ่าน (defl-t 2.10 + OOS>0). peak `buf0.5/rr1.0` t=1.28 OOS=-0.035 = overfit

## Verdict
ถ้าส่วนใหญ่ ❌ = edge ไม่รอด param validation → เก็บ default, อย่า tune ฝืน (quant-sat ch3).