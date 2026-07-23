"""connectors/worldmonitor.py — live geopolitical/gold-signal ingestion (ฟรี ไม่ต้อง key).

Primary : GDELT DOC (ให้ sourcecountry → map dots ตรง) — แต่ throttle IP ง่าย (429 ถ้ายิงถี่).
Fallback: Google News RSS (ทนกว่า, ฟรี, query gold ตรง) — derive geo จาก keyword ในพาดหัว.
เขียน data/worldmonitor.json → dashboard flat map (live risk dots) + ตารางข่าว + SELECTION/risk layer.
cache 30 นาที (กัน rate-limit), fail-soft, 0 token.
⚠️ SELECTION/context เท่านั้น — ไม่ใช่ entry signal (direction ไม่มี edge). = attention/risk proxy ไม่ใช่ทิศ.
"""
import email.utils
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT = os.path.join(_BASE, "data", "worldmonitor.json")
_TTL = 1800          # 30 นาที cache (ฟรี tier = rate-limited)
_UA = "Mozilla/5.0 xauusd-bot"
_QUERY = 'gold (conflict OR sanctions OR war OR "central bank" OR "safe haven" OR geopolitical)'
_GNEWS_Q = 'gold (safe haven OR geopolitical OR sanctions OR war OR central bank)'

# GDELT sourcecountry (ชื่อ) → พิกัดคร่าว (สำหรับ map). gold-relevant + major.
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

# keyword (lowercase) → (label, lat, lng) — derive geo จากพาดหัว (fallback ที่ไม่มี country field).
# ลำดับสำคัญ: เฉพาะเจาะจงก่อน (Hormuz/Red Sea) แล้วค่อยกว้าง (Middle East/US).
_GEO_KW = [
    (("hormuz", "strait of hormuz"), "Strait of Hormuz", 26.57, 56.25),
    (("red sea", "houthi", "yemen"), "Red Sea", 15.4, 44.2),
    (("iran", "tehran"), "Iran", 35.7, 51.4),
    (("israel", "gaza", "netanyahu", "idf"), "Israel", 31.8, 35.2),
    (("ukraine", "kyiv", "kiev", "zelensk"), "Ukraine", 50.4, 30.5),
    (("russia", "moscow", "putin", "kremlin"), "Russia", 55.8, 37.6),
    (("taiwan",), "Taiwan", 24.5, 119.5),
    (("china", "beijing", "pboc", "yuan"), "China", 39.9, 116.4),
    (("middle east", "mideast"), "Middle East", 29.0, 47.0),
    (("ecb", "euro zone", "eurozone"), "Euro Area", 50.1, 8.7),
    (("fed", "federal reserve", "powell", "fomc", "u.s.", "treasury", "dollar"), "United States", 38.9, -77.0),
]


def _fresh():
    try:
        return (time.time() - os.path.getmtime(_OUT)) < _TTL
    except Exception:
        return False


def _geo_from_title(title):
    """หา geo ที่พาดหัวพาดพิง (keyword แรกที่เจอ). คืน (label,lat,lng) หรือ None."""
    tl = title.lower()
    for kws, label, lat, lng in _GEO_KW:
        if any(kw in tl for kw in kws):
            return label, lat, lng
    return None


def _aggregate(geo_counts, headlines, n, source):
    """สร้าง output schema เดียวกันจาก per-geo count + headlines."""
    mx = max((v[1] for v in geo_counts.values()), default=1) or 1
    events = [{"name": lbl, "lat": ll[0], "lng": ll[1], "count": cnt, "sev": min(1.0, cnt / mx)}
              for lbl, (ll, cnt) in sorted(geo_counts.items(), key=lambda x: -x[1][1])]
    return {"ok": True, "ts": int(time.time()), "source": source, "n_articles": n,
            "attention": round(min(1.0, n / 60.0), 2), "events": events, "headlines": headlines[:12]}


def _try_gdelt():
    """GDELT DOC artlist — sourcecountry → geo ตรง. คืน dict (ok) หรือ None ถ้าพลาด."""
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode({
        "query": _QUERY, "mode": "artlist", "format": "json",
        "maxrecords": "60", "sort": "datedesc", "timespan": "48h"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            arts = json.loads(r.read().decode()).get("articles", [])
    except Exception:
        return None
    if not arts:
        return None
    geo = {}
    for a in arts:
        c = a.get("sourcecountry") or ""
        if c in _CC:
            geo.setdefault(c, [_CC[c], 0])[1] += 1
    heads = [{"title": a.get("title", "")[:140], "domain": a.get("domain", ""),
              "country": a.get("sourcecountry", ""), "url": a.get("url", ""),
              "seen": a.get("seendate", "")} for a in arts[:12]]
    return _aggregate(geo, heads, len(arts), "GDELT")


def _try_gnews():
    """Google News RSS — query gold ตรง, derive geo จาก keyword ในพาดหัว. คืน dict (ok) หรือ None."""
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": _GNEWS_Q + " when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=25) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return None
    items = root.findall(".//item")
    if not items:
        return None
    geo = {}
    heads = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        src = (src_el.text or "").strip() if src_el is not None else ""
        if src and title.endswith(" - " + src):          # Google ต่อ " - Source" ท้ายพาดหัว → ตัดออก
            title = title[:-(len(src) + 3)].strip()
        pub = it.findtext("pubDate") or ""
        seen = ""
        try:                                              # RFC822 → "YYYYMMDDTHHMMSSZ" (ให้ front-end parse ได้)
            seen = email.utils.parsedate_to_datetime(pub).strftime("%Y%m%dT%H%M%SZ")
        except Exception:
            pass
        g = _geo_from_title(title)
        label = g[0] if g else ""
        if g:
            geo.setdefault(label, [(g[1], g[2]), 0])[1] += 1
        heads.append({"title": title[:140], "domain": src, "country": label,
                      "url": it.findtext("link") or "", "seen": seen})
    return _aggregate(geo, heads, len(items), "GoogleNews")


def refresh(force=False):
    """pull → เขียน data/worldmonitor.json. GDELT ก่อน, ตกไป Google News. cache TTL, fail-soft."""
    if not force and _fresh():
        try:
            return json.load(open(_OUT, encoding="utf-8"))
        except Exception:
            pass
    out = _try_gdelt() or _try_gnews()
    if out is None:                                       # ทั้งสอง source พลาด → เก็บของเก่า ok=False
        out = {}
        try:
            out = json.load(open(_OUT, encoding="utf-8"))
        except Exception:
            pass
        out.update({"ok": False, "ts": int(time.time()), "error": "GDELT+GoogleNews unavailable"})
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
    print(f"ok={d.get('ok')} source={d.get('source')} n_articles={d.get('n_articles')} "
          f"attention={d.get('attention')} events={len(d.get('events', []))}")
    for e in d.get("events", [])[:8]:
        print(f"  ● {e['name']:20} count={e['count']} sev={e['sev']:.2f}")
    for h in d.get("headlines", [])[:6]:
        print(f"  [{(h['country'] or '-')[:14]:14}] {h['title'][:70]}")
