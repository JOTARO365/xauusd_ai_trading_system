"""agents/weekly_outlook.py — หน้าแนวโน้มประจำสัปดาห์ (LLM Opus สังเคราะห์).

รวม data จริง (ปฏิทิน ForexFactory 7 วัน + event_scenarios hot/cool→ทอง + news sentiment + macro_regime + COT)
→ Opus 1 ครั้ง/สัปดาห์ → narrative: สรุปสัปดาห์ที่แล้ว · ปฏิทิน+scenario สัปดาห์นี้ · ทิศทาง/bias · เฝ้าระวัง · macro ติดตาม.
cache data/weekly_outlook.json ต่อ ISO-week (แสดง 0 token). trigger: auto ต้นสัปดาห์ + ปุ่ม refresh.
"""
import json
import os

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE = os.path.join(_BASE, "data", "weekly_outlook.json")
_MODEL = os.getenv("WEEKLY_OUTLOOK_MODEL", "claude-opus-4-6")   # env-override เผื่อ model id เปลี่ยน


def _iso_week(dt=None):
    from datetime import datetime, timezone
    dt = dt or datetime.now(timezone.utc)
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _read_text(path, limit=4000):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()[:limit]
    except Exception:
        return ""


def _gather():
    """รวม data จริงที่ป้อน LLM (compact). ไม่เรียก LLM."""
    ctx = {}
    # 1. ปฏิทินสัปดาห์นี้ (ForexFactory 7 วัน, high/med)
    try:
        from connectors.web_news import fetch_forexfactory_calendar
        evs = fetch_forexfactory_calendar(hours_ahead=168, include_all_us=True) or []
        ctx["calendar"] = [{"title": e.get("title"), "country": e.get("country"),
                            "date": e.get("date"), "impact": e.get("impact"),
                            "forecast": e.get("forecast"), "previous": e.get("previous")}
                           for e in evs[:40]]
    except Exception as e:
        ctx["calendar"] = []
        logger.debug(f"[weekly] calendar: {e}")
    # 2. event_scenarios (hot/cool→ทอง จริง) — grounding ของ scenario
    sc = _read_json(os.path.join(_BASE, "data", "event_scenarios.json"), {})
    ctx["event_scenarios"] = sc.get("scenarios", {})
    # 3. news sentiment ปัจจุบัน
    ni = _read_json(os.path.join(_BASE, "data", "news_impact.json"), {})
    ctx["news_sentiment"] = ni.get("aggregate", {})
    ctx["recent_headlines"] = [h.get("title") for h in (ni.get("scored") or [])[:12] if h.get("title")]
    # 4. macro regime stance (ไฟล์ที่ analyst ใช้)
    ctx["macro_regime"] = _read_text(os.path.join(_BASE, "agents", "prompts", "macro_regime.md"), 3000)
    # 5. COT positioning
    cot = _read_json(os.path.join(_BASE, "data", "cot.json"), {})
    ctx["cot"] = {k: cot.get(k) for k in ("net_position", "net_change", "label", "updated") if k in cot}
    # 6. ราคาทองล่าสุด
    try:
        import MetaTrader5 as mt5
        import config as _cfg
        t = mt5.symbol_info_tick(_cfg.SYMBOL)
        ctx["gold_price"] = round(float(t.bid), 2) if t else None
    except Exception:
        ctx["gold_price"] = None
    return ctx


_PROMPT = """คุณคือนักวิเคราะห์ตลาดทองคำ (XAUUSD) มืออาชีพ เขียนภาษาไทย.
วิเคราะห์ "แนวโน้มประจำสัปดาห์" จากข้อมูลจริงด้านล่าง — กระชับ ตรงประเด็น ใช้ได้จริงสำหรับเทรดเดอร์.

ข้อมูล (JSON):
{context}

เขียนเป็น Markdown ตามหัวข้อนี้ (ห้ามเพิ่มหัวข้ออื่น):

## 📅 สรุปสัปดาห์ที่แล้ว
2-4 บรรทัด: เกิดอะไร ข่าว/ตัวเลขสำคัญ ราคาทองตอบสนองยังไง (จาก sentiment + headlines + macro_regime)

## 🎯 ทิศทาง & Bias สัปดาห์นี้
ทิศทางหลักที่น่าจะเป็น (ขึ้น/ลง/sideways) + เหตุผลจาก macro_regime + COT + sentiment. ระบุความมั่นใจ (สูง/กลาง/ต่ำ)

## 🗓️ ปฏิทิน & Scenario สัปดาห์นี้
ต่อ event สำคัญใน calendar: วันเวลา + ถ้าเลข hot→ทองไปทางไหน / cool→ทองไปทางไหน
**ใช้ตัวเลขจาก event_scenarios ที่ให้มา** (magnitude% + n) เป็นหลัก อย่าเดาเอง. ถ้า event ไหนไม่มีใน scenarios บอกว่า "ไม่มีสถิติ"

## ⚠️ เฝ้าระวัง (Risk Factors)
ปัจจัยที่ต้องระวังสัปดาห์นี้ตาม sentiment (geopolitics/Fed/DXY/yields ฯลฯ) — bullet สั้นๆ

## 🔍 Macro ที่ต้องติดตาม
ตัวชี้วัด/ธีม macro ที่ควรจับตาต่อเนื่อง (ไม่ใช่แค่สัปดาห์นี้) — bullet สั้นๆ

จบด้วยประโยคเดียว: **สรุป 1 บรรทัด** สำหรับสัปดาห์นี้.
"""


_BUILDING = {"on": False}                                # กัน Opus รันซ้อน (poll หลายรอบ)


def build(force=False):
    """สร้าง/คืน weekly outlook. cache ต่อ ISO-week (ไม่ force = ใช้ cache ถ้าสัปดาห์เดิม). คืน dict."""
    wk = _iso_week()
    cached = _read_json(_CACHE)
    if not force and cached and cached.get("week") == wk and cached.get("markdown"):
        return cached
    if _BUILDING["on"]:                                  # กำลังสร้างอยู่ (thread อื่น) → คืน cache/generating
        return {**(cached or {"ok": False}), "generating": True}
    _BUILDING["on"] = True
    try:
        from langchain_anthropic import ChatAnthropic
        import config as _cfg
        ctx = _gather()
        llm = ChatAnthropic(model=_MODEL, api_key=_cfg.ANTHROPIC_API_KEY,
                            max_tokens=2200, temperature=0.4, timeout=90)
        msg = _PROMPT.format(context=json.dumps(ctx, ensure_ascii=False)[:14000])
        resp = llm.invoke(msg)
        md = resp.content if isinstance(resp.content, str) else str(resp.content)
        from datetime import datetime, timezone
        out = {"ok": True, "week": wk, "markdown": md,
               "generated": datetime.now(timezone.utc).isoformat()[:16] + "Z",
               "model": _MODEL, "n_events": len(ctx.get("calendar", []))}
        try:
            os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
            with open(_CACHE, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        logger.info(f"[weekly] outlook สร้างใหม่ ({wk}, {out['n_events']} events, {_MODEL})")
        return out
    except Exception as e:
        logger.warning(f"[weekly] build fail: {e}")
        if cached:
            return {**cached, "stale": True}
        return {"ok": False, "error": str(e)[:200]}
    finally:
        _BUILDING["on"] = False


def get_cached():
    """คืน cache (0 token). None ถ้ายังไม่มี."""
    return _read_json(_CACHE)


def tick():
    """auto: สร้างครั้งแรกของสัปดาห์ใหม่ (เรียกจาก loop/dashboard). ไม่ force. fail-soft."""
    try:
        cached = _read_json(_CACHE)
        if cached and cached.get("week") == _iso_week():
            return None                                  # มีของสัปดาห์นี้แล้ว
        return build(force=False)
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa
    force = len(sys.argv) > 1 and sys.argv[1] == "force"
    r = build(force=force)
    print(r.get("markdown", r) if r.get("ok") else r)
