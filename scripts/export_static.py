"""scripts/export_static.py — export dashboard "public-safe" data → site/data/*.json สำหรับ GitHub Pages.

Static snapshot: อ่าน display-only data (edge/backtest/regime/macro) → sanitize (ตัดเงิน/บัญชี/positions) →
เขียน site/data/. หน้า site/index.html fetch ไฟล์พวกนี้ (ไม่มี Flask/MT5/account).
รัน: python scripts/export_static.py   (MT5 login อยู่ = ได้ cointegration/real-edge สด; ไม่ต่อ = ข้าม fail-soft)
refresh page = รันซ้ำ + git commit site/.
"""
import os
import sys
import json
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)
_DATA = os.path.join(_BASE, "data")
_OUT = os.path.join(_BASE, "site", "data")

# ── sanitize: ตัด key ที่เป็นเงิน/บัญชี/สถานะ port ออกทุกชั้น ──────────────────
_BLOCK = ("profit", "pnl", "balance", "equity", "margin", "free_margin", "login",
          "account", "deposit", "withdraw", "ticket", "price_open", "volume", "usd_thb",
          "baht", "thb", "money", "capital", "new_baseline", "baseline")


def _sanitize(obj):
    """ลบ key ที่มี substring ใน _BLOCK (case-insensitive) recursive. เก็บ ratio/stat/edge ไว้."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(b in kl for b in _BLOCK):
                continue
            out[k] = _sanitize(v)
        return out
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def _write(name, obj):
    os.makedirs(_OUT, exist_ok=True)
    with open(os.path.join(_OUT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    print(f"  ok  {name}")


def _copy_file(src_name, out_name=None):
    """copy data/<src> → site/data/<out> (sanitized). fail-soft."""
    p = os.path.join(_DATA, src_name)
    try:
        obj = json.load(open(p, encoding="utf-8"))
        _write(out_name or src_name, _sanitize(obj))
        return True
    except Exception as e:
        print(f"  --  {src_name}: {str(e)[:60]}")
        return False


def _computed(name, fn):
    try:
        _write(name, _sanitize(fn()))
    except Exception as e:
        print(f"  --  {name} (computed): {str(e)[:70]}")


def main():
    print("export static → site/data/")
    # 1) copy-safe raw files (market/analytics — ตัดเงินออกด้วย sanitize)
    for f in ("backtest_results.json", "regime_analytics.json", "regime_monitor.json",
              "macro_strip.json", "cot.json", "event_stats.json", "event_scenarios.json",
              "news_impact.json", "calibration.json", "impact_calibration.json",
              "regime_extra.json", "risk_regime_now.json", "regime_state.json"):
        _copy_file(f)
    # 2) computed (ต้อง import agent; บางตัวใช้ MT5 — fail-soft ถ้าไม่ต่อ)
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
    except Exception:
        pass
    _computed("real_edge.json", lambda: __import__("agents.real_edge", fromlist=["build"]).build())
    _computed("risk_sat.json", lambda: __import__("agents.risk_analytics", fromlist=["summary"]).summary())
    _computed("equity_curve.json", lambda: __import__("agents.risk_analytics", fromlist=["equity_curve"]).equity_curve())
    def _coint():
        sys.path.insert(0, os.path.join(_BASE, "scripts"))
        return __import__("cointegration_scan", fromlist=["run"]).run()
    _computed("cointegration.json", _coint)
    # 3) manifest (เวลา export)
    _write("_manifest.json", {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "note": "public snapshot — no account/money/positions. refresh: python scripts/export_static.py"})
    print("done. → git add site/ && commit")


if __name__ == "__main__":
    main()
