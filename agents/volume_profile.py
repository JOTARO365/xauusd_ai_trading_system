"""agents/volume_profile.py — S/R Book add-on (A): volume-at-price / VPOC.

Spot XAUUSD (retail CFD) has NO market-wide open interest or order book, so
"how many contracts are held at a price" is not directly observable. This module
computes the closest free proxy: a VOLUME PROFILE from MT5 bars — for each bar it
spreads that bar's tick_volume evenly across the price bins the bar spanned (H..L),
then reports, per price bin, the share of total activity. Peaks (VPOC / value-area)
mark where the most contracts actually transacted = the structurally strongest S/R.

tick_volume = number of price ticks in the bar (spot has no real traded size), a
standard activity proxy on FX/metals feeds. Pure compute, import-safe, 0 token.

Consumed by /api/volume-profile → annotates the S/R Book ladder rows.
"""


def compute(bars, bins=60, value_area_pct=0.70):
    """bars = iterable of records with keys high/low/close/tick_volume (MT5 rate rows
    work directly — numpy void supports ['high'] indexing). Returns a profile dict:
        {ok, bins:[{lo,hi,mid,vol,pct}], vpoc, va_high, va_low,
         price_min, price_max, bin_size, total_vol, n_bars}
    pct = share of total volume in that bin (0..100). Fail-soft → {ok:False}."""
    try:
        rows = [(float(b["high"]), float(b["low"]), float(b["tick_volume"] if b["tick_volume"] else 1))
                for b in bars]
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "bad bars"}
    rows = [r for r in rows if r[0] >= r[1] and r[0] > 0]
    if len(rows) < 10:
        return {"ok": False, "error": "not enough bars"}

    pmax = max(r[0] for r in rows)
    pmin = min(r[1] for r in rows)
    span = pmax - pmin
    if span <= 0:
        return {"ok": False, "error": "zero range"}
    bins = max(10, min(int(bins), 200))
    bin_size = span / bins
    vol = [0.0] * bins

    def _idx(price):
        i = int((price - pmin) / bin_size)
        return 0 if i < 0 else (bins - 1 if i >= bins else i)

    for hi, lo, tv in rows:
        i0, i1 = _idx(lo), _idx(hi)
        share = tv / (i1 - i0 + 1)          # spread bar's activity across bins it spanned
        for i in range(i0, i1 + 1):
            vol[i] += share

    total = sum(vol) or 1.0
    prof = [{"lo": round(pmin + i * bin_size, 2),
             "hi": round(pmin + (i + 1) * bin_size, 2),
             "mid": round(pmin + (i + 0.5) * bin_size, 2),
             "vol": round(vol[i], 1),
             "pct": round(vol[i] / total * 100, 2)} for i in range(bins)]

    poc_i = max(range(bins), key=lambda i: vol[i])
    vpoc = prof[poc_i]["mid"]

    # value area: grow out from POC until ≥ value_area_pct of total volume
    lo_i = hi_i = poc_i
    acc = vol[poc_i]
    target = total * value_area_pct
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        below = vol[lo_i - 1] if lo_i > 0 else -1
        above = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if above >= below:
            hi_i += 1; acc += vol[hi_i]
        else:
            lo_i -= 1; acc += vol[lo_i]

    return {"ok": True, "bins": prof, "vpoc": vpoc,
            "va_high": prof[hi_i]["hi"], "va_low": prof[lo_i]["lo"],
            "price_min": round(pmin, 2), "price_max": round(pmax, 2),
            "bin_size": round(bin_size, 2), "total_vol": round(total, 1),
            "n_bars": len(rows)}


def pct_at(profile, price):
    """volume-share % of the bin containing `price` (0 if outside range / bad profile)."""
    if not profile or not profile.get("ok"):
        return 0.0
    for b in profile["bins"]:
        if b["lo"] <= price < b["hi"]:
            return b["pct"]
    if profile["bins"] and price >= profile["bins"][-1]["hi"]:
        return profile["bins"][-1]["pct"]
    return 0.0
