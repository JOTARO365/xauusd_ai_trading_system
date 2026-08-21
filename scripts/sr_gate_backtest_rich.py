#!/usr/bin/env python
"""scripts/sr_gate_backtest_rich.py — วัดผล RICH-zone gate (เด้งมีนัยสถิติ) ต่อ algo×คู่ (OFF vs rich-ON).

ต่างจาก sr_gate_backtest.py: gate นี้ block เฉพาะโซนที่ **causal bounce_pct ≥ min + tests ≥ min**
(sr_entry_gate.blocks_at rich mode) ไม่ใช่แค่มี swing ใกล้ — เลือกกว่า (rich 3-ชั้น: revisit+bounce-sig+ATR).
gate ต้องรับ c (close) → สร้าง gate closure ต่อ symbol/TF ให้ c ตรงกับ h,l ที่ bt_ ใช้ (parity).

เกณฑ์เปิด live เดียวกับ sr_gate_backtest (auto-backtest-live-authorization).
out: data/sr_gate_combos_rich.json (ตัวผ่าน) + docs/reviews/sr-gate-eval-rich.md
รัน: python scripts/sr_gate_backtest_rich.py
"""
import json
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

MIN_N = B.MIN_N
COMBOS_OUT = os.path.join(_ROOT, "data", "sr_gate_combos_rich.json")
REPORT_OUT = os.path.join(_ROOT, "docs", "reviews", "sr-gate-eval-rich.md")


def _decide(off, on):
    if not on or not off or not on.get("n"):
        return False, "no data"
    if on["n"] < MIN_N:
        return False, f"n_on {on['n']}<{MIN_N}"
    if on["n"] < 0.15 * off["n"]:
        return False, f"gate ตัดเยอะเกิน (n {off['n']}→{on['n']})"
    if on["exp_R"] <= 0:
        return False, f"exp_R_on {on['exp_R']}≤0"
    if on["oos"] < 0:
        return False, f"OOS_on {on['oos']}<0"
    if on["t"] < 2.0:
        return False, f"t_on {on['t']}<2"
    if on["exp_R"] < off["exp_R"]:
        return False, f"rich gate ทำแย่ลง (exp_R {off['exp_R']}→{on['exp_R']})"
    return True, "ผ่าน (rich gate ช่วย + robust)"


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init fail"); return
    from connectors.pair_collector import _broker_map
    from agents import algo_registry as reg
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None
    bm = _broker_map() or {}
    params = SR.params_from_config()
    mb = float(getattr(__import__("config"), "SR_RICH_MIN_BOUNCE", 55))
    mt = int(getattr(__import__("config"), "SR_RICH_MIN_TESTS", 3))
    rich = (mb, mt)
    cost_of = lambda lg: (_sc.cost_pips(lg) if _sc else None) or 30.0           # noqa: E731

    def macro_series(lg, tm, tf):
        macro_lg, sign = R.macro_for(lg)
        e = bm.get(macro_lg, macro_lg); mt5.symbol_select(e, True)
        r = mt5.copy_rates_from_pos(e, tf, 0, len(tm) + 500)
        if r is None:
            return None, sign
        emap = {int(t): float(cc) for t, cc in zip(r["time"], r["close"])}
        return np.array([emap.get(int(t), np.nan) for t in tm], float), sign

    rows = []

    def run(algo, lg, tf, off_fn, on_fn):
        off = B._stats(off_fn()); on = B._stats(on_fn())
        en, why = _decide(off, on)
        rows.append({"algo": algo, "pair": lg, "tf": tf, "off": off, "on": on, "enable": en, "why": why})
        _f = lambda s: f"exp_R {s['exp_R']:+.3f} t {s['t']:+.2f} OOS {s['oos']:+.3f} n {s['n']}" if s else "—"
        print(f"  {'✓' if en else '·'} {algo:20s} {lg:8s} | OFF {_f(off):42s} | rich-ON {_f(on):42s} | {why}")

    print(f"RICH S/R gate eval — params={params} · rich(min_bounce,min_tests)={rich}\n")
    for lg in reg.UNIVERSE:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
        except Exception:
            info = rh = None
        if not info or rh is None or len(rh) < 800:
            print(f"  {lg}: ข้อมูลไม่พอ"); continue
        pt = float(info.point); cost = cost_of(lg)
        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float); tm = rh["time"]
        # gate closure ต่อ symbol: c (H1) ตรงกับ h,l ที่ bt_ H1 ใช้ → parity
        g1 = (lambda cc: (lambda hh, ll, i, px, d, av: SR.blocks_at(hh, ll, i, px, d, av, params, c=cc, rich=rich)))(c)
        run("regime_momentum", lg, "H1",
            lambda: B.bt_momentum(h, l, c, cost, pt, brk=B._pc("regime_momentum", lg, "BRK", 20),
                                  sl_atr=B._pc("regime_momentum", lg, "SL_ATR", 1.5),
                                  rr=B._pc("regime_momentum", lg, "RR", 2.0), tm=tm, sym=lg),
            lambda: B.bt_momentum(h, l, c, cost, pt, brk=B._pc("regime_momentum", lg, "BRK", 20),
                                  sl_atr=B._pc("regime_momentum", lg, "SL_ATR", 1.5),
                                  rr=B._pc("regime_momentum", lg, "RR", 2.0), tm=tm, sym=lg, gate=g1))
        run("regime_momentum_fvg", lg, "H1",
            lambda: B.bt_momentum_fvg(h, l, c, cost, pt, tm=tm, sym=lg),
            lambda: B.bt_momentum_fvg(h, l, c, cost, pt, tm=tm, sym=lg, gate=g1))
        run("mean_reversion", lg, "H1",
            lambda: B.bt_meanrev(h, l, c, cost, pt),
            lambda: B.bt_meanrev(h, l, c, cost, pt, gate=g1))
        run("sweep_reversal", lg, "H1",
            lambda: B.bt_sweep(h, l, c, tm, cost, pt, rr=B._pc("sweep_reversal", lg, "RR", 1.5),
                               buf_atr=B._pc("sweep_reversal", lg, "BUF_ATR", 0.5)),
            lambda: B.bt_sweep(h, l, c, tm, cost, pt, rr=B._pc("sweep_reversal", lg, "RR", 1.5),
                               buf_atr=B._pc("sweep_reversal", lg, "BUF_ATR", 0.5), gate=g1))
        rh4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 30000)
        if rh4 is not None and len(rh4) > 500:
            h4 = rh4["high"].astype(float); l4 = rh4["low"].astype(float); c4 = rh4["close"].astype(float)
            g4 = (lambda cc: (lambda hh, ll, i, px, d, av: SR.blocks_at(hh, ll, i, px, d, av, params, c=cc, rich=rich)))(c4)
            mac, msign = macro_series(lg, rh4["time"], mt5.TIMEFRAME_H4)
            if mac is not None:
                run("macro_momentum", lg, "H4",
                    lambda: B.bt_macro(h4, l4, c4, mac, cost, pt, brk=B._pc("macro_momentum", lg, "BRK", 20),
                                       mlb=B._pc("macro_momentum", lg, "MLB", 24),
                                       sl_atr=B._pc("macro_momentum", lg, "SL_ATR", 1.5),
                                       rr=B._pc("macro_momentum", lg, "RR", 2.0), msign=msign, tm=rh4["time"], sym=lg),
                    lambda: B.bt_macro(h4, l4, c4, mac, cost, pt, brk=B._pc("macro_momentum", lg, "BRK", 20),
                                       mlb=B._pc("macro_momentum", lg, "MLB", 24),
                                       sl_atr=B._pc("macro_momentum", lg, "SL_ATR", 1.5),
                                       rr=B._pc("macro_momentum", lg, "RR", 2.0), msign=msign, tm=rh4["time"], sym=lg, gate=g4))
    mt5.shutdown()

    passing = [f"{r['algo']}|{r['pair']}" for r in rows if r["enable"]]
    json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "params": {"lookback": params[0], "pivot": params[1], "block_atr": params[2],
                          "min_touches": params[3], "cluster_atr": params[4]},
               "rich": {"min_bounce": mb, "min_tests": mt},
               "criteria": "exp_R>0 · OOS≥0 · t≥2 · n≥%d · exp_R_on≥exp_R_off · n_on≥0.15·n_off" % MIN_N,
               "combos": passing}, open(COMBOS_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        f.write(f"# RICH S/R gate — evaluation ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write(f"params=`{params}` · rich(min_bounce,min_tests)=`{rich}`\n\n")
        f.write("block เฉพาะโซนที่ **causal bounce_pct ≥ min + tests ≥ min** (ไม่ใช่แค่มี swing)\n\n")
        f.write("| ✓ | algo | คู่ | TF | OFF exp_R/t/n | rich-ON exp_R/t/n | Δexp_R | verdict |\n")
        f.write("|---|------|-----|----|----|----|----|----|\n")
        for r in sorted(rows, key=lambda x: (not x["enable"], x["algo"], x["pair"])):
            off, on = r["off"], r["on"]
            of = f"{off['exp_R']:+.3f}/{off['t']:+.2f}/{off['n']}" if off else "—"
            onf = f"{on['exp_R']:+.3f}/{on['t']:+.2f}/{on['n']}" if on else "—"
            dd = f"{on['exp_R'] - off['exp_R']:+.3f}" if (on and off) else "—"
            f.write(f"| {'✓' if r['enable'] else ''} | {r['algo']} | {r['pair']} | {r['tf']} | {of} | {onf} | {dd} | {r['why']} |\n")
        f.write(f"\n**เปิด live (rich) {len(passing)} combo:** {', '.join(passing) or '(ไม่มี)'}\n")

    ev = [r for r in rows if r["off"] and r["on"]]
    deltas = [r["on"]["exp_R"] - r["off"]["exp_R"] for r in ev]
    up = sum(1 for d in deltas if d > 0.0005); dn = sum(1 for d in deltas if d < -0.0005)
    avg = sum(deltas) / len(deltas) if deltas else 0.0
    print(f"\n=== RICH GATE AGGREGATE ({len(ev)} combo) ===")
    print(f"  ดีขึ้น {up} · แย่ลง {dn} · เท่าเดิม {len(ev)-up-dn} · Δexp_R เฉลี่ย {avg:+.4f}R")
    print(f"ผ่านเกณฑ์ live เข้ม {len(passing)} combo → {COMBOS_OUT}")
    for cc in passing:
        print(f"   ✓ {cc}")
    print(f"report → {REPORT_OUT}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
