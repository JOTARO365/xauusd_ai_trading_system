#!/usr/bin/env python
"""
export_drivers.py — dump USD-proxy / driver symbols จาก MT5 → data/drv_<sym>_<tf>.json (READ-ONLY)

สำหรับ probe_gold_lead.py: ทดสอบว่ามี driver ไหน "นำ" ทองจริงระดับ M15/H1 (ช่องที่ deep research
ยังไม่เทส). **สำคัญ: ต้องมาจาก MT5 feed เดียวกับทอง (GOLD#)** → timestamp/timezone ตรงกัน align ได้จริง
(ถ้าดึง EURUSD จากแหล่งอื่น timezone จะเหลื่อม → lead-lag เพี้ยน).

discover อัตโนมัติ (ชื่อ symbol ต่าง broker): EURUSD/USDJPY (USD proxy หลัก, ผกผัน/ตามทอง) +
DXY-proxy (ถ้ามี) + XAG (silver, Tier 2). dump M15 + H1 (โฟกัส band ที่จะ probe).

⚠️ READ-ONLY: copy_rates อ่านอย่างเดียว ไม่ส่งออเดอร์/แก้ position/config. MT5 terminal ต้องเปิด+login.
รัน: python scripts\\export_drivers.py
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
TF_SEC = {"m15": 900, "h1": 3600}
TFS = [("m15", mt5.TIMEFRAME_M15, 60000), ("h1", mt5.TIMEFRAME_H1, 25000)]

# กลุ่ม driver → keyword (ชื่อต่าง broker); EURUSD/USDJPY มีแทบทุก broker = USD proxy หลัก
GROUPS = {
    "EURUSD": ["EURUSD"],
    "USDJPY": ["USDJPY"],
    "DXY":    ["DXY", "USDX", "USDIDX", "USDOLLAR", "DX"],
    "XAG":    ["XAG"],
}


def fetch_paginated(sym, tf, target, chunk=40000):
    acc = {}
    pos = 0
    while pos < target:
        n = min(chunk, target - pos)
        rates = mt5.copy_rates_from_pos(sym, tf, pos, n)
        if rates is None or len(rates) == 0:
            break
        for r in rates:
            acc[int(r["time"])] = r
        if len(rates) < n:
            break
        pos += len(rates)
    return [acc[t] for t in sorted(acc)]


def main():
    if not mt5.initialize():
        print("[FAIL] mt5.initialize() — เปิด MT5 terminal + login ก่อน"); print("  ", mt5.last_error()); return
    allsyms = [s.name for s in (mt5.symbols_get() or [])]
    print(f"[OK] MT5 attached | broker มี {len(allsyms)} symbols")

    # discover 1 symbol ต่อกลุ่ม (ชื่อสั้น/ตรงสุด)
    picked = {}
    for grp, kws in GROUPS.items():
        cands = sorted([n for n in allsyms if any(k in n.upper() for k in kws)], key=len)
        if cands:
            picked[grp] = cands[0]
    print("[discover]", ", ".join(f"{g}={s}" for g, s in picked.items()) or "— ไม่พบ —")
    if not picked:
        print("[FAIL] ไม่พบ driver symbol เลย"); mt5.shutdown(); return

    os.makedirs(os.path.join(_BASE, "data"), exist_ok=True)
    meta = {"drivers": {}}
    for grp, sym in picked.items():
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
        for name, tf, cnt in TFS:
            rates = fetch_paginated(sym, tf, cnt)
            if not rates:
                print(f"  [WARN] {grp}/{name}: ดึงไม่ได้"); continue
            rows = [[int(r["time"]), float(r["open"]), float(r["high"]),
                     float(r["low"]), float(r["close"]), int(r["tick_volume"])] for r in rates]
            out = os.path.join(_BASE, "data", f"drv_{grp.lower()}_{name}.json")
            json.dump(rows, open(out, "w"))
            span = (rows[-1][0] - rows[0][0]) / 86400 / 365
            print(f"  [OK] {grp:7}/{name}: {len(rows):>6} แท่ง (~{span:.1f} ปี) point={getattr(info,'point','?')}")
        meta["drivers"][grp] = {"symbol": sym, "point": getattr(info, "point", None)}
    json.dump(meta, open(os.path.join(_BASE, "data", "drv_meta.json"), "w"), indent=2, ensure_ascii=False)
    print("[OK] meta -> data/drv_meta.json")
    print("เสร็จ — บอก Claude ว่า export เสร็จ แล้วมันจะรัน probe_gold_lead.py")
    mt5.shutdown()


if __name__ == "__main__":
    main()
