"""agents/liquidity_proxy.py — "poor man's order book" (volume-profile + cluster + COT → order-flow proxy). 0 token.

⚠️ CAVEAT (ตรงไปตรงมา): XAUUSD retail/MT5 **ไม่มี order book จริง** (market-maker, tick-volume ไม่ใช่ volume จริง).
นี่คือ **proxy** ของ liquidity/order-flow จากข้อมูลที่มี → confidence ต่ำโดยเจตนา. ไม่ใช่สัญญาณ HFT.
ของจริงต้องใช้ COMEX GC futures (มี book) + low-latency. ใช้เป็น SELECTION guide เท่านั้น (ไม่ตัดสิน entry).

รวม: volume-profile (HVN/tilt, tick-vol proxy) + cluster dwell-zone (ราคาอยู่นาน=order ค้าง proxy) +
COT (positioning เชิงโครงสร้างรายสัปดาห์) → flow tilt (−100..+100) + liquidity magnets (walls/pools).
"""
import json
import math
import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    try:
        with open(os.path.join(_BASE, "data", name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def build_liquidity(cluster=None):
    """อ่าน volume_profile + liquidity_pools (logs/bot_status) + COT (data/) + cluster (optional). 0 token, fail-soft."""
    try:
        with open(os.path.join(_BASE, "logs", "bot_status.json"), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, json.JSONDecodeError):
        st = {}
    cot = _read("cot.json")
    return {
        "vp": st.get("volume_profile") or {},
        "pools": st.get("liquidity_pools") or {},
        "price": (st.get("price_info") or {}).get("bid"),
        "cot": {"net": cot.get("net"), "net_chg": cot.get("net_chg")},
        "cluster": cluster or {},
    }


def liquidity_score(cluster=None):
    """รวม → flow tilt (−100..+100) + liquidity magnets. confidence ต่ำ (proxy). auditable breakdown."""
    f = build_liquidity(cluster)
    vp = f["vp"]; comps = {}

    # ── flow tilt components (gold-directional, tanh-bounded) ──
    bp = vp.get("buy_pct")
    if bp is not None:
        comps["vol_tilt"] = (0.35, math.tanh((float(bp) - 50.0) / 18.0))   # tick-vol proxy (อ่อน)
    ncg = f["cot"]["net_chg"]
    if ncg is not None:
        comps["cot_flow"] = (0.35, math.tanh(float(ncg) / 20000.0))        # positioning momentum (net long เพิ่ม→บวก)
    mom = (f["cluster"] or {}).get("momentum")
    if mom in ("up", "down"):
        comps["cluster_mom"] = (0.30, 0.6 if mom == "up" else -0.6)        # ราคากำลังไปทางไหน (dwell proxy)

    if not comps:
        return {"ok": False, "error": "ไม่มีข้อมูล liquidity (volume_profile/COT)"}
    tw = sum(w for w, _ in comps.values())
    contrib = {k: round(w * v, 4) for k, (w, v) in comps.items()}
    net = sum(contrib.values()) / tw if tw else 0.0
    score = int(round(max(-1, min(1, net)) * 100))
    tilt = "BUY-flow" if score > 12 else ("SELL-flow" if score < -12 else "balanced")

    # ── liquidity magnets: HVN walls + stop pools (เป็น "กำแพง/แม่เหล็ก" proxy — ไม่ใช่ tilt) ──
    px = f["price"]
    hvn = vp.get("hvn") or []
    walls_above = sorted([h for h in hvn if h.get("level") and px and h["level"] > px], key=lambda h: h["level"])
    walls_below = sorted([h for h in hvn if h.get("level") and px and h["level"] < px], key=lambda h: -h["level"])
    pools = f["pools"]
    magnets = {
        "wall": vp.get("wall"),                                            # HVN ใหญ่สุด = แนวดูดหลัก
        "hvn_above": walls_above[0] if walls_above else None,
        "hvn_below": walls_below[0] if walls_below else None,
        "stop_pools_below": (pools.get("sell_side") or [])[:2],            # stop cluster (แม่เหล็กล่าง)
        "stop_pools_above": (pools.get("buy_side") or [])[:2],
    }
    cot_net = f["cot"]["net"]
    return {
        "ok": True, "score": score, "tilt": tilt,
        "confidence": 0.35,                                                # ต่ำโดยเจตนา (proxy — ไม่มี book จริง)
        "components": contrib, "coverage": f"{len(comps)}/3",
        "magnets": magnets, "cot_net": cot_net, "vp_basis": vp.get("basis"),
        "caveat": "proxy — XAUUSD retail ไม่มี order book จริง (tick-vol/dwell/COT); guide เท่านั้น",
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(liquidity_score(), ensure_ascii=False, indent=2))
