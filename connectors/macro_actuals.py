"""connectors/macro_actuals.py — ตัวเลขเศรษฐกิจ US "จริง" (actual) จาก AlphaVantage.

ForexFactory feed ให้แค่ forecast+previous (ไม่มี actual) → หลังประกาศตัวเลขไม่อัปเดต.
โมดูลนี้ดึง actual ของ US high-impact (CPI/NFP/Unemployment/Retail/GDP/Fed) จาก AV แล้ว
map เข้า calendar event ที่ "ประกาศแล้ว" (title keyword). free 25 call/วัน → cache รายวัน (1 batch = 6 call).

⚠️ US เท่านั้น (AV ไม่ครอบ EUR/GBP/JPY) · ไม่มี key → คืน {} (calendar ทำงานเหมือนเดิม, actual=pending).
0 LLM token. อ่านโดย connectors/web_news.fetch_forexfactory_calendar.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

from loguru import logger

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)                               # รันตรง (python connectors/macro_actuals.py) → หา config เจอ
_CACHE = os.path.join(_BASE, "data", "macro_actuals.json")
_CACHE_TTL = 12 * 3600     # refresh ทุก 12 ชม. (2 refresh/วัน × 5 series = 10 call < AV free 25/วัน)
_AV_URL = "https://www.alphavantage.co/query?function={fn}&interval={iv}&apikey={key}"

# AV function → interval. เฉพาะ indicator ที่ derive ตรงกับ calendar เชื่อถือได้
# (ตัด REAL_GDP: annualize จาก level ไม่ตรง FF = แสดงเลขผิด → ปล่อย pending ดีกว่า)
_SERIES = {
    "CPI": "monthly", "UNEMPLOYMENT": "monthly", "FEDERAL_FUNDS_RATE": "monthly",
    "RETAIL_SALES": "monthly", "NONFARM_PAYROLL": "monthly", "DURABLES": "monthly",
}


def _fetch_series(fn, iv, key):
    """ดึง time series ตัวหนึ่งจาก AV → list ของ (date, float) เรียงใหม่→เก่า. ว่างถ้า fail/rate-limit."""
    try:
        url = _AV_URL.format(fn=fn, iv=iv, key=key)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as res:
            d = json.loads(res.read().decode("utf-8"))
        rows = d.get("data") or []
        if not rows and ("Note" in d or "Information" in d):
            logger.warning(f"[macro_actuals] AV rate-limit/note ({fn}): {d.get('Note') or d.get('Information')}")
        out = []
        for r in rows:
            try:
                out.append((r["date"], float(r["value"])))
            except (KeyError, ValueError, TypeError):
                continue
        return out                                          # AV คืนเรียงใหม่→เก่าอยู่แล้ว
    except Exception as e:
        logger.warning(f"[macro_actuals] fetch {fn} fail: {e}")
        return []


def _pct(cur, prev):
    return round((cur / prev - 1.0) * 100, 1) if prev else None


def _derive(series):
    """แปลง raw AV series → ค่าที่ตรงกับ calendar (mom%/yoy%/change/level). คืน dict ต่อ indicator + release date."""
    out = {}
    cpi = series.get("CPI") or []
    if len(cpi) >= 13:
        out["cpi_mom"] = (f"{_pct(cpi[0][1], cpi[1][1]):+.1f}%", cpi[0][0])
        out["cpi_yoy"] = (f"{_pct(cpi[0][1], cpi[12][1]):+.1f}%", cpi[0][0])
    un = series.get("UNEMPLOYMENT") or []
    if un:
        out["unemployment"] = (f"{un[0][1]:.1f}%", un[0][0])
    ff = series.get("FEDERAL_FUNDS_RATE") or []
    if ff:
        out["fed_funds"] = (f"{ff[0][1]:.2f}%", ff[0][0])
    rs = series.get("RETAIL_SALES") or []
    if len(rs) >= 2:
        out["retail_mom"] = (f"{_pct(rs[0][1], rs[1][1]):+.1f}%", rs[0][0])
    nf = series.get("NONFARM_PAYROLL") or []
    if len(nf) >= 2:
        chg = nf[0][1] - nf[1][1]                            # การเปลี่ยนแปลง (พันคน)
        out["nfp"] = (f"{chg:+,.0f}K", nf[0][0])
    du = series.get("DURABLES") or []
    if len(du) >= 2:
        out["durables_mom"] = (f"{_pct(du[0][1], du[1][1]):+.1f}%", du[0][0])
    return out


# title keyword (lower) → derived key. ตรวจตามลำดับ (เฉพาะเจาะจงก่อน)
_MATCH = [
    # None = จับ keyword ก่อน แต่ปล่อย pending (กันแสดงเลขผิด: core/ADP = คนละ series ที่ AV ไม่มี)
    ("core cpi", None),                                     # AV ไม่มี core CPI
    ("cpi y/y", "cpi_yoy"), ("cpi m/m", "cpi_mom"), ("cpi", "cpi_mom"),
    ("unemployment rate", "unemployment"),
    ("federal funds", "fed_funds"),                         # ตัวเลขอัตราจริง (FOMC Statement = ข้อความ ไม่ map)
    ("adp", None),                                          # ADP = private payrolls คนละรายงานกับ BLS NFP
    ("non-farm", "nfp"), ("nonfarm", "nfp"), ("nfp", "nfp"),
    ("core retail", None), ("retail sales", "retail_mom"),
    ("core durable", None), ("durable goods", "durables_mom"),   # AV DURABLES = headline (core=ex-transport ไม่มี → pending)
]


def _load_cache():
    try:
        with open(_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_actuals():
    """คืน dict {derived_key: (value_str, release_date)} ของ US actuals ล่าสุด. cache รายวัน.
    ไม่มี ALPHAVANTAGE_API_KEY → {} (calendar เหมือนเดิม)."""
    try:
        import config
        key = getattr(config, "ALPHAVANTAGE_API_KEY", "") or ""
    except Exception:
        key = ""
    if not key:
        return {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache = _load_cache()
    if cache.get("actuals") and time.time() - cache.get("ts", 0) < _CACHE_TTL:
        return {k: tuple(v) for k, v in cache["actuals"].items()}   # cache สด (< TTL) → actual ล่าสุดโผล่ภายใน TTL หลังประกาศ
    # refresh: ดึงทุก series → derive → cache. เว้น ≥1 วิ/call (AV free burst = 1 req/sec)
    series = {}
    for i, (fn, iv) in enumerate(_SERIES.items()):
        if i:
            time.sleep(1.3)
        series[fn] = _fetch_series(fn, iv, key)
    if not any(series.values()):                            # ดึงไม่ได้เลย (rate-limit/เน็ต) → ใช้ cache เก่า (ถ้ามี)
        return {k: tuple(v) for k, v in (cache.get("actuals") or {}).items()}
    actuals = _derive(series)
    try:
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        with open(_CACHE, "w", encoding="utf-8") as f:
            json.dump({"date": today, "actuals": actuals, "ts": time.time()}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    logger.info(f"[macro_actuals] refresh AV actuals: {len(actuals)} indicators")
    return actuals


def actual_for(title, actuals=None):
    """title ของ calendar event → (value_str, release_date) ถ้า match US indicator, ไม่งั้น None.
    actuals: ส่ง dict จาก get_actuals() มาใช้ซ้ำ (กันเรียกซ้ำต่อ event)."""
    if actuals is None:
        actuals = get_actuals()
    if not actuals:
        return None
    t = (title or "").lower()
    for kw, dkey in _MATCH:
        if kw in t:
            if dkey is None:                                # จับ core* ก่อน → ไม่มีข้อมูล → pending (ไม่แสดงผิด)
                return None
            return actuals.get(dkey)
    return None


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import config  # noqa
    a = get_actuals()
    print(f"US actuals ({len(a)}):")
    for k, v in a.items():
        print(f"  {k:14s} = {v[0]:>10s}  (release {v[1]})")
