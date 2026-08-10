"""agents/candle_patterns.py — candle-pattern probability (UHAS-style, display-only).

ตรวจแพทเทิร์นแท่งเทียนบนแท่ง H1 ปิดล่าสุด + คำนวณ **hit-rate เชิงสถิติ** จากประวัติในหน้าต่าง
(แพทเทิร์นเดียวกันในอดีต → ราคาไปทางที่แพทเทิร์นบอกภายใน fwd แท่ง กี่ %). read-only ต่อ MT5, 0 token.
ไม่ตัดสิน entry (CORE INVARIANT) — เป็นตัวเลข display ให้คนดู เหมือน UHAS terminal.
"""
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)


def _detect(o, h, l, c, i):
    """คืน list ของ (name, dir) ที่แท่ง i (ใช้ i และ i-1). dir = 'BUY'/'SELL'."""
    out = []
    body = abs(c[i] - o[i]); rng = h[i] - l[i]
    if rng <= 0:
        return out
    up_wick = h[i] - max(o[i], c[i]); lo_wick = min(o[i], c[i]) - l[i]
    pb = abs(c[i-1] - o[i-1])
    # engulfing (body ครอบ body แท่งก่อน + สลับสี)
    if c[i] > o[i] and c[i-1] < o[i-1] and c[i] >= o[i-1] and o[i] <= c[i-1] and body > pb:
        out.append(("bullish_engulfing", "BUY"))
    if c[i] < o[i] and c[i-1] > o[i-1] and o[i] >= c[i-1] and c[i] <= o[i-1] and body > pb:
        out.append(("bearish_engulfing", "SELL"))
    # hammer / shooting star (ไส้ยาวข้างเดียว, body เล็ก)
    if lo_wick > 2 * body and up_wick < body and body > 0:
        out.append(("hammer", "BUY"))
    if up_wick > 2 * body and lo_wick < body and body > 0:
        out.append(("shooting_star", "SELL"))
    return out


def detect(symbol, count=2000, fwd=6, margin_pct=0.0008):
    """แพทเทิร์นบนแท่ง H1 ปิดล่าสุด + hist win-rate. คืน {ok, patterns:[{name,dir,winrate,n,fwd}]} หรือ {error}."""
    try:
        import MetaTrader5 as mt5
        from connectors.price_feed import get_ohlcv
        try:
            from connectors.pair_collector import _broker_map
            broker = _broker_map().get(symbol, symbol)
        except Exception:
            broker = symbol
        rates = get_ohlcv(symbol=broker, timeframe=mt5.TIMEFRAME_H1, count=count)
        if rates is None or len(rates) < 120:
            return {"error": "บาร์ไม่พอ"}
        o = rates["open"].astype(float); h = rates["high"].astype(float)
        l = rates["low"].astype(float); c = rates["close"].astype(float)
        n = len(c)
        # 1) สร้างสถิติ hit-rate ต่อ (name,dir) จากทั้งหน้าต่าง (occurrence → ไปทางนั้น > margin ภายใน fwd)
        stats = {}                                        # key=(name,dir) → [wins, total]
        for i in range(1, n - fwd - 1):
            for name, d in _detect(o, h, l, c, i):
                fut = c[i + fwd]; base = c[i]
                win = (fut > base * (1 + margin_pct)) if d == "BUY" else (fut < base * (1 - margin_pct))
                s = stats.setdefault((name, d), [0, 0])
                s[0] += int(win); s[1] += 1
        # 2) แพทเทิร์นบนแท่งปิดล่าสุด (i = n-2)
        cur = _detect(o, h, l, c, n - 2)
        patterns = []
        for name, d in cur:
            wins, tot = stats.get((name, d), [0, 0])
            patterns.append({
                "name": name, "dir": d, "fwd": fwd,
                "winrate": round(100 * wins / tot) if tot else None, "n": tot,
            })
        return {"ok": True, "symbol": symbol, "fwd": fwd, "patterns": patterns}
    except Exception as e:
        return {"error": str(e)[:120]}
