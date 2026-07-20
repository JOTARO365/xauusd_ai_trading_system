"""agents/macro_quant.py — unified macro/news quant layer (ข่าว + เศรษฐกิจ → ตัวเลข → gold bias). 0 token.

รวมตัวเลขที่มีอยู่ (กระจัดกระจายคนละไฟล์) เป็น **feature vector เดียว → gold_macro_score** สำหรับ SELECTION
(เลือก algo/regime bias) + แสดงผล. ไม่ recompute LLM — consume ผลที่ scored ไว้แล้ว.

หลักการ (ดู docs): gold-directional signing (ข่าวเดียวกันเซ็นต์เทียบทอง) · bounded (tanh กันข่าวสุดโต่งครอบงำ) ·
weighted-average over available (ไฟล์หาย → renormalize) · auditable (components breakdown) · staleness-aware.

CORE INVARIANT: ตัวเลข = guide เลือก regime/algo (SELECTION) ไม่ใช่ตัดสิน entry.
"""
import json
import math
import os
from datetime import datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    try:
        with open(os.path.join(_BASE, "data", name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _age_min(iso):
    """อายุนาทีของ timestamp iso (None ถ้า parse ไม่ได้)."""
    if not iso:
        return None
    try:
        s = str(iso).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        return max(0.0, (datetime.now(timezone.utc) - d).total_seconds() / 60.0)
    except (ValueError, TypeError):
        return None


def build_features():
    """อ่านตัวเลขที่ scored/fetched ไว้ → feature dict ดิบ (พร้อม age). 0 token, fail-soft."""
    ni = _read("news_impact.json"); ms = _read("macro_strip.json")
    rx = _read("regime_extra.json"); rr = _read("risk_regime_now.json")
    cot = _read("cot.json"); rs = _read("regime_state.json")
    agg = (ni.get("aggregate") or {})
    return {
        "news":   {"score": agg.get("score"), "n_scored": agg.get("n_scored"),
                   "age_min": _age_min(ni.get("updated"))},
        "macro":  {"dxy_chg": (ms.get("dxy") or {}).get("chg"), "y10_chg": (ms.get("y10") or {}).get("chg"),
                   "real_yield": (ms.get("real_yield") or {}).get("val"),
                   "real_yield_chg": (ms.get("real_yield") or {}).get("chg"), "age_min": _age_min(ms.get("updated"))},
        "risk":   {"vix": (rx.get("vix") or {}).get("val"), "vix_chg": (rx.get("vix") or {}).get("chg"),
                   "gsr_chg": (rx.get("gsr") or {}).get("chg"), "regime": rr.get("regime"),
                   "age_min": _age_min(rx.get("updated"))},
        "pos":    {"cot_net": cot.get("net"), "cot_net_chg": cot.get("net_chg")},
        "econ":   {"real_rate": rs.get("real_rate"), "fed_dir": rs.get("fed_dir"), "cpi_yoy": rs.get("cpi_yoy")},
    }


# ── gold-directional components: (weight, value→[-1,+1] contribution เทียบทอง) ──
# + = bullish gold, − = bearish gold. bounded ด้วย tanh (หลัก 10).
def _components(f):
    c = {}
    news = f["news"]["score"]
    if news is not None:
        fresh = 1.0
        age = f["news"].get("age_min")
        if age is not None:
            fresh = math.exp(-age / 180.0)              # ข่าว decay ครึ่งชีวิต ~180 นาที (หลัก 5)
        c["news"] = (0.25, max(-1, min(1, news / 100.0)) * fresh)
    ry = f["macro"]["real_yield"]
    if ry is not None:
        c["real_yield"] = (0.20, -math.tanh(ry / 1.5))  # real yield สูง → ลบทอง (ต้นทุนถือ)
    ryc = f["macro"]["real_yield_chg"]
    if ryc is not None:
        c["real_yield_chg"] = (0.08, -math.tanh(ryc / 0.5))
    dxy = f["macro"]["dxy_chg"]
    if dxy is not None:
        c["dxy"] = (0.15, -math.tanh(dxy / 0.3))        # USD แข็ง → ลบทอง
    y10 = f["macro"]["y10_chg"]
    if y10 is not None:
        c["y10"] = (0.08, -math.tanh(y10 / 0.1))        # yield ขึ้น → ลบทอง
    vix, vixc = f["risk"]["vix"], f["risk"]["vix_chg"]
    if vix is not None:
        lvl = math.tanh((vix - 18.0) / 8.0)             # VIX สูง/พุ่ง → บวกทอง (risk-off, safe haven)
        chg = math.tanh((vixc or 0) / 3.0)
        c["vix"] = (0.15, max(-1, min(1, 0.5 * lvl + 0.5 * chg)))
    reg = f["risk"]["regime"]
    if reg:
        c["risk_regime"] = (0.05, 0.6 if reg == "RISK-OFF" else (-0.6 if reg == "RISK-ON" else 0.0))
    cotc = f["pos"]["cot_net_chg"]
    if cotc is not None:
        c["cot"] = (0.10, math.tanh(cotc / 20000.0))    # net long เพิ่ม → บวก (positioning momentum)
    gsrc = f["risk"]["gsr_chg"]
    if gsrc is not None:
        c["gsr"] = (0.02, math.tanh(gsrc / 2.0))
    fed = f["econ"]["fed_dir"]
    if fed:
        c["fed"] = (0.10, {"cutting": 0.7, "hiking": -0.7}.get(str(fed).lower(), 0.0))
    return c


def gold_macro_score():
    """รวม components → gold bias score (−100..+100) + regime stance + breakdown. 0 token, auditable."""
    f = build_features()
    comps = _components(f)
    if not comps:
        return {"ok": False, "error": "ไม่มีข้อมูล macro/news"}
    tw = sum(w for w, _ in comps.values())
    contrib = {k: round(w * v, 4) for k, (w, v) in comps.items()}      # ส่วนถ่วงน้ำหนักจริง (auditable)
    net = sum(contrib.values()) / tw if tw else 0.0
    score = int(round(max(-1, min(1, net)) * 100))
    # confidence: coverage (มีกี่ component) × agreement (กี่ตัวเซ็นต์ตรง net)
    n_tot = 11
    coverage = len(comps) / n_tot
    sgn = 1 if score >= 0 else -1
    agree = sum(1 for v in contrib.values() if (v >= 0) == (sgn >= 0) and abs(v) > 1e-6)
    agreement = agree / len(comps) if comps else 0.0
    conf = round(min(1.0, 0.4 + 0.6 * coverage) * (0.5 + 0.5 * agreement), 2)
    bias = "BULLISH" if score > 15 else ("BEARISH" if score < -15 else "NEUTRAL")
    driver = max(contrib.items(), key=lambda kv: abs(kv[1]))[0] if contrib else None
    # stance (การ analysis): ผสม risk_regime + real_yield + score
    if f["risk"]["regime"] == "RISK-OFF" and score > 0:
        stance = "RISK-OFF safe-haven bid"
    elif (f["macro"]["real_yield"] is not None and f["macro"]["real_yield"] < 0.5) and score > 0:
        stance = "inflation/real-rate hedge"
    elif score > 15:
        stance = "gold-supportive"
    elif score < -15:
        stance = "gold-headwind"
    else:
        stance = "two-sided / neutral"
    stale = [k for k in ("news", "macro", "risk")
             if (f[k].get("age_min") or 0) > (240 if k == "news" else 1440)]
    return {
        "ok": True, "score": score, "bias": bias, "confidence": conf, "stance": stance,
        "driver": driver, "components": contrib, "coverage": f"{len(comps)}/{n_tot}",
        "stale": stale, "as_of": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(gold_macro_score(), ensure_ascii=False, indent=2))
