#!/usr/bin/env python
"""scripts/confirm_tf_matrix.py — ทุก algo × confirm-TF (M15/H1/H4/D1): แท่งปิด TF ไหน confirm ดีสุดต่อ algo.

ต่อยอด confirm_gate_backtest: แทนที่ confirm ด้วยแท่ง "TF เดียวกับ signal" → ทดสอบ confirm ด้วยแท่งปิดของ
**หลาย TF** (MTF entry trigger). สำหรับ signal ที่เวลา t (TF ของ algo) → หาแท่ง confirm-TF ที่ "ปิดครบก่อน t"
(causal เข้ม, กัน look-ahead) → apply CLV/pin (โหมดต่อ algo: momentum=cont, fade=rev).

metric = Δexp_R เทียบ OFF ต่อ (algo×pair×confirmTF). สรุปต่อ algo: confirm-TF ที่ Δexp_R เฉลี่ยดีสุด (n_keep พอ).
out: docs/reviews/confirm-tf-matrix.md + data/confirm_tf_matrix.json
รัน: python scripts/confirm_tf_matrix.py
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
from agents import confirm_gate as CF                       # noqa: E402

MIN_N = B.MIN_N
MIN_KEEP = 0.30
TF_SEC = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
CONFIRM_TFS = ["M15", "H1", "H4", "D1"]
REPORT_OUT = os.path.join(_ROOT, "docs", "reviews", "confirm-tf-matrix.md")
JSON_OUT = os.path.join(_ROOT, "data", "confirm_tf_matrix.json")


def _mtf_gate(sig_tm, sig_sec, cf_h, cf_l, cf_c, cf_tm, cf_sec, mode, thr):
    """gate(h,l,i,px,d,av) ที่ confirm ด้วยแท่ง confirm-TF ที่ปิดครบก่อน 'signal bar i ปิด' (causal).
    ใช้ body ของแท่ง confirm-TF เอง (cf_c[j], cf_h/cf_l รอบ j) — ไม่ใช้ px ของ signal."""
    sig_close = sig_tm.astype(np.int64) + sig_sec
    cf_close = cf_tm.astype(np.int64) + cf_sec
    j_of = np.searchsorted(cf_close, sig_close, side="right") - 1     # แท่ง confirm ล่าสุดที่ปิด ≤ signal ปิด
    p = (thr, mode)

    def gate(h, l, i, px, d, av):
        if i >= len(j_of):
            return False
        j = int(j_of[i])
        if j < CF.PIN_LB:                                             # ยังไม่มีแท่ง confirm พอ → ไม่ block
            return False
        return CF.blocks_at(cf_h, cf_l, j, float(cf_c[j]), d, av, p)
    return gate


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
    thr = CF.params_from_config()[0]
    cost_of = lambda lg: (_sc.cost_pips(lg) if _sc else None) or 30.0     # noqa: E731

    def macro_series(lg, tm, tf):
        macro_lg, sign = R.macro_for(lg)
        e = bm.get(macro_lg, macro_lg); mt5.symbol_select(e, True)
        r = mt5.copy_rates_from_pos(e, tf, 0, len(tm) + 500)
        if r is None:
            return None, sign
        emap = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
        return np.array([emap.get(int(t), np.nan) for t in tm], float), sign

    # rows: {algo, pair, mode, sig_tf, base(stats), tf:{TF: {dR, on_expR, on_t, on_oos, n}}}
    rows = []

    def add(algo, lg, sig_tf, base_fn, on_fn_for_tf, cf):
        """base_fn() → list R baseline. on_fn_for_tf(gate) → list R with confirm. cf = {TF:(h,l,c,tm,sec)}."""
        base = B._stats(base_fn())
        mode = CF.mode_for(algo)
        rec = {"algo": algo, "pair": lg, "mode": mode, "sig_tf": sig_tf, "base": base, "tf": {}}
        sig_tm, sig_sec = cf["_sig"]
        for tf in CONFIRM_TFS:
            if tf not in cf:
                continue
            ch, cl, cc, ctm, csec = cf[tf]
            gate = _mtf_gate(sig_tm, sig_sec, ch, cl, cc, ctm, csec, mode, thr)
            on = B._stats(on_fn_for_tf(gate))
            if base and on:
                rec["tf"][tf] = {"dR": round(on["exp_R"] - base["exp_R"], 4), "on_expR": on["exp_R"],
                                 "on_t": on["t"], "on_oos": on["oos"], "n": on["n"]}
        rows.append(rec)
        best = _best_tf(rec)
        bt = f"{best[0]} Δ{best[1]:+.3f}" if best else "—"
        bexp = f"{base['exp_R']:+.3f}" if base else "—"
        print(f"  {algo:20s} {lg:8s} [{mode:4s}] sig={sig_tf:3s} base exp_R {bexp} → best confirm: {bt}")

    print(f"Confirm-TF matrix — clv_thr={thr} · confirm ด้วยแท่งปิด {CONFIRM_TFS}\n")
    for lg in reg.UNIVERSE:
        sym = bm.get(lg, lg)
        try:
            mt5.symbol_select(sym, True); info = mt5.symbol_info(sym)
            r15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 40000)
            rh = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
            rh4 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 30000)
            rd = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 3000)
        except Exception:
            info = r15 = rh = rh4 = rd = None
        if not info or rh is None or len(rh) < 800:
            print(f"  {lg}: ข้อมูลไม่พอ"); continue
        pt = float(info.point); cost = cost_of(lg)

        def arr(r):
            return (r["high"].astype(float), r["low"].astype(float), r["close"].astype(float),
                    r["time"].astype(np.int64), None) if r is not None and len(r) > 50 else None

        cf_all = {}
        for tf, r in (("M15", r15), ("H1", rh), ("H4", rh4), ("D1", rd)):
            a = arr(r)
            if a:
                cf_all[tf] = (a[0], a[1], a[2], a[3], TF_SEC[tf])

        h = rh["high"].astype(float); l = rh["low"].astype(float); c = rh["close"].astype(float); tm = rh["time"].astype(np.int64)
        # H1 signal algos
        cf_h1 = dict(cf_all); cf_h1["_sig"] = (tm, TF_SEC["H1"])
        add("regime_momentum", lg, "H1",
            lambda: B.bt_momentum(h, l, c, cost, pt, brk=B._pc("regime_momentum", lg, "BRK", 20),
                                  sl_atr=B._pc("regime_momentum", lg, "SL_ATR", 1.5),
                                  rr=B._pc("regime_momentum", lg, "RR", 2.0), tm=rh["time"], sym=lg),
            lambda g: B.bt_momentum(h, l, c, cost, pt, brk=B._pc("regime_momentum", lg, "BRK", 20),
                                    sl_atr=B._pc("regime_momentum", lg, "SL_ATR", 1.5),
                                    rr=B._pc("regime_momentum", lg, "RR", 2.0), tm=rh["time"], sym=lg, gate=g), cf_h1)
        add("regime_momentum_fvg", lg, "H1",
            lambda: B.bt_momentum_fvg(h, l, c, cost, pt, tm=rh["time"], sym=lg),
            lambda g: B.bt_momentum_fvg(h, l, c, cost, pt, tm=rh["time"], sym=lg, gate=g), cf_h1)
        add("mean_reversion", lg, "H1",
            lambda: B.bt_meanrev(h, l, c, cost, pt),
            lambda g: B.bt_meanrev(h, l, c, cost, pt, gate=g), cf_h1)
        add("sweep_reversal", lg, "H1",
            lambda: B.bt_sweep(h, l, c, rh["time"], cost, pt, rr=B._pc("sweep_reversal", lg, "RR", 1.5),
                               buf_atr=B._pc("sweep_reversal", lg, "BUF_ATR", 0.5)),
            lambda g: B.bt_sweep(h, l, c, rh["time"], cost, pt, rr=B._pc("sweep_reversal", lg, "RR", 1.5),
                                 buf_atr=B._pc("sweep_reversal", lg, "BUF_ATR", 0.5), gate=g), cf_h1)
        # H4 signal: macro_momentum
        if rh4 is not None and len(rh4) > 500:
            h4 = rh4["high"].astype(float); l4 = rh4["low"].astype(float); c4 = rh4["close"].astype(float)
            mac, msign = macro_series(lg, rh4["time"], mt5.TIMEFRAME_H4)
            if mac is not None:
                cf_h4 = dict(cf_all); cf_h4["_sig"] = (rh4["time"].astype(np.int64), TF_SEC["H4"])
                add("macro_momentum", lg, "H4",
                    lambda: B.bt_macro(h4, l4, c4, mac, cost, pt, brk=B._pc("macro_momentum", lg, "BRK", 20),
                                       mlb=B._pc("macro_momentum", lg, "MLB", 24),
                                       sl_atr=B._pc("macro_momentum", lg, "SL_ATR", 1.5),
                                       rr=B._pc("macro_momentum", lg, "RR", 2.0), msign=msign, tm=rh4["time"], sym=lg),
                    lambda g: B.bt_macro(h4, l4, c4, mac, cost, pt, brk=B._pc("macro_momentum", lg, "BRK", 20),
                                         mlb=B._pc("macro_momentum", lg, "MLB", 24),
                                         sl_atr=B._pc("macro_momentum", lg, "SL_ATR", 1.5),
                                         rr=B._pc("macro_momentum", lg, "RR", 2.0), msign=msign, tm=rh4["time"], sym=lg, gate=g), cf_h4)
        # D1 signal: cdc_zone
        if rd is not None and len(rd) >= 300:
            dh = rd["high"].astype(float); dl = rd["low"].astype(float); dc = rd["close"].astype(float)
            cf_d1 = dict(cf_all); cf_d1["_sig"] = (rd["time"].astype(np.int64), TF_SEC["D1"])
            add("cdc_zone", lg, "D1",
                lambda: B.bt_cdc(dh, dl, dc, cost * pt),
                lambda g: B.bt_cdc(dh, dl, dc, cost * pt, gate=g), cf_d1)
            add("tsmom_d1", lg, "D1",
                lambda: B.bt_tsmom(dh, dl, dc, cost * pt),
                lambda g: B.bt_tsmom(dh, dl, dc, cost * pt, gate=g), cf_d1)
        print(f"  {lg}: done")
    mt5.shutdown()

    _write(rows)


def _best_tf(rec):
    """คืน (TF, dR) ของ confirm-TF ที่ Δexp_R ดีสุด (n_keep ≥ MIN_KEEP·base_n). None ถ้าไม่มี."""
    base = rec.get("base")
    if not base or not base.get("n"):
        return None
    cand = []
    for tf, d in rec["tf"].items():
        if d["n"] >= MIN_KEEP * base["n"]:
            cand.append((tf, d["dR"]))
    if not cand:
        return None
    return max(cand, key=lambda t: t[1])


def _write(rows):
    # per-algo aggregate: เฉลี่ย Δexp_R ต่อ confirm-TF ข้ามคู่ → หา TF ดีสุดของ algo
    algos = {}
    for r in rows:
        a = r["algo"]
        algos.setdefault(a, {"mode": r["mode"], "sig_tf": r["sig_tf"], "tf": {tf: [] for tf in CONFIRM_TFS}, "n_pairs": 0})
        algos[a]["n_pairs"] += 1
        base = r.get("base")
        for tf, d in r["tf"].items():
            if base and base.get("n") and d["n"] >= MIN_KEEP * base["n"]:
                algos[a]["tf"][tf].append(d["dR"])

    summary = []
    for a, v in algos.items():
        avg = {tf: (round(sum(xs) / len(xs), 4) if xs else None) for tf, xs in v["tf"].items()}
        valid = {tf: x for tf, x in avg.items() if x is not None}
        best = max(valid.items(), key=lambda t: t[1]) if valid else (None, None)
        summary.append({"algo": a, "mode": v["mode"], "sig_tf": v["sig_tf"], "avg_dR": avg,
                        "best_tf": best[0], "best_dR": best[1], "n_pairs": v["n_pairs"]})
    summary.sort(key=lambda s: (-(s["best_dR"] or -9)))

    json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "clv_thr": CF.params_from_config()[0], "min_keep": MIN_KEEP,
               "note": "Δexp_R เฉลี่ยข้ามคู่ ต่อ confirm-TF; best_tf = แท่งปิด TF ที่ confirm ดีสุดของ algo นั้น",
               "summary": summary, "rows": rows}, open(JSON_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        f.write(f"# Confirm-TF matrix — algo ไหนเหมาะแท่งปิด TF ไหน ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})\n\n")
        f.write("confirm = เข้าเฉพาะเมื่อแท่งปิดของ **confirm-TF** ยืนยันทิศ (mode ต่อ algo: cont=momentum/trend, rev=fade). ")
        f.write("Δexp_R = exp_R(confirm) − exp_R(OFF) เฉลี่ยข้ามคู่ (นับเฉพาะคู่ที่ confirm เก็บไม้ ≥%.0f%%).\n\n" % (MIN_KEEP * 100))
        f.write("## สรุปต่อ algo\n\n")
        f.write("| algo | mode | signal TF | **แท่งปิดที่ confirm ดีสุด** | Δexp_R | M15 | H1 | H4 | D1 |\n")
        f.write("|------|------|-----------|------------------------------|--------|-----|----|----|----|\n")
        for s in summary:
            g = lambda tf: (f"{s['avg_dR'][tf]:+.3f}" if s['avg_dR'].get(tf) is not None else "·")
            bt = f"**{s['best_tf']}**" if s["best_tf"] else "—"
            bd = f"{s['best_dR']:+.3f}" if s["best_dR"] is not None else "—"
            f.write(f"| {s['algo']} | {s['mode']} | {s['sig_tf']} | {bt} | {bd} | {g('M15')} | {g('H1')} | {g('H4')} | {g('D1')} |\n")
        f.write("\n> Δexp_R > 0 = แท่งปิด TF นั้นช่วยกรอง noise ของ algo · `·` = ตัดไม้เยอะเกิน (n<%.0f%%) ไม่นับ\n\n" % (MIN_KEEP * 100))

        # per algo × pair detail (flagship pairs)
        f.write("## รายละเอียดต่อคู่ (Δexp_R ต่อ confirm-TF)\n\n")
        f.write("| algo | คู่ | base exp_R | M15 | H1 | H4 | D1 |\n|---|---|---|---|---|---|---|\n")
        for r in sorted(rows, key=lambda x: (x["algo"], x["pair"])):
            base = r.get("base")
            be = f"{base['exp_R']:+.3f}" if base else "—"
            g = lambda tf: (f"{r['tf'][tf]['dR']:+.3f}" if tf in r["tf"] else "·")
            f.write(f"| {r['algo']} | {r['pair']} | {be} | {g('M15')} | {g('H1')} | {g('H4')} | {g('D1')} |\n")

    print("\n=== สรุปต่อ algo (confirm-TF ดีสุด) ===")
    for s in summary:
        print(f"  {s['algo']:20s} [{s['mode']:4s}] sig={s['sig_tf']:3s} → best {s['best_tf'] or '—'} "
              f"(Δ{s['best_dR']:+.3f})" if s["best_dR"] is not None else
              f"  {s['algo']:20s} [{s['mode']:4s}] sig={s['sig_tf']:3s} → best — (ไม่มี TF ที่ผ่าน n_keep)")
    print(f"\nreport → {REPORT_OUT}\njson → {JSON_OUT}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
