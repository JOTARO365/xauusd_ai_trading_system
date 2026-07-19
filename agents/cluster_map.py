"""agents/cluster_map.py — Price-Cluster decision-support (display-only, 0 order, 0 token).

หลักฐาน 07-19: กฎ fade S/R+cluster อัตโนมัติ **ไม่มี mechanical edge** (ทดสอบ ~12 แบบ ตก OOS). แต่ **วิจารณญาณ
ของ owner มี edge** (fade แนวรับ +2128฿ จริง). → บอทไม่ตัดสินใจแทน แต่ **คำนวณ cluster ให้ owner ตัดสินใจ**.

compute_cluster_map(): histogram หา dwell zone (touch เยอะ = S/R นัยสำคัญ) → แนวรับ/ต้านใกล้สุด + momentum
+ "ราคาใกล้ cluster" flag. owner อ่านแล้วเทรดเอง (SELECTION = คน, บอท = คำนวณ+execution+risk).
"""
import os
import sys

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R

LOOKBACK = 200
MIN_TOUCH = 6


def compute_cluster_map(high, low, close, lookback=LOOKBACK, min_touch=MIN_TOUCH):
    """คืน dict: ราคา, ATR, momentum, แนวรับ/ต้าน cluster ใกล้สุด (level+touches+ระยะ), near flag, clusters list."""
    n = len(close)
    if n < lookback + 20:
        return {"ok": False, "error": "bars ไม่พอ"}
    atr_v = R.atr(high, low, close)
    atr = float(atr_v[-1])
    if not np.isfinite(atr) or atr <= 0:
        return {"ok": False, "error": "ATR ไม่พร้อม"}
    window = close[-lookback:]
    bw = 0.25 * atr
    lo = float(window.min())
    counts = {}
    for px in window:
        b = int((px - lo) / bw)
        counts[b] = counts.get(b, 0) + 1
    clusters = [{"level": lo + (b + 0.5) * bw, "touches": c} for b, c in counts.items() if c >= min_touch]
    clusters.sort(key=lambda x: x["level"])
    px = float(close[-1])

    def enrich(c):
        if not c:
            return None
        return {"level": round(c["level"], 2), "touches": c["touches"],
                "dist_atr": round(abs(c["level"] - px) / atr, 2)}

    res = [c for c in clusters if c["level"] > px]
    sup = [c for c in clusters if c["level"] < px]
    nearest_res = min(res, key=lambda c: c["level"] - px) if res else None
    nearest_sup = max(sup, key=lambda c: c["level"]) if sup else None
    mom = ("up" if close[-1] > close[-2] > close[-3]
           else ("down" if close[-1] < close[-2] < close[-3] else "flat"))
    near = bool((nearest_res and (nearest_res["level"] - px) <= 0.5 * atr) or
                (nearest_sup and (px - nearest_sup["level"]) <= 0.5 * atr))
    # hint (แค่ context ให้คน — ไม่ใช่คำสั่ง): แตะต้าน+momentum อ่อน = พิจารณา fade
    hint = None
    if near and nearest_res and (nearest_res["level"] - px) <= 0.5 * atr and mom != "up":
        hint = f"ราคาใกล้แนวต้าน cluster {nearest_res['touches']} touch — momentum {mom} (พิจารณา SELL ตามวิจารณญาณ)"
    elif near and nearest_sup and (px - nearest_sup["level"]) <= 0.5 * atr and mom != "down":
        hint = f"ราคาใกล้แนวรับ cluster {nearest_sup['touches']} touch — momentum {mom} (พิจารณา BUY ตามวิจารณญาณ)"
    lv = R.momentum_levels(n - 2, high, low, close, atr_v)   # Donchian levels ที่ algo ใช้ (สำหรับ overlay กราฟ)
    donchian = {"buy": round(lv["buy_level"], 2), "sell": round(lv["sell_level"], 2)} if lv else None
    return {"ok": True, "price": round(px, 2), "atr": round(atr, 2), "momentum": mom,
            "resistance": enrich(nearest_res), "support": enrich(nearest_sup),
            "near": near, "hint": hint, "donchian": donchian,
            "clusters": [enrich(c) for c in clusters][:14]}


def from_mt5(count=600):
    """ดึง H1 bars จาก MT5 → compute. คืน {ok:False} ถ้าไม่พร้อม."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        rates = get_ohlcv(timeframe=mt5.TIMEFRAME_H1, count=count)
        if rates is None or len(rates) < LOOKBACK + 20:
            return {"ok": False, "error": "ดึง bars ไม่ได้"}
        return compute_cluster_map(rates["high"].astype(float), rates["low"].astype(float),
                                   rates["close"].astype(float))
    except Exception as e:
        return {"ok": False, "error": str(e)}
