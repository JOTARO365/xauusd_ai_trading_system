"""agents/options_oi.py — S/R Book add-on (B): real options open-interest walls.

Spot XAUUSD (retail CFD) is OTC with no open interest of its own. The closest
*real* "contracts held at a price" proxy is GOLD OPTIONS open interest — and the
freest liquid gold-options chain is GLD (SPDR Gold Shares ETF) options, published
delayed + key-free by CBOE. This module fetches that chain, aggregates call/put OI
per strike over the front expiries, and converts each GLD strike into an XAU-price
equivalent (factor = XAU_spot / GLD_price, since GLD ≈ 1/10.8 oz net of fees).

Big PUT OI below price = a support wall (writers defend it); big CALL OI above =
a resistance / cap wall. The strike that minimises option-holder payout is the
classic "max pain" magnet. All display-only, 0 token (HTTP fetch, not an LLM call).

Caveats surfaced to the reader: GLD options ≈ proxy for gold (not COMEX GC futures
options); strikes are coarse ($1–$5 GLD ≈ $11–$54 XAU); OI updates once daily.

Consumed by /api/options-oi → overlays the S/R Book ladder + a walls header.
"""
import json
import os
import re
import time
import urllib.request
from datetime import date, datetime, timezone

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_RAW = os.path.join(_BASE, "data", "options_oi_raw.json")
_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/GLD.json"
_OCC = re.compile(r"^[A-Z]+(\d{6})([CP])(\d{8})")
_RAW_TTL = 1800            # refresh CBOE at most every 30 min (OI is a daily figure)
_FRONT_DAYS = 60           # aggregate the front expiries (near-term gamma matters most)
_BAND_PCT = 0.12           # "walls near price" = strikes within ±12% of spot


def _fetch_raw():
    """CBOE GLD chain, cached to disk with a TTL so we don't hammer the CDN. Fail-soft."""
    try:
        if os.path.exists(_CACHE_RAW) and time.time() - os.path.getmtime(_CACHE_RAW) < _RAW_TTL:
            with open(_CACHE_RAW, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    req = urllib.request.Request(_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = json.load(r)
    try:
        with open(_CACHE_RAW, "w", encoding="utf-8") as f:
            json.dump(raw, f)
    except OSError:
        pass
    return raw


def build(spot_xau, front_days=_FRONT_DAYS):
    """Aggregate GLD option OI per strike (front expiries) and map to XAU price.
    spot_xau = current XAUUSD price (drives the GLD→XAU conversion). Returns a dict:
        {ok, asof, gld_price, factor, front_days, total_oi,
         strikes:[{gld,xau,call_oi,put_oi,total_oi,pct,kind}],   # kind = support|resistance|—
         walls_near:[…strikes within ±band, top OI first…],
         top_support, top_resistance, max_pain_xau}
    Fail-soft → {ok:False, error}."""
    try:
        spot_xau = float(spot_xau)
        if spot_xau <= 0:
            return {"ok": False, "error": "bad spot"}
        raw = _fetch_raw()
        data = raw["data"]
        gld = float(data["current_price"])
        opts = data["options"]
    except Exception as e:
        return {"ok": False, "error": f"fetch/parse: {type(e).__name__}"}
    if gld <= 0:
        return {"ok": False, "error": "bad gld price"}
    factor = spot_xau / gld
    today = datetime.now(timezone.utc).date()

    agg = {}                          # strike -> [call_oi, put_oi]
    for o in opts:
        m = _OCC.match(o.get("option", ""))
        if not m:
            continue
        yy, mm, dd = int(m.group(1)[:2]), int(m.group(1)[2:4]), int(m.group(1)[4:6])
        try:
            exp = date(2000 + yy, mm, dd)
        except ValueError:
            continue
        days = (exp - today).days
        if days < 0 or days > front_days:
            continue
        strike = int(m.group(3)) / 1000.0
        oi = o.get("open_interest") or 0
        cell = agg.setdefault(strike, [0.0, 0.0])
        cell[0 if m.group(2) == "C" else 1] += oi

    if not agg:
        return {"ok": False, "error": "no OI in window"}
    total = sum(c + p for c, p in agg.values()) or 1.0

    strikes = []
    for k in sorted(agg):
        c, p = agg[k]
        t = c + p
        kind = "support" if p > c * 1.3 else "resistance" if c > p * 1.3 else "—"
        strikes.append({"gld": round(k, 2), "xau": round(k * factor, 0),
                        "call_oi": int(c), "put_oi": int(p), "total_oi": int(t),
                        "pct": round(t / total * 100, 2), "kind": kind})

    band = [s for s in strikes if abs(s["xau"] - spot_xau) <= spot_xau * _BAND_PCT]
    walls_near = sorted(band, key=lambda s: -s["total_oi"])[:10]
    top_support = max((s for s in band if s["kind"] == "support" and s["xau"] <= spot_xau),
                      key=lambda s: s["put_oi"], default=None)
    top_resistance = max((s for s in band if s["kind"] == "resistance" and s["xau"] >= spot_xau),
                         key=lambda s: s["call_oi"], default=None)

    # max pain (near band): strike minimising total intrinsic payout to option holders
    max_pain_xau = None
    if band:
        best_k, best_pain = None, None
        for cand in band:
            K = cand["gld"]
            pain = sum(agg[k][0] * max(0.0, K - k) + agg[k][1] * max(0.0, k - K) for k in agg)
            if best_pain is None or pain < best_pain:
                best_pain, best_k = pain, K
        if best_k is not None:
            max_pain_xau = round(best_k * factor, 0)

    return {"ok": True, "asof": datetime.now(timezone.utc).isoformat()[:16] + "Z",
            "gld_price": round(gld, 2), "factor": round(factor, 3), "front_days": front_days,
            "total_oi": int(total), "strikes": strikes, "walls_near": walls_near,
            "top_support": top_support, "top_resistance": top_resistance,
            "max_pain_xau": max_pain_xau}


def oi_at(profile, xau_price, tol_pct=0.005):
    """Nearest strike (within ±tol_pct of xau_price) for a ladder-row annotation, or None."""
    if not profile or not profile.get("ok"):
        return None
    tol = xau_price * tol_pct
    hit = [s for s in profile["strikes"] if abs(s["xau"] - xau_price) <= tol]
    return min(hit, key=lambda s: abs(s["xau"] - xau_price)) if hit else None


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    r = build(4044.0)
    if not r["ok"]:
        print("ERR", r["error"]); raise SystemExit
    print(f"GLD {r['gld_price']} factor {r['factor']} totOI {r['total_oi']} maxpain XAU {r['max_pain_xau']}")
    print("near-price walls:")
    for s in r["walls_near"]:
        print(f"  XAU {s['xau']:.0f} (GLD {s['gld']}) {s['kind']:10s} call {s['call_oi']} put {s['put_oi']} ({s['pct']}%)")
