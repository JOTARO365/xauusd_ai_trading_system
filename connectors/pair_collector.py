"""connectors/pair_collector.py — Batch A: เก็บ OHLC + spread ของ gold-complex universe (0 token, read-only MT5).

Phase 2 ของ docs/DESIGN_multipair.md. เก็บ data ทุกคู่ (trade แค่ XAUUSD; คู่อื่น data-only จน toggle).
ไม่มี order_send — copy_rates / symbol_info เท่านั้น. รันเป็น process แยก (ปลอดภัยกับ loop บอท) หรือ import collect_once().
รัน standalone (ผู้ใช้ควบคุม): & $PY connectors\pair_collector.py    [--once]
เขียน: data/pairs/<logical>_<tf>.json (OHLC), data/pairs/spread_log.jsonl, data/pair_context.json.
broker symbol map อ่านจาก data/universe_probe.json (validated โดย scripts/probe_universe.py — กัน mis-resolve).
"""
import datetime as dt
import json
import os
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAIRDIR = os.path.join(_BASE, "data", "pairs")
_PROBE = os.path.join(_BASE, "data", "universe_probe.json")
_CTX = os.path.join(_BASE, "data", "pair_context.json")
_SPREAD_LOG = os.path.join(_PAIRDIR, "spread_log.jsonl")

# คู่ที่เก็บ (Phase-1: trade XAUUSD only, collect all). XAU* + XAG + USD cluster.
COLLECT = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "AUDUSD", "EURUSD", "USDCHF", "USDJPY"]
_TF_BARS = {"m15": 700, "h1": 500, "h4": 400, "d1": 300}    # เก็บล่าสุดเท่านี้ต่อ TF (bounded)
INTERVAL = 60                                                # standalone loop วินาที/รอบ


def _mt5():
    import MetaTrader5 as mt5
    return mt5


def _tfmap(mt5):
    return {"m15": mt5.TIMEFRAME_M15, "h1": mt5.TIMEFRAME_H1,
            "h4": mt5.TIMEFRAME_H4, "d1": mt5.TIMEFRAME_D1}


def _broker_map():
    """logical → broker symbol จาก universe_probe.json (validated). fallback = logical เอง."""
    try:
        p = json.load(open(_PROBE, encoding="utf-8"))
        inst = p.get("instruments", {})
        return {k: (inst.get(k, {}).get("broker_symbol") or k) for k in COLLECT if k in inst}
    except Exception:
        return {}


def _write_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


def collect_once():
    """pull OHLC (4 TF) + spread snapshot ต่อ symbol → เขียนไฟล์. คืน dict สรุป (n symbols ok)."""
    mt5 = _mt5()
    os.makedirs(_PAIRDIR, exist_ok=True)
    bmap = _broker_map()
    if not bmap:
        return {"ok": False, "error": "no universe_probe.json (run probe_universe.py first)"}
    tfmap = _tfmap(mt5)
    now = int(time.time())
    ok = 0
    spreads = []
    for logical, sym in bmap.items():
        try:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
            tick = mt5.symbol_info_tick(sym)
            if info and tick and info.point:
                sp = round((tick.ask - tick.bid) / info.point)
                spreads.append({"ts": now, "sym": logical, "broker": sym,
                                "spread_pts": sp, "bid": tick.bid, "ask": tick.ask})
            for tf, cnt in _TF_BARS.items():
                rates = mt5.copy_rates_from_pos(sym, tfmap[tf], 0, cnt)
                if rates is None or len(rates) == 0:
                    continue
                arr = [[int(r["time"]), float(r["open"]), float(r["high"]),
                        float(r["low"]), float(r["close"]), int(r["tick_volume"])] for r in rates]
                _write_json(os.path.join(_PAIRDIR, f"{logical.lower()}_{tf}.json"), arr)
            ok += 1
        except Exception:
            continue
    # append spread snapshots (jsonl)
    try:
        with open(_SPREAD_LOG, "a", encoding="utf-8") as f:
            for s in spreads:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
    except Exception:
        pass
    ctx = compute_context()
    return {"ok": ok > 0, "n": ok, "ts": now, "context": ctx}


def _closes(logical, tf="d1", n=25):
    """อ่าน close ล่าสุด n บาร์ จากไฟล์ที่ collect ไว้."""
    try:
        arr = json.load(open(os.path.join(_PAIRDIR, f"{logical.lower()}_{tf}.json"), encoding="utf-8"))
        return [row[4] for row in arr[-n:]]
    except Exception:
        return []


def compute_context():
    """cross-pair signals (0 token): gold-complex breadth, USD-leg decomposition, gold/silver ratio z.
    = context ให้ pipeline XAUUSD เดิม (read-only) + dashboard. ไม่ใช่ entry signal."""
    out = {"ok": False, "ts": int(time.time())}
    try:
        # ── gold-complex breadth: กี่คู่ยืนยันทิศ gold (last vs ~5 D1 bars ก่อน) ──
        gold_pairs = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY"]
        signs = []
        for g in gold_pairs:
            c = _closes(g, "d1", 6)
            if len(c) >= 6 and c[-6] != 0:
                signs.append(1 if c[-1] > c[-6] else (-1 if c[-1] < c[-6] else 0))
        breadth = round(sum(signs) / len(signs), 2) if signs else None

        # ── USD-leg decomposition: XAUUSD move vs EURUSD move (same window) ──
        xau = _closes("XAUUSD", "d1", 6); eur = _closes("EURUSD", "d1", 6)
        story = None; xr = er = None
        if len(xau) >= 6 and len(eur) >= 6 and xau[-6] and eur[-6]:
            xr = (xau[-1] / xau[-6] - 1)
            er = (eur[-1] / eur[-6] - 1)
            if abs(xr) > 1e-4:
                # EUR ขึ้นตาม XAU (USD อ่อนดันทั้งคู่) = USD story; EUR สวน = gold-specific
                story = "USD-driven" if (xr > 0) == (er > 0) else "gold-specific"

        # ── gold/silver ratio + z-score (RV context) ──
        xg = _closes("XAUUSD", "d1", 60); xs = _closes("XAGUSD", "d1", 60)
        ratio = ratio_z = None
        if len(xg) >= 30 and len(xs) >= 30:
            m = min(len(xg), len(xs))
            series = [xg[-m + i] / xs[-m + i] for i in range(m) if xs[-m + i]]
            if len(series) >= 30:
                ratio = round(series[-1], 2)
                mean = sum(series) / len(series)
                var = sum((x - mean) ** 2 for x in series) / len(series)
                sd = var ** 0.5 or 1e-9
                ratio_z = round((series[-1] - mean) / sd, 2)

        out.update({"ok": True, "breadth": breadth, "breadth_n": len(signs),
                    "usd_story": story, "xau_ret": round(xr, 4) if xr is not None else None,
                    "eur_ret": round(er, 4) if er is not None else None,
                    "gold_silver_ratio": ratio, "ratio_z": ratio_z})
    except Exception as e:
        out["error"] = str(e)[:80]
    _write_json(_CTX, out)
    return out


def _init_mt5():
    mt5 = _mt5()
    if not mt5.initialize():                                 # attach terminal ที่รันอยู่ก่อน (ไม่ re-login)
        import sys
        sys.path.insert(0, _BASE)
        try:
            from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
            if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
                return False
        except Exception:
            return False
    return True


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if not _init_mt5():
        print(f"MT5 init failed: {_mt5().last_error()}"); sys.exit(1)
    once = "--once" in sys.argv
    print(f"pair_collector | {'ONCE' if once else f'loop {INTERVAL}s'} | pairs={len(_broker_map())}")
    while True:
        r = collect_once()
        c = r.get("context", {})
        stamp = dt.datetime.utcnow().strftime("%H:%M:%S")
        print(f"[{stamp}] ok={r.get('n')} breadth={c.get('breadth')} story={c.get('usd_story')} "
              f"gsr={c.get('gold_silver_ratio')} z={c.get('ratio_z')}")
        if once:
            break
        time.sleep(INTERVAL)
