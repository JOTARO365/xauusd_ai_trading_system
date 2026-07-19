"""agents/sr_engine.py — S/R view กลาง (P-A, DESIGN_algo_v2 §2). display/compute-only, 0 order, 0 token.

รวม sr_meta (chart_watcher `_build_sr_meta` — ยังคำนวณใน REGIME_LIVE) + cluster dwell density เป็น view เดียว
ให้ entry/exit อ่าน. **decoupled: consume sr_meta ที่มีอยู่ ไม่ rebuild scorer.** deterministic ตรง CORE INVARIANT.

sr_meta entry (จาก _build_sr_meta): level, side("R"/"S"), tf("W1"/"D1"/"H4"/"H1"), touches, bars_since_touch,
  avg_bounce, bounce_pct, break_pct, n_tests, break_hold, strength, why, confluence{with,count}, score, grade("A/B/C").

ใช้: entry_gate (P-B) เลือกทิศ · pick_tp_target (P-D) · sr_trailing_stop (P-D).
"""
import json
import os
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_BASE, "scripts"))
import regime_lib as R                                   # POINT

_CLUSTER_MATCH_ATR = 0.3                                 # cluster ถือว่า "ตรง" S/R ถ้าห่าง ≤ 0.3·ATR


def _cluster_density(level, clusters, atr):
    """touches ของ dwell-cluster ที่ตรงกับ S/R level นี้ (0 ถ้าไม่มี)."""
    if not clusters or atr <= 0:
        return 0
    best = 0
    for c in clusters:
        cl = c.get("level")
        if cl is not None and abs(cl - level) <= _CLUSTER_MATCH_ATR * atr:
            best = max(best, int(c.get("touches", 0)))
    return best


def _enrich(lvl, price, atr, clusters):
    """เติม dist + cluster density ให้ level entry (คัดฟิลด์ที่ entry/exit ใช้)."""
    level = float(lvl["level"])
    return {
        "level": round(level, 2), "side": lvl.get("side"), "tf": lvl.get("tf"),
        "grade": lvl.get("grade"), "score": lvl.get("score"), "touches": lvl.get("touches"),
        "bounce_pct": lvl.get("bounce_pct"), "break_pct": lvl.get("break_pct"), "n_tests": lvl.get("n_tests"),
        "confluence": lvl.get("confluence"),           # {"with":[...],"count":int} หรือ None (ไม่มี partner)
        "dist_atr": round(abs(level - price) / atr, 2) if atr > 0 else None,
        "dist_pips": round(abs(level - price) / R.POINT),
        "cluster_density": _cluster_density(level, clusters, atr),
    }


def level_significance(lvl):
    """MAJOR (แนวใหญ่ราคากระจุก) / MINOR / MID — ใช้เลือก TP: MAJOR→TP ไกล, MINOR→TP ใกล้.
    หมายเหตุ: sr_meta มีแต่ tf H4/H1 (D1/W1 = scoring context ผ่าน grade+confluence) → วัดความใหญ่จาก
    grade A + cluster density + confluence (แนวชน D1/W1/HTF) + touches ไม่ใช่ tf โดยตรง."""
    if not lvl:
        return "MID"
    grade = (lvl.get("grade") or "").upper()
    dens = lvl.get("cluster_density", 0) or 0
    conf = lvl.get("confluence") or {}
    conf_ct = conf.get("count", 0) if isinstance(conf, dict) else 0
    touches = lvl.get("touches", 0) or 0
    if grade == "A" and (dens >= 8 or conf_ct >= 1 or touches >= 7):
        return "MAJOR"                                  # grade A + ยืนยันด้วย cluster/confluence/touch = แนวใหญ่
    if grade == "C":
        return "MINOR"
    return "MID"


def build_sr_view(sr_meta, price, atr, cluster=None):
    """รวม sr_meta + cluster → view เดียว. pure (testable). คืน ok=False ถ้า data ไม่พอ."""
    price = float(price)
    atr = float(atr) if atr else 0.0
    if not sr_meta or atr <= 0:
        return {"ok": False, "error": "sr_meta/atr ไม่พร้อม"}
    clusters = (cluster or {}).get("clusters") or []
    res_raw = [l for l in sr_meta if l.get("side") == "R" and float(l["level"]) > price]
    sup_raw = [l for l in sr_meta if l.get("side") == "S" and float(l["level"]) < price]
    res = sorted((_enrich(l, price, atr, clusters) for l in res_raw), key=lambda x: x["level"])
    sup = sorted((_enrich(l, price, atr, clusters) for l in sup_raw), key=lambda x: -x["level"])
    # dedup targets ตาม level ปัด (เก็บ score สูงสุด) — กันแนวซ้ำข้าม TF
    def _dedup(rows):
        seen = {}
        for r in rows:
            k = round(r["level"], 1)
            if k not in seen or (r.get("score") or 0) > (seen[k].get("score") or 0):
                seen[k] = r
        return list(seen.values())
    targets_up = sorted(_dedup(res), key=lambda x: x["level"])
    targets_down = sorted(_dedup(sup), key=lambda x: -x["level"])
    return {
        "ok": True, "price": round(price, 2), "atr": round(atr, 2),
        "resistance": res[0] if res else None,
        "support": sup[0] if sup else None,
        "targets_up": targets_up, "targets_down": targets_down,
        "clusters": clusters,
    }


def pick_tp_target(sr_view, direction, entry, sl_pips, min_rr=1.5):
    """เลือก TP จาก S/R เป้าหมาย ตามความสำคัญของแนวที่เข้า.
    เข้าที่แนว MAJOR (W1/กระจุก) → TP แนวไกลกว่า · MINOR (H1) → แนวถัดไปใกล้ๆ. floor ด้วย min_rr.
    คืน {tp, level, tf, grade, rr, source}. fallback = entry ± min_rr·risk ถ้าไม่มีแนวไกลพอ."""
    if not sr_view.get("ok"):
        return None
    entry = float(entry)
    risk = sl_pips * R.POINT
    if risk <= 0:
        return None
    sign = 1 if direction == "BUY" else -1
    min_dist = min_rr * risk
    entry_lvl = sr_view["support"] if direction == "BUY" else sr_view["resistance"]  # แนวที่กำลังเข้า
    sig = level_significance(entry_lvl)
    targets = sr_view["targets_up"] if direction == "BUY" else sr_view["targets_down"]
    valid = [t for t in targets if abs(t["level"] - entry) >= min_dist]   # ต้องไกลกว่า min_rr
    chosen = None
    if valid:
        if sig in ("MAJOR", "MID"):                       # เข้าแนวใหญ่/กลาง → เล็ง target ที่ significant (ข้ามแนว minor)
            tier = [t for t in valid if level_significance(t) in ("MAJOR", "MID")] or valid
        else:                                             # MINOR → target ถัดไปใกล้สุด (H1 ใกล้ ตาม directive)
            tier = valid
        chosen = tier[0]                                  # ใกล้สุดใน tier (realistic — แนวแรกที่ราคาจะ react)
    if not chosen:
        tp = entry + sign * min_dist                      # fallback: RR คงที่
        return {"tp": round(tp, 2), "level": None, "tf": None, "grade": None,
                "rr": round(min_rr, 2), "source": "min_rr_fallback", "entry_sig": sig}
    tp = chosen["level"] - sign * 0.1 * sr_view["atr"]     # เผื่อ buffer ก่อนถึงแนว (ไม่รอชนเป๊ะ)
    return {"tp": round(tp, 2), "level": chosen["level"], "tf": chosen["tf"], "grade": chosen["grade"],
            "rr": round(abs(tp - entry) / risk, 2), "source": "sr_target", "entry_sig": sig}


def sr_trailing_stop(sr_view, direction, atr=None, buffer_atr=0.3):
    """Trailing SL จาก S/R แข็งแรง + vol buffer: long → ใต้ support เล็กน้อย, short → เหนือ resistance.
    ตั้งต่ำกว่าแนวเล็กน้อย (buffer_atr·ATR) กันราคาแกว่งชน. คืน price หรือ None."""
    if not sr_view.get("ok"):
        return None
    atr = float(atr) if atr else sr_view.get("atr", 0)
    if direction == "BUY":
        s = sr_view.get("support")
        return round(s["level"] - buffer_atr * atr, 2) if s else None
    r = sr_view.get("resistance")
    return round(r["level"] + buffer_atr * atr, 2) if r else None


def from_live():
    """assemble sr_meta จาก logs/bot_status.json (chart_watcher เขียนทุก cycle) + cluster จาก MT5 → view.
    fail-soft: คืน {ok:False} ถ้าไม่พร้อม. ใช้ตอน live (entry/exit path)."""
    try:
        status_p = os.path.join(_BASE, "logs", "bot_status.json")
        with open(status_p, encoding="utf-8") as f:
            st = json.load(f)
        sr_meta = ((st.get("zones") or {}).get("sr_meta")) or []
        price = (st.get("price_info") or {}).get("bid") or st.get("last_signal", {}).get("price")
        if not sr_meta or price is None:
            return {"ok": False, "error": "bot_status ไม่มี sr_meta/price"}
        try:
            from agents.cluster_map import from_mt5
            cluster = from_mt5()
        except Exception:
            cluster = None
        atr = (cluster or {}).get("atr")
        if not atr:                                       # fallback: ATR จาก plan หรือประมาณจาก sr distance
            atr = float(st.get("market", {}).get("atr") or 0) or None
        if not atr:
            return {"ok": False, "error": "ATR ไม่พร้อม"}
        return build_sr_view(sr_meta, float(price), float(atr), cluster)
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    v = from_live()
    print(json.dumps(v, ensure_ascii=False, indent=2, default=str)[:2000])
