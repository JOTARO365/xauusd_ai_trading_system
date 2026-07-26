"""agents/sr_stats.py — touch-outcome stats ต่อเส้น S/R (section C+D ของ dropdown explainer).

scan H1 bars: ทุกครั้งราคาแตะแนว → เด้ง(bounce)/ทะลุ(break) + ราคาไปไกลแค่ไหนหลังแตะ (C) +
recency/session (D). display-only · 0 token · read-only ต่อ MT5. reuse แนวคิดจาก chart_watcher._break_bounce_stats.
"""
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

_SESSIONS = [("Asian", 0, 7), ("London", 7, 13), ("NY", 13, 21), ("Late", 21, 24)]


def _session(hour):
    for name, a, b in _SESSIONS:
        if a <= hour < b:
            return name
    return "?"


def level_touch_stats(symbol, level, side, count=2000, zone_pct=0.003,
                      fwd=8, margin_pct=0.0012):
    """C+D ต่อเส้น. side='R'(ต้าน)/'S'(รับ). scan H1. คืน dict หรือ {error}.
    C: เด้ง/ทะลุแล้วราคาไปไกลเฉลี่ย/สูงสุด (price = $ สำหรับทอง) · D: N แตะล่าสุด + per-session hold%."""
    try:
        import MetaTrader5 as mt5
        from datetime import datetime, timezone
        from connectors.price_feed import get_ohlcv
        try:
            from connectors.pair_collector import _broker_map
            broker = _broker_map().get(symbol, symbol)
        except Exception:
            broker = symbol
        level = float(level)
        info = mt5.symbol_info(broker)
        point = float(info.point) if (info and info.point) else 0.01
        rates = get_ohlcv(symbol=broker, timeframe=mt5.TIMEFRAME_H1, count=count)
        if rates is None or len(rates) < 60:
            return {"error": "บาร์ไม่พอ"}
        highs = rates["high"].astype(float); lows = rates["low"].astype(float)
        closes = rates["close"].astype(float); times = rates["time"]
        n = len(highs)
        zone, margin = level * zone_pct, level * margin_pct
        is_R = (side == "R")
        touches = []                                     # per touch: {broke, move_price, hour, ts}
        in_zone = False
        for i in range(n):
            hit = lows[i] <= level + zone and highs[i] >= level - zone
            if hit and not in_zone and i + 1 < n:
                j0, j1 = i + 1, min(i + 1 + fwd, n)
                win_c = closes[j0:j1]; win_h = highs[j0:j1]; win_l = lows[j0:j1]
                broke = bool((win_c > level + margin).any()) if is_R else bool((win_c < level - margin).any())
                if broke:                                # ทะลุ → ไปต่อไกลแค่ไหนเลยแนว
                    move = float(win_h.max() - level) if is_R else float(level - win_l.min())
                else:                                    # เด้ง → กลับไปไกลแค่ไหนฝั่งตรงข้าม
                    move = float(level - win_l.min()) if is_R else float(win_h.max() - level)
                hour = datetime.fromtimestamp(int(times[i]), timezone.utc).hour
                touches.append({"broke": broke, "move": max(0.0, move), "hour": hour, "ts": int(times[i])})
            in_zone = hit
        if not touches:
            return {"error": "ไม่พบการแตะในช่วงข้อมูล"}
        from datetime import datetime, timezone
        nt = len(touches)
        breaks = [t for t in touches if t["broke"]]
        bounces = [t for t in touches if not t["broke"]]

        def _avg(xs):
            return round(sum(xs) / len(xs), 2) if xs else None

        # C — magnitude (price = $ สำหรับทอง; pip = /point)
        bounce_moves = [t["move"] for t in bounces]
        break_moves = [t["move"] for t in breaks]
        # D — recency (5 ล่าสุด) + per-session hold%
        last = sorted(touches, key=lambda t: t["ts"], reverse=True)[:5]
        recent = [{"broke": t["broke"],
                   "when": datetime.fromtimestamp(t["ts"], timezone.utc).strftime("%m-%d %H:%M")}
                  for t in last]
        by_sess = {}
        for t in touches:
            s = _session(t["hour"])
            d = by_sess.setdefault(s, {"n": 0, "hold": 0})
            d["n"] += 1; d["hold"] += 0 if t["broke"] else 1
        sess = {s: {"n": d["n"], "hold_pct": round(100 * d["hold"] / d["n"])}
                for s, d in by_sess.items()}
        last_ts = max(t["ts"] for t in touches)
        bars_since = sum(1 for x in times if int(x) > last_ts)
        return {
            "ok": True, "symbol": symbol, "level": round(level, 3), "side": side, "n_touches": nt,
            "held": len(bounces), "broke": len(breaks),
            "bounce_avg": _avg(bounce_moves), "bounce_max": round(max(bounce_moves), 2) if bounce_moves else None,
            "break_avg": _avg(break_moves), "break_max": round(max(break_moves), 2) if break_moves else None,
            "bounce_avg_pips": round(_avg(bounce_moves) / point) if bounce_moves else None,
            "break_avg_pips": round(_avg(break_moves) / point) if break_moves else None,
            "recent": recent, "by_session": sess, "bars_since_touch": bars_since,
        }
    except Exception as e:
        return {"error": str(e)[:120]}
