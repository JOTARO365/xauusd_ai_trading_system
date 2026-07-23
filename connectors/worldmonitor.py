"""connectors/worldmonitor.py — live geopolitical/gold-signal ingestion จาก GDELT (ฟรี ไม่ต้อง key).

WorldMonitor ดึง conflict/geopolitical จาก GDELT (Global event DB) — เราดึง upstream เดียวกันตรง.
pull gold-relevant geopolitical headlines → attention/risk score + per-country geo → data/worldmonitor.json.
feed: dashboard globe (live risk dots) + SELECTION/risk layer. cache 30 นาที (กัน rate-limit), fail-soft, 0 token.
⚠️ SELECTION/context เท่านั้น — ไม่ใช่ entry signal (direction ไม่มี edge). GDELT = attention/risk proxy ไม่ใช่ทิศ.
"""
import json
import os
import time
import urllib.parse
import urllib.request

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT = os.path.join(_BASE, "data", "worldmonitor.json")
_TTL = 1800          # 30 นาที cache (GDELT free = rate-limited)
_QUERY = 'gold (conflict OR sanctions OR war OR "central bank" OR "safe haven" OR geopolitical)'

# GDELT sourcecountry (ชื่อ) → พิกัดคร่าว (สำหรับ globe). gold-relevant + major.
_CC = {
    "United States": (38.9, -77.0), "United Kingdom": (51.5, -0.1), "China": (39.9, 116.4),
    "Russia": (55.8, 37.6), "Iran": (35.7, 51.4), "Israel": (31.8, 35.2), "Ukraine": (50.4, 30.5),
    "Japan": (35.7, 139.7), "India": (28.6, 77.2), "Germany": (52.5, 13.4), "France": (48.9, 2.4),
    "Switzerland": (46.9, 7.4), "United Arab Emirates": (24.5, 54.4), "Saudi Arabia": (24.7, 46.7),
    "Turkey": (39.9, 32.9), "Taiwan": (25.0, 121.6), "Hong Kong": (22.3, 114.2), "Singapore": (1.35, 103.8),
    "South Korea": (37.6, 127.0), "Australia": (-35.3, 149.1), "Canada": (45.4, -75.7), "Egypt": (30.0, 31.2),
    "Yemen": (15.4, 44.2), "Syria": (33.5, 36.3), "Iraq": (33.3, 44.4), "North Korea": (39.0, 125.8),
    "Venezuela": (10.5, -66.9), "Brazil": (-15.8, -47.9), "South Africa": (-25.7, 28.2),
}


def _fresh():
    try:
        return (time.time() - os.path.getmtime(_OUT)) < _TTL
    except Exception:
        return False


def refresh(force=False):
    """pull GDELT → เขียน data/worldmonitor.json. คืน dict. cache TTL, fail-soft (error → เก็บของเก่า ok=False)."""
    if not force and _fresh():
        try:
            return json.load(open(_OUT, encoding="utf-8"))
        except Exception:
            pass
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode({
        "query": _QUERY, "mode": "artlist", "format": "json",
        "maxrecords": "60", "sort": "datedesc", "timespan": "48h"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 xauusd-bot"})
        with urllib.request.urlopen(req, timeout=25) as r:
            arts = json.loads(r.read().decode()).get("articles", [])
    except Exception as e:
        prev = {}
        try:
            prev = json.load(open(_OUT, encoding="utf-8"))
        except Exception:
            pass
        prev.update({"ok": False, "error": str(e)[:80], "ts": int(time.time())})
        _write(prev)
        return prev
    # aggregate: per-country count → geo points; attention = จำนวน article; headlines ล่าสุด
    cc = {}
    for a in arts:
        c = a.get("sourcecountry") or ""
        if c in _CC:
            cc[c] = cc.get(c, 0) + 1
    mx = max(cc.values()) if cc else 1
    events = [{"name": c, "lat": _CC[c][0], "lng": _CC[c][1], "count": n,
               "sev": min(1.0, n / mx)} for c, n in sorted(cc.items(), key=lambda x: -x[1])]
    heads = [{"title": a.get("title", "")[:140], "domain": a.get("domain", ""),
              "country": a.get("sourcecountry", ""), "url": a.get("url", ""),
              "seen": a.get("seendate", "")} for a in arts[:12]]
    # attention/risk proxy: จำนวน article (24-48h) normalize (baseline ~30 = ปกติ)
    n = len(arts)
    out = {"ok": True, "ts": int(time.time()), "source": "GDELT", "n_articles": n,
           "attention": round(min(1.0, n / 60.0), 2), "events": events, "headlines": heads}
    _write(out)
    return out


def _write(d):
    try:
        with open(_OUT, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    d = refresh(force=True)
    print(f"ok={d.get('ok')} n_articles={d.get('n_articles')} attention={d.get('attention')} "
          f"events={len(d.get('events', []))}")
    for h in d.get("headlines", [])[:6]:
        print(f"  [{h['country'][:12]:12}] {h['title'][:80]}")
