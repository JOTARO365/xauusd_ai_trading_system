"""agents/sr_pair.py — S/R ladder ต่อคู่ใดก็ได้ (เหมือน gold zone-ladder) โดย reuse chart_watcher helpers.

คำนวณ sr_meta เต็ม (bounce_pct/break_pct/n_tests · break_hold ยืน/ไส้เทียน · touches · recency · strength ·
score/grade) จาก OHLC ของ symbol นั้น — ตัวเดียวกับที่ gold ใช้ → ladder หน้าตาเหมือนกันทุกคู่.
DISPLAY-ONLY, 0 token, read-only. symbol=None → ทอง (SYMBOL).
"""
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)


def sr_ladder(symbol=None, count=600):
    """คืน {ok, symbol, price, point, zones:{resistance,support,sr_meta,setups,htf_zone}} — โครง zones เหมือน bot_status ของทอง."""
    try:
        import MetaTrader5 as mt5
        import pandas as pd
        from connectors.price_feed import get_ohlcv
        from agents import chart_watcher as cw
        import config as _cfg

        broker = _cfg.SYMBOL
        if symbol:
            from connectors.pair_collector import _broker_map
            broker = _broker_map().get(symbol, symbol)

        def _df(tf, n):
            r = get_ohlcv(symbol=broker, timeframe=tf, count=n)
            if r is None or len(r) < 60:
                return None
            return pd.DataFrame({"open": r["open"].astype(float), "high": r["high"].astype(float),
                                 "low": r["low"].astype(float), "close": r["close"].astype(float)})

        h1 = _df(mt5.TIMEFRAME_H1, count)
        if h1 is None:
            return {"ok": False, "error": f"ดึง bars ไม่ได้ ({broker})"}
        h4 = _df(mt5.TIMEFRAME_H4, 400)
        h1_sr = cw.find_swing_levels(h1)
        h4_sr = cw.find_swing_levels(h4) if h4 is not None else {"resistance": [], "support": []}
        key = cw.find_key_levels(h1)
        meta = cw._build_sr_meta(h4_sr, h1_sr, key, None, None, h4, h1)
        for m in meta:
            sc, gr = cw._score_zone(m)                # + unified score/grade (เหมือน gold)
            m["score"] = sc; m["grade"] = gr

        px = round(float(h1["close"].iloc[-1]), 5)
        point = 0.01
        try:
            info = mt5.symbol_info(broker)
            if info and info.point:
                point = float(info.point)
        except Exception:
            pass
        res = sorted({m["level"] for m in meta if m["side"] == "R"}, reverse=True)
        sup = sorted({m["level"] for m in meta if m["side"] == "S"}, reverse=True)
        return {"ok": True, "symbol": symbol or "XAUUSD", "price": px, "point": point,
                "zones": {"resistance": res, "support": sup, "sr_meta": meta,
                          "setups": [], "htf_zone": None}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa
    import json
    print(json.dumps(sr_ladder(), ensure_ascii=False)[:400])
