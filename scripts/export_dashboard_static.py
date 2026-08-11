"""scripts/export_dashboard_static.py — snapshot dashboard /api/* GET responses → site/data/api/*.json

หน้า public (site/index.html) = สำเนา dashboard จริง + fetch-shim ที่ map GET /api/<name> → ./data/api/<name>.json
สคริปต์นี้ยิง Flask test_client ทุก endpoint แบบ display-only, sanitize (ตัดเงิน/บัญชี/positions recursive),
เขียนไฟล์ static. POST/DELETE (config/close/switch) ไม่ถูก snapshot — shim ทำให้ตายเงียบบนหน้า public.

รัน: python scripts/export_dashboard_static.py   (MT5 login อยู่ = data สด; ไม่ต่อ = endpoint fail-soft ได้ {} )
refresh หน้า public = รันซ้ำ + git commit site/
"""
import os
import sys
import json
import importlib.util
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)
_OUT = os.path.join(_BASE, "site", "data", "api")

# ── sanitize: ตัด key เงิน/บัญชี/positions ทุกชั้น (เก็บ ratio/stat/edge) ──────────
_BLOCK = ("profit", "pnl", "balance", "equity", "margin", "free_margin", "login",
          "account", "deposit", "withdraw", "ticket", "price_open", "volume", "usd_thb",
          "baht", "thb", "money", "capital", "new_baseline", "baseline", "lots", "lot",
          "swap", "commission")


def _sanitize(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if any(b in str(k).lower() for b in _BLOCK):
                continue
            out[k] = _sanitize(v)
        return out
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


# ── endpoints ที่เก็บ (display-only). (path, outname). param = ตัวแทน 1 snapshot ──
# outname ต้องตรงกับ fetch-shim: u.slice(5).split('?')[0]  →  /api/foo-bar → foo-bar.json
_ENDPOINTS = [
    ("/api/data", "data"),
    ("/api/monitor", "monitor"),
    ("/api/macro-strip", "macro-strip"),
    ("/api/cot", "cot"),
    ("/api/algo-status", "algo-status"),
    ("/api/worldmap", "worldmap"),
    ("/api/map-layers", "map-layers"),
    ("/api/map-context", "map-context"),
    ("/api/worldmonitor", "worldmonitor"),
    ("/api/pair-moves", "pair-moves"),
    ("/api/news-impact", "news-impact"),
    ("/api/pair-context", "pair-context"),
    ("/api/ecosystem", "ecosystem"),
    ("/api/smc-monitor", "smc-monitor"),
    ("/api/smc-backtest", "smc-backtest"),
    ("/api/tsmom", "tsmom"),
    ("/api/sr-book", "sr-book"),
    ("/api/live-symbols", "live-symbols"),
    ("/api/cluster-map", "cluster-map"),
    ("/api/owner-gate", "owner-gate"),
    ("/api/macro-quant", "macro-quant"),
    ("/api/liquidity-proxy", "liquidity-proxy"),
    ("/api/algo-journal", "algo-journal"),
    ("/api/algo-potential", "algo-potential"),
    ("/api/shadow-matrix", "shadow-matrix"),
    ("/api/real-edge", "real-edge"),
    ("/api/algo-selector", "algo-selector"),
    ("/api/shadow-tsmom", "shadow-tsmom"),
    ("/api/owner-edge", "owner-edge"),
    ("/api/daily-summary", "daily-summary"),
    ("/api/regime-analytics", "regime-analytics"),
    ("/api/regime-monitor", "regime-monitor"),
    ("/api/calibration", "calibration"),
    ("/api/news-gate", "news-gate"),
    ("/api/impact-calibration", "impact-calibration"),
    ("/api/event-stats", "event-stats"),
    ("/api/event-scenario", "event-scenario"),
    ("/api/event-engine", "event-engine"),
    ("/api/regime", "regime"),
    ("/api/regime-state", "regime-state"),
    ("/api/regime-extra", "regime-extra"),
    ("/api/risk-regime", "risk-regime"),
    ("/api/calendar", "calendar"),
    ("/api/volume-profile", "volume-profile"),
    ("/api/options-oi", "options-oi"),
    ("/api/sentiment-score", "sentiment-score"),
    ("/api/candle-patterns", "candle-patterns"),
    ("/api/gate-blocks", "gate-blocks"),
    ("/api/ride-stats", "ride-stats"),
    ("/api/comex", "comex"),
    ("/api/pairs", "pairs"),
    ("/api/pair-context", "pair-context"),
    ("/api/backtest-results", "backtest-results"),
    ("/api/risk-sat", "risk-sat"),
    ("/api/equity-curve", "equity-curve"),
    ("/api/cointegration", "cointegration"),
    ("/api/regime", "regime"),
    ("/api/trade-symbols", "trade-symbols"),
    ("/api/weekly-outlook", "weekly-outlook"),
    ("/api/gap-monitor", "gap-monitor"),
    # parameterized — ตัวแทน default
    ("/api/backtest?system=", "backtest"),
    ("/api/trades-symbol?symbol=XAUUSD", "trades-symbol"),
    ("/api/sr-ladder", "sr-ladder"),
    ("/api/candles?tf=H1", "candles"),
]


def _load_app():
    spec = importlib.util.spec_from_file_location(
        "dashboard_app", os.path.join(_BASE, "dashboard", "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


def main():
    print("export dashboard static -> site/data/api/")
    os.makedirs(_OUT, exist_ok=True)
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
    except Exception:
        pass
    app = _load_app()
    client = app.test_client()
    ok = 0
    for path, name in _ENDPOINTS:
        try:
            r = client.get(path)
            if r.status_code != 200:
                print(f"  --  {name}: HTTP {r.status_code}")
                continue
            obj = _sanitize(r.get_json(force=True, silent=True) or {})
            with open(os.path.join(_OUT, name + ".json"), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
            print(f"  ok  {name}")
            ok += 1
        except Exception as e:
            print(f"  --  {name}: {str(e)[:70]}")
    with open(os.path.join(_OUT, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "endpoints": ok, "note": "public snapshot — no account/money/positions"},
                  f, ensure_ascii=False, indent=1)
    print(f"done. {ok}/{len(_ENDPOINTS)} endpoints -> git add site/ then commit")


if __name__ == "__main__":
    main()
