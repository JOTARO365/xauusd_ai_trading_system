#!/usr/bin/env python
"""scripts/sr_gate_backtest_extra.py — S/R entry-gate eval ครอบ 3 algo ที่ sr_gate_backtest.py ข้าม:
tsmom_d1 (D1) · cdc_zone (D1) · pullback_buy (H1) — XAUUSD, gate OFF vs ON, เกณฑ์เดียวกับตัวเดิม
(_decide import ตรงจาก sr_gate_backtest = criteria ไม่ drift).

⚠️ parity caveats (อ่านก่อนเชื่อเลข):
  1. tsmom_d1: live อยู่ใน SR_BREAKOUT_ALGOS (ยกเว้น gate) + XAUUSD ไม่อยู่ eligible ของ MSE
     (gold ผ่าน tsmom_manager ซึ่งไม่เรียก gate เลย) → ผล ON = counterfactual ล้วน.
     gate hook ใน bt_tsmom = "เลื่อน flip ทั้งไม้" (block → คง pos เดิม ไม่ exit) ≠ live ที่ mgmt
     exit-on-flip ทำงานเสมอแล้วค่อย block entry ใหม่ (live = flat ช่วง block, backtest = ถือไม้เก่า).
  2. cdc_zone: hook เดิมใน B.bt_cdc ส่ง av=0.0 → SR.blocks_at คืน False เสมอ (dead no-op) —
     script นี้ wrap gate ให้คำนวณ ATR-D1 (R.atr) ที่ bar i เอง = ตรง live ที่ executor ส่ง
     _simple_atr(bars)[-1] (Wilder 14 เหมือนกัน ต่างแค่ seed ช่วง warmup).
  3. pullback_buy: B.bt_pullback ไม่มี gate param → copy local + hook ตำแหน่งเดียวกับ bt_momentum
     (หลัง filter ทั้งหมด ก่อน _resolve) + assert gate=None ให้ผลเท่าต้นฉบับ (กัน copy drift).
  4. offset 1 แท่ง (มีใน sr_gate_backtest.py เดิมด้วย): live เรียก gate ที่ i=len(c)-1 (แท่ง forming)
     แต่ signal อยู่ n-2 → live เห็น pivot ที่ confirm ด้วยแท่ง signal เอง + ATR รวม TR แท่ง forming;
     backtest hook ที่ signal bar i (pivot < i). ทิศ bias: backtest เห็นแนวช้ากว่า live 1 แท่ง.

ไม่เขียน data/sr_gate_combos.json (ไม่แตะ allowlist live — ผลที่ผ่านต้องให้ user ตัดสินเอง).
out: append docs/reviews/sr-gate-eval-extra.md   รัน: python scripts/sr_gate_backtest_extra.py
"""
import os
import sys
from datetime import datetime, timezone

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import backtest_all as B                                    # noqa: E402
import regime_lib as R                                      # noqa: E402
from agents import sr_entry_gate as SR                      # noqa: E402
from sr_gate_backtest import _decide                        # noqa: E402  (เกณฑ์เดียวกันเป๊ะ)

MIN_N = B.MIN_N
REPORT_OUT = os.path.join(_ROOT, "docs", "reviews", "sr-gate-eval-extra.md")


def bt_pullback_gated(h, l, c, tm, d1_time, d1_close, cost, pt, ema_n=20, d1_ema=20, lb=8,
                      buf_atr=0.25, cap_atr=2.0, rr=3.0, mh=72, gate=None):
    """copy ตรงจาก B.bt_pullback + gate hook (convention เดียวกับ bt_momentum: skip แท่งนี้ ลองใหม่แท่งหน้า).
    gate=None ต้องคืนผลเท่า B.bt_pullback เป๊ะ — main() assert กัน copy drift."""
    de = B._ema_arr(d1_close, d1_ema); up = (d1_close > de).astype(int)
    idx = np.clip(np.searchsorted(d1_time, tm.astype(np.int64), side="right") - 2, 0, len(up) - 1)
    d1_up = up[idx].astype(bool)
    ema = B._ema_arr(c, ema_n); atr = R.atr(h, l, c)
    n = len(c); tr = []; i = max(ema_n, lb, R.VOL_LOOKBACK) + 2
    while i < n - 1:
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0 or not d1_up[i] or not (c[i] > ema[i] and c[i - 1] <= ema[i - 1]):
            i += 1; continue
        px = float(c[i]); swing = float(l[i - lb:i + 1].min())
        sld = min((px - swing) + buf_atr * av, cap_atr * av)
        if sld <= 0:
            i += 1; continue
        if gate and gate(h, l, i, px, 1, av):               # S/R gate: BUY ชนแนวต้านแข็งใกล้ → skip
            i += 1; continue
        r, ei = B._resolve(h, l, c, i, 1, px, sld / pt, rr, pt, cost, mh)
        tr.append(r); i = ei + 1
    return tr


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    from connectors.pair_collector import _broker_map
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    import config as _cfg
    bm = _broker_map() or {}
    params = SR.params_from_config()
    gate = lambda h, l, i, px, d, av: SR.blocks_at(h, l, i, px, d, av, params)  # noqa: E731
    lg = "XAUUSD"
    sym = bm.get(lg, lg)
    mt5.symbol_select(sym, True)
    info = mt5.symbol_info(sym)
    rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)   # เท่า backtest_all/sr_gate_backtest
    rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
    mt5.shutdown()
    if not info or rh is None or len(rh) < 2000 or rd is None or len(rd) < 300:
        print(f"{lg}: ข้อมูลไม่พอ (H1 {0 if rh is None else len(rh)} / D1 {0 if rd is None else len(rd)})")
        return
    pt = float(info.point)
    cost = (_sc.cost_pips(lg) if _sc else None) or 30.0
    h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float); tm = rh["time"]
    dh = rd["high"].astype(float); dl = rd["low"].astype(float); dc = rd["close"].astype(float)
    dt = rd["time"].astype(np.int64)
    print(f"S/R gate eval EXTRA — {lg} · params (lookback,pivot,block_atr,min_touch,cluster_atr)={params}")
    print(f"data: H1 n={len(c)} · D1 n={len(dc)} · cost={cost} pips\n")

    rows = []

    def run(algo, tf, off_fn, on_fn, note=""):
        off = B._stats(off_fn()); on = B._stats(on_fn())
        en, why = _decide(off, on)
        rows.append({"algo": algo, "pair": lg, "tf": tf, "off": off, "on": on,
                     "enable": en, "why": why, "note": note})
        _f = lambda s: f"exp_R {s['exp_R']:+.3f} t {s['t']:+.2f} OOS {s['oos']:+.3f} n {s['n']}" if s else "—"
        print(f"  {'✓' if en else '·'} {algo:14s} {tf:3s} | OFF {_f(off):44s} | ON {_f(on):44s} | {why}")

    # ── tsmom_d1 (D1) — hook เดิมใน bt_tsmom (เลื่อน flip เมื่อ block; ดู caveat 1 ใน docstring) ──
    run("tsmom_d1", "D1",
        lambda: B.bt_tsmom(dh, dl, dc, cost * pt),
        lambda: B.bt_tsmom(dh, dl, dc, cost * pt, gate=gate),
        note="counterfactual: live ยกเว้น gate (SR_BREAKOUT_ALGOS) + gold ไป tsmom_manager (ไม่มี gate)")

    # ── cdc_zone (D1) — hook เดิมส่ง av=0.0 (no-op) → wrap gate คำนวณ ATR-D1 เอง (caveat 2) ──
    atr_d1 = R.atr(dh, dl, dc)

    def gate_d1(hh, ll, i, px, d, av):
        if av <= 0:
            av = float(atr_d1[i]) if atr_d1[i] == atr_d1[i] else 0.0
        return SR.blocks_at(hh, ll, i, px, d, av, params)

    cdc_mode = str(getattr(_cfg, "CDC_DIR_MODE", "long")).lower()   # ตรง live CDCZoneAlgo
    run("cdc_zone", "D1",
        lambda: B.bt_cdc(dh, dl, dc, cost * pt, mode=cdc_mode),
        lambda: B.bt_cdc(dh, dl, dc, cost * pt, mode=cdc_mode, gate=gate_d1),
        note=f"mode={cdc_mode} · gate wrap ATR-D1 (hook เดิม av=0.0 = no-op)")

    # ── pullback_buy (H1) — local copy + gate hook (caveat 3) · config args ตรง live PULLBACK_* ──
    pb_args = dict(ema_n=int(getattr(_cfg, "PULLBACK_EMA", 20)),
                   d1_ema=int(getattr(_cfg, "PULLBACK_D1_EMA", 20)),
                   lb=int(getattr(_cfg, "PULLBACK_SWING_LB", 8)),
                   buf_atr=float(getattr(_cfg, "PULLBACK_SL_BUF_ATR", 0.25)),
                   cap_atr=float(getattr(_cfg, "PULLBACK_SL_CAP_ATR", 2.0)),
                   rr=float(getattr(_cfg, "PULLBACK_RR", 3.0)))
    ref = B.bt_pullback(h, l, c, tm, dt, dc, cost, pt, **pb_args)
    loc = bt_pullback_gated(h, l, c, tm, dt, dc, cost, pt, **pb_args, gate=None)
    if len(ref) != len(loc) or any(abs(a - b) > 1e-9 for a, b in zip(ref, loc)):
        print(f"  ⚠️ bt_pullback_gated(gate=None) ≠ B.bt_pullback ({len(loc)} vs {len(ref)} trades) — "
              "copy drift! ผล pullback_buy เชื่อไม่ได้จนกว่าจะ sync")
    run("pullback_buy", "H1",
        lambda: ref,
        lambda: bt_pullback_gated(h, l, c, tm, dt, dc, cost, pt, **pb_args, gate=gate),
        note="OFF=B.bt_pullback ตรงตัว (assert local copy เท่ากันก่อน) · exit จำลอง SL/TP ไม่ใช่ managed BE/trailing")

    # ── report (append — ไม่ทับผลรอบก่อน) ─────────────────────────────────────
    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    new_file = not os.path.exists(REPORT_OUT)
    with open(REPORT_OUT, "a", encoding="utf-8") as f:
        if new_file:
            f.write("# S/R Entry Gate — extra coverage (tsmom_d1 · cdc_zone · pullback_buy)\n")
        f.write(f"\n## Run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z — XAUUSD\n\n")
        f.write(f"params (lookback,pivot,block_atr,min_touches,cluster_atr) = `{params}` · cost {cost} pips · "
                f"H1 n={len(c)} · D1 n={len(dc)}\n\n")
        f.write("เกณฑ์เปิด live (เดียวกับ sr_gate_backtest): gated `exp_R>0 · OOS≥0 · t≥2 · n≥%d · "
                "exp_R_on≥exp_R_off · n_on≥0.15·n_off`\n\n" % MIN_N)
        f.write("| ✓ | algo | TF | OFF exp_R/t/OOS/n | ON exp_R/t/OOS/n | Δexp_R | verdict | parity note |\n")
        f.write("|---|------|----|----|----|----|----|----|\n")
        for r in rows:
            off, on = r["off"], r["on"]
            of = f"{off['exp_R']:+.3f}/{off['t']:+.2f}/{off['oos']:+.3f}/{off['n']}" if off else "—"
            onf = f"{on['exp_R']:+.3f}/{on['t']:+.2f}/{on['oos']:+.3f}/{on['n']}" if on else "—"
            dd = f"{on['exp_R'] - off['exp_R']:+.3f}" if (on and off) else "—"
            f.write(f"| {'✓' if r['enable'] else ''} | {r['algo']} | {r['tf']} | {of} | {onf} | {dd} | "
                    f"{r['why']} | {r['note']} |\n")
        f.write("\ncaveats: (1) tsmom hook = เลื่อน flip ทั้งไม้ ≠ live exit-แล้ว-block · "
                "(2) live gate เรียกที่แท่ง forming (offset 1 แท่งจาก hook นี้ — เหมือน sr_gate_backtest เดิม) · "
                "(3) ไม่เขียน sr_gate_combos.json — ตัวผ่านต้องให้ user ตัดสินก่อนแตะ allowlist\n")

    passing = [f"{r['algo']}|{lg}" for r in rows if r["enable"]]
    print(f"\nผ่านเกณฑ์ live เข้ม {len(passing)} combo: {', '.join(passing) or '(ไม่มี)'}")
    print("(ไม่เขียน data/sr_gate_combos.json — เจตนา: allowlist live ต้องผ่านการตัดสินของ user)")
    print(f"report → {REPORT_OUT}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
