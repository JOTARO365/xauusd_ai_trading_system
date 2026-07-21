"""agents/owner_gate.py — owner-gate ADVISORY (เตือนอย่างเดียว, ไม่ปิด/ไม่บล็อก). 0 token.

จาก owner_edge analysis (robust): owner เสียต่อเนื่องใน (ก) mid-vol regime (−9,672฿ WR38% PF0.57)
(ข) SELL/short (−6,220฿ PF0.88 vs BUY +7,299). gate นี้ **เตือน** เมื่อเข้าเงื่อนไขเสี่ยง — owner ตัดสินเอง
(ไม่ auto-close manual = เคารพ discretion + iron rule "ห้ามปิด order เป็น side effect").

owner_gate_now() → {vol_regime, warnings:[{level,msg}]}. ใช้ใน dashboard banner + terminal.
"""
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))


def owner_gate_now():
    """คืน warnings ตาม robust owner-edge (mid-vol + manual short). fail-soft, advisory เท่านั้น."""
    out = {"ok": True, "vol_regime": None, "vol_pct": None, "manual_shorts": 0, "warnings": []}
    try:                                              # ensure MT5 connection (idempotent — no-op ถ้าต่อแล้ว)
        import MetaTrader5 as mt5
        mt5.initialize()
    except Exception:
        pass
    # ── vol regime ปัจจุบัน (จาก live H1 bars) ──
    try:
        import regime_lib as R
        from agents.regime_shadow import _bars_from_feed
        bars = _bars_from_feed()
        if bars is not None:
            _h, _l, close, _t = bars
            vp = R.vol_percentile(close)
            v = float(vp[-2])
            if v == v:
                b = "low-vol" if v < 0.33 else ("high-vol" if v > 0.67 else "mid-vol")
                out["vol_regime"] = b; out["vol_pct"] = round(v, 2)
                if b == "mid-vol":
                    out["warnings"].append({"level": "warn", "tag": "MID-VOL",
                        "msg": "regime MID-VOL — โซนที่พี่เสียต่อเนื่อง (hist −9,672฿ · WR 38% · PF 0.57). ระวัง / ลด size / เลี่ยง"})
    except Exception:
        pass
    # ── manual SHORT ที่เปิดอยู่ ──
    try:
        from connectors.mt5_connector import get_open_positions
        shorts = [p for p in (get_open_positions() or [])
                  if str(p.get("direction", "")).upper() == "SELL"
                  and not str(p.get("comment") or "").startswith("ALGO")]
        out["manual_shorts"] = len(shorts)
        if shorts:
            out["warnings"].append({"level": "warn", "tag": "SHORT",
                "msg": f"{len(shorts)} SHORT (manual) เปิดอยู่ — SELL ของพี่ underperform (hist −6,220฿ · PF 0.88 vs BUY +7,299)"})
    except Exception:
        pass
    return out


if __name__ == "__main__":
    import json
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(owner_gate_now(), ensure_ascii=False, indent=2))
