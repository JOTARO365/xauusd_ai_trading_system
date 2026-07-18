#!/usr/bin/env python
"""
export_xau_history.py — dump XAUUSD OHLC หลาย TF จาก MT5 → data/xau_<tf>.json (READ-ONLY)

สำหรับ gold entry simulator (offline replay ระบบทองจริง): sim ต้องการ OHLC ของ broker จริง
หลาย TF ที่บอทใช้ (M15 timing + H4/H1/D1/W1). PAXG proxy เพี้ยน (S/R/spread ไม่ตรง) → ต้อง MT5 จริง.

⚠️ READ-ONLY: แค่ copy_rates อ่านอย่างเดียว ไม่ส่งออเดอร์ ไม่แก้ position ไม่แตะ config/บอท.
   MT5 terminal ต้องเปิด + login อยู่แล้ว (เหมือน probe_intermarket.py) — script แค่ attach อ่าน.

รัน (ใน session นี้พิมพ์ ! นำหน้าได้):
  $PY = "C:\\Users\\pornnatcha\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe"
  & $PY scripts\\export_xau_history.py            (ใช้ config.SYMBOL อัตโนมัติ)
  & $PY scripts\\export_xau_history.py XAUUSDm    (ระบุ symbol เองถ้าชื่อไม่ตรง)
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import MetaTrader5 as mt5

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# TF ที่บอทใช้ (chart_watcher.py:1528-1532) + จำนวนแท่งย้อนหลัง (มากพอสำหรับ backtest)
TFS = [
    ("m15", mt5.TIMEFRAME_M15, 250000),  # entry timing — เอาเยอะสุด (~7 ปีถ้า broker มี) → CI แคบ
    ("h1",  mt5.TIMEFRAME_H1,  70000),
    ("h4",  mt5.TIMEFRAME_H4,  20000),
    ("d1",  mt5.TIMEFRAME_D1,   6000),
    ("w1",  mt5.TIMEFRAME_W1,   2000),
]


def fetch_paginated(sym, tf, target, chunk=40000):
    """ดึงย้อนหลังทีละ chunk ผ่าน copy_rates_from_pos(start_pos) — กัน limit 'Invalid params'
    ตอน count ใหญ่. pos=0 คือแท่งล่าสุด, เพิ่ม pos ถอยหลังไปเรื่อยๆ. dedupe ด้วย time."""
    acc = {}
    pos = 0
    while pos < target:
        n = min(chunk, target - pos)
        rates = mt5.copy_rates_from_pos(sym, tf, pos, n)
        if rates is None or len(rates) == 0:
            break
        for r in rates:
            acc[int(r["time"])] = r
        if len(rates) < n:      # ถึงต้นประวัติแล้ว
            break
        pos += len(rates)
    return [acc[t] for t in sorted(acc)]


def _resolve_symbol(argv):
    if len(argv) > 1:
        return argv[1]
    try:
        import config
        s = getattr(config, "SYMBOL", None)
        if s:
            return s
    except Exception:
        pass
    return "XAUUSD"


def main():
    if not mt5.initialize():
        print("[FAIL] mt5.initialize() — เปิด MT5 terminal + login ก่อน แล้วรันใหม่")
        print("       last_error:", mt5.last_error())
        return
    sym = _resolve_symbol(sys.argv)
    info = mt5.symbol_info(sym)
    if info is None:
        # ลองค้น symbol ที่มี XAU/GOLD
        cands = [s.name for s in (mt5.symbols_get() or []) if "XAU" in s.name.upper() or "GOLD" in s.name.upper()]
        print(f"[FAIL] ไม่พบ symbol '{sym}'. broker มี gold เหล่านี้: {cands or '— ไม่พบ —'}")
        print("       รันใหม่: & $PY scripts\\export_xau_history.py <ชื่อที่ถูก>")
        mt5.shutdown()
        return
    mt5.symbol_select(sym, True)
    point = info.point
    print(f"[OK] MT5 attached | symbol={sym} | point={point} | digits={info.digits}")
    os.makedirs(os.path.join(_BASE, "data"), exist_ok=True)

    meta = {"symbol": sym, "point": point, "digits": info.digits, "tfs": {}}
    for name, tf, count in TFS:
        rates = fetch_paginated(sym, tf, count)   # paginate กัน limit
        if not rates:
            print(f"  [WARN] {name}: ดึงไม่ได้ ({mt5.last_error()})")
            continue
        # เก็บเฉพาะ field ที่ sim ใช้ — [time, open, high, low, close, tick_volume]
        rows = [[int(r["time"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]), int(r["tick_volume"])] for r in rates]
        out = os.path.join(_BASE, "data", f"xau_{name}.json")
        json.dump(rows, open(out, "w"))
        meta["tfs"][name] = {"bars": len(rows), "file": f"data/xau_{name}.json"}
        span_days = (rows[-1][0] - rows[0][0]) / 86400
        print(f"  [OK] {name:3}: {len(rows):>6} แท่ง (~{span_days/365:.1f} ปี) -> {out}")

    json.dump(meta, open(os.path.join(_BASE, "data", "xau_meta.json"), "w"), indent=2, ensure_ascii=False)
    print(f"[OK] meta -> data/xau_meta.json  (symbol/point/digits + bar counts)")
    print("เสร็จ — ส่งให้ Claude รู้ว่า export เสร็จ แล้วมันจะ build simulator ต่อ")
    mt5.shutdown()


if __name__ == "__main__":
    main()
