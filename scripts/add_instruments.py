"""scripts/add_instruments.py — Phase 0: add BTC + WTI to data/universe_probe.json (broker map + baseline).

Probes the broker for each logical→broker symbol and writes an entry matching the existing schema so
pair_collector picks them up. Data-pipeline only — does NOT touch the algo registry or shadow universe
(per-instrument algos are Phase 2). Idempotent. Run: python scripts/add_instruments.py
"""
import json
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
import config  # noqa: E402,F401

_PROBE = os.path.join(_BASE, "data", "universe_probe.json")
# logical → broker symbol (BTC live; OILCash# = broker oil cash CFD, likely WTI — no separate BRENT offered)
ADD = {"BTCUSD": "BTCUSD#", "WTIUSD": "OILCash#"}


def _entry(mt5, logical, broker):
    mt5.symbol_select(broker, True)
    i = mt5.symbol_info(broker); t = mt5.symbol_info_tick(broker)
    if i is None:
        return None
    bid = float(t.bid) if t and t.bid else 0.0
    ask = float(t.ask) if t and t.ask else 0.0
    sp = round((ask - bid) / i.point) if (bid and ask and i.point) else int(getattr(i, "spread", 0))
    vpp = None
    try:
        ref = bid or float(getattr(i, "trade_tick_value", 0)) or 1.0
        pr = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, broker, 1.0, ref, ref + i.point)
        vpp = round(float(pr), 4) if pr is not None else None
    except Exception:
        pass
    return {"broker_symbol": broker, "digits": int(i.digits), "point": float(i.point),
            "spread_points": int(sp), "spread_current_pts": int(sp),
            "contract_size": float(getattr(i, "trade_contract_size", 0) or 0),
            "swap_long": float(getattr(i, "swap_long", 0) or 0),
            "swap_short": float(getattr(i, "swap_short", 0) or 0),
            "swap_mode": int(getattr(i, "swap_mode", 0) or 0),
            "currency_base": getattr(i, "currency_base", ""),
            "currency_profit": getattr(i, "currency_profit", ""),
            "value_per_point_per_lot": vpp,
            "trade_mode": int(getattr(i, "trade_mode", 0) or 0), "bid": bid,
            "vol_min": float(getattr(i, "volume_min", 0) or 0),
            "vol_step": float(getattr(i, "volume_step", 0) or 0)}


def main():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)
    p = json.load(open(_PROBE, encoding="utf-8"))
    inst = p.setdefault("instruments", {})
    for logical, broker in ADD.items():
        e = _entry(mt5, logical, broker)
        if e is None:
            print(f"  {logical} ({broker}): NOT FOUND — skipped"); continue
        inst[logical] = e
        print(f"  {logical} = {broker} · point={e['point']} spread={e['spread_points']}pt "
              f"contract={e['contract_size']} bid={e['bid'] or '(closed)'} vpp={e['value_per_point_per_lot']}")
    with open(_PROBE, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    print(f"\ninstruments now: {list(inst.keys())}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
