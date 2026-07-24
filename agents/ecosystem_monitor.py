"""agents/ecosystem_monitor.py — Ecosystem Monitor: ราคาทั้งระบบนิเวศทอง + co-movement กับทอง real-time.

หน้าสรุป (refresh 30s บน dashboard) ตอบว่า "ตอนนี้" ทองวิ่งทางไหน แล้วแต่ละ asset วิ่ง WITH/AGAINST ทอง
+ correlation ปกติ (flag divergence) + สังเคราะห์ sentiment (safe-haven / risk-on beta / USD-driven / mixed).

READ-ONLY บน MT5 · 0 token (compute-in-code) · display/วิเคราะห์อย่างเดียว ไม่ป้อน entry/gate (CORE INVARIANT).
reuse helper จาก equities_intermarket (symbol discovery / H1 closes / rolling corr).
"""
from agents.equities_intermarket import _pick_symbol, _closes_h1, _rolling_corr

# key, label, keywords (prefix priority), role (ใช้สังเคราะห์ sentiment)
_ECO = [
    ("DXY", "USD Index",   ["USD_FX", "USDX", "DXY"],        "usd"),
    ("SPX", "S&P 500",     ["US500CASH", "US500", "SPX"],    "risk"),
    ("NDX", "Nasdaq 100",  ["US100CASH", "US100", "USTEC"],  "risk"),
    ("VIX", "VIX",         ["VIX"],                          "fear"),
    ("XAG", "Silver",      ["SILVER", "XAG"],                "metal"),
    ("WTI", "Oil (WTI)",   ["OILCASH", "OIL", "WTI"],        "commodity"),
    ("EUR", "EURUSD",      ["EURUSD"],                       "usd_inv"),
    ("JPY", "USDJPY",      ["USDJPY"],                       "usd"),
    ("AUD", "AUDUSD",      ["AUDUSD"],                       "risk_fx"),
    ("BTC", "BTC",         ["BTCUSD", "BITCOIN"],            "risk"),
]
_DEAD = 0.01           # deadband % — ต่ำกว่านี้ = FLAT (ทอง $0.4/ชม; เดิม 0.03=$1.2 ใหญ่ไป ขึ้น "นิ่ง" บ่อย)
_TYP_W = 100           # window (H1 bars) สำหรับ correlation "ปกติ"


def _move_1h(mt5, symbol, hclose):
    """(%เปลี่ยน rolling ~60นาที, ราคาปัจจุบัน) — tick เทียบ close ~60 นาทีที่แล้ว (M15×4 = window คงที่
    ไม่ผูกกับต้นชั่วโมง กัน bias reset ทุกต้น ชม.). fallback H1 (since hour start) ถ้า M15 ไม่พร้อม."""
    tick = mt5.symbol_info_tick(symbol)
    price = float(tick.bid) if tick and tick.bid else None
    ref = None
    m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 6)
    if m15 is not None and len(m15) >= 5:
        ref = float(m15[-5]["close"])         # close ของแท่ง M15 ~60 นาทีก่อน (rolling)
        if price is None:
            price = float(m15[-1]["close"])
    if (price is None or not ref) and hclose:  # fallback: H1 series
        ts = sorted(hclose)
        if price is None:
            price = hclose[ts[-1]]
        if not ref and len(ts) >= 2:
            ref = hclose[ts[-2]]
    if price is None or not ref:
        return None, price
    return round((price - ref) / ref * 100, 2), price


def _sign(x):
    if x is None or abs(x) < _DEAD:
        return 0
    return 1 if x > 0 else -1


def _sentiment(gold_mv, rows):
    """สังเคราะห์ว่าการวิ่งของทองรอบนี้เป็นแบบไหน (rule-based, 0 token)."""
    mv = {r["key"]: (r["move"] or 0.0) for r in rows}
    stocks = (mv.get("SPX", 0) + mv.get("NDX", 0)) / 2
    vix, dxy = mv.get("VIX", 0), mv.get("DXY", 0)
    gd = gold_mv or 0.0
    if abs(gd) < _DEAD:
        return {"emoji": "⚪", "label": "ทองนิ่ง / Range", "detail": "ทองแทบไม่ขยับ — รอทิศทาง"}
    if gd > 0:                                                       # ทองขึ้น
        if stocks > _DEAD and vix < -_DEAD:
            return {"emoji": "🟢", "label": "Risk-on beta", "detail": "ทอง↑ พร้อมหุ้น↑ VIX↓ — ขึ้นแบบสินทรัพย์เสี่ยง (beta) ไม่ใช่ safe-haven"}
        if stocks < -_DEAD and vix > _DEAD:
            return {"emoji": "🛡️", "label": "Safe-haven", "detail": "ทอง↑ หุ้น↓ VIX↑ — เงินไหลเข้าสินทรัพย์ปลอดภัย (fear bid)"}
        if dxy < -_DEAD:
            return {"emoji": "💵", "label": "USD-driven", "detail": "ทอง↑ DXY↓ — ดอลลาร์อ่อนดันทอง"}
        return {"emoji": "⚪", "label": "Mixed (ทอง↑)", "detail": "ทองขึ้นแต่สัญญาณ cross-asset ผสม"}
    else:                                                           # ทองลง
        if stocks < -_DEAD and vix > _DEAD:
            return {"emoji": "🔴", "label": "Risk-off (เทขายรวม)", "detail": "ทอง↓ หุ้น↓ VIX↑ — เทขายทุกอย่าง / USD bid"}
        if stocks > _DEAD and vix < -_DEAD:
            return {"emoji": "🟢", "label": "Risk-on (หมุนออกทอง)", "detail": "ทอง↓ หุ้น↑ — เงินหมุนจากทองเข้าสินทรัพย์เสี่ยง"}
        if dxy > _DEAD:
            return {"emoji": "💵", "label": "USD-driven (ทอง↓)", "detail": "ทอง↓ DXY↑ — ดอลลาร์แข็งกดทอง"}
        return {"emoji": "⚪", "label": "Mixed (ทอง↓)", "detail": "ทองลงแต่สัญญาณ cross-asset ผสม"}


def ecosystem():
    """{ok, gold:{symbol,price,move}, sentiment, n_with, n_against, rows[...]}. live MT5, read-only."""
    import MetaTrader5 as mt5
    try:
        already = mt5.terminal_info() is not None
    except Exception:
        already = False
    if not already:
        try:
            from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
            if not mt5.initialize():
                return {"ok": False, "error": "MT5 init failed", "rows": []}
            mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
        except Exception as e:
            return {"ok": False, "error": f"MT5 attach: {e}", "rows": []}
    try:
        allsyms = [s.name for s in (mt5.symbols_get() or [])]
        gsym = _pick_symbol(allsyms, ["GOLD", "XAUUSD"]) or "GOLD#"
        mt5.symbol_select(gsym, True)
        gclose = _closes_h1(mt5, gsym)
        gmove, gprice = _move_1h(mt5, gsym, gclose)
        gsign = _sign(gmove)

        rows, n_with, n_against = [], 0, 0
        for key, label, kws, role in _ECO:
            sym = _pick_symbol(allsyms, kws)
            if not sym:
                rows.append({"key": key, "label": label, "symbol": None, "price": None,
                             "move": None, "rel": "—", "typ_corr": None, "diverge": False})
                continue
            mt5.symbol_select(sym, True)
            hclose = _closes_h1(mt5, sym)
            move, price = _move_1h(mt5, sym, hclose)
            typ = _rolling_corr(gclose, hclose).get(f"corr{_TYP_W}")
            s = _sign(move)
            if s == 0 or gsign == 0:
                rel = "FLAT"
            elif s == gsign:
                rel = "WITH"; n_with += 1
            else:
                rel = "AGAINST"; n_against += 1
            # divergence: ปกติ corr แรง แต่ตอนนี้วิ่งผิดจากปกติ
            diverge = False
            if typ is not None and rel in ("WITH", "AGAINST"):
                if typ > 0.3 and rel == "AGAINST":
                    diverge = True                    # ปกติตาม แต่ตอนนี้สวน
                elif typ < -0.3 and rel == "WITH":
                    diverge = True                    # ปกติสวน แต่ตอนนี้ตาม
            rows.append({"key": key, "label": label, "symbol": sym, "price": price,
                         "move": move, "rel": rel, "typ_corr": typ, "diverge": diverge, "role": role})

        return {"ok": True,
                "gold": {"symbol": gsym, "price": gprice, "move": gmove},
                "sentiment": _sentiment(gmove, rows),
                "n_with": n_with, "n_against": n_against, "window": "1h",
                "rows": rows}
    finally:
        if not already:
            mt5.shutdown()


if __name__ == "__main__":
    import sys, json
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(ecosystem(), ensure_ascii=False, indent=2))
