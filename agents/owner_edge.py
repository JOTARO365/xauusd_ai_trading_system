"""agents/owner_edge.py — วิเคราะห์ edge ของ owner (ไม้ manual) × vol regime. 0 token.

หลัก: directional mechanical edge หมดแล้ว (15+ tests) แต่ owner มี discretionary edge จริง (+2128฿).
map แต่ละไม้ manual → **vol regime ตอนเข้า** (จาก H1 bars) → รู้ว่า owner ชนะ/แพ้ regime/สภาพไหน
→ actionable: เพิ่มน้ำหนักช่วงที่แข็ง, ลด/เลี่ยงช่วงที่อ่อน. offline, fail-soft.

CLI: python agents/owner_edge.py   ·   dashboard: /api/owner-edge
"""
import json
import os
from collections import defaultdict
from datetime import datetime

import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _h1_regime():
    """โหลด H1 → (epoch[], vol_percentile[], regime_label[]). fail-soft → None."""
    try:
        import sys
        sys.path.insert(0, os.path.join(_BASE, "scripts"))
        import regime_lib as R
        d = np.array(json.load(open(os.path.join(_BASE, "data", "xau_h1.json"))), dtype=float)
        ep, high, low, close = d[:, 0], d[:, 2], d[:, 3], d[:, 4]
        er = R.efficiency_ratio(close); adx = R.adx(high, low, close)
        vp = R.vol_percentile(close); atr = R.atr(high, low, close)
        reg = np.array([R.detect_regime(er[i], adx[i], vp[i]) for i in range(len(close))], dtype=object)
        return ep, vp, reg
    except Exception:
        return None


def _vol_bucket(vp):
    if vp != vp:
        return None
    return "low-vol" if vp < 0.33 else ("high-vol" if vp > 0.67 else "mid-vol")


def _stats(rows):
    """สรุปกลุ่มไม้: n, WR, net฿, avg฿, profit-factor."""
    pnls = [float(t.get("pnl") or 0) for t in rows]
    if not pnls:
        return None
    w = [p for p in pnls if p > 0]; l = [p for p in pnls if p <= 0]
    net = sum(pnls); srt = sorted(pnls, reverse=True)
    return {"n": len(pnls), "wins": len(w), "win_rate": round(len(w) / len(pnls), 3),
            "net": round(net, 2), "avg": round(net / len(pnls), 2),
            "avg_win": round(sum(w) / len(w), 2) if w else 0,
            "avg_loss": round(sum(l) / len(l), 2) if l else 0,
            "pf": round(sum(w) / abs(sum(l)), 2) if l and sum(l) != 0 else None,
            "top3_pct": round(sum(srt[:3]) / net * 100) if net > 0 else None}  # outlier check: % net จาก top-3


def build_owner_edge():
    """คืน {by_vol, by_regime, by_dir, overall, n_mapped} — edge ของ owner แยกตาม vol regime. 0 token."""
    try:
        tr = json.load(open(os.path.join(_BASE, "logs", "trades.json"), encoding="utf-8"))
        tr = tr if isinstance(tr, list) else tr.get("trades", [])
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": "ไม่สามารถอ่าน trades.json ได้"}
    man = [t for t in tr if isinstance(t, dict) and t.get("status") == "CLOSED"
           and t.get("pnl") is not None and t.get("timestamp")
           and (t.get("source") == "MANUAL" or t.get("entry_type") == "MANUAL")]
    h1 = _h1_regime()
    by_vol = defaultdict(list); by_reg = defaultdict(list); by_dir = defaultdict(list)
    n_map = 0
    for t in man:
        by_dir[str(t.get("direction") or "?")].append(t)
        if not h1:
            continue
        ep, vp, reg = h1
        try:
            te = datetime.fromisoformat(str(t["timestamp"])).timestamp()   # naive → local epoch
        except (ValueError, TypeError):
            continue
        idx = int(np.searchsorted(ep, te)) - 1                             # H1 bar ก่อน/ตอนเข้าไม้
        if idx < 0 or idx >= len(vp):
            continue
        b = _vol_bucket(float(vp[idx]))
        if b:
            by_vol[b].append(t); by_reg[str(reg[idx])].append(t); n_map += 1
    order_v = ["low-vol", "mid-vol", "high-vol"]
    order_r = ["TREND", "RANGE", "RISK-OFF", "NEUTRAL", "WARMUP"]
    return {
        "ok": True, "n_manual": len(man), "n_mapped": n_map,
        "overall": _stats(man),
        "by_vol": [{"key": k, **_stats(by_vol[k])} for k in order_v if by_vol[k]],
        "by_regime": [{"key": k, **_stats(by_reg[k])} for k in order_r if by_reg[k]],
        "by_dir": [{"key": k, **_stats(by_dir[k])} for k in by_dir if by_dir[k]],
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    e = build_owner_edge()
    if not e.get("ok"):
        print(e); raise SystemExit
    print(f"OWNER EDGE — ออเดอร์ manual {e['n_manual']} (map vol ได้ {e['n_mapped']})")
    o = e["overall"]
    print(f"รวม: n={o['n']} WR={o['win_rate']*100:.0f}% net={o['net']:+.0f}฿ avg={o['avg']:+.1f}฿ PF={o['pf']}\n")
    for title, key in (("× VOL REGIME", "by_vol"), ("× MARKET REGIME", "by_regime"), ("× ทิศทาง", "by_dir")):
        print(f"── {title} ──")
        print(f"  {'':>10} {'n':>4} {'WR':>5} {'net฿':>8} {'avg฿':>7} {'PF':>5}")
        for r in e[key]:
            print(f"  {r['key']:>10} {r['n']:>4} {r['win_rate']*100:>4.0f}% {r['net']:>+8.0f} {r['avg']:>+7.1f} {str(r['pf']):>5}")
        print()
    print("อ่าน: regime ที่ WR/PF สูง+net บวก = owner แข็ง (เพิ่มน้ำหนัก) · net ลบหนัก = อ่อน (เลี่ยง/ลด size)")
