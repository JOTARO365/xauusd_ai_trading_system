"""dxy_gate_backtest.py — DO-NOT-WIRE eval of a DXY-directional-GATE on the 4 live-registry algos.

Tests the user's mental-model step "factor inverse assets (DXY vs gold)": block a gold BUY when DXY
momentum is strongly UP (USD strong = gold headwind); block a gold SELL when DXY strongly DOWN. WTI
(USD-priced) uses the same gate. Block-only, compute-in-code, 0 token.

THE LOAD-BEARING TEST (drift-null discipline): a gate that only cuts trade count can look better by
luck. The DXY-gated result must beat a RANDOM-BLOCK-SAME-RATE null run in the SAME engine — else the
DXY relationship carries zero tradeable directional information (how pullback_buy died at p0.570, #5).

Reuses scripts/backtest_all.py bt_* engines (they already expose a `gate(h,l,i,px,d,av)->bool` hook)
+ _stats. READ-ONLY (MT5 copy_rates only). Prints a table; wires nothing.

Run: PYTHONIOENCODING=utf-8 <py311> scripts/dxy_gate_backtest.py
"""
import os
import sys
import json
import math

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regime_lib as R  # noqa: E402
from backtest_all import bt_momentum, bt_cdc, bt_tsmom, bt_macro, _stats  # noqa: E402

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS = 300          # random-block null runs per config
LOOKBACKS = (10, 20, 50)


def _load_dxy_d1():
    """DXC D1 close+time (closed bars). Prefer cached json, else MT5."""
    p = os.path.join(_BASE, "data", "drv_dxy_d1.json")
    if os.path.exists(p):
        d = json.load(open(p))
        t = np.array([x["t"] for x in d], np.int64)
        c = np.array([x["c"] for x in d], float)
        return t, c
    return None, None


def _dxy_mom_aligned(bar_times, dxy_t, dxy_c, L):
    """สำหรับแต่ละ bar (time t) → sign ของ DXY momentum over L, จาก DXC D1 แท่งปิดล่าสุด (time+86400<=t).
    คืน np.array len=len(bar_times) ค่า {-1,0,+1} (0 = ข้อมูลไม่พอ = ไม่ block)."""
    out = np.zeros(len(bar_times), np.int8)
    # closed-bar index per bar_time: largest k with dxy_t[k]+86400 <= t (causal, ปิดแล้ว)
    closed_end = dxy_t + 86400
    for bi, t in enumerate(bar_times):
        k = int(np.searchsorted(closed_end, t, side="right")) - 1
        if k - L < 0 or k < 0:
            continue
        out[bi] = int(np.sign(dxy_c[k] - dxy_c[k - L]))
    return out


def _make_dxy_gate(mom_aligned, strong=None, dxy_c_at=None):
    """gate(h,l,i,px,d,av)->True=block. block เมื่อ DXY วิ่งสวนทิศ entry:
    gold BUY (d>0) + DXY up (mom>0) = สวน macro → block. gold SELL (d<0) + DXY down (mom<0) → block.
    (WTI ใช้ตรรกะเดียว: DXY up = commodity headwind → block BUY.)
    strong=None → sign gate; strong=z → block เฉพาะเมื่อ |Δ| เกิน threshold (ใช้ mom sign เท่านั้นถ้า None)."""
    ctr = {"eval": 0, "block": 0}

    def gate(h, l, i, px, d, av):
        ctr["eval"] += 1
        if i >= len(mom_aligned):
            return False
        m = mom_aligned[i]
        blk = (d > 0 and m > 0) or (d < 0 and m < 0)
        if blk:
            ctr["block"] += 1
        return bool(blk)
    gate._ctr = ctr
    return gate


def _make_random_gate(p_block, rng):
    ctr = {"eval": 0, "block": 0}

    def gate(h, l, i, px, d, av):
        ctr["eval"] += 1
        if rng.random() < p_block:
            ctr["block"] += 1
            return True
        return False
    gate._ctr = ctr
    return gate


def _run_algo(name, runner):
    """runner(gate)->trade list. คืน dict ผล baseline/gated(best L)/null."""
    base = runner(None)
    bs = _stats(base)
    print(f"\n=== {name} ===")
    if not bs:
        print(f"  baseline n<20 ({len(base)}) — ข้าม", flush=True)
        return
    print(f"  baseline: n={bs['n']} exp_R={bs['exp_R']} t={bs['t']} oos={bs['oos']} wr={bs['wr']}")
    best = None
    for L, mom in runner.moms.items():
        g = _make_dxy_gate(mom)
        tr = runner(g)
        s = _stats(tr)
        if not s:
            print(f"  DXY-gate L={L}: n<20 ({len(tr)}) — untradeable"); continue
        ev, bl = g._ctr["eval"], g._ctr["block"]
        p_block = bl / ev if ev else 0.0
        # random-block-same-rate null (same engine)
        rng = np.random.default_rng(12345 + L)
        null = []
        for s_i in range(SEEDS):
            rg = _make_random_gate(p_block, rng)
            ns = _stats(runner(rg))
            if ns:
                null.append(ns["exp_R"])
        null = np.array(null, float)
        p_val = float((null >= s["exp_R"]).mean()) if len(null) else float("nan")
        d_exp = round(s["exp_R"] - bs["exp_R"], 4)
        d_t = round(s["t"] - bs["t"], 2)
        print(f"  DXY-gate L={L:<3} block={p_block*100:4.1f}% | n={s['n']:<4} exp_R={s['exp_R']:+.4f} "
              f"(Δ{d_exp:+.4f}) t={s['t']:+.2f} (Δ{d_t:+.2f}) oos={s['oos']:+.4f} | "
              f"null-mean={null.mean():+.4f} p(DXY>=rand)={p_val:.3f} "
              f"{'<-- beats random' if p_val < 0.05 else '(= random-block, no info)' if p_val>0.2 else ''}")
        cand = (s["exp_R"], L, s, p_val, p_block)
        if best is None or cand[0] > best[0]:
            best = cand
    return best


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init FAIL", mt5.last_error()); return
    try:
        from connectors.pair_collector import _broker_map
        bm = _broker_map() or {}
    except Exception:
        bm = {}
    try:
        from agents import shadow_cost as _sc
    except Exception:
        _sc = None

    def cost_of(lg):
        return (_sc.cost_pips(lg) if _sc else None) or 30.0

    dxy_t, dxy_c = _load_dxy_d1()
    if dxy_t is None:
        print("no DXC data"); return
    import datetime as dt
    print(f"DXC D1: {len(dxy_t)} bars {dt.datetime.utcfromtimestamp(int(dxy_t[0])).date()} -> "
          f"{dt.datetime.utcfromtimestamp(int(dxy_t[-1])).date()}")

    # ---- XAUUSD ----
    xau = bm.get("XAUUSD", "XAUUSD"); mt5.symbol_select(xau, True)
    info = mt5.symbol_info(xau); pt = float(info.point); cost = cost_of("XAUUSD")
    rh = mt5.copy_rates_from_pos(xau, mt5.TIMEFRAME_H1, 0, 50000)
    rd = mt5.copy_rates_from_pos(xau, mt5.TIMEFRAME_D1, 0, 4000)
    rh4 = mt5.copy_rates_from_pos(xau, mt5.TIMEFRAME_H4, 0, 30000)
    h, l, c, tm = (rh["high"].astype(float), rh["low"].astype(float), rh["close"].astype(float),
                   rh["time"].astype(np.int64))
    dh, dl, dc, dtm = (rd["high"].astype(float), rd["low"].astype(float), rd["close"].astype(float),
                       rd["time"].astype(np.int64))
    h4, l4, c4, t4 = (rh4["high"].astype(float), rh4["low"].astype(float), rh4["close"].astype(float),
                      rh4["time"].astype(np.int64))
    print(f"XAU H1={len(c)} D1={len(dc)} H4={len(c4)} | cost={cost}p pt={pt}")

    # regime_momentum (H1)
    moms_h1 = {L: _dxy_mom_aligned(tm, dxy_t, dxy_c, L) for L in LOOKBACKS}

    def run_regime(gate):
        return bt_momentum(h, l, c, cost, pt, brk=20, sl_atr=1.5, rr=2.0, trend=True, mh=120, tm=tm, sym="XAUUSD", gate=gate)
    run_regime.moms = moms_h1
    _run_algo("regime_momentum:XAUUSD (H1 momentum breakout, BUY+SELL universe)", run_regime)

    # cdc_zone (D1, long-only)
    moms_d1 = {L: _dxy_mom_aligned(dtm, dxy_t, dxy_c, L) for L in LOOKBACKS}

    def run_cdc(gate):
        return bt_cdc(dh, dl, dc, cost * pt, sl_atr=2.0, mode="long", gate=gate)
    run_cdc.moms = moms_d1
    _run_algo("cdc_zone:XAUUSD (D1 CDC trend-follow, long-only)", run_cdc)

    # macro_momentum (H4) — keep its EURUSD confirm, ADD DXY gate on top
    e = bm.get("EURUSD", "EURUSD"); mt5.symbol_select(e, True)
    re = mt5.copy_rates_from_pos(e, mt5.TIMEFRAME_H4, 0, len(t4) + 500)
    emap = {int(x["time"]): float(x["close"]) for x in re} if re is not None else {}
    mac = np.array([emap.get(int(t), np.nan) for t in t4], float)
    moms_h4 = {L: _dxy_mom_aligned(t4, dxy_t, dxy_c, L) for L in LOOKBACKS}

    def run_macro(gate):
        return bt_macro(h4, l4, c4, mac, cost, pt, brk=20, mlb=24, rr=2.0, sl_atr=1.5, mh=120, msign=1, tm=t4, sym="XAUUSD", gate=gate)
    run_macro.moms = moms_h4
    _run_algo("macro_momentum:XAUUSD (H4 breakout + EURUSD confirm; DXY gate added)", run_macro)

    # tsmom_d1 (WTI D1)
    wti = bm.get("WTIUSD", "WTIUSD"); mt5.symbol_select(wti, True)
    rw = mt5.copy_rates_from_pos(wti, mt5.TIMEFRAME_D1, 0, 6000)
    if rw is not None and len(rw) > 200:
        wpt = float(mt5.symbol_info(wti).point); wcost = cost_of("WTIUSD")
        wh, wl, wc, wtm = (rw["high"].astype(float), rw["low"].astype(float), rw["close"].astype(float),
                           rw["time"].astype(np.int64))
        print(f"\nWTI D1={len(wc)} cost={wcost}p pt={wpt}")
        moms_w = {L: _dxy_mom_aligned(wtm, dxy_t, dxy_c, L) for L in LOOKBACKS}

        def run_tsmom(gate):
            return bt_tsmom(wh, wl, wc, wcost * wpt, lbs=(21, 63, 126), confirm=21, sl_atr=3.0, gate=gate)
        run_tsmom.moms = moms_w
        _run_algo("tsmom_d1:WTIUSD (D1 TSMOM; DXY-vs-oil gate)", run_tsmom)
    else:
        print("\nWTI data insufficient — skip tsmom")

    mt5.shutdown()
    print("\n[done] DO-NOT-WIRE eval. HELPS = beats no-gate AND p(DXY>=rand)<0.05. NEUTRAL = p>0.2 (no info).")


if __name__ == "__main__":
    main()
