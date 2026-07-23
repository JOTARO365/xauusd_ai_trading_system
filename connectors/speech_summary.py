"""connectors/speech_summary.py — Phase 3: สรุป speech ครั้งก่อน ด้วย LLM (Haiku) จากพาดหัวข่าว.

on-demand (เรียกตอนเปิด speech modal), cached ต่อ speech (1 call/speech/วัน), flag-gated ที่ endpoint.
0 ผลกระทบต่อ per-cycle cost ของบอท (คนละ path, user กดเอง). fail-soft.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE = os.path.join(_BASE, "data", "speech_summary_cache.json")
_HAIKU = os.getenv("MODEL_SPEECH") or "claude-haiku-4-5-20251001"
_TTL = 86400   # cache 1 วัน (สรุปใหม่วันละครั้ง/speech)


def _query_of(title):
    """ดึงคำค้น (ชื่อ speaker/หัวข้อ) จาก title โดยตัดคำ speech ทิ้ง."""
    t = re.sub(r"\b(speaks?|speech|testifies|testimony|remarks|press conference|statement)\b", "",
               title or "", flags=re.I).strip()
    return t or title or ""


def _gnews(q, n=8):
    """พาดหัวข่าวล่าสุด 3 วัน จาก Google News RSS (ฟรี ไม่ต้อง key)."""
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": q + " when:3d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 xauusd-bot"})
        with urllib.request.urlopen(req, timeout=15) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return []
    out = []
    for it in root.findall(".//item")[:n]:
        t = (it.findtext("title") or "").strip()
        src = it.find("source")
        s = (src.text or "").strip() if src is not None else ""
        if s and t.endswith(" - " + s):
            t = t[:-(len(s) + 3)].strip()
        if t:
            out.append(t)
    return out


# keyword → ทิศทางทอง: hawkish = ทองลง / dovish + safe-haven = ทองขึ้น (Fed-speak ↔ gold)
_HAWKISH = ("rate hike", "raise rate", "higher for longer", "inflation", "hawkish", "tighten",
            "restrictive", "strong economy", "vigilant", "overheat", "hot economy", "sticky inflation")
_DOVISH = ("rate cut", "cut rate", "lower rate", "dovish", "easing", "ease", "stimulus", "patient",
           "pause", "slowdown", "weak", "recession", "accommodative", "soft landing", "cooling")
_SAFEHAVEN = ("war", "conflict", "sanction", "crisis", "geopolit", "attack", "escalat", "tension",
              "safe haven", "safe-haven", "uncertainty", "turmoil")


def bias_score(heads):
    """คะแนน gold bias −100..+100 (ทองลง↔ทองขึ้น) จาก keyword ในพาดหัว. deterministic, 0 token."""
    text = " ".join(heads).lower()
    haw = sum(text.count(k) for k in _HAWKISH)
    dov = sum(text.count(k) for k in _DOVISH)
    sh = sum(text.count(k) for k in _SAFEHAVEN)
    up, down = dov + sh, haw                          # ทองขึ้น = dovish+risk-off ; ทองลง = hawkish
    tot = up + down
    score = 0 if tot == 0 else round((up - down) / tot * 100)
    label = ("ทองขึ้น (dovish / risk-off)" if score > 15
             else "ทองลง (hawkish)" if score < -15 else "กลาง / ยังไม่ชัด")
    return {"score": score, "label": label, "hawkish": haw, "dovish": dov, "safehaven": sh, "n_heads": len(heads)}


def bias_from_news(title):
    """fetch ข่าว speech → คะแนน bias + พาดหัว. (0 token — ใช้ keyword ล้วน)."""
    heads = _gnews(_query_of(title), n=12)
    b = bias_score(heads)
    b["headlines"] = heads[:6]
    return b


def summarize_speech(title, key):
    """คืน {ok, summary, sources, cached} — cache ต่อ speech (TTL 1 วัน). ต้องเปิด flag ที่ endpoint ก่อนเรียก."""
    try:
        cache = json.load(open(_CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    ent = cache.get(key)
    if ent and time.time() - ent.get("_ts", 0) < _TTL:
        return {**ent, "cached": True}

    heads = _gnews(_query_of(title))
    if not heads:
        return {"ok": False, "note": "ไม่พบข่าวเกี่ยวกับ speech นี้ (Google News)"}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"ok": False, "note": "ไม่มี ANTHROPIC_API_KEY"}
    try:
        import anthropic
        cli = anthropic.Anthropic(api_key=api_key)
        prompt = (f"จากพาดหัวข่าวด้านล่าง สรุปเป็นภาษาไทยสั้นๆ 3-5 bullet ว่า \"{title}\" "
                  f"สื่อ/พูดประเด็นอะไร และมีผลต่อทองคำ (XAUUSD)/ตลาดยังไง. "
                  f"ตอบเฉพาะ bullet ภาษาไทย ขึ้นต้นด้วย •  ไม่ต้องเกริ่นนำ:\n"
                  + "\n".join("- " + h for h in heads))
        msg = cli.messages.create(model=_HAIKU, max_tokens=350,
                                  messages=[{"role": "user", "content": prompt}])
        summary = (msg.content[0].text or "").strip()
        out = {"ok": True, "summary": summary, "sources": heads[:5], "_ts": int(time.time())}
        cache[key] = out
        try:
            with open(_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass
        return {**out, "cached": False}
    except Exception as e:
        return {"ok": False, "note": "LLM error: " + str(e)[:80]}
