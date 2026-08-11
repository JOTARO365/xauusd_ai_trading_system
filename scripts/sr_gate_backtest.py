#!/usr/bin/env python
"""scripts/sr_gate_backtest.py — วัดผล S/R entry gate ต่อ algo×คู่ (gate OFF vs ON) → ตัดสินเปิด live.

reuse bt_* จาก backtest_all (parity เป๊ะ) + inject gate = agents.sr_entry_gate.blocks_at.
เกณฑ์เปิด (auto-backtest-live-authorization): gated ต้อง exp_R>0 · OOS≥0 · t≥2 · n≥MIN ·
exp_R_on ≥ exp_R_off (ไม่ทำแย่ลง) · n_on ≥ 0.15·n_off (ไม่ block ทิ้งเกือบหมด).

out: data/sr_gate_combos.json (combo ที่ผ่าน → live gate เฉพาะตัวนี้) + docs/reviews/sr-gate-eval.md
รัน: python scripts/sr_gate_backtest.py
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
COMBOS_OUT = os.path.join(_ROOT, "data", "sr_gate_combos.json")
REPORT_OUT = os.path.join(_ROOT, "docs", "reviews", "sr-gate-eval.md")


def _decide(off, on):
    """คืน (enable: bool, why: str)."""
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
        return False, f"gate ทำแย่ลง (exp_R {off['exp_R']}→{on['exp_R']})"
    return True, "ผ่าน (gate ช่วย + robust)"


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
    gate = lambda h, l, i, px, d, av: SR.blocks_at(h, l, i, px, d, av, params)  # noqa: E731
    cost_of = lambda lg: (_sc.cost_pips(lg) if _sc else None) or 30.0           # noqa: E731

    def macro_series(lg, tm, tf):
        macro_lg, sign = R.macro_for(lg)
        e = bm.get(macro_lg, macro_lg); mt5.symbol_select(e, True)
        r = mt5.copy_rates_from_pos(e, tf, 0, len(tm) + 500)
        if r is None:
            return None, sign
        emap = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
        return np.array([emap.get(int(t), np.nan) for t in tm], float), sign

    rows = []

    def run(algo, lg, tf, off_fn, on_fn):
        off = B._stats(off_fn()); on = B._stats(on_fn())
        en, why = _decide(off, on)
        rows.append({"algo": algo, "pair": lg, "tf": tf, "off": off, "on": on, "enable": en, "why": why})
        _f = lambda s: f"exp_R {s['exp_R']:+.3f} t {s['t']:+.2f} OOS {s['oos']:+.3f} n {s['n']}" if s else "—"
        print(f"  {'✓' if en else '·'} {algo:20s} {lg:8s} | OFF {_f(off):42s} | ON {_f(on):42s} | {why}")

    print(f"S/R gate eval — params (lookback,pivot,block_atr,min_touch,cluster_atr)={params}\n")
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
        run("regime_momentum", lg, "H1",
            lambda: B.bt_momentum(h, l, c, cost, pt, brk=B._pc("regime_momentum", lg, "BRK", 20),
                                  sl_atr=B._pc("regime_momentum", lg, "SL_ATR", 1.5),
                                  rr=B._pc("regime_momentum", lg, "RR", 2.0), tm=tm, sym=lg),
            lambda: B.bt_momentum(h, l, c, cost, pt, brk=B._pc("regime_momentum", lg, "BRK", 20),
                                  sl_atr=B._pc("regime_momentum", lg, "SL_ATR", 1.5),
                                  rr=B._pc("regime_momentum", lg, "RR", 2.0), tm=tm, sym=lg, gate=gate))
        run("regime_momentum_fvg", lg, "H1",
            lambda: B.bt_momentum_fvg(h, l, c, cost, pt, tm=tm, sym=lg),
            lambda: B.bt_momentum_fvg(h, l, c, cost, pt, tm=tm, sym=lg, gate=gate))
        run("mean_reversion", lg, "H1",
            lambda: B.bt_meanrev(h, l, c, cost, pt),
            lambda: B.bt_meanrev(h, l, c, cost, pt, gate=gate))
        run("sweep_reversal", lg, "H1",
            lambda: B.bt_sweep(h, l, c, tm, cost, pt, rr=B._pc("sweep_reversal", lg, "RR", 1.5),
                               buf_atr=B._pc("sweep_reversal", lg, "BUF_ATR", 0.5)),
            lambda: B.bt_sweep(h, l, c, tm, cost, pt, rr=B._pc("sweep_reversal", lg, "RR", 1.5),
                               buf_atr=B._pc("sweep_reversal", lg, "BUF_ATR", 0.5), gate=gate))
        rh4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 30000)
        if rh4 is not None and len(rh4) > 500:
            h4 = rh4["high"].astype(float); l4 = rh4["low"].astype(float); c4 = rh4["close"].astype(float)
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
                                       rr=B._pc("macro_momentum", lg, "RR", 2.0), msign=msign, tm=rh4["time"], sym=lg, gate=gate))
        try:
            run("confluence_15m", lg, "M15",
                lambda: B.bt_conf15m(mt5, sym, bm.get("EURUSD", "EURUSD"), cost, pt,
                                     brk=B._pc("confluence_15m", lg, "BRK", 12), rr=B._pc("confluence_15m", lg, "RR", 2.0),
                                     sl_atr=B._pc("confluence_15m", lg, "SL_ATR", 1.0), vk=B._pc("confluence_15m", lg, "VK", 1.5),
                                     session=B._pc("confluence_15m", lg, "session", None), season_sym=lg),
                lambda: B.bt_conf15m(mt5, sym, bm.get("EURUSD", "EURUSD"), cost, pt,
                                     brk=B._pc("confluence_15m", lg, "BRK", 12), rr=B._pc("confluence_15m", lg, "RR", 2.0),
                                     sl_atr=B._pc("confluence_15m", lg, "SL_ATR", 1.0), vk=B._pc("confluence_15m", lg, "VK", 1.5),
                                     session=B._pc("confluence_15m", lg, "session", None), season_sym=lg, gate=gate))
        except Exception as e:
            print(f"    confluence_15m {lg}: {str(e)[:50]}")
    mt5.shutdown()

    passing = [f"{r['algo']}|{r['pair']}" for r in rows if r["enable"]]
    json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "params": {"lookback": params[0], "pivot": params[1], "block_atr": params[2],
                          "min_touches": params[3], "cluster_atr": params[4]},
               "criteria": "exp_R>0 · OOS≥0 · t≥2 · n≥%d · exp_R_on≥exp_R_off · n_on≥0.15·n_off" % MIN_N,
               "combos": passing}, open(COMBOS_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        f.write(f"# S/R Entry Gate — evaluation ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write(f"params (lookback,pivot,block_atr,min_touches,cluster_atr) = `{params}`\n\n")
        f.write("เกณฑ์เปิด live: gated `exp_R>0 · OOS≥0 · t≥2 · n≥%d · exp_R_on≥exp_R_off · n_on≥0.15·n_off`\n\n" % MIN_N)
        f.write("| ✓ | algo | คู่ | TF | OFF exp_R/t/n | ON exp_R/t/n | Δexp_R | verdict |\n")
        f.write("|---|------|-----|----|----|----|----|----|\n")
        for r in sorted(rows, key=lambda x: (not x["enable"], x["algo"], x["pair"])):
            off, on = r["off"], r["on"]
            of = f"{off['exp_R']:+.3f}/{off['t']:+.2f}/{off['n']}" if off else "—"
            onf = f"{on['exp_R']:+.3f}/{on['t']:+.2f}/{on['n']}" if on else "—"
            dd = f"{on['exp_R'] - off['exp_R']:+.3f}" if (on and off) else "—"
            f.write(f"| {'✓' if r['enable'] else ''} | {r['algo']} | {r['pair']} | {r['tf']} | {of} | {onf} | {dd} | {r['why']} |\n")
        f.write(f"\n**เปิด live {len(passing)} combo:** {', '.join(passing) or '(ไม่มี combo ผ่าน)'}\n")

    # aggregate (global gate lens): กี่ combo ดีขึ้น/แย่ลง, Δexp_R เฉลี่ย, ตัวที่ flip +EV
    ev = [r for r in rows if r["off"] and r["on"]]
    deltas = [r["on"]["exp_R"] - r["off"]["exp_R"] for r in ev]
    up = sum(1 for d in deltas if d > 0.0005)
    dn = sum(1 for d in deltas if d < -0.0005)
    flat = len(ev) - up - dn
    avg = sum(deltas) / len(deltas) if deltas else 0.0
    flip = [f"{r['algo']}|{r['pair']}" for r in ev if r["off"]["exp_R"] <= 0 < r["on"]["exp_R"]]
    lost = [f"{r['algo']}|{r['pair']}" for r in ev if r["off"]["exp_R"] > 0 >= r["on"]["exp_R"]]
    with open(REPORT_OUT, "a", encoding="utf-8") as f:
        f.write(f"\n## Global gate aggregate ({len(ev)} combo มีผล)\n\n")
        f.write(f"- Δexp_R > 0 (ดีขึ้น): **{up}** · < 0 (แย่ลง): **{dn}** · ~เท่าเดิม: {flat}\n")
        f.write(f"- Δexp_R เฉลี่ยทั้งพอร์ต: **{avg:+.4f} R**\n")
        f.write(f"- flip เป็น +EV เพราะ gate: {', '.join(flip) or '(ไม่มี)'}\n")
        f.write(f"- หลุด +EV เพราะ gate: {', '.join(lost) or '(ไม่มี)'}\n")
    print(f"\n=== GLOBAL GATE AGGREGATE ({len(ev)} combo) ===")
    print(f"  ดีขึ้น {up} · แย่ลง {dn} · เท่าเดิม {flat} · Δexp_R เฉลี่ย {avg:+.4f}R")
    print(f"  flip→+EV: {flip or '(ไม่มี)'}")
    print(f"  หลุด+EV: {lost or '(ไม่มี)'}")
    print(f"\nผ่านเกณฑ์ live เข้ม {len(passing)} combo → {COMBOS_OUT}")
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
