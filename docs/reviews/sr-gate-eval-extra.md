# S/R Entry Gate — extra coverage (tsmom_d1 · cdc_zone · pullback_buy)

## Run 2026-08-20 02:29Z — XAUUSD

params (lookback,pivot,block_atr,min_touches,cluster_atr) = `(60, 3, 0.5, 2, 0.3)` · cost 30.0 pips · H1 n=50000 · D1 n=3000

เกณฑ์เปิด live (เดียวกับ sr_gate_backtest): gated `exp_R>0 · OOS≥0 · t≥2 · n≥80 · exp_R_on≥exp_R_off · n_on≥0.15·n_off`

| ✓ | algo | TF | OFF exp_R/t/OOS/n | ON exp_R/t/OOS/n | Δexp_R | verdict | parity note |
|---|------|----|----|----|----|----|----|
|  | tsmom_d1 | D1 | +0.167/+1.02/+0.680/103 | +0.177/+1.08/+0.701/101 | +0.010 | t_on 1.08<2 | counterfactual: live ยกเว้น gate (SR_BREAKOUT_ALGOS) + gold ไป tsmom_manager (ไม่มี gate) |
|  | cdc_zone | D1 | +1.013/+2.07/+2.731/46 | +1.019/+2.09/+2.744/46 | +0.006 | n_on 46<80 | mode=long · gate wrap ATR-D1 (hook เดิม av=0.0 = no-op) |
|  | pullback_buy | H1 | +0.118/+1.77/+0.219/677 | +0.096/+1.43/+0.222/656 | -0.022 | t_on 1.43<2 | OFF=B.bt_pullback ตรงตัว (assert local copy เท่ากันก่อน) · exit จำลอง SL/TP ไม่ใช่ managed BE/trailing |

caveats: (1) tsmom hook = เลื่อน flip ทั้งไม้ ≠ live exit-แล้ว-block · (2) live gate เรียกที่แท่ง forming (offset 1 แท่งจาก hook นี้ — เหมือน sr_gate_backtest เดิม) · (3) ไม่เขียน sr_gate_combos.json — ตัวผ่านต้องให้ user ตัดสินก่อนแตะ allowlist
