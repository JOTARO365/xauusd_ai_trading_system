"""agents/equities_intermarket.py — ราคาดัชนีหุ้นที่ขับทอง (S&P500 / Nasdaq / VIX) + correlation กับทอง.

Display-only · READ-ONLY บน MT5 (copy_rates/tick เท่านั้น — ไม่ส่งออเดอร์ / ไม่แตะ config / ไม่ป้อน entry/gate).
คำนวณ returns-based rolling correlation (50/100/200 H1 bars) เทียบ GOLD# บน feed เดียวกัน (timezone ตรง +
align by timestamp กัน spurious). ใช้โดย /api/equities บน dashboard. 0 token (compute-in-code).

⚠️ intermarket = บริบทให้ "ดูวิเคราะห์" ไม่ใช่ตัวตัดสินเทรด (CORE INVARIANT: ข่าว/context = sentiment เท่านั้น).
"""
import numpy as np

# logical → keyword ค้นหา symbol บน broker (ชื่อต่าง broker ได้). VIX = futures มี expiry (roll) → เลือก front.
_INSTRUMENTS = [
    ("SPX", "S&P 500",    ["US500CASH", "US500", "SP500", "SPX"]),
    ("NDX", "Nasdaq 100", ["US100CASH", "USTEC", "US100", "NAS100", "NDX"]),
    ("VIX", "VIX",        ["VIX"]),
]
_GOLD_KWS = ["GOLD", "XAUUSD"]
_WINDOWS = (50, 100, 200)
_NEED = max(_WINDOWS) + 60          # H1 bars ที่ดึง (เผื่อ align/gap ตลาดหุ้นปิดกลางคืน)


def _pick_symbol(allsyms, kws):
    """symbol บน broker ที่ตรง keyword. kws เรียง priority (เจาะจงสุดก่อน). prefix/exact ก่อน แล้วค่อย substring
    — กัน keyword หลวม (เช่น 'NDX') ไปโดน 'AI_INDX#'. ในกลุ่มที่ตรง = ชื่อสั้นสุด (VIX → front contract)."""
    up = {n: n.upper() for n in allsyms}
    for k in kws:                                         # 1) prefix/exact ตาม priority
        cands = [n for n in allsyms if up[n].startswith(k)]
        if cands:
            return sorted(cands, key=len)[0]
    for k in kws:                                         # 2) fallback substring (broker ชื่อแปลก)
        cands = [n for n in allsyms if k in up[n]]
        if cands:
            return sorted(cands, key=len)[0]
    return None


def _closes_h1(mt5, symbol):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, _NEED)
    if rates is None or len(rates) == 0:
        return None
    return {int(r["time"]): float(r["close"]) for r in rates}


def _price_and_change(mt5, symbol):
    """ราคาปัจจุบัน (tick) + %เปลี่ยนของวัน (เทียบ open ของแท่ง D1 ล่าสุด)."""
    tick = mt5.symbol_info_tick(symbol)
    d1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 1)
    price = float(tick.bid) if tick and tick.bid else (float(d1[-1]["close"]) if d1 is not None and len(d1) else None)
    op = float(d1[-1]["open"]) if d1 is not None and len(d1) else None
    chg = round((price - op) / op * 100, 2) if (price and op) else None
    return price, chg


def _rolling_corr(gclose, iclose):
    """Pearson correlation ของ log-returns (align by timestamp) หลาย window."""
    out = {f"corr{w}": None for w in _WINDOWS}
    if not gclose or not iclose:
        return out
    common = sorted(set(gclose) & set(iclose))            # แท่งที่มีทั้งทองและดัชนี (ตลาดหุ้นปิดกลางคืน → gap)
    if len(common) < min(_WINDOWS) + 1:
        return out
    g = np.array([gclose[t] for t in common], dtype=float)
    x = np.array([iclose[t] for t in common], dtype=float)
    gr, xr = np.diff(np.log(g)), np.diff(np.log(x))
    for w in _WINDOWS:
        if len(gr) >= w:
            a, b = gr[-w:], xr[-w:]
            if a.std() > 0 and b.std() > 0:
                out[f"corr{w}"] = round(float(np.corrcoef(a, b)[0, 1]), 2)
    return out


def equities_vs_gold():
    """{ok, gold, windows, rows[{key,label,symbol,price,chg_pct,corr50/100/200,n}]}. live จาก MT5, read-only."""
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
        gold_sym = _pick_symbol(allsyms, _GOLD_KWS) or "GOLD#"
        mt5.symbol_select(gold_sym, True)
        gclose = _closes_h1(mt5, gold_sym)
        rows = []
        for key, label, kws in _INSTRUMENTS:
            sym = _pick_symbol(allsyms, kws)
            if not sym:
                rows.append({"key": key, "label": label, "symbol": None, "price": None,
                             "chg_pct": None, "corr50": None, "corr100": None, "corr200": None, "n": 0})
                continue
            mt5.symbol_select(sym, True)
            iclose = _closes_h1(mt5, sym)
            price, chg = _price_and_change(mt5, sym)
            corr = _rolling_corr(gclose, iclose)
            n = len(set(gclose) & set(iclose)) if (gclose and iclose) else 0
            rows.append({"key": key, "label": label, "symbol": sym, "price": price,
                         "chg_pct": chg, "n": n, **corr})
        return {"ok": True, "gold": gold_sym, "windows": list(_WINDOWS), "rows": rows}
    finally:
        if not already:
            mt5.shutdown()


if __name__ == "__main__":
    import sys, json
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(equities_vs_gold(), ensure_ascii=False, indent=2))
