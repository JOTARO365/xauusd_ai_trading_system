"""agents/event_engine.py — event-driven engine (NFP/CPI/FOMC) SHADOW-first. user 08-07 (จากวิดีโอ NFP prep).

ใช้ data ที่เดิม display-only:
  - ff_calendar_raw.json : ปฏิทินข่าว (impact/forecast/actual/date) → timing + surprise
  - event_scenarios.json : rubric (hot/cool → ทิศทอง + magnitude, n173-181)
ทำ 2 อย่าง:
  1. PRE-EVENT  : ก่อนข่าวแรง N นาที → แนะนำ flat/pause (NFP ทิศ=coinflip + move ใหญ่ → กัน whipsaw)
  2. POST-EVENT : หลัง release มี actual → surprise (actual vs forecast) → event_scenarios ทิศ → bias ทอง

⚠️ SHADOW-first: log สิ่งที่ "จะทำ" ลง journal (data/event_engine_journal.jsonl) เก็บ forward data — **ไม่แตะ trade จริง**
จนกว่า EVENT_ENGINE_LIVE=true (validate forward ก่อน). rubric = economic + n ประวัติ, backtest เต็มไม่ได้ (ไม่มี forecast ย้อนหลัง).
snapshot() = dashboard. fail-soft ทุกจุด.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from loguru import logger

_BASE = Path(__file__).resolve().parent.parent
_CAL = _BASE / "data" / "ff_calendar_raw.json"
_SCEN = _BASE / "data" / "event_scenarios.json"
_JOURNAL = _BASE / "data" / "event_engine_journal.jsonl"
_STATE = _BASE / "data" / "event_engine_state.json"

# title (FF) → event_scenarios key
_MAP = [
    (r"non.?farm|nfp|employment change", "NFP"),
    (r"core cpi", "CORE_CPI"),
    (r"\bcpi\b|consumer price", "CPI"),
    (r"unemployment rate", "UNEMPLOYMENT"),
    (r"ism.*manufac|manufacturing pmi", "ISM_MFG"),
    (r"ism.*serv|services pmi", "ISM_SVC"),
    (r"\badp\b", "ADP"),
    (r"fomc|federal funds|interest rate", "FOMC"),
]


def _cfg(name, default):
    import config as _c
    return getattr(_c, name, default)


def _num(s):
    """'+432K' / '3.9%' / '-0.3%' / '54.7' → float. คืน None ถ้าแปลงไม่ได้."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("%", "")
    mult = 1.0
    if t[-1:].upper() == "K":
        mult, t = 1e3, t[:-1]
    elif t[-1:].upper() == "M":
        mult, t = 1e6, t[:-1]
    elif t[-1:].upper() == "B":
        mult, t = 1e9, t[:-1]
    try:
        return float(t) * mult
    except Exception:
        return None


def _scen_key(title):
    t = (title or "").lower()
    for pat, key in _MAP:
        if re.search(pat, t):
            return key
    return None


def _load_events():
    try:
        d = json.loads(_CAL.read_text(encoding="utf-8"))
        evs = d.get("events") or d.get("data") or (d if isinstance(d, list) else [])
        out = []
        for e in evs:
            if not isinstance(e, dict):
                continue
            key = _scen_key(e.get("title", ""))
            imp = str(e.get("impact", "")).lower()
            ctry = str(e.get("country", "")).upper()
            if not key or imp not in ("high", "medium"):
                continue
            if ctry not in ("USD", "ALL", ""):        # ทอง = USD-driven (+ FOMC=USD)
                continue
            try:
                dt = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
            except Exception:
                continue
            out.append({"key": key, "title": e.get("title"), "impact": imp, "dt": dt,
                        "forecast": e.get("forecast"), "actual": e.get("actual"), "previous": e.get("previous")})
        return out
    except Exception:
        return []


def _scenarios():
    try:
        return json.loads(_SCEN.read_text(encoding="utf-8")).get("scenarios", {})
    except Exception:
        return {}


def evaluate(now=None):
    """คืน dict สถานะ event ปัจจุบันสำหรับทอง (PRE/POST/NONE + bias). ไม่แตะ trade."""
    now = now or datetime.now(timezone.utc)
    pre_min = int(_cfg("EVENT_PRE_MIN", 30))
    post_min = int(_cfg("EVENT_POST_MIN", 120))
    scen = _scenarios()
    evs = _load_events()
    # PRE: ข่าวแรงใกล้ (ยังไม่ถึง)
    for e in sorted(evs, key=lambda x: x["dt"]):
        delta = (e["dt"] - now).total_seconds() / 60.0
        if 0 <= delta <= pre_min:
            return {"phase": "PRE", "key": e["key"], "title": e["title"], "in_min": round(delta, 1),
                    "action": "flat/pause (กัน whipsaw ข่าวแรง)", "bias_dir": None}
    # POST: เพิ่ง release (มี actual) ภายใน window
    for e in sorted(evs, key=lambda x: x["dt"], reverse=True):
        age = (now - e["dt"]).total_seconds() / 60.0
        if 0 <= age <= post_min and e.get("actual"):
            a = _num(e["actual"]); f = _num(e["forecast"])
            if a is None or f is None:
                continue
            hot = a > f                                # actual สูงกว่าคาด = "hot" reading
            sc = scen.get(e["key"], {})
            leg = sc.get("hot" if hot else "cool", {})
            d = leg.get("dir")                          # 'up'/'down' (ทอง)
            if d in ("up", "down"):
                return {"phase": "POST", "key": e["key"], "title": e["title"], "age_min": round(age, 1),
                        "surprise": "hot" if hot else "cool", "actual": e["actual"], "forecast": e["forecast"],
                        "bias_dir": "BUY" if d == "up" else "SELL",
                        "magnitude_pct": leg.get("magnitude_pct"), "n": leg.get("n"),
                        "action": "bias ทอง %s (rubric)" % ("BUY" if d == "up" else "SELL")}
    return {"phase": "NONE", "bias_dir": None}


def _journal(rec):
    try:
        rec = {**rec, "ts": datetime.now(timezone.utc).isoformat()}
        with open(_JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


_last_logged = {"k": None}


def tick():
    """เรียกทุก cycle. SHADOW: คำนวณ + log journal เมื่อ phase เปลี่ยน. ไม่แตะ trade เว้น EVENT_ENGINE_LIVE.
    คืน state dict หรือ None. fail-soft."""
    try:
        st = evaluate()
        # snapshot ล่าสุด (dashboard)
        try:
            _STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        if st.get("phase") in ("PRE", "POST"):
            k = "%s:%s:%s" % (st["phase"], st.get("key"), st.get("surprise", ""))
            if k != _last_logged["k"]:                 # log ครั้งเดียวต่อ phase-event (กัน spam)
                _last_logged["k"] = k
                # ราคาทองตอน event (สำหรับวัด forward outcome ภายหลัง)
                px = None
                try:
                    import MetaTrader5 as mt5
                    import config as _c
                    tk = mt5.symbol_info_tick(_c.SYMBOL)
                    px = tk.bid if tk else None
                except Exception:
                    pass
                _journal({**st, "gold_px": px, "live": bool(_cfg("EVENT_ENGINE_LIVE", False))})
                logger.info("[EVENT-ENGINE] %s %s → %s (shadow%s)" % (
                    st["phase"], st.get("key"), st.get("action"),
                    "" if not _cfg("EVENT_ENGINE_LIVE", False) else "/LIVE"))
        return st
    except Exception as e:
        logger.debug("[EVENT-ENGINE] fail-soft: %s" % e)
        return None


def bias():
    """directional bias สำหรับ algo อื่นใช้ (เมื่อ EVENT_ENGINE_LIVE) — POST-event ทิศ rubric.
    คืน dict {dir, phase, key} หรือ None. shadow (LIVE=false) → คืน None เสมอ (ไม่แตะ trade)."""
    if not _cfg("EVENT_ENGINE_LIVE", False):
        return None
    st = evaluate()
    if st.get("phase") == "POST" and st.get("bias_dir"):
        return {"dir": st["bias_dir"], "phase": "POST", "key": st["key"]}
    if st.get("phase") == "PRE":
        return {"dir": "FLAT", "phase": "PRE", "key": st["key"]}
    return None


def snapshot():
    """dashboard — สถานะ event ปัจจุบัน + upcoming. 0 order."""
    try:
        st = evaluate()
        up = []
        now = datetime.now(timezone.utc)
        for e in sorted(_load_events(), key=lambda x: x["dt"]):
            d = (e["dt"] - now).total_seconds() / 3600.0
            if 0 <= d <= 72:
                up.append({"key": e["key"], "title": e["title"], "in_hours": round(d, 1),
                           "forecast": e.get("forecast"), "impact": e["impact"]})
        return {"ok": True, "state": st, "upcoming": up[:8], "live": bool(_cfg("EVENT_ENGINE_LIVE", False))}
    except Exception:
        return {"ok": False}
