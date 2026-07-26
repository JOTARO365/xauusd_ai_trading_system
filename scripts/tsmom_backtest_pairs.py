"""scripts/tsmom_backtest_pairs.py — รัน TSMOM-D1 (frozen live signal) ต่อคู่ แล้ว merge ผลลง
docs/reports/shadow_backtest.json เป็น algo_id="tsmom_d1" → โผล่คอลัมน์ backtest ใน Shadow Matrix
(เทียบ backtest-promise กับ real edge ต่อคู่ เหมือน regime_momentum).

reuse ตรง: scripts/tsmom_pairs_screen.backtest() = signal + lifecycle เดียวกับ agents/tsmom_manager
(ensemble vote L=63/126/252, exit-on-flip, 3×ATR disaster SL, net spread ×2, IS/OOS 60/40).
เขียน row {algo_id, symbol(logical), exp_R, n, wr, managed=False, note}. ลบ tsmom_d1 rows เก่าก่อน (idempotent).
read-only ต่อ MT5, 0 order.  python scripts/tsmom_backtest_pairs.py
"""
import json
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
sys.path.insert(0, _BASE)

_OUT = os.path.join(_BASE, "docs", "reports", "shadow_backtest.json")
# คู่ที่ backtest = tsmom screen เดิม + คู่ที่เทรด live (WTI/BTC/GBP) ให้ครบ universe
PAIRS = ["XAUUSD", "XAGUSD", "EURUSD", "AUDUSD", "USDCHF", "USDJPY", "GBPUSD", "WTIUSD", "BTCUSD"]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import MetaTrader5 as mt5
    from connectors.price_feed import connect_mt5, is_mt5_connected
    from connectors.pair_collector import _broker_map
    from tsmom_pairs_screen import backtest

    if not (is_mt5_connected() or connect_mt5()):
        print("MT5 init failed:", mt5.last_error()); sys.exit(1)

    bmap = _broker_map()
    new_rows = []
    print(f"{'pair':8s} {'broker':10s} {'n':>5s} {'exp_R':>7s} {'wr':>5s} {'t':>5s} {'oos':>7s} note")
    for lg in PAIRS:
        broker = bmap.get(lg, lg)
        if not mt5.symbol_info(broker):
            print(f"{lg:8s} {broker:10s} {'—':>5s}  no symbol"); continue
        d = backtest(lg, broker)
        if not d.get("n"):
            print(f"{lg:8s} {broker:10s} {'0':>5s}  {d.get('note','')}"); continue
        print(f"{lg:8s} {broker:10s} {d['n']:>5d} {d['exp_R']:>+7.3f} {d.get('wr','—'):>5} "
              f"{d['t']:>5.1f} {str(d.get('oos_exp')):>7s} {'BELIEVE' if d.get('believe') else ''}")
        new_rows.append({
            "algo_id": "tsmom_d1", "logical": lg, "ok": True, "exp_R": d["exp_R"], "n": d["n"],
            "wr": d.get("wr"), "sum_R": d.get("sum_R"), "t": d.get("t"),
            "oos_exp": d.get("oos_exp"), "is_exp": d.get("is_exp"),
            "managed": False, "believe": bool(d.get("believe")),
            "note": "TSMOM-D1 frozen (exit-on-flip, 3xATR disaster SL, net spread x2, IS/OOS 60/40)"})

    rows = []
    if os.path.exists(_OUT):
        try:
            rows = json.load(open(_OUT, encoding="utf-8"))
        except Exception:
            rows = []
    rows = [r for r in rows if r.get("algo_id") != "tsmom_d1"]      # ลบเก่า (idempotent)
    rows += new_rows
    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nmerged {len(new_rows)} tsmom_d1 rows → {_OUT}")


if __name__ == "__main__":
    main()
