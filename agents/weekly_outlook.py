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
_MODEL = os.getenv("WEEKLY_OUTLOOK_MODEL", "claude-opus-4-8")   # env-override เผื่อ model id เปลี่ยน


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
        # High/Medium เท่านั้น (ตัวขยับทอง; ไม่เอา US Low รก). web_news มี memory+disk cache กัน 429 แล้ว
        evs = fetch_forexfactory_calendar(hours_ahead=168, include_all_us=False) or []
        ctx["calendar"] = [{"title": e.get("title"), "currency": e.get("currency"),
                            "when": e.get("timestamp_iso"), "impact": e.get("impact"),
                            "forecast": e.get("forecast"), "previous": e.get("previous")}
                           for e in evs[:40]]
        if not ctx["calendar"]:
            logger.warning("[weekly] calendar ว่าง (ForexFactory ไม่ตอบ) — outlook จะใช้ cadence แทน")
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
    # 7. macro strip (DXY/10y yield/real yield) — backdrop มหภาค
    ms = _read_json(os.path.join(_BASE, "data", "macro_strip.json"), {})
    ctx["macro_strip"] = {k: ms.get(k) for k in ("dxy", "y10", "real_yield", "updated") if k in ms}
    # 8. regime + risk-on/off
    rs = _read_json(os.path.join(_BASE, "data", "regime_state.json"), {})
    ctx["regime_state"] = {k: rs.get(k) for k in
                           ("fed_dir", "real_rate_sign", "sentiment_tilt", "cpi_yoy", "fed_funds", "real_rate", "shift") if k in rs}
    rr = _read_json(os.path.join(_BASE, "data", "risk_regime_now.json"), {})
    ctx["risk_regime"] = {k: rr.get(k) for k in ("regime", "vix", "gold_ctx_yr") if k in rr}
    # 9. cross-asset drivers: DXY(UUP proxy) + silver — % เปลี่ยน 5 วัน (H1 ~120 บาร์) = ทิศทาง
    ctx["drivers"] = {"DXY": _ohlc_sum(_read_json(os.path.join(_BASE, "data", "drv_dxy_h1.json"), [])),
                      "silver": _ohlc_sum(_read_json(os.path.join(_BASE, "data", "drv_xag_h1.json"), []))}
    # 10. เทคนิคทองเอง: ดึง MT5 สด (xau_*.json อาจ stale). แยก last_week (W1[-2] ปิดแล้ว = สรุปสัปดาห์ที่แล้ว)
    #     vs this_week (W1[-1] = สัปดาห์นี้) + D1 10 วัน. **สำคัญ: last_week ≠ this_week (กัน LLM สรุปผิดสัปดาห์)**
    ctx["gold_tech"] = {**_week_bars(), "daily": _mt5_tf_sum("D1", 10)}
    # 11. worldmonitor (ภูมิรัฐศาสตร์/ความเสี่ยงโลก) → เฝ้าระวัง
    wm = _read_json(os.path.join(_BASE, "data", "worldmonitor.json"), {})
    ctx["world"] = {"attention": wm.get("attention"),
                    "events": (wm.get("events") or [])[:6],
                    "headlines": [h.get("title") if isinstance(h, dict) else h
                                  for h in (wm.get("headlines") or [])[:8]]}
    # 12. event reliability + baseline
    es = _read_json(os.path.join(_BASE, "data", "event_stats.json"), {})
    ctx["event_baseline_abs_pct"] = es.get("baseline_avg_abs_pct")
    ic = _read_json(os.path.join(_BASE, "data", "impact_calibration.json"), {})
    ctx["news_reliability"] = {"status": ic.get("status"), "tiers": ic.get("tiers")}
    return ctx


def _week_bars():
    """W1 bars จาก MT5 → last_week (บาร์ปิดล่าสุด = สัปดาห์ที่แล้ว) + this_week (บาร์ปัจจุบัน).
    pct_chg = (close−open)/open ต่อสัปดาห์. กัน LLM สรุปสัปดาห์ที่แล้วด้วยข้อมูลสัปดาห์นี้."""
    try:
        import MetaTrader5 as mt5
        import config as _cfg
        from connectors.price_feed import get_ohlcv
        from datetime import datetime, timezone
        r = get_ohlcv(_cfg.SYMBOL, mt5.TIMEFRAME_W1, 4)
        if r is None or len(r) < 2:
            return {}

        def _bar(x):
            o, h, l, c = float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])
            return {"date": datetime.fromtimestamp(int(x["time"]), timezone.utc).strftime("%Y-%m-%d"),
                    "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2),
                    "pct_chg": round((c - o) / o * 100, 2) if o else None}
        return {"last_week": _bar(r[-2]), "this_week": _bar(r[-1])}
    except Exception:
        return {}


def _mt5_tf_sum(tf, n=10):
    """สรุปกรอบทองจาก MT5 สด (แม่นกว่า xau_*.json ที่อาจ stale). tf='D1'/'W1'/'H4'. None ถ้าดึงไม่ได้."""
    try:
        import MetaTrader5 as mt5
        import config as _cfg
        from connectors.price_feed import get_ohlcv
        tfmap = {"H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1}
        r = get_ohlcv(_cfg.SYMBOL, tfmap.get(tf, mt5.TIMEFRAME_D1), n + 2)
        if r is None or len(r) < 3:
            return None
        arr = [[int(x["time"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), 0] for x in r]
        s = _ohlc_sum(arr, n)
        if s:
            s["last_bar"] = None
            try:
                from datetime import datetime, timezone
                s["last_bar"] = datetime.fromtimestamp(int(r[-1]["time"]), timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                pass
        return s
    except Exception:
        return None


def _ohlc_sum(arr, n=10):
    """สรุป OHLC array [[ts,o,h,l,c,v],...] → last/high/low/%chg/atr (compact, กัน token). None ถ้าว่าง."""
    try:
        if not arr or len(arr) < 3:
            return None
        seg = arr[-max(n, 3):]
        closes = [float(r[4]) for r in seg]
        highs = [float(r[2]) for r in seg]
        lows = [float(r[3]) for r in seg]
        last = closes[-1]
        ref = closes[0]
        trs = [highs[i] - lows[i] for i in range(len(seg))]
        atr = round(sum(trs) / len(trs), 3)
        return {"last": round(last, 3), "high": round(max(highs), 3), "low": round(min(lows), 3),
                "pct_chg": round((last - ref) / ref * 100, 2) if ref else None, "atr": atr, "bars": len(seg)}
    except Exception:
        return None


_PROMPT = """คุณคือนักวิเคราะห์ตลาดทองคำ (XAUUSD) มืออาชีพ เขียนภาษาไทย.
วิเคราะห์ "แนวโน้มประจำสัปดาห์" จากข้อมูลจริงด้านล่าง — กระชับ ตรงประเด็น ใช้ได้จริงสำหรับเทรดเดอร์.

ข้อมูล (JSON):
{context}

เขียนเป็น Markdown ตามหัวข้อนี้ (ห้ามเพิ่มหัวข้ออื่น):

## 📅 สรุปสัปดาห์ที่แล้ว
2-4 บรรทัด: เกิดอะไร ข่าว/ตัวเลขสำคัญ ราคาทองตอบสนองยังไง.
**ใช้ราคาจาก gold_tech.last_week (open/close/high/low/pct_chg ของสัปดาห์ที่ปิดแล้ว) เท่านั้น — ห้ามใช้ this_week**

## 🎯 ทิศทาง & Bias สัปดาห์นี้
ทิศทางหลักที่น่าจะเป็น (ขึ้น/ลง/sideways) + ระบุความมั่นใจ (สูง/กลาง/ต่ำ). อ้างอิงข้อมูลจริงที่ให้:
- **DXY/ดอลลาร์** (drivers.DXY %chg, macro_strip.dxy) — ดอลลาร์แข็ง = กดทอง (inverse)
- **real yield / 10y** (macro_strip.real_yield/y10, regime_state.real_rate_sign) — real yield ขึ้น = ลบต่อทอง
- **Fed/CPI stance** (regime_state.fed_dir/cpi_yoy/fed_funds) · **COT** positioning · **news sentiment**
- **regime/risk** (risk_regime.regime/vix) · **เงิน** (drivers.silver) ยืนยันโลหะ
- **เทคนิคทอง** (gold_tech.this_week + daily high/low): ทองสัปดาห์นี้อยู่โซนไหน ใกล้แนวรับ/ต้านไหน (ใช้ this_week ไม่ใช่ last_week)

## 🗓️ ปฏิทิน & Scenario สัปดาห์นี้
ต่อ event สำคัญใน calendar: วันเวลา + ถ้าเลข hot→ทองไปทางไหน / cool→ทองไปทางไหน
**ใช้ตัวเลขจาก event_scenarios ที่ให้มา** (magnitude% + n) เป็นหลัก อย่าเดาเอง. ถ้า event ไหนไม่มีใน scenarios บอกว่า "ไม่มีสถิติ"

## ⚠️ เฝ้าระวัง (Risk Factors)
ปัจจัยที่ต้องระวังสัปดาห์นี้ — bullet สั้นๆ. ใช้ world.events/headlines (ภูมิรัฐศาสตร์) + risk_regime.vix + event ใหญ่ในปฏิทิน

## 🔍 Macro ที่ต้องติดตาม
ตัวชี้วัด/ธีม macro ที่ควรจับตาต่อเนื่อง (Fed path, real yield, DXY trend, CPI จาก regime_state) — bullet สั้นๆ

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
        # limit สูง (ยังไม่จำกัดจริง) — วัด token จริงก่อน ค่อยตั้ง limit (max_tokens env-override ได้)
        _maxtok = int(os.getenv("WEEKLY_OUTLOOK_MAX_TOKENS") or 6000)   # วัดจริง out~2261 → 6000 = headroom พอ (cap ไม่ใช่ cost)
        llm = ChatAnthropic(model=_MODEL, api_key=_cfg.ANTHROPIC_API_KEY,
                            max_tokens=_maxtok, timeout=120)   # ไม่ตั้ง temperature — Opus 4.8 deprecated
        msg = _PROMPT.format(context=json.dumps(ctx, ensure_ascii=False)[:60000])   # กว้าง — Opus รับได้เยอะ
        resp = llm.invoke(msg)
        md = resp.content if isinstance(resp.content, str) else str(resp.content)
        usage = getattr(resp, "usage_metadata", None) or {}
        tin, tout = usage.get("input_tokens"), usage.get("output_tokens")
        from datetime import datetime, timezone
        out = {"ok": True, "week": wk, "markdown": md,
               "generated": datetime.now(timezone.utc).isoformat()[:16] + "Z",
               "model": _MODEL, "n_events": len(ctx.get("calendar", [])),
               "tokens_in": tin, "tokens_out": tout, "ctx_chars": len(json.dumps(ctx, ensure_ascii=False))}
        logger.info(f"[weekly] tokens: in={tin} out={tout} (max={_maxtok}) ctx={out['ctx_chars']}ch")
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


def is_building():
    """กำลังสร้าง (Opus) อยู่ไหม — ให้ endpoint บอก frontend poll ต่อจนได้อันใหม่ (กันแสดง cache เก่าค้าง)."""
    return _BUILDING["on"]


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
