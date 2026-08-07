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
    """ISO week ตาม **เวลาเครื่อง (local)** — ขอบสัปดาห์ = จันทร์ท้องถิ่น.
    เดิมใช้ UTC → จันทร์เช้าไทย (UTC+7) ยังเป็นอาทิตย์ใน UTC → บทวิเคราะห์ roll สัปดาห์ช้า 7 ชม.
    (bot รันเครื่อง user เดียว → local = โซนผู้ใช้). ตั้ง WEEKLY_OUTLOOK_UTC=true เพื่อกลับไปใช้ UTC."""
    from datetime import datetime, timezone
    if dt is None:
        dt = datetime.now(timezone.utc) if os.getenv("WEEKLY_OUTLOOK_UTC", "").lower() == "true" else datetime.now()
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
    try:                                                 # ensure MT5 (standalone/auto-tick ไม่มี init → gold data null)
        from connectors.price_feed import connect_mt5, is_mt5_connected
        if not is_mt5_connected():
            connect_mt5()
    except Exception:
        pass
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
    ctx["recent_headlines"] = [h.get("title") for h in (ni.get("scored") or [])[:20] if h.get("title")]
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
                    "events": (wm.get("events") or [])[:12],
                    "headlines": [h.get("title") if isinstance(h, dict) else h
                                  for h in (wm.get("headlines") or [])[:16]]}
    # 12. event reliability + baseline
    es = _read_json(os.path.join(_BASE, "data", "event_stats.json"), {})
    ctx["event_baseline_abs_pct"] = es.get("baseline_avg_abs_pct")
    ic = _read_json(os.path.join(_BASE, "data", "impact_calibration.json"), {})
    ctx["news_reliability"] = {"status": ic.get("status"), "tiers": ic.get("tiers")}
    return ctx


def _week_bars():
    """W1 bars จาก MT5 → last_week / this_week เลือกด้วย **วันที่จริง** (จันทร์ของสัปดาห์) เทียบสัปดาห์ปัจจุบัน
    (local) ไม่ใช่ index — กันเคสแท่งสัปดาห์ใหม่ยังไม่ก่อ → last_week ชี้ผิดสัปดาห์ (เช่นเห็น 19 ก.ค.).
    broker W1 เปิดวันอาทิตย์ → เลื่อนเป็นจันทร์ของสัปดาห์นั้น. label = ช่วง จ.–ศ. ให้ LLM อ้างวันถูก."""
    try:
        import MetaTrader5 as mt5
        import config as _cfg
        from connectors.price_feed import get_ohlcv
        from datetime import datetime, timezone, timedelta, date
        r = get_ohlcv(_cfg.SYMBOL, mt5.TIMEFRAME_W1, 6)
        if r is None or len(r) < 2:
            return {}
        today = datetime.now()                                       # local (ตรงกับ _iso_week)
        cur_mon = (today - timedelta(days=today.weekday())).date()   # จันทร์สัปดาห์นี้

        def _wk(x):
            o, h, l, c = float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])
            bd = datetime.fromtimestamp(int(x["time"]), timezone.utc).date()
            mon = bd + timedelta(days=(0 - bd.weekday()) % 7)        # อาทิตย์(เปิด)→จันทร์สัปดาห์นั้น
            return {"week_of": f"{mon:%Y-%m-%d}(จ.)–{mon + timedelta(days=4):%Y-%m-%d}(ศ.)",
                    "monday": mon.isoformat(),
                    "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2),
                    "pct_chg": round((c - o) / o * 100, 2) if o else None}
        bars = [_wk(x) for x in r]
        by_mon = {date.fromisoformat(b["monday"]): b for b in bars}
        this_wk = by_mon.get(cur_mon)
        last_wk = by_mon.get(cur_mon - timedelta(days=7))
        if last_wk is None:                                          # fallback: สัปดาห์ที่ปิดล่าสุดก่อนสัปดาห์นี้
            prev = [b for b in bars if date.fromisoformat(b["monday"]) < cur_mon]
            last_wk = prev[-1] if prev else None
        return {k: v for k, v in {"last_week": last_wk, "this_week": this_wk}.items() if v}
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


_SYSTEM = """You are a senior ECONOMICS JOURNALIST and gold-market expert writing a weekly analysis
column for a general audience interested in gold (not a trader's dashboard). 15+ years in macro + geopolitics.

OUTPUT LANGUAGE: write the ENTIRE article in THAI (natural, fluent Thai prose). These instructions are
in English; the article you produce is in Thai. Keep the Thai section headings from the user prompt exactly.

Goal: make the reader understand WHAT happened and WHY — a coherent cause-and-effect narrative, easy to
read, not a pile of numbers.

Writing principles (most important — the reader must understand):
- Plain-language storytelling; explain the "why" before any number. Turn raw data into meaning: write the
  Thai equivalent of "the dollar strengthened and pressured gold", NOT "DXY +0.8%, real_yield 0.1%".
- NEVER print variable/field names or bare values (real_yield, COT net_position, risk_regime.vix,
  drivers.DXY). The reader doesn't know them. Use a number only when it helps the picture, always with
  context (e.g. "gold closed at $4,052, up 1.3%").
- Briefly gloss unavoidable technical terms (real yield, safe-haven) in parentheses on first use.
- Be specific with real event names/figures when narrating news; no vague filler ("structural factors").
- Active voice; vary sentence length; NO em-dash; cut throat-clearing ("overall", "in summary").
- News/geopolitics sections: substantive narrative paragraphs (event + mechanism to gold), not terse bullets.
- Use ONLY the real data provided (calendar/scenarios/news/macro/COT/world) — never invent numbers or events.
- ALWAYS anchor to the "target week" (Mon–Sun window) stated at the top of the prompt; analyse only that week."""

_PROMPT = """Real data for analysis (JSON):
{context}

Write in Markdown using EXACTLY these Thai headings, in this order (do not add, remove, reorder, or
translate the headings). Write ALL body text in Thai.

## 📅 สรุปข่าว & ตลาดสัปดาห์ที่แล้ว
(4-6 lines) Recap last week's key news / data / geopolitical events and how gold reacted, plus the main
driver (Fed / dollar / safe-haven). Use ONLY gold_tech.last_week for prices (open/close/high/low/pct),
never this_week. Cite dates ONLY from gold_tech.last_week.week_of (Mon–Fri range) — do not guess or
compute dates. Reference real recent_headlines + world.headlines.

## 🌍 ภูมิรัฐศาสตร์ & Safe-Haven
(3-5 substantive lines) Geopolitical factors moving gold now (from world.events/headlines/attention):
what happened, tension level and direction (easing/rising), and the MECHANISM to gold (safe-haven bid,
central-bank buying, oil→inflation).

## 🎯 ทิศทาง & Bias สัปดาห์นี้
Main direction (up/down/sideways) + confidence (high/medium/low) with reasons in plain prose (paragraphs,
not a value dump):
- Are the US dollar and Treasury yields supporting or pressuring gold — explain why (use
  drivers/macro_strip/regime_state as EVIDENCE, but never show field names or bare values; add a number
  only with context).
- Fed stance & inflation, institutional/fund positioning (from COT), market risk mood, and the direction
  of silver — which way each pushes gold and why.
- Technical picture: where gold sits in its range, near which key support/resistance (use real prices from
  gold_tech.this_week + daily).

## 🤖 แนะนำเปิด Algo สัปดาห์นี้
จาก ALGO ROSTER ข้างล่าง แนะนำว่าควรเปิด (enable) algo ไหนบ้างให้เหมาะกับ bias/regime ของสัปดาห์นี้ + ระบุทิศ
(สำหรับ tsmom_d1: long / short / both) พร้อมเหตุผลสั้นๆ ภาษาชาวบ้าน. ยึด domain ของแต่ละ algo; ตัวไหนไม่เข้าสภาพ
ตลาดสัปดาห์นี้ให้บอก "พัก (stand down)". เขียนเป็น bullet สั้น algo ละบรรทัด.
ALGO ROSTER (✅=+EV backtest, LIVE ได้ · ⚠️=อ่อน/−EV):
✅ macro_momentum (ทอง H4: breakout + DXY/EURUSD ยืนยันทิศ + sentiment · เข้าจุดสำคัญ ไม่สวน macro) ·
✅ confluence_15m (ทอง M15 NY-session: breakout + H1+H4+DXY + volume surge · scalp คุณภาพสูง ถี่) ·
✅ xau_xag_pairs (stat-arb 2-leg XAU-XAG spread z-fade · market-neutral · WR57%) ·
✅ tsmom_d1 (time-series momentum D1 · 21/63/126 + short-term confirm; long/short/both) ·
⚠️ regime_momentum (momentum breakout · TREND; ทอง H1 อ่อน, BTC H4 +EV) ·
⚠️ regime_momentum_fvg (momentum+FVG · TREND; −EV) · mean_reversion (z-fade · RANGE; CUT −EV) ·
sweep_reversal (fade ไฮ/โลว์วันก่อน · RANGE/NEUTRAL; −EV).

## 🗓️ ปฏิทิน & Scenario สัปดาห์นี้
For each key event in calendar: date/time + hot→gold direction / cool→gold direction. Base magnitudes on
event_scenarios (magnitude% + n) — do not guess; if an event has no stats, say "ไม่มีสถิติ". Convey the
statistic's reliability from n as a Thai WORD, never the raw count or "n=": n≥100 → "ความน่าเชื่อถือสูง",
30–100 → "ปานกลาง", <30 → "ต่ำ (ตัวอย่างน้อย)".

## ⚠️ เฝ้าระวัง (Risk Factors)
This week's risks — bullets + short reason: geopolitics (world) + market risk mood + major calendar events.

## 🔍 Macro ที่ต้องติดตาม
Ongoing macro themes (Fed path, real yield, dollar trend, CPI, central-bank gold buying) — bullets.

End with: a one-line **สรุป** (summary) for this week, in Thai.
"""


import threading as _threading
_BUILD_LOCK = _threading.Lock()                          # atomic check-and-set (กัน Opus รันซ้อน = เงินจริง)
_BUILDING = {"on": False}                                # กัน Opus รันซ้อน (poll หลายรอบ)


def build(force=False):
    """สร้าง/คืน weekly outlook. cache ต่อ ISO-week (ไม่ force = ใช้ cache ถ้าสัปดาห์เดิม). คืน dict."""
    wk = _iso_week()
    cached = _read_json(_CACHE)
    if not force and cached and cached.get("week") == wk and cached.get("markdown"):
        return cached
    with _BUILD_LOCK:                                    # check-then-set ต้อง atomic (2 thread ยิง Opus พร้อมกันไม่ได้)
        if _BUILDING["on"]:                              # กำลังสร้างอยู่ (thread อื่น) → คืน cache/generating
            return {**(cached or {"ok": False}), "generating": True}
        _BUILDING["on"] = True
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import SystemMessage, HumanMessage
        import config as _cfg
        ctx = _gather()
        _maxtok = int(os.getenv("WEEKLY_OUTLOOK_MAX_TOKENS") or 6000)   # cap (ไม่ใช่ cost); +geopolitics section = ยาวขึ้น
        llm = ChatAnthropic(model=_MODEL, api_key=_cfg.ANTHROPIC_API_KEY,
                            max_tokens=_maxtok, timeout=120)   # ไม่ตั้ง temperature — Opus 4.8 deprecated
        from datetime import datetime as _dt, timedelta as _td
        _now = _dt.now()                                   # local — ขอบสัปดาห์จันทร์ท้องถิ่น (ตรงกับ _iso_week)
        _mon = _now - _td(days=_now.weekday()); _sun = _mon + _td(days=6)
        _whdr = (f"Target week to analyse: **{wk}** (Mon {_mon:%Y-%m-%d} to Sun {_sun:%Y-%m-%d}). "
                 f"Write this week's outlook for this window only; 'last week' = the preceding Monday. "
                 f"Write the entire output in Thai.\n\n")
        user_msg = _whdr + _PROMPT.format(context=json.dumps(ctx, ensure_ascii=False)[:60000])   # กว้าง — Opus รับได้เยอะ
        resp = llm.invoke([SystemMessage(content=_SYSTEM), HumanMessage(content=user_msg)])
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
