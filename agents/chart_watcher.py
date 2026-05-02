import anthropic
import pandas as pd
import numpy as np
import ta
import MetaTrader5 as mt5
from pathlib import Path
from connectors.price_feed import get_ohlcv, get_current_price
from config import ANTHROPIC_API_KEY, SYMBOL
from loguru import logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = Path("agents/prompts/chart_watcher.md").read_text(encoding="utf-8")

SR_ZONE_PCT   = 0.004   # 0.4% = "อยู่ในโซน S/R" (ขยายสำหรับ scalping)
EMA_TOUCH_PCT = 0.002   # 0.2% = "แตะ EMA"
SL_MIN_PIPS   = 1000
SL_MAX_PIPS   = 2000

FIB_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
FIB_NAMES  = ["0%", "23.6%", "38.2%", "50%", "61.8%", "78.6%", "100%"]
FIB_KEY    = {0.382, 0.5, 0.618, 0.786}   # levels ที่สำคัญที่สุด
FIB_ZONE_PCT = 0.0025                      # 0.25% = ถือว่าอยู่ใน fib zone


# ─────────────────────────────────────────────────────────────
#  INDICATORS
# ─────────────────────────────────────────────────────────────

def calculate_indicators(rates) -> dict:
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)

    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    df["ema20"]  = ta.trend.ema_indicator(close, window=20)
    df["ema50"]  = ta.trend.ema_indicator(close, window=50)
    df["ema200"] = ta.trend.ema_indicator(close, window=200)
    df["rsi"]    = ta.momentum.rsi(close, window=14)

    macd_obj          = ta.trend.MACD(close)
    df["macd"]        = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    bb             = ta.volatility.BollingerBands(close, window=20)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"]   = bb.bollinger_mavg()
    df["atr"]      = ta.volatility.average_true_range(high, low, close, window=14)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    def s(v):
        try:
            return round(float(v), 4) if v == v else 0
        except Exception:
            return 0

    return {
        "close":       s(last["close"]),
        "open":        s(last["open"]),
        "high":        s(last["high"]),
        "low":         s(last["low"]),
        "ema20":       s(last["ema20"]),
        "ema50":       s(last["ema50"]),
        "ema200":      s(last["ema200"]),
        "rsi":         s(last["rsi"]),
        "macd":        s(last["macd"]),
        "macd_signal": s(last["macd_signal"]),
        "macd_hist":   s(last["macd_hist"]),
        "bb_upper":    s(last["bb_upper"]),
        "bb_lower":    s(last["bb_lower"]),
        "bb_mid":      s(last["bb_mid"]),
        "atr":         s(last["atr"]),
        "prev_close":  s(prev["close"]),
        "prev_high":   s(prev["high"]),
        "prev_low":    s(prev["low"]),
        "prev_macd_hist": s(prev["macd_hist"]),
        "df":          df,
    }


# ─────────────────────────────────────────────────────────────
#  S/R LEVELS
# ─────────────────────────────────────────────────────────────

def find_swing_levels(df: pd.DataFrame, window: int = 5, max_levels: int = 5) -> dict:
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values

    swing_highs, swing_lows = [], []
    for i in range(window, len(high) - window):
        if all(high[i] >= high[i-j] for j in range(1, window+1)) and \
           all(high[i] >= high[i+j] for j in range(1, window+1)):
            swing_highs.append(round(float(high[i]), 2))
        if all(low[i] <= low[i-j] for j in range(1, window+1)) and \
           all(low[i] <= low[i+j] for j in range(1, window+1)):
            swing_lows.append(round(float(low[i]), 2))

    def dedup(levels):
        levels = sorted(set(levels), reverse=True)
        result = []
        for lv in levels:
            if not result or abs(lv - result[-1]) / result[-1] > 0.002:
                result.append(lv)
        return result

    current = float(close[-1])
    resistances = sorted([h for h in dedup(swing_highs) if h > current])[:max_levels]
    supports    = sorted([l for l in dedup(swing_lows)  if l < current], reverse=True)[:max_levels]
    return {"resistance": resistances, "support": supports}


def find_key_levels(df: pd.DataFrame) -> dict:
    close = float(df["close"].iloc[-1])
    prev_day = df.iloc[-48:-24] if len(df) >= 48 else df.iloc[:len(df)//2]
    pdh = round(float(prev_day["high"].max()), 2) if len(prev_day) > 0 else 0
    pdl = round(float(prev_day["low"].min()), 2)  if len(prev_day) > 0 else 0
    base      = round(close / 50) * 50
    rounds    = [base + i * 50 for i in range(-3, 4)]
    round_lvl = [r for r in rounds if abs(r - close) / close > 0.001]
    return {"pdh": pdh, "pdl": pdl, "round_numbers": round_lvl}


def calc_sl_from_wick(m15: dict, direction: str) -> int:
    """SL = ปลาย wick แท่งก่อนหน้า M15, clamp 1000–2000 pips"""
    point = 0.01
    if direction == "BUY":
        sl_pips = round((m15["close"] - m15["prev_low"]) / point)
    else:
        sl_pips = round((m15["prev_high"] - m15["close"]) / point)
    return max(SL_MIN_PIPS, min(SL_MAX_PIPS, max(sl_pips, 0)))


def format_sr_text(h4_sr: dict, h1_sr: dict, key: dict, current_price: float) -> str:
    all_res = sorted(set(
        h4_sr["resistance"] + h1_sr["resistance"] +
        ([key["pdh"]] if key["pdh"] else []) + key["round_numbers"]
    ))
    all_sup = sorted(set(
        h4_sr["support"] + h1_sr["support"] +
        ([key["pdl"]] if key["pdl"] else []) + key["round_numbers"]
    ), reverse=True)

    res_near = [r for r in all_res if r > current_price][:5]
    sup_near = [s for s in all_sup if s < current_price][:5]

    zone_size = current_price * SR_ZONE_PCT
    in_res = [r for r in res_near if abs(r - current_price) <= zone_size]
    in_sup = [s for s in sup_near if abs(s - current_price) <= zone_size]

    lines = [
        f"H4 Resistance: {h4_sr['resistance'][:4]}",
        f"H4 Support   : {h4_sr['support'][:4]}",
        f"H1 Resistance: {h1_sr['resistance'][:4]}",
        f"H1 Support   : {h1_sr['support'][:4]}",
        f"PDH: {key['pdh']} | PDL: {key['pdl']} | Round: {key['round_numbers'][:4]}",
    ]
    if in_res:
        lines.append(f"*** อยู่ในโซน RESISTANCE: {in_res} ***")
    if in_sup:
        lines.append(f"*** อยู่ในโซน SUPPORT: {in_sup} ***")
    if not in_res and not in_sup:
        lines.append("ราคาอยู่ระหว่าง zone (ไม่มี S/R ชัดเจน)")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  CANDLE PATTERNS
# ─────────────────────────────────────────────────────────────

def detect_candle_pattern(df: pd.DataFrame) -> dict:
    c   = df.iloc[-1]
    p   = df.iloc[-2]
    atr = float(df["atr"].iloc[-1]) if "atr" in df.columns else 1

    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    body        = abs(cl - o)
    candle      = h - l
    upper_wick  = h - max(o, cl)
    lower_wick  = min(o, cl) - l
    bullish     = cl > o
    p_body      = abs(float(p["close"]) - float(p["open"]))

    patterns = []
    if lower_wick > body * 2 and lower_wick > upper_wick * 2:
        patterns.append("HAMMER")
    if upper_wick > body * 2 and upper_wick > lower_wick * 2:
        patterns.append("SHOOTING_STAR")
    if bullish and float(p["close"]) < float(p["open"]) and body > p_body * 1.2:
        patterns.append("BULLISH_ENGULFING")
    if not bullish and float(p["close"]) > float(p["open"]) and body > p_body * 1.2:
        patterns.append("BEARISH_ENGULFING")
    if candle > 0 and body / candle > 0.70:
        if bullish and cl > h - (candle * 0.15):
            patterns.append("STRONG_BULL_CANDLE")
        if not bullish and cl < l + (candle * 0.15):
            patterns.append("STRONG_BEAR_CANDLE")
    if body < atr * 0.1:
        patterns.append("DOJI")

    bull_p = {"HAMMER", "BULLISH_ENGULFING", "STRONG_BULL_CANDLE"}
    bear_p = {"SHOOTING_STAR", "BEARISH_ENGULFING", "STRONG_BEAR_CANDLE"}
    bias = "NEUTRAL"
    if any(pp in bull_p for pp in patterns):
        bias = "BULLISH"
    elif any(pp in bear_p for pp in patterns):
        bias = "BEARISH"

    return {
        "patterns": patterns if patterns else ["NORMAL"],
        "bias":     bias,
        "body_pct": round(body / candle * 100, 1) if candle > 0 else 0,
        "bullish":  bullish,
    }


# ─────────────────────────────────────────────────────────────
#  FIBONACCI RETRACEMENT
# ─────────────────────────────────────────────────────────────

def calc_fibonacci(df: pd.DataFrame, lookback: int = 60) -> dict:
    """
    หา Fibonacci retracement จาก swing high/low ล่าสุดใน lookback bars

    Logic:
    - ถ้า swing high เกิดหลัง swing low  → upswing → วัด retracement ลงจาก high
      (ราคาอาจ pullback หา 38.2/50/61.8 ก่อน bounce ต่อขึ้น)
    - ถ้า swing low เกิดหลัง swing high → downswing → วัด retracement ขึ้นจาก low
      (ราคาอาจ bounce หา 38.2/50/61.8 ก่อน ร่วงต่อ)

    คืน:
      swing_high, swing_low, swing_dir (UP/DOWN),
      levels: dict[price → (ratio, name, is_key)],
      nearest: {price, name, ratio, distance_pct, in_zone, is_key}
    """
    recent   = df.tail(lookback)
    sh_price = float(recent["high"].max())
    sl_price = float(recent["low"].min())
    sh_idx   = recent["high"].idxmax()
    sl_idx   = recent["low"].idxmin()
    current  = float(df["close"].iloc[-1])
    diff     = sh_price - sl_price

    if diff == 0:
        return {"swing_high": sh_price, "swing_low": sl_price,
                "swing_dir": "FLAT", "levels": {}, "nearest": None}

    swing_dir = "UP" if sh_idx > sl_idx else "DOWN"

    # คำนวณ levels จาก swing ล่าสุด
    # UP  = ราคา pullback ลงจาก high → levels วัดจาก high ลงมา
    # DOWN = ราคา bounce ขึ้นจาก low → levels วัดจาก low ขึ้นไป
    levels: dict[float, tuple] = {}
    for ratio, name in zip(FIB_RATIOS, FIB_NAMES):
        if swing_dir == "UP":
            price_lvl = round(sh_price - ratio * diff, 2)
        else:
            price_lvl = round(sl_price + ratio * diff, 2)
        is_key = ratio in FIB_KEY
        levels[price_lvl] = (ratio, name, is_key)

    # หา level ที่ใกล้ราคาปัจจุบันมากสุด
    nearest_price = min(levels.keys(), key=lambda p: abs(p - current))
    ratio_n, name_n, is_key_n = levels[nearest_price]
    dist_pct = abs(nearest_price - current) / current * 100

    return {
        "swing_high": round(sh_price, 2),
        "swing_low":  round(sl_price, 2),
        "swing_dir":  swing_dir,
        "levels":     levels,
        "nearest": {
            "price":       nearest_price,
            "name":        name_n,
            "ratio":       ratio_n,
            "distance_pct": round(dist_pct, 3),
            "in_zone":     dist_pct < FIB_ZONE_PCT * 100,
            "is_key":      is_key_n,
        },
    }


def _format_fib_text(fib: dict, label: str) -> str:
    """สร้างข้อความ Fibonacci สำหรับส่ง Claude"""
    n = fib.get("nearest")
    if not n:
        return f"  {label}: ไม่สามารถคำนวณได้"

    arrow  = "▲" if fib["swing_dir"] == "UP" else "▼"
    zone_s = "*** IN ZONE ***" if n["in_zone"] else ""
    key_s  = "[KEY]" if n["is_key"] else ""
    lines  = [
        f"  {label}: Swing {fib['swing_low']}─{fib['swing_high']} ({arrow}{fib['swing_dir']})",
        f"  Nearest level: {n['name']} {key_s} @ {n['price']}  (dist={n['distance_pct']:.2f}%)  {zone_s}",
        "  All levels: " + "  |  ".join(
            f"{'*' if v[2] else ''}{v[1]}={p}"
            for p, v in sorted(fib["levels"].items(), reverse=(fib["swing_dir"] == "UP"))
        ),
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  MOMENTUM
# ─────────────────────────────────────────────────────────────

def calc_momentum(ind: dict, df: pd.DataFrame) -> dict:
    """
    วัด momentum direction + strength จาก 4 ตัวชี้วัด:
    RSI slope, MACD hist direction/expansion, Price ROC (5 bar), EMA alignment
    คืน: direction (UP/DOWN/FLAT), strength (STRONG/MODERATE/WEAK)
    """
    # RSI slope (เทียบ bar ปัจจุบัน vs 4 bar ก่อน)
    rsi_vals  = df["rsi"].dropna().values
    rsi_slope = float(rsi_vals[-1] - rsi_vals[-4]) if len(rsi_vals) >= 5 else 0.0

    # MACD histogram: ทิศทาง + expanding
    hist_vals      = df["macd_hist"].dropna().values
    hist_now       = float(hist_vals[-1])       if len(hist_vals) >= 1 else 0.0
    hist_prev      = float(hist_vals[-3])       if len(hist_vals) >= 3 else hist_now
    hist_expanding = abs(hist_now) > abs(hist_prev)

    # Price Rate of Change 5 bars
    close_vals = df["close"].values
    roc5 = (close_vals[-1] - close_vals[-6]) / close_vals[-6] * 100 if len(close_vals) >= 6 else 0.0

    # EMA alignment (close > EMA20 > EMA50 = bullish stack)
    ema_bull = ind["close"] > ind["ema20"] > ind["ema50"]
    ema_bear = ind["close"] < ind["ema20"] < ind["ema50"]

    up = dn = 0
    if rsi_slope >  1.5: up += 1
    elif rsi_slope < -1.5: dn += 1

    if hist_now > 0: up += 2 if hist_expanding else 1
    elif hist_now < 0: dn += 2 if hist_expanding else 1

    if roc5 > 0: up += 1
    elif roc5 < 0: dn += 1

    if ema_bull: up += 1
    elif ema_bear: dn += 1

    if up > dn:
        direction = "UP"
        strength  = "STRONG" if up >= 4 else "MODERATE"
    elif dn > up:
        direction = "DOWN"
        strength  = "STRONG" if dn >= 4 else "MODERATE"
    else:
        direction = "FLAT"
        strength  = "WEAK"

    return {
        "direction":      direction,
        "strength":       strength,
        "rsi_slope":      round(rsi_slope, 2),
        "macd_hist":      round(hist_now, 4),
        "hist_expanding": hist_expanding,
        "roc_5bar":       round(roc5, 3),
        "ema_align":      "BULL" if ema_bull else "BEAR" if ema_bear else "MIXED",
    }


def detect_sr_action(df: pd.DataFrame, sr_levels: list, zone_pct: float = SR_ZONE_PCT) -> list:
    current    = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    candle_pat = detect_candle_pattern(df)
    zone_size  = current * zone_pct
    actions    = []

    for level in sr_levels:
        if abs(current - level) > zone_size * 2:
            continue

        is_res = level > current or (prev_close < level <= current)
        is_sup = level < current or (prev_close > level >= current)

        if is_res and candle_pat["bias"] == "BEARISH":
            actions.append({"level": level, "action": "REJECTION", "direction": "SELL",
                            "zone": "RESISTANCE", "pattern": candle_pat["patterns"],
                            "note": f"reject resistance {level}"})
        if is_sup and candle_pat["bias"] == "BULLISH":
            actions.append({"level": level, "action": "REJECTION", "direction": "BUY",
                            "zone": "SUPPORT", "pattern": candle_pat["patterns"],
                            "note": f"reject support {level}"})
        if prev_close < level <= current and candle_pat["bias"] == "BULLISH":
            actions.append({"level": level, "action": "BREAKOUT", "direction": "BUY",
                            "zone": "RESISTANCE_BROKEN", "pattern": candle_pat["patterns"],
                            "note": f"breakout resistance {level}"})
        if prev_close > level >= current and candle_pat["bias"] == "BEARISH":
            actions.append({"level": level, "action": "BREAKOUT", "direction": "SELL",
                            "zone": "SUPPORT_BROKEN", "pattern": candle_pat["patterns"],
                            "note": f"breakout support {level}"})
    return actions


# ─────────────────────────────────────────────────────────────
#  ENTRY SETUP SCANNER  ← ใหม่
# ─────────────────────────────────────────────────────────────

def scan_entry_setups(h4: dict, h1: dict, m15: dict,
                      h4_sr: dict, h1_sr: dict, key_lvl: dict) -> dict:
    """
    สแกนหา entry setup จากทุก timeframe และ S/R
    คืน dict: setups (list), best_direction, best_score, confluence_count, h4_bias
    """
    price = h4["close"]
    setups: list[dict] = []

    # ── H4 Bias ───────────────────────────────────────────────
    ema200_dist_pct = abs(price - h4["ema200"]) / h4["ema200"] if h4["ema200"] else 0
    if ema200_dist_pct < 0.005:
        h4_bias = "SIDEWAYS"
    elif price > h4["ema200"]:
        h4_bias = "BULLISH"
    else:
        h4_bias = "BEARISH"

    # ── 1. S/R Zone (H4 + H1) — scalping: ไม่ filter H4 bias ────
    zone = price * SR_ZONE_PCT
    m15_bias = "BULLISH" if m15["close"] > m15["ema20"] else "BEARISH"

    h4_levels = (
        h4_sr["resistance"] + h4_sr["support"] +
        ([key_lvl["pdh"]] if key_lvl["pdh"] else []) +
        ([key_lvl["pdl"]] if key_lvl["pdl"] else []) +
        key_lvl["round_numbers"]
    )
    for lv in h4_levels:
        if abs(price - lv) <= zone:
            direction = "SELL" if lv >= price else "BUY"
            m15_align = (direction == "BUY" and m15_bias == "BULLISH") or \
                        (direction == "SELL" and m15_bias == "BEARISH")
            setups.append({
                "type": "SR_ZONE", "tf": "H4", "direction": direction,
                "score": 80 if m15_align else 65, "level": lv,
                "note": f"H4 S/R {lv:.2f} ({direction}) M15={'align' if m15_align else 'counter'}"
            })

    # ── 1b. H1 S/R Zone ──────────────────────────────────────
    h1_levels = h1_sr["resistance"] + h1_sr["support"]
    for lv in h1_levels:
        if abs(price - lv) <= zone:
            direction = "SELL" if lv >= price else "BUY"
            m15_align = (direction == "BUY" and m15_bias == "BULLISH") or \
                        (direction == "SELL" and m15_bias == "BEARISH")
            setups.append({
                "type": "SR_ZONE", "tf": "H1", "direction": direction,
                "score": 72 if m15_align else 58, "level": lv,
                "note": f"H1 S/R {lv:.2f} ({direction}) M15={'align' if m15_align else 'counter'}"
            })

    # ── 2. EMA200 H4 Dynamic S/R ─────────────────────────────
    ema200_dist = abs(price - h4["ema200"])
    if ema200_dist / price < 0.002:   # ราคาแตะ EMA200 H4
        direction = "BUY" if price > h4["ema200"] else "SELL"
        setups.append({
            "type": "EMA200_TOUCH", "tf": "H4", "direction": direction,
            "score": 72, "level": h4["ema200"],
            "note": f"ราคาแตะ EMA200 H4 ({h4['ema200']:.2f}) — dynamic S/R แข็งแกร่ง"
        })

    # ── 3. Bollinger Band H4 ─────────────────────────────────
    if price <= h4["bb_lower"] * 1.001 and h4_bias != "BEARISH":
        setups.append({
            "type": "BB_LOWER", "tf": "H4", "direction": "BUY",
            "score": 65, "level": h4["bb_lower"],
            "note": f"ราคาแตะ BB Lower H4 ({h4['bb_lower']:.2f}) — oversold zone"
        })
    if price >= h4["bb_upper"] * 0.999 and h4_bias != "BULLISH":
        setups.append({
            "type": "BB_UPPER", "tf": "H4", "direction": "SELL",
            "score": 65, "level": h4["bb_upper"],
            "note": f"ราคาแตะ BB Upper H4 ({h4['bb_upper']:.2f}) — overbought zone"
        })

    # ── 4. EMA Pullback H1 ───────────────────────────────────
    # ราคา H1 กลับมาแตะ EMA20 แล้ว bounce ในทิศทาง trend
    h1_ema20_dist = abs(h1["close"] - h1["ema20"]) / h1["ema20"] if h1["ema20"] else 1
    if h1_ema20_dist < EMA_TOUCH_PCT:
        if h4_bias == "BULLISH" and h1["close"] >= h1["ema20"]:
            setups.append({
                "type": "EMA_PULLBACK", "tf": "H1", "direction": "BUY",
                "score": 70, "level": h1["ema20"],
                "note": f"ราคา H1 pullback แตะ EMA20 ({h1['ema20']:.2f}) ใน Bullish trend"
            })
        elif h4_bias == "BEARISH" and h1["close"] <= h1["ema20"]:
            setups.append({
                "type": "EMA_PULLBACK", "tf": "H1", "direction": "SELL",
                "score": 70, "level": h1["ema20"],
                "note": f"ราคา H1 pullback แตะ EMA20 ({h1['ema20']:.2f}) ใน Bearish trend"
            })

    # ── 5. EMA Cross H1 ─────────────────────────────────────
    # EMA20 เพิ่งข้าม EMA50 (prev_close ใช้เป็น proxy)
    ema_gap = h1["ema20"] - h1["ema50"]
    if abs(ema_gap) / h1["ema50"] < 0.001:   # ใกล้จะข้าม หรือเพิ่งข้าม
        if ema_gap > 0 and h4_bias == "BULLISH":
            setups.append({
                "type": "EMA_CROSS", "tf": "H1", "direction": "BUY",
                "score": 65, "level": h1["ema20"],
                "note": f"EMA20 > EMA50 H1 (gap={ema_gap:.2f}) — bullish cross"
            })
        elif ema_gap < 0 and h4_bias == "BEARISH":
            setups.append({
                "type": "EMA_CROSS", "tf": "H1", "direction": "SELL",
                "score": 65, "level": h1["ema20"],
                "note": f"EMA20 < EMA50 H1 (gap={ema_gap:.2f}) — bearish cross"
            })

    # ── 6. MACD Cross H1 ────────────────────────────────────
    # histogram เพิ่งเปลี่ยนทิศทาง (prev histogram ต่างเครื่องหมายกับปัจจุบัน)
    if h1["macd_hist"] > 0 and h1["prev_macd_hist"] <= 0 and h4_bias == "BULLISH":
        setups.append({
            "type": "MACD_CROSS", "tf": "H1", "direction": "BUY",
            "score": 60, "level": h1["close"],
            "note": f"MACD cross up H1 (hist={h1['macd_hist']:.3f})"
        })
    elif h1["macd_hist"] < 0 and h1["prev_macd_hist"] >= 0 and h4_bias == "BEARISH":
        setups.append({
            "type": "MACD_CROSS", "tf": "H1", "direction": "SELL",
            "score": 60, "level": h1["close"],
            "note": f"MACD cross down H1 (hist={h1['macd_hist']:.3f})"
        })

    # ── 7. RSI Extreme M15 ───────────────────────────────────
    if m15["rsi"] < 32 and h4_bias == "BULLISH":
        setups.append({
            "type": "RSI_OVERSOLD", "tf": "M15", "direction": "BUY",
            "score": 58, "level": m15["close"],
            "note": f"RSI M15 = {m15['rsi']:.1f} — oversold ใน Bullish trend"
        })
    elif m15["rsi"] > 68 and h4_bias == "BEARISH":
        setups.append({
            "type": "RSI_OVERBOUGHT", "tf": "M15", "direction": "SELL",
            "score": 58, "level": m15["close"],
            "note": f"RSI M15 = {m15['rsi']:.1f} — overbought ใน Bearish trend"
        })

    # ── 8. EMA50 Pullback M15 (entry timing) ─────────────────
    m15_ema50_dist = abs(m15["close"] - m15["ema50"]) / m15["ema50"] if m15["ema50"] else 1
    if m15_ema50_dist < EMA_TOUCH_PCT:
        if h4_bias == "BULLISH" and m15["close"] >= m15["ema50"] and h1["ema20"] > h1["ema50"]:
            setups.append({
                "type": "EMA50_PULLBACK", "tf": "M15", "direction": "BUY",
                "score": 62, "level": m15["ema50"],
                "note": f"ราคา M15 pullback EMA50 ({m15['ema50']:.2f}) — timing entry"
            })
        elif h4_bias == "BEARISH" and m15["close"] <= m15["ema50"] and h1["ema20"] < h1["ema50"]:
            setups.append({
                "type": "EMA50_PULLBACK", "tf": "M15", "direction": "SELL",
                "score": 62, "level": m15["ema50"],
                "note": f"ราคา M15 pullback EMA50 ({m15['ema50']:.2f}) — timing entry"
            })

    # ── 9. Momentum Breakout (US Session / Strong Move) ───────
    # ไม่ต้องอยู่ที่ zone — momentum คือ edge
    # เงื่อนไข: 3 แท่ง M15 ปิดติดกันทิศทางเดียว + body >= 40% + H4 aligned
    m15_df = m15.get("df")
    if m15_df is not None and len(m15_df) >= 5:
        last3 = m15_df.iloc[-4:-1]   # 3 closed candles ก่อนแท่งปัจจุบัน

        def _sig_candle(row) -> bool:
            rng = float(row["high"]) - float(row["low"])
            return rng > 0 and abs(float(row["close"]) - float(row["open"])) / rng >= 0.40

        bull3 = all(float(r["close"]) > float(r["open"]) for _, r in last3.iterrows())
        bear3 = all(float(r["close"]) < float(r["open"]) for _, r in last3.iterrows())
        sig3  = all(_sig_candle(r) for _, r in last3.iterrows())

        if sig3:
            h1_bull = h1["close"] > h1["ema20"] > h1["ema50"]
            h1_bear = h1["close"] < h1["ema20"] < h1["ema50"]

            if bull3 and h4_bias == "BULLISH":
                score_base = 68 if h1_bull else 57
                setups.append({
                    "type": "MOMENTUM_BREAKOUT", "tf": "M15", "direction": "BUY",
                    "score": score_base, "level": m15["close"],
                    "note": (
                        f"3 bull M15 candles | H4 BULLISH"
                        + (" | H1 EMA stack aligned" if h1_bull else "")
                    ),
                })
            elif bear3 and h4_bias == "BEARISH":
                score_base = 68 if h1_bear else 57
                setups.append({
                    "type": "MOMENTUM_BREAKOUT", "tf": "M15", "direction": "SELL",
                    "score": score_base, "level": m15["close"],
                    "note": (
                        f"3 bear M15 candles | H4 BEARISH"
                        + (" | H1 EMA stack aligned" if h1_bear else "")
                    ),
                })

    # ── Confluence bonus ─────────────────────────────────────
    buy_count  = sum(1 for s in setups if s["direction"] == "BUY")
    sell_count = sum(1 for s in setups if s["direction"] == "SELL")

    for s in setups:
        same = buy_count if s["direction"] == "BUY" else sell_count
        s["score"] = min(100, s["score"] + 8 * (same - 1))

    # ── สรุปทิศทางที่แข็งแกร่งที่สุด ─────────────────────────
    best_dir   = "NONE"
    best_score = 0
    conf_count = 0

    if buy_count > 0 or sell_count > 0:
        if buy_count >= sell_count:
            best_dir   = "BUY"
            conf_count = buy_count
            best_score = max((s["score"] for s in setups if s["direction"] == "BUY"), default=0)
        else:
            best_dir   = "SELL"
            conf_count = sell_count
            best_score = max((s["score"] for s in setups if s["direction"] == "SELL"), default=0)

    return {
        "setups":           setups,
        "best_direction":   best_dir,
        "best_score":       best_score,
        "confluence_count": conf_count,
        "h4_bias":          h4_bias,
    }


def _format_setups_text(scan: dict) -> str:
    setups    = scan["setups"]
    h4_bias   = scan["h4_bias"]
    best_dir  = scan["best_direction"]
    best_score= scan["best_score"]
    conf      = scan["confluence_count"]

    if not setups:
        return f"  ไม่พบ setup ที่ชัดเจน (H4 Bias: {h4_bias})"

    lines = [f"  H4 Trend Bias: {h4_bias}  |  Best Direction: {best_dir} ({conf} setups, top score {best_score})"]
    lines.append(f"  {'Type':<16} {'TF':<6} {'Dir':<6} {'Score':>6}  Note")
    lines.append(f"  {'-'*16} {'-'*6} {'-'*6} {'-'*6}  {'-'*40}")

    for s in sorted(setups, key=lambda x: x["score"], reverse=True):
        lines.append(
            f"  {s['type']:<16} {s['tf']:<6} {s['direction']:<6} {s['score']:>5}  {s['note']}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
#  MAIN ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyze_chart() -> dict:
    logger.info("Agent 1: กำลังวิเคราะห์กราฟ...")

    h4_rates  = get_ohlcv(timeframe=mt5.TIMEFRAME_H4,  count=200)
    h1_rates  = get_ohlcv(timeframe=mt5.TIMEFRAME_H1,  count=100)
    m15_rates = get_ohlcv(timeframe=mt5.TIMEFRAME_M15, count=100)

    if h4_rates is None or h1_rates is None or m15_rates is None:
        logger.error("ดึง OHLCV ไม่ได้")
        return {"signal": "NO_TRADE", "confidence": 0,
                "sl_pips": 1000, "tp_pips": 1500, "raw": "OHLCV unavailable"}

    h4  = calculate_indicators(h4_rates)
    h1  = calculate_indicators(h1_rates)
    m15 = calculate_indicators(m15_rates)

    h4_sr   = find_swing_levels(h4["df"], window=5, max_levels=5)
    h1_sr   = find_swing_levels(h1["df"], window=3, max_levels=5)
    key_lvl = find_key_levels(h4["df"])
    price   = get_current_price()
    current = price.get("bid", h4["close"])

    sr_text    = format_sr_text(h4_sr, h1_sr, key_lvl, current)
    all_levels = h4_sr["resistance"] + h4_sr["support"] + h1_sr["resistance"] + h1_sr["support"]
    sr_actions = detect_sr_action(h4["df"], h4_sr["resistance"] + h4_sr["support"])
    candle_pat = detect_candle_pattern(m15["df"])

    # SL จาก wick แท่งก่อนหน้า M15 (ทั้งสองทิศทาง)
    buy_sl_pips  = calc_sl_from_wick(m15, "BUY")
    sell_sl_pips = calc_sl_from_wick(m15, "SELL")

    # Fibonacci retracement (H4 = major swing, H1 = minor swing)
    fib_h4  = calc_fibonacci(h4["df"],  lookback=80)
    fib_h1  = calc_fibonacci(h1["df"],  lookback=60)
    fib_text = _format_fib_text(fib_h4, "H4") + "\n" + _format_fib_text(fib_h1, "H1")

    # Momentum per timeframe
    mom_h4  = calc_momentum(h4,  h4["df"])
    mom_h1  = calc_momentum(h1,  h1["df"])
    mom_m15 = calc_momentum(m15, m15["df"])

    def _mom_str(m: dict) -> str:
        return f"{m['direction']}_{m['strength']}  (RSI_slope={m['rsi_slope']:+.1f}  MACD_hist={m['macd_hist']:+.4f}{'↑exp' if m['hist_expanding'] else '↓con'}  ROC5={m['roc_5bar']:+.3f}%  EMA={m['ema_align']})"

    # Entry setup scanner
    scan         = scan_entry_setups(h4, h1, m15, h4_sr, h1_sr, key_lvl)
    setups_text  = _format_setups_text(scan)

    # SR action text
    if sr_actions:
        sr_action_text = "\n".join(
            f"  [{a['action']}] {a['zone']} {a['level']} → {a['direction']} | {a['note']}"
            for a in sr_actions
        )
    else:
        sr_action_text = "  ไม่มีสัญญาณ Rejection/Breakout"

    user_message = f"""ราคาปัจจุบัน: Bid={price.get('bid')} / Ask={price.get('ask')}

=== Fibonacci Retracement ===
{fib_text}

=== Momentum Analysis (ทิศทาง momentum ณ ตอนนี้) ===
H4  Momentum: {_mom_str(mom_h4)}
H1  Momentum: {_mom_str(mom_h1)}
M15 Momentum: {_mom_str(mom_m15)}

=== Entry Setup Scanner (Scalping M15) ===
{setups_text}

=== Rejection / Breakout ที่ S/R ===
{sr_action_text}

=== Candle Pattern M15 (สัญญาณเข้า) ===
Pattern: {candle_pat['patterns']} | Bias: {candle_pat['bias']} | Body: {candle_pat['body_pct']}%
Prev Candle: High={m15['prev_high']}  Low={m15['prev_low']}  Close={m15['prev_close']}
SL แนะนำ: BUY_SL={buy_sl_pips} pips (prev low)  |  SELL_SL={sell_sl_pips} pips (prev high)

=== แนวรับแนวต้าน (H4 + H1) ===
{sr_text}

=== H4 Context ===
Close:{h4['close']} EMA20:{h4['ema20']} EMA50:{h4['ema50']} EMA200:{h4['ema200']}
RSI:{h4['rsi']} ATR:{h4['atr']} BB:{h4['bb_lower']}~{h4['bb_upper']}

=== H1 Context ===
Close:{h1['close']} EMA20:{h1['ema20']} EMA50:{h1['ema50']}
RSI:{h1['rsi']} MACD Hist:{h1['macd_hist']}

=== M15 Entry ===
Close:{m15['close']} EMA20:{m15['ema20']} EMA50:{m15['ema50']}
RSI:{m15['rsi']} MACD Hist:{m15['macd_hist']}

วิเคราะห์ตามกฎที่กำหนดและตอบในรูปแบบที่ระบุไว้"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )

    analysis_text = response.content[0].text
    logger.info(f"Chart result: {analysis_text[:200]}")

    result = {
        "raw":           analysis_text,
        "signal":        "NO_TRADE",
        "confidence":    0,
        "sl_pips":       1000,
        "tp_pips":       1500,
        "buy_sl_pips":   buy_sl_pips,
        "sell_sl_pips":  sell_sl_pips,
        "trend":         scan["h4_bias"],
        "sr_zone":       "NONE",
        "sr_strength":   "NORMAL",
        "entry_type":    "NONE",
        "entry_score":   scan["best_score"],
        "momentum":      "—",
        "momentum_tf":   {"h4": mom_h4, "h1": mom_h1, "m15": mom_m15},
        "fib_level":     "—",           # filled by parser below
        "fib_h4":        fib_h4,
        "fib_h1":        fib_h1,
        "sr_actions":    sr_actions,
        "candle_pat":    candle_pat,
        "scan":          scan,
        "sr_zones":      {"resistance": h4_sr["resistance"] + h1_sr["resistance"],
                          "support":    h4_sr["support"]    + h1_sr["support"]},
        "key_levels":    key_lvl,
        "indicators":    {"h4":  {k: v for k, v in h4.items()  if k != "df"},
                          "h1":  {k: v for k, v in h1.items()  if k != "df"},
                          "m15": {k: v for k, v in m15.items() if k != "df"}},
    }

    for line in analysis_text.splitlines():
        if ":" not in line:
            continue
        key = line.split(":")[0].strip()
        val = line.split(":", 1)[1].strip()
        if key == "SIGNAL":
            result["signal"] = val
        elif key == "CONFIDENCE":
            try:
                result["confidence"] = int(val)
            except Exception:
                pass
        elif key == "TREND":
            result["trend"] = val
        elif key == "SR_ZONE":
            result["sr_zone"] = val.split("—")[0].strip()
        elif key == "SR_STRENGTH":
            result["sr_strength"] = val.split("—")[0].strip()
        elif key == "ENTRY_TYPE":
            result["entry_type"] = val
        elif key == "MOMENTUM":
            result["momentum"] = val
        elif key == "FIB_LEVEL":
            result["fib_level"] = val
        elif key == "SL_PIPS":
            try:
                result["sl_pips"] = float(val)
            except Exception:
                pass
        elif key == "TP_PIPS":
            try:
                result["tp_pips"] = float(val)
            except Exception:
                pass

    return result
