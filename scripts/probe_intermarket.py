#!/usr/bin/env python
"""
probe_intermarket.py — READ-ONLY diagnostic (ไม่แตะการเทรด / ไม่ส่งออเดอร์ / ไม่แก้ config)

จุดประสงค์: พิสูจน์เร็ว ๆ ว่าไอเดีย "intermarket lead-lag" เวิร์คกับ broker เรามั้ย
  1) broker ลิสต์ symbol ตัวขับทองมั้ย: DXY (ดอลลาร์), silver, bond yield (US10Y), oil (WTI/Brent)
  2) ทอง correlate กับตัวพวกนั้นแรงแค่ไหน (บน returns ไม่ใช่ price level = กัน spurious)
  3) ตัวไหน "นำ" ทอง (lead) กี่แท่ง — ผ่าน cross-correlation หลาย lag
  4) correlation drift ตาม regime มั้ย — วัดหลาย window (50/100/200/full) ให้เห็นกับตา

⚠️ real yield (TIPS): broker retail เกือบไม่มี symbol นี้ — script จะลองหา แต่ปกติต้องดึงจาก
   AlphaVantage/FRED (real yield = nominal 10Y − breakeven inflation) แยกต่างหาก. flag ไว้ให้.

วิธีรัน (MT5 terminal ต้องเปิด + login บัญชีอยู่แล้ว — script แค่ attach เข้า session อ่านอย่างเดียว):
  $PY = "C:\\Users\\pornnatcha\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe"
  & $PY scripts\\probe_intermarket.py
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")   # กัน cp874 พังตอน print ไทย/สัญลักษณ์
except Exception:
    pass

import MetaTrader5 as mt5
import numpy as np

# ── กลุ่ม keyword: ชื่อ symbol ต่าง broker ไม่เหมือนกัน เลยค้นแบบ substring ──
GROUPS = {
    "GOLD":   ["XAU", "GOLD"],
    "DXY":    ["DXY", "USDX", "USIDX", "DOLLAR", "USDOLLAR", "USDIDX"],
    "SILVER": ["XAG", "SILVER"],
    "BTC":    ["BTC", "XBT", "BITCOIN"],   # BTC module + gold intermarket feature (F8)
    "US10Y":  ["US10", "UST10", "TNOTE", "US10YR", "US10Y", "USTBOND", "T10Y", "USTNOTE", "US10YB", "TN10"],
    "OIL":    ["WTI", "USOIL", "XTIUSD", "CRUDE", "USCRUDE", "OILUSD"],
    "BRENT":  ["BRENT", "UKOIL", "XBRUSD", "BRENTOIL"],
    "REALYLD":["TIP", "REAL", "DFII", "USRY", "R10Y"],   # ปกติหาไม่เจอ — flag gap
}
# timeframe ที่วัด (ชื่อโชว์, ค่า mt5, จำนวนแท่ง)
TFS = [("H1", mt5.TIMEFRAME_H1, 300), ("H4", mt5.TIMEFRAME_H4, 300), ("D1", mt5.TIMEFRAME_D1, 250)]
WINDOWS = [50, 100, 200]   # window สำหรับดู corr drift (บวก full)
MAX_LAG = 4                # cross-corr lags: −4..+4 แท่ง


def find_symbols():
    """คืน {group: [symbol names]} จาก symbols_get() ทั้งหมดของ broker."""
    allsyms = mt5.symbols_get() or []
    names = [s.name for s in allsyms]
    hits = {}
    for grp, kws in GROUPS.items():
        found = [n for n in names if any(k in n.upper() for k in kws)]
        # กัน XAG หลุดเข้า GOLD group ฯลฯ — ตัด GOLD ที่จริง ๆ เป็น silver ออก
        hits[grp] = sorted(set(found))
    return hits, len(names)


def get_series(sym, tf, n):
    """ดึง close series (read-only). symbol_select เพิ่มเข้า Market Watch (harmless, ลบเองได้)."""
    mt5.symbol_select(sym, True)
    rates = mt5.copy_rates_from_pos(sym, tf, 0, n)
    if rates is None or len(rates) < 30:
        return None
    return rates


def aligned_returns(a, b):
    """align 2 series ด้วย timestamp → pct returns ที่ตรงเวลา."""
    ma = {int(r["time"]): float(r["close"]) for r in a}
    mb = {int(r["time"]): float(r["close"]) for r in b}
    ts = sorted(set(ma) & set(mb))
    if len(ts) < 30:
        return None, None, None
    ca = np.array([ma[t] for t in ts], dtype=float)
    cb = np.array([mb[t] for t in ts], dtype=float)
    ra = np.diff(ca) / ca[:-1]
    rb = np.diff(cb) / cb[:-1]
    return ts[1:], ra, rb


def corr(x, y):
    if len(x) < 10 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def lead_lag(rg, rx, max_lag=MAX_LAG):
    """cross-corr ที่หลาย lag. lag>0 = X นำทอง lag แท่ง (X[t-lag] ~ GOLD[t])."""
    best_lag, best_c = 0, 0.0
    table = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:      xx, gg = rx[:-lag], rg[lag:]
        elif lag < 0:    xx, gg = rx[-lag:], rg[:lag]
        else:            xx, gg = rx, rg
        c = corr(xx, gg)
        table[lag] = c
        if not np.isnan(c) and abs(c) > abs(best_c):
            best_lag, best_c = lag, c
    return best_lag, best_c, table


def main():
    if not mt5.initialize():
        print("❌ mt5.initialize() ล้มเหลว — เปิด MT5 terminal + login บัญชีก่อน แล้วรันใหม่")
        print("   last_error:", mt5.last_error())
        return
    acc = mt5.account_info()
    term = mt5.terminal_info()
    print("=" * 70)
    print("INTERMARKET PROBE (read-only)  |  terminal:",
          getattr(term, "name", "?"), "| account:", getattr(acc, "login", "n/a"))
    print("=" * 70)

    hits, total = find_symbols()
    print(f"\n[1] SYMBOL DISCOVERY  (broker มี {total} symbols ทั้งหมด)")
    gold = None
    for grp in ["GOLD", "DXY", "SILVER", "BTC", "US10Y", "OIL", "BRENT", "REALYLD"]:
        got = hits.get(grp, [])
        mark = "✅" if got else "❌"
        print(f"   {mark} {grp:8s}: {', '.join(got) if got else '— ไม่พบ —'}")
        if grp == "GOLD":
            # เลือกตัวที่ชื่อสั้น/ตรงสุดเป็น gold reference
            golds = [g for g in got if "XAU" in g.upper()] or got
            gold = golds[0] if golds else None
    if not gold:
        print("\n❌ หา gold symbol ไม่เจอ — จบ")
        mt5.shutdown()
        return
    print(f"\n   → ใช้ '{gold}' เป็น GOLD reference")
    if not hits.get("REALYLD"):
        print("   ⚠️  REAL YIELD ไม่มีใน broker (ปกติ) → ต้องดึงจาก AlphaVantage/FRED แยก")

    # ตัวขับที่จะเทียบ (เอาตัวแรกของแต่ละกลุ่มที่เจอ)
    drivers = []
    for grp in ["DXY", "SILVER", "BTC", "US10Y", "OIL", "BRENT"]:
        if hits.get(grp):
            drivers.append((grp, hits[grp][0]))
    if not drivers:
        print("\n❌ ไม่พบตัวขับเลย (DXY/silver/yield/oil) — intermarket ทำต่อไม่ได้กับ broker นี้")
        print("   ทางเลือก: ใช้ AlphaVantage MCP (TREASURY_YIELD / FX_INTRADAY / GOLD_SILVER_SPOT)")
        mt5.shutdown()
        return

    for tf_name, tf, n in TFS:
        g = get_series(gold, tf, n)
        if g is None:
            print(f"\n[{tf_name}] ดึงทองไม่ได้ — ข้าม")
            continue
        print(f"\n[2] CORRELATION & LEAD-LAG @ {tf_name}  (gold={gold}, ~{n} แท่ง, บน returns)")
        print(f"   {'driver':>16s} | {'n':>4s} | {'corr':>6s} | {'lead(แท่ง)':>10s} | corr@lead | drift(50/100/200/full)")
        print("   " + "-" * 92)
        for grp, sym in drivers:
            x = get_series(sym, tf, n)
            if x is None:
                print(f"   {sym:>16s} | ดึงข้อมูลไม่ได้")
                continue
            ts, rg, rx = aligned_returns(g, x)
            if ts is None:
                print(f"   {sym:>16s} | overlap น้อยเกินไป")
                continue
            c_full = corr(rg, rx)
            lag, c_lag, _ = lead_lag(rg, rx)
            lead_txt = (f"X นำ {lag}" if lag > 0 else f"ทองนำ {-lag}" if lag < 0 else "sync")
            drift = []
            for w in WINDOWS:
                if len(rg) >= w:
                    drift.append(f"{corr(rg[-w:], rx[-w:]):+.2f}")
                else:
                    drift.append("  - ")
            drift.append(f"{c_full:+.2f}")
            print(f"   {sym:>16s} | {len(ts):>4d} | {c_full:>+6.2f} | {lead_txt:>10s} | "
                  f"{c_lag:>+8.2f} | {' '.join(drift)}")

    print("\n[3] อ่านผลยังไง")
    print("   • |corr| ≥ 0.5 = ใช้ได้ ; 0.3–0.5 = อ่อน ; < 0.3 = อย่าใช้")
    print("   • เครื่องหมาย: DXY/yield ควรเป็นลบ (ผกผัน) ; silver ควรเป็นบวก")
    print("   • lead 'X นำ N' = ตัวนั้นขยับก่อนทอง N แท่ง → มี edge ล่วงหน้า ; 'sync/ทองนำ' = ไม่มี edge")
    print("   • drift: ถ้า 50 vs full ต่างกันมาก/สลับเครื่องหมาย = correlation ไม่คงที่ตาม regime")
    print("     → ยืนยันประเด็นที่ว่า 'ต้องดูตาม theme ข่าว/รอบดอกเบี้ย' ไม่ใช่ค่าตายตัว")
    print("\n(probe จบ — ไม่มีการเทรด/แก้ไขใด ๆ)")
    mt5.shutdown()


if __name__ == "__main__":
    main()
