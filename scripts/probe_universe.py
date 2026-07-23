#!/usr/bin/env python
"""probe_universe.py — READ-ONLY broker probe สำหรับ Phase 1 (gold-complex universe consultation).

ไม่มี order_send/trade — attach MT5 อ่าน: availability, spread, swap, contract, pip-value (order_calc_profit
= broker truth, กัน 10x pip bug), + D1 history → correlation matrix. เขียน data/universe_probe.json.
รัน (ผู้ใช้ควบคุม terminal): & $PY scripts\probe_universe.py
⚠️ read-only: เรียกแค่ symbols_get / symbol_info / copy_rates / order_calc_profit — ไม่แตะออร์เดอร์บอท.
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
import MetaTrader5 as mt5
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER

# economic target → token ที่ต้องมีในชื่อ broker symbol (จับ suffix เช่น GOLD#, EURUSDm)
# USD-quoted commodity (XAUUSD/XAGUSD) มักชื่อ GOLD#/SILVER# = ไม่มี "USD" ในชื่อ → match แค่ metal token
# แล้วกรอง cross ทิ้ง (exclude quote-ccy อื่น). cross (XAUEUR ฯลฯ) ต้องมี metal + quote ในชื่อ.
_CROSS_CCY = ("EUR", "JPY", "AUD", "GBP", "CHF", "CAD", "NZD")
TARGETS = {
    "XAUUSD": [("XAU", "GOLD")], "XAGUSD": [("XAG", "SILVER")],
    "XAUEUR": [("XAU", "GOLD"), ("EUR",)], "XAUJPY": [("XAU", "GOLD"), ("JPY",)],
    "XAUAUD": [("XAU", "GOLD"), ("AUD",)], "XAUGBP": [("XAU", "GOLD"), ("GBP",)],
    "AUDUSD": [("AUD",), ("USD",)], "USDCHF": [("USD",), ("CHF",)],
    "USDJPY": [("USD",), ("JPY",)], "EURUSD": [("EUR",), ("USD",)],
}
_USD_METAL = {"XAUUSD", "XAGUSD"}                              # กรอง cross ออกจาก metal-USD


def _match(target_tokens, names):
    """หา broker symbol ที่ชื่อมี token ครบทุกกลุ่ม (แต่ละกลุ่ม = OR). เลือกชื่อสั้นสุด (ตรงสุด)."""
    cands = []
    for nm in names:
        up = nm.upper()
        if all(any(tok in up for tok in grp) for grp in target_tokens):
            cands.append(nm)
    # ยกเว้น cross ที่ token ปน (เช่น XAUUSD ไม่ควรจับ XAUEUR) → เลือกที่ base ตรง
    return sorted(cands, key=lambda x: (len(x), x))[:3]


def _pip_value(sym, price, point):
    """value ต่อ 1 point ต่อ 1 lot (account ccy) จาก order_calc_profit — broker truth."""
    try:
        p = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, 1.0, price, price + point)
        return round(p, 4) if p is not None else None
    except Exception:
        return None


def main():
    # attach terminal ที่รันอยู่ก่อน (ไม่ force re-login = ไม่กวน session บอท); fallback ค่อย login
    if not mt5.initialize():
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            print(f"MT5 initialize FAILED: {mt5.last_error()}")
            return
    acc = mt5.account_info()
    ccy = acc.currency if acc else "?"
    print(f"MT5 connected | login={getattr(acc,'login','?')} ccy={ccy} server={MT5_SERVER}")
    all_names = [s.name for s in (mt5.symbols_get() or [])]
    print(f"broker symbols total: {len(all_names)}")

    found = {}
    out = {"account_ccy": ccy, "instruments": {}, "unmatched": []}
    for tgt, toks in TARGETS.items():
        cands = _match(toks, all_names)
        # metal-USD (GOLD#/SILVER#): ต้อง startswith metal token (กัน "heXAGon") + กรอง cross ccy
        if tgt in _USD_METAL:
            cands = [c for c in cands if c.upper().startswith(("GOLD", "SILVER", "XAU", "XAG"))
                     and not any(x in c.upper() for x in _CROSS_CCY)]
            if tgt == "XAGUSD":
                sv = [n for n in all_names if n.upper().startswith(("SILVER", "XAG"))]
                print(f"    [silver candidates: {sv[:6]}]")
        if not cands:
            out["unmatched"].append(tgt)
            print(f"  {tgt:8} → ❌ ไม่พบใน broker")
            continue
        sym = cands[0]
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if not info or not tick:
            out["unmatched"].append(tgt)
            print(f"  {tgt:8} → {sym}: no info/tick")
            continue
        mid = (tick.bid + tick.ask) / 2 or info.bid or 1.0
        spread_pts = round((tick.ask - tick.bid) / info.point) if info.point else None
        pv = _pip_value(sym, mid, info.point)
        rec = {
            "broker_symbol": sym, "digits": info.digits, "point": info.point,
            "spread_points": spread_pts, "spread_current_pts": info.spread,
            "contract_size": info.trade_contract_size,
            "swap_long": info.swap_long, "swap_short": info.swap_short, "swap_mode": info.swap_mode,
            "currency_base": info.currency_base, "currency_profit": info.currency_profit,
            "value_per_point_per_lot": pv, "trade_mode": info.trade_mode, "bid": tick.bid,
            "vol_min": info.volume_min, "vol_step": info.volume_step,
        }
        out["instruments"][tgt] = rec
        found[tgt] = sym
        print(f"  {tgt:8} → {sym:12} spread={spread_pts}pt swapL/S={info.swap_long}/{info.swap_short} "
              f"contract={info.trade_contract_size} pv/pt/lot={pv}{ccy} profit_ccy={info.currency_profit}")

    # ── correlation: D1 log-returns (180 บาร์) ──
    import numpy as np
    closes = {}
    for tgt, sym in found.items():
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 200)
        if rates is not None and len(rates) > 40:
            closes[tgt] = {int(r["time"]): float(r["close"]) for r in rates}
    keys = list(closes.keys())
    # align ด้วย timestamp ร่วม
    common = set.intersection(*[set(closes[k].keys()) for k in keys]) if keys else set()
    common = sorted(common)
    print(f"\ncorrelation basis: {len(common)} common D1 bars across {len(keys)} instruments")
    corr = {}
    if len(common) > 40:
        mat = np.array([[closes[k][t] for t in common] for k in keys])
        rets = np.diff(np.log(mat), axis=1)
        for win, name in [(30, "30d"), (90, "90d")]:
            sub = rets[:, -win:] if rets.shape[1] >= win else rets
            cm = np.corrcoef(sub)
            corr[name] = {keys[i]: {keys[j]: round(float(cm[i, j]), 2) for j in range(len(keys))}
                          for i in range(len(keys))}
        # print 90d matrix
        print("\n90d return correlation:")
        print("         " + "".join(f"{k[:6]:>8}" for k in keys))
        for i, k in enumerate(keys):
            print(f"  {k:7}" + "".join(f"{corr['90d'][k][kj]:>8.2f}" for kj in keys))
    out["correlation"] = corr
    out["correlation_keys"] = keys
    with open(os.path.join(_BASE, "data", "universe_probe.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ เขียน data/universe_probe.json ({len(found)} instruments)")
    mt5.shutdown()


if __name__ == "__main__":
    main()
