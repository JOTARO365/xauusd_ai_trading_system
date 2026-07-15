import os
import re
import anthropic
import json
from datetime import datetime
import pandas as pd
import numpy as np
import ta
import MetaTrader5 as mt5
from pathlib import Path
from connectors.price_feed import get_ohlcv, get_current_price
from config import ANTHROPIC_API_KEY, SYMBOL, EMA_PULLBACK_MAX_SL, EMA_PULLBACK_MIN_CONF
from loguru import logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=40.0, max_retries=1)

SYSTEM_PROMPT = json.dumps(
    json.loads(Path("agents/prompts/chart_watcher.json").read_text(encoding="utf-8")),
    separators=(",", ":"),
)

_last_usage = None   # set after each API call — read by accountant

# ── A/B SHADOW HARNESS (Phase 1+2 — พิสูจน์ terse + Haiku ก่อนสลับจริง) ──────────
# เปิดด้วย env CHART_SHADOW=true → ยิง variant "terse + Haiku" (= end state จริง) คู่ขนาน
# บน input เดียวกัน เทียบผลลง logs/shadow_chart.jsonl — ไม่แตะ result/_last_usage/การเทรด.
# shadow รอบเดียวพิสูจน์ทั้ง 2 เรื่อง: (1) terse เปลี่ยนการตัดสินใจมั้ย (2) Haiku เก่งพอมั้ย.
# ปรับ model ที่ทดสอบได้ด้วย CHART_SHADOW_MODEL (default = Haiku 4.5).
_CHART_SHADOW = (os.getenv("CHART_SHADOW") or "").strip().lower() in ("1", "true", "yes", "on")
_SHADOW_MODEL = (os.getenv("CHART_SHADOW_MODEL") or "claude-haiku-4-5-20251001").strip()

_TERSE_SUFFIX = (
    "\n\n[OUTPUT MODE: TERSE] ใช้กฎ/ข้อมูลเดิมทุกประการในการตัดสิน "
    "แต่ตอบเฉพาะฟิลด์ด้านล่างเท่านั้น — ห้าม markdown header, ห้ามเล่าซ้ำ input, "
    "ห้ามบทวิเคราะห์ยาว. (SL/TP คำนวณในโค้ด ไม่ต้องตอบ). รูปแบบ (บรรทัดละฟิลด์):\n"
    "SIGNAL: <BUY|SELL|NO_TRADE>\nCONFIDENCE: <0-100>\nTREND: <...>\n"
    "SR_ZONE: <...>\nSR_STRENGTH: <...>\nENTRY_TYPE: <...>\nMOMENTUM: <...>\n"
    "FIB_LEVEL: <...>\nREASON: <สั้น 1 บรรทัด>"
)
SYSTEM_PROMPT_TERSE = SYSTEM_PROMPT + _TERSE_SUFFIX


def _parse_chart_fields(text: str) -> dict:
    """Parse 10 ฟิลด์จาก response (กฎเดียวกับ parser หลัก) — ใช้เทียบ shadow."""
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key = line.split(":")[0].strip()
        val = line.split(":", 1)[1].strip()
        if key == "SIGNAL":
            s = val.strip().upper().split()[0] if val.strip() else ""
            if s in ("BUY", "SELL", "NO_TRADE"):
                out["signal"] = s
        elif key == "CONFIDENCE":
            try: out["confidence"] = int(val)
            except Exception: pass
        elif key == "TREND":       out["trend"] = val
        elif key == "SR_ZONE":     out["sr_zone"] = val.split("—")[0].strip()
        elif key == "SR_STRENGTH": out["sr_strength"] = val.split("—")[0].strip()
        elif key == "ENTRY_TYPE":  out["entry_type"] = val
        elif key == "MOMENTUM":    out["momentum"] = val
        elif key == "FIB_LEVEL":   out["fib_level"] = val
        elif key == "SL_PIPS":
            try: out["sl_pips"] = float(val)
            except Exception: pass
        elif key == "TP_PIPS":
            try: out["tp_pips"] = float(val)
            except Exception: pass
    return out


def _shadow_chart_call(user_message: str, real_result: dict) -> None:
    """A/B SHADOW: ยิง terse-variant บน input เดียวกัน เทียบกับของจริง.
    ไม่แตะ result/_last_usage/การเทรด — ของจริงใช้ output เดิมตลอด (zero-risk).
    เปิดด้วย env CHART_SHADOW=true."""
    if not _CHART_SHADOW:
        return
    try:
        import time as _time
        t0 = _time.monotonic()
        resp = client.messages.create(
            model=_SHADOW_MODEL,
            max_tokens=300,
            system=[{"type": "text", "text": SYSTEM_PROMPT_TERSE,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
        )
        lat = int((_time.monotonic() - t0) * 1000)
        sf  = _parse_chart_fields(resp.content[0].text)

        # SL/TP คำนวณในโค้ดแล้ว (เหมือนกันทั้ง verbose/terse) → เทียบเฉพาะ signal+confidence
        # ซึ่งคือ "การตัดสินใจเทรด" จริง.
        crit = ("signal", "confidence")
        real = {k: real_result.get(k) for k in crit}
        shad = {k: sf.get(k) for k in crit}
        sig_match  = real["signal"] == shad["signal"]
        conf_match = (real["confidence"] is not None and shad["confidence"] is not None
                      and abs(real["confidence"] - shad["confidence"]) <= 5)
        decision_match = sig_match and conf_match   # จุดชี้ขาด: terse เปลี่ยน "การตัดสินใจเทรด" มั้ย

        real_out   = getattr(_last_usage, "output_tokens", None)
        shadow_out = getattr(resp.usage, "output_tokens", None)
        rec = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "decision_match": decision_match,
            "sig_match": sig_match, "conf_match": conf_match,
            "real": real, "shadow": shad,
            "real_out_tok": real_out, "shadow_out_tok": shadow_out,
            "shadow_model": _SHADOW_MODEL,
            "shadow_lat_ms": lat,
        }
        with Path("logs/shadow_chart.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tag = "MATCH" if decision_match else "DIFF "
        logger.info(f"[SHADOW] {tag} ({_SHADOW_MODEL.split('-')[1]}) out {real_out}->{shadow_out} tok | "
                    f"real={real['signal']}/{real['confidence']} "
                    f"shadow={shad['signal']}/{shad['confidence']}")
    except Exception as e:
        logger.warning(f"[SHADOW] failed (ignored): {e}")

SR_ZONE_PCT   = 0.004   # 0.4% = "อยู่ในโซน S/R" (ขยายสำหรับ scalping)
EMA_TOUCH_PCT = 0.002   # 0.2% = "แตะ EMA"
SL_MIN_PIPS   = 500     # ลดจาก 1000 — ไม่บังคับ SL กว้างเกินในตลาดเงียบ
SL_MAX_PIPS   = 3500    # เพิ่มจาก 2000 — อนุญาต SL กว้างพอในตลาดผันผวน
ATR_SL_MULT   = 1.0     # SL ต้องไม่ต่ำกว่า 1.0× H4 ATR — ป้องกันโดน noise ปกติ

FIB_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
FIB_NAMES  = ["0%", "23.6%", "38.2%", "50%", "61.8%", "78.6%", "100%"]
FIB_KEY    = {0.382, 0.5, 0.618, 0.786}   # levels ที่สำคัญที่สุด
FIB_ZONE_PCT = 0.0025                      # 0.25% = ถือว่าอยู่ใน fib zone


# ─────────────────────────────────────────────────────────────
#  INDICATORS
# ─────────────────────────────────────────────────────────────

def calculate_indicators(rates) -> dict:
    df = pd.DataFrame(rates)
    if len(df) < 2:
        return {}
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
            if not result or result[-1] == 0 or abs(lv - result[-1]) / result[-1] > 0.002:
                result.append(lv)
        return result

    current = float(close[-1])
    resistances = sorted([h for h in dedup(swing_highs) if h > current])[:max_levels]
    supports    = sorted([l for l in dedup(swing_lows)  if l < current], reverse=True)[:max_levels]
    return {"resistance": resistances, "support": supports}


def find_liquidity_pools(df, current, window: int = 5, cluster_pct: float = 0.0015,
                         min_count: int = 2, max_pools: int = 4) -> dict:
    """DISPLAY-ONLY (UHAS #1): stop-cluster liquidity pools.
    equal highs = buy-side liquidity (BSL) เหนือราคา (stop ของ short + breakout buy) ; equal lows =
    sell-side (SSL) ใต้ราคา. count = จำนวน swing ที่เกาะกลุ่ม (ยิ่งมาก = pool หนา). ราคาชอบ 'กวาด'
    pool ก่อนกลับตัว — ต่างจาก S/R zone (จุด reject). ไม่เข้า LLM (display), zero token.
    คืน {"buy_side":[{level,count,dist_pct}], "sell_side":[...]} ; fail-soft ว่างเมื่อ df/current ไม่พอ."""
    empty = {"buy_side": [], "sell_side": []}
    if df is None or current is None or "high" not in df or len(df) < 2 * window + 1:
        return empty
    high, low = df["high"].values, df["low"].values
    n = len(high)
    sh, sl = [], []
    for i in range(window, n - window):
        if all(high[i] >= high[i-j] for j in range(1, window+1)) and all(high[i] >= high[i+j] for j in range(1, window+1)):
            sh.append(round(float(high[i]), 2))
        if all(low[i] <= low[i-j] for j in range(1, window+1)) and all(low[i] <= low[i+j] for j in range(1, window+1)):
            sl.append(round(float(low[i]), 2))
    cur = float(current)

    def cluster(levels):
        out, grp = [], []
        for lv in sorted(levels):
            if grp and (lv - grp[0]) / grp[0] > cluster_pct:
                if len(grp) >= min_count:
                    out.append((round(sum(grp) / len(grp), 2), len(grp)))
                grp = []
            grp.append(lv)
        if len(grp) >= min_count:
            out.append((round(sum(grp) / len(grp), 2), len(grp)))
        return out

    bsl = [{"level": lv, "count": c, "dist_pct": round((lv - cur) / cur * 100, 2)}
           for lv, c in cluster(sh) if lv > cur]
    ssl = [{"level": lv, "count": c, "dist_pct": round((cur - lv) / cur * 100, 2)}
           for lv, c in cluster(sl) if lv < cur]
    bsl.sort(key=lambda x: x["dist_pct"])
    ssl.sort(key=lambda x: x["dist_pct"])
    return {"buy_side": bsl[:max_pools], "sell_side": ssl[:max_pools]}


def analyze_volume_profile(df, current, recent: int = 20, n_bins: int = 24) -> dict:
    """DISPLAY-ONLY (UHAS #3): volume-by-price wall (HVN) + buy/sell imbalance.
    ⚠️ MT5 gold volume = TICK-volume (จำนวน tick) ไม่ใช่ contract volume จริง — basis ป้ายไว้เสมอ.
    wall = ช่องราคาที่ tick_volume สะสมหนาสุด (กำแพง) ; buy/sell = vol แท่งขึ้น vs ลง (recent).
    ไม่เข้า LLM (display), zero token. fail-soft → ค่า None/ว่างเมื่อ df/tick_volume ไม่พอ."""
    empty = {"wall": None, "hvn": [], "buy_pct": None, "sell_pct": None, "tilt": None,
             "basis": "tick-volume (ไม่ใช่ contract จริง)"}
    if (df is None or current is None or "tick_volume" not in df
            or "open" not in df or len(df) < 5):
        return empty
    vol   = [float(x) for x in df["tick_volume"].values]
    close = [float(x) for x in df["close"].values]
    opn   = [float(x) for x in df["open"].values]
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return empty
    width = (hi - lo) / n_bins
    bins: dict = {}
    for c, v in zip(close, vol):
        idx = min(max(int((c - lo) / width), 0), n_bins - 1) if width > 0 else 0
        bins[idx] = bins.get(idx, 0.0) + v
    total = sum(bins.values()) or 1.0
    ranked = sorted(bins.items(), key=lambda kv: kv[1], reverse=True)
    hvn = [{"level": round(lo + (i + 0.5) * width, 2), "pct": round(v / total * 100, 1)}
           for i, v in ranked[:3]]
    rc, ro, rv = close[-recent:], opn[-recent:], vol[-recent:]
    buy  = sum(v for c, o, v in zip(rc, ro, rv) if c >= o)
    sell = sum(v for c, o, v in zip(rc, ro, rv) if c < o)
    tot2 = buy + sell
    buy_pct = round(buy / tot2 * 100, 1) if tot2 else None
    sell_pct = round(100 - buy_pct, 1) if buy_pct is not None else None
    tilt = None
    if buy_pct is not None:
        tilt = "buy" if buy_pct >= 58 else "sell" if buy_pct <= 42 else "balanced"
    return {"wall": (hvn[0] if hvn else None), "hvn": hvn, "buy_pct": buy_pct,
            "sell_pct": sell_pct, "tilt": tilt, "basis": "tick-volume (ไม่ใช่ contract จริง)"}


def detect_htf_zone(current: float, d1_sr: dict, w1_sr: dict,
                    threshold_pct: float = 0.5) -> dict | None:
    """
    ตรวจว่าราคาปัจจุบันอยู่ใกล้ D1 หรือ W1 S/R zone มั้ย
    threshold_pct: ห่างได้ไม่เกิน X% ของราคา (default 0.5%)
    คืน: {"tf": "W1"|"D1", "level": float, "zone_type": "SUPPORT"|"RESISTANCE", "dist_pct": float}
    หรือ None ถ้าไม่อยู่ใกล้
    """
    best = None
    for tf_name, sr in [("W1", w1_sr), ("D1", d1_sr)]:
        for zone_type, levels in [("RESISTANCE", sr["resistance"]), ("SUPPORT", sr["support"])]:
            for lv in levels:
                dist_pct = abs(current - lv) / current * 100
                if dist_pct <= threshold_pct:
                    if best is None or dist_pct < best["dist_pct"] or tf_name == "W1":
                        best = {"tf": tf_name, "level": lv,
                                "zone_type": zone_type, "dist_pct": round(dist_pct, 3)}
    return best


def format_htf_sr_text(d1_sr: dict, w1_sr: dict, current: float) -> str:
    lines = ["=== Major S/R Zones (D1 + W1) ==="]
    for tf_name, sr in [("W1", w1_sr), ("D1", d1_sr)]:
        res = sr["resistance"][:3]
        sup = sr["support"][:3]
        dists_r = [f"{lv} ({abs(current-lv)/current*100:.2f}%↑)" for lv in res]
        dists_s = [f"{lv} ({abs(current-lv)/current*100:.2f}%↓)" for lv in sup]
        lines.append(f"{tf_name} Resistance: {', '.join(dists_r) or 'none'}")
        lines.append(f"{tf_name} Support   : {', '.join(dists_s) or 'none'}")
    return "\n".join(lines)


def find_key_levels(df: pd.DataFrame) -> dict:
    close = float(df["close"].iloc[-1])
    prev_day = df.iloc[-48:-24] if len(df) >= 48 else df.iloc[:len(df)//2]
    pdh = round(float(prev_day["high"].max()), 2) if len(prev_day) > 0 else 0
    pdl = round(float(prev_day["low"].min()), 2)  if len(prev_day) > 0 else 0
    base      = round(close / 50) * 50
    rounds    = [base + i * 50 for i in range(-3, 4)]
    round_lvl = [r for r in rounds if abs(r - close) / close > 0.001]
    return {"pdh": pdh, "pdl": pdl, "round_numbers": round_lvl}


def calc_sl_atr_floor(h4_atr: float) -> int:
    """คำนวณ SL ขั้นต่ำจาก H4 ATR — ป้องกัน SL แคบกว่า noise ปกติของ H4"""
    if h4_atr <= 0:
        return SL_MIN_PIPS
    point = 0.01
    atr_pips = round(h4_atr / point * ATR_SL_MULT)
    return max(SL_MIN_PIPS, min(SL_MAX_PIPS, atr_pips))


def _sane_atr(h4: dict) -> float:
    """กัน H4 ATR เพี้ยนช่วง thin/holiday market — clamp ATR ปัจจุบันให้อยู่ในช่วง median 20 แท่ง.
    ATR ตัวเดียว (แท่งล่าสุด) สูง/ต่ำผิดปกติ → SL แคบหรือกว้างเกินจริง. ใช้ median เป็นกรอบสมเหตุผล.
    """
    cur = float(h4.get("atr", 0.0) or 0.0)
    df  = h4.get("df")
    try:
        if df is not None and "atr" in df.columns and len(df) >= 20:
            import numpy as np
            med = float(np.nanmedian(df["atr"].tail(20).to_numpy()))
            if med > 0:
                return float(min(max(cur, 0.4 * med), 2.5 * med))
    except Exception:
        pass
    return cur


def calc_sl_from_wick(m15: dict, direction: str, h4_atr: float = 0.0) -> int:
    """SL = max(prev M15 wick distance, ATR-based floor)
    - wick SL: ปลาย wick แท่งก่อนหน้า M15
    - ATR floor: SL ต้องไม่น้อยกว่า ATR_SL_MULT × H4 ATR
    - clamp: SL_MIN_PIPS – SL_MAX_PIPS
    """
    point = 0.01
    if direction == "BUY":
        wick_pips = round((m15["close"] - m15["prev_low"]) / point)
    else:
        wick_pips = round((m15["prev_high"] - m15["close"]) / point)
    wick_pips = max(wick_pips, 0)
    atr_floor = calc_sl_atr_floor(h4_atr)
    # ใช้ค่าที่กว้างกว่า: wick vs ATR floor — ป้องกันโดนทั้งสองทาง
    sl = max(wick_pips, atr_floor)
    return max(SL_MIN_PIPS, min(SL_MAX_PIPS, sl))


def compute_tp_pips(signal: str, price: float, sl_pips: float,
                    levels: list, min_rr: float = 2.0) -> int:
    """TP = next S/R level in trade direction, อย่างน้อย min_rr × SL; ถ้าไม่มี zone → min_rr × SL.
    คำนวณในโค้ด (deterministic, auditable) — แทนการให้ LLM ตอบ TP_PIPS.
    ตรงตาม tp_rule ใน chart_watcher.json: target=next_sr_in_direction, min_rr=2.0.
    """
    point = 0.01
    floor = sl_pips * min_rr
    cands = []
    for lv in levels or []:
        try:
            dist = (lv - price) if signal == "BUY" else (price - lv)
        except Exception:
            continue
        if dist > 0:
            cands.append(dist / point)          # แปลงเป็น pips
    qualifying = [c for c in cands if c >= floor]
    return int(round(min(qualifying) if qualifying else floor))


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
#  DISPLAY-ONLY (0-token) — เทคนิคจากคลิป LIVE ทองคำ 14 ก.ค. (kInccbPzQFs)
#  ทั้ง 3 = compute-in-code, ใส่ใน output dict (ไม่ส่งเข้า LLM เหมือน sr_meta)
# ─────────────────────────────────────────────────────────────

def suggest_retrace_entry(df, direction, retrace=0.5, point=0.01):
    """GAP1: แทนที่จะเข้าที่ราคาปิดของแท่ง signal — เสนอ 'รอราคาย่อกลับเข้าไส้' แล้วเข้า, SL แค่พ้น
    extreme ของแท่ง → SL แคบลง R:R ดีขึ้น. เทียบ SL wick-fill vs close-fill. คืน None ถ้าข้อมูลไม่พอ."""
    if df is None or len(df) < 1 or direction not in ("BUY", "SELL"):
        return None
    c = df.iloc[-1]
    hi, lo, close = float(c["high"]), float(c["low"]), float(c["close"])
    rng = hi - lo
    if rng <= 0:
        return None
    buf = rng * 0.10   # SL เผื่อพ้น extreme เล็กน้อย
    if direction == "BUY":
        suggested = round(close - rng * retrace, 2)   # รอย่อลงเข้าไส้ล่าง
        sl        = round(lo - buf, 2)
        close_sl  = round((close - sl) / point)
        wick_sl   = round((suggested - sl) / point)
    else:
        suggested = round(close + rng * retrace, 2)   # รอเด้งขึ้นเข้าไส้บน
        sl        = round(hi + buf, 2)
        close_sl  = round((sl - close) / point)
        wick_sl   = round((sl - suggested) / point)
    if wick_sl <= 0 or close_sl <= 0:
        return None
    return {"direction": direction, "suggested_entry": suggested, "tight_sl": sl,
            "close_sl_pips": close_sl, "wick_sl_pips": wick_sl,
            "sl_tighter_pct": round((close_sl - wick_sl) / close_sl * 100)}


def classify_market_structure(df, window=3, lookback=60, eq_pct=0.0008):
    """GAP2: label โครงสร้างตลาดจาก swing highs/lows ล่าสุด →
    UPTREND(HH+HL) / DOWNTREND(LH+LL) / ACCUMULATION(low ยก + high เสมอ) /
    DISTRIBUTION(high ต่ำลง + low เสมอ) / RANGE. Display-only. คืน None ถ้า swing ไม่พอ."""
    if df is None or len(df) < window * 2 + 2:
        return None
    r = df.tail(lookback)
    highs, lows = [], []
    hv, lv = r["high"].values, r["low"].values
    for i in range(window, len(r) - window):
        if all(hv[i] >= hv[i - j] for j in range(1, window + 1)) and \
           all(hv[i] >= hv[i + j] for j in range(1, window + 1)):
            highs.append(float(hv[i]))
        if all(lv[i] <= lv[i - j] for j in range(1, window + 1)) and \
           all(lv[i] <= lv[i + j] for j in range(1, window + 1)):
            lows.append(float(lv[i]))
    if len(highs) < 2 or len(lows) < 2:
        return None
    def _cmp(a, b):
        if abs(a - b) <= b * eq_pct: return "EQ"
        return "UP" if a > b else "DN"
    h, l = _cmp(highs[-1], highs[-2]), _cmp(lows[-1], lows[-2])
    if   h == "UP" and l == "UP": state, why = "UPTREND",      "HH + HL"
    elif h == "DN" and l == "DN": state, why = "DOWNTREND",    "LH + LL"
    elif l == "UP" and h == "EQ": state, why = "ACCUMULATION", "low ยก, high เสมอ (ยังไม่ยืนยัน)"
    elif h == "DN" and l == "EQ": state, why = "DISTRIBUTION", "high ต่ำลง, low เสมอ (ยังไม่ยืนยัน)"
    else:                         state, why = "RANGE",        f"H:{h} L:{l}"
    return {"state": state, "why": why, "last_high": highs[-1], "last_low": lows[-1]}


def reversal_confirm_status(df, sr_actions):
    """GAP3: reversal PA ที่ zone ต้องมีแท่งถัดไปยืนยันก่อนเข้า. คืน status:
    'confirmed' = แท่งล่าสุด follow-through ทิศ reversal | 'waiting' = ยังไม่ยืนยัน. None ถ้าไม่มี rejection."""
    rej = next((a for a in (sr_actions or []) if a.get("action") == "REJECTION"), None)
    if not rej:
        return None
    d = rej.get("direction")
    if df is None or len(df) < 1 or d not in ("BUY", "SELL"):
        return {"status": "waiting", "direction": d, "note": "reversal ที่ zone — รอแท่งถัดไปยืนยัน"}
    last = df.iloc[-1]
    bull = float(last["close"]) > float(last["open"])
    follow = (bull and d == "BUY") or (not bull and d == "SELL")
    return ({"status": "confirmed", "direction": d, "note": "แท่งล่าสุดยืนยันทิศ reversal แล้ว"}
            if follow else
            {"status": "waiting", "direction": d, "note": "reversal ที่ zone — แท่งล่าสุดยังไม่ตามทิศ รอยืนยัน"})


# ─────────────────────────────────────────────────────────────
#  ENTRY SETUP SCANNER  ← ใหม่
# ─────────────────────────────────────────────────────────────

def _check_h1_structure(df: pd.DataFrame, direction: str, lookback: int = 40) -> bool:
    """
    ตรวจ price structure บน H1 — BUY ต้องการ higher lows, SELL ต้องการ lower highs
    คืน True ถ้า structure สนับสนุน direction
    ใช้ swing lows/highs 3 จุดล่าสุดใน lookback bars
    """
    recent = df.tail(lookback)
    window = 3

    if direction == "BUY":
        lows = []
        for i in range(window, len(recent) - window):
            row_low = float(recent["low"].iloc[i])
            if all(row_low <= float(recent["low"].iloc[i - j]) for j in range(1, window + 1)) and \
               all(row_low <= float(recent["low"].iloc[i + j]) for j in range(1, window + 1)):
                lows.append(row_low)
        if len(lows) < 2:
            return True   # ข้อมูลน้อยเกินไป → ไม่บล็อก
        return lows[-1] >= lows[-2]   # higher low = structure ดี

    else:  # SELL
        highs = []
        for i in range(window, len(recent) - window):
            row_high = float(recent["high"].iloc[i])
            if all(row_high >= float(recent["high"].iloc[i - j]) for j in range(1, window + 1)) and \
               all(row_high >= float(recent["high"].iloc[i + j]) for j in range(1, window + 1)):
                highs.append(row_high)
        if len(highs) < 2:
            return True
        return highs[-1] <= highs[-2]   # lower high = structure ดี


def _count_zone_touches(df: pd.DataFrame, level: float, zone_pct: float = 0.003) -> int:
    """นับจำนวน 'visit' ที่ราคาเข้ามาในโซน level (ไม่นับแท่งต่อเนื่องเป็นหลาย touch)"""
    zone = level * zone_pct
    touches, in_zone = 0, False
    for h, l in zip(df["high"].values, df["low"].values):
        hit = l <= level + zone and h >= level - zone
        if hit and not in_zone:
            touches += 1
        in_zone = hit
    return touches


def _touch_score_bonus(touches: int) -> int:
    """แปลง touch count → score bonus (2026-06-30: เพิ่มน้ำหนัก multi-touch zone)
    2-4 touches = zone แข็งแกร่ง (ราคากลับมาหลายรอบ) → bonus มากขึ้น
    5+ touches  = zone อ่อนแอ ใกล้แตก → penalty (คงไว้ — worn zone มักทะลุ = fade เสี่ยง)"""
    if touches <= 1:  return 0    # fresh — ยังไม่ proven
    if touches <= 4:  return 15   # 2-4 touches = sweet spot (เดิม 10 → 15)
    if touches <= 6:  return 8    # 5-6 = ยังดีแต่เริ่มอ่อน (เดิม 5 → 8)
    return -10                    # 7+ = worn zone, risk of break (คงเดิม)


def _touch_recency_bounce(df: pd.DataFrame, level: float, side: str,
                          zone_pct: float = 0.003, fwd: int = 10) -> tuple:
    """DISPLAY-ONLY (UHAS #2): (bars_since_touch, avg_bounce_$) ต่อ zone.
    bars_since_touch = แท่งนับจากที่ราคาแตะโซนครั้งล่าสุด.
    avg_bounce = ค่าเฉลี่ย $ ที่ราคาเด้งออกจากโซนภายใน fwd แท่ง หลัง touch (ทิศตาม side:
      S=เด้งขึ้น, R=สะบัดลง) เฉลี่ยจาก 5 touch ล่าสุด. คืน (None, None) ถ้าไม่มี touch/df.
    ไม่กระทบ logic เทรด — ไม่ถูกส่งเข้า LLM (sr_meta = display)."""
    if df is None or "high" not in df or "low" not in df:
        return None, None
    highs, lows = df["high"].values, df["low"].values
    n = len(highs)
    zone = level * zone_pct
    touch_idx, in_zone = [], False
    for i in range(n):
        hit = lows[i] <= level + zone and highs[i] >= level - zone
        if hit and not in_zone:
            touch_idx.append(i)
        in_zone = hit
    if not touch_idx:
        return None, None
    bars_since = int((n - 1) - touch_idx[-1])
    bounces = []
    for i in touch_idx[-5:]:
        j0, j1 = i + 1, min(i + 1 + fwd, n)
        if j0 >= n:
            continue
        exc = (float(highs[j0:j1].max()) - level) if side == "S" else (level - float(lows[j0:j1].min()))
        if exc > 0:
            bounces.append(exc)
    avg_bounce = round(sum(bounces) / len(bounces), 1) if bounces else None
    return bars_since, avg_bounce


def _break_bounce_stats(df: pd.DataFrame, level: float, side: str,
                        zone_pct: float = 0.003, fwd: int = 8,
                        margin_pct: float = 0.0012) -> tuple:
    """DISPLAY-ONLY (คลิป n0ate2cd5AY): (bounce_pct, break_pct, n_tests) ต่อแนว.
    ทุกครั้งที่ราคาเข้าโซนแนว ดูใน fwd แท่งถัดไปว่า 'ทะลุ' (close ข้ามเกิน margin)
    หรือ 'เด้ง' (ไม่ผ่าน). R=แนวต้าน (break=ปิดเหนือ), S=แนวรับ (break=ปิดใต้).
    คืน (None,None,n) ถ้า test < 3 (สถิติน้อยไป). ไม่ส่งเข้า LLM (sr_meta = display)."""
    if df is None or "high" not in df or "low" not in df or "close" not in df:
        return None, None, 0
    highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
    n = len(highs)
    zone, margin = level * zone_pct, level * margin_pct
    in_zone = False
    breaks = tests = 0
    for i in range(n):
        hit = lows[i] <= level + zone and highs[i] >= level - zone
        if hit and not in_zone:
            j0, j1 = i + 1, min(i + 1 + fwd, n)
            if j0 < n:
                window = closes[j0:j1]
                broke = bool((window > level + margin).any()) if side == "R" \
                    else bool((window < level - margin).any())
                tests += 1
                breaks += 1 if broke else 0
        in_zone = hit
    if tests < 3:
        return None, None, tests
    break_pct = round(100 * breaks / tests)
    return 100 - break_pct, break_pct, tests


def _break_hold_status(df: pd.DataFrame, level: float, side: str,
                       hold_n: int = 3, margin_pct: float = 0.0006) -> dict | None:
    """DISPLAY-ONLY (คลิป n0ate2cd5AY): ยืนยันเบรก = ปิด 'ยืน' ข้ามแนว ไม่ใช่แค่ไส้เทียน.
    ดู hold_n แท่งล่าสุด. R: held=ปิดยืนเหนือแนว, S: held=ปิดยืนใต้แนว. wick=ไส้ทะลุแต่ปิดกลับ.
    คืน {"status","closes"} หรือ None ถ้าราคายังไม่แตะแนวใน N แท่ง (แนวไกล = ไม่โชว์). ไม่ส่งเข้า LLM."""
    if df is None or "high" not in df or "low" not in df or "close" not in df:
        return None
    if len(df) < hold_n:
        return None
    highs  = df["high"].values[-hold_n:]
    lows   = df["low"].values[-hold_n:]
    closes = df["close"].values[-hold_n:]
    margin = level * margin_pct
    if side == "R":
        pierced = bool((highs > level + margin).any())
        closes_beyond = int((closes > level + margin).sum())
    else:
        pierced = bool((lows < level - margin).any())
        closes_beyond = int((closes < level - margin).sum())
    if not pierced and closes_beyond == 0:
        return None
    if closes_beyond >= 2:
        status = "held"
    elif pierced:
        status = "wick"
    else:
        return None
    return {"status": status, "closes": closes_beyond}


def _tag_confluence(meta: list, fib_h4: dict, fib_h1: dict,
                    cluster_pct: float = 0.0015) -> None:
    """DISPLAY-ONLY (คลิป n0ate2cd5AY): mark แนวที่ 'ชนกัน' หลายที่ = โซนแข็ง.
    หาแนว sr_meta ที่มีแนวโครงสร้างอื่นอยู่ในระยะ cluster_pct (~$6 ที่ทอง 4000):
      • แนว sr_meta อีก TF, • fib key level (H4/H1).
    เติม field 'confluence' = {"with":[label...], "count":n} ใน meta ที่มี ≥1 partner.
    แก้ meta in-place. ไม่ส่งเข้า LLM."""
    def _fib_keys(fib: dict, tf: str) -> list:
        out = []
        for p, v in (fib or {}).get("levels", {}).items():
            if v[2]:                       # is_key
                out.append((float(p), f"fib {v[1]} {tf}"))
        return out

    anchors = _fib_keys(fib_h4, "H4") + _fib_keys(fib_h1, "H1")
    for i, m in enumerate(meta):
        lv = m["level"]
        band = lv * cluster_pct
        partners = []
        for j, other in enumerate(meta):
            if j != i and abs(other["level"] - lv) <= band:
                partners.append(f"{other['tf']} {other['side']}")
        for plv, plabel in anchors:
            if abs(plv - lv) <= band:
                partners.append(plabel)
        if partners:
            m["confluence"] = {"with": partners[:3], "count": len(partners)}


def _build_sr_meta(h4_sr: dict, h1_sr: dict, key_lvl: dict,
                   d1_sr: dict | None, w1_sr: dict | None,
                   h4_df, h1_df,
                   fib_h4: dict | None = None, fib_h1: dict | None = None) -> list:
    """Metadata ต่อ S/R level สำหรับ dashboard (07-03): strength % + เหตุผลว่าทำไมวาง level นี้
    เกณฑ์เดียวกับ setup scanner — touches (_touch_score_bonus) + HTF confluence + key-level confluence
    ไม่กระทบ logic เทรดใดๆ (display เท่านั้น)"""
    d1_levels = (d1_sr.get("resistance", []) + d1_sr.get("support", [])) if d1_sr else []
    w1_levels = (w1_sr.get("resistance", []) + w1_sr.get("support", [])) if w1_sr else []
    rounds    = key_lvl.get("round_numbers") or []
    pdh, pdl  = key_lvl.get("pdh"), key_lvl.get("pdl")

    def _one(lv: float, side: str, tf: str, df) -> dict:
        score = 60 if tf == "H4" else 50            # H4 swing น่าเชื่อถือกว่า H1
        why   = [f"{tf} swing"]
        touches = _count_zone_touches(df, lv) if df is not None else 0
        tb = _touch_score_bonus(touches)
        score += tb
        if touches >= 2:
            why.append(f"แตะ {touches} ครั้ง" + (" — ใกล้สึก/เสี่ยงทะลุ" if tb < 0 else " (proven)"))
        if any(abs(lv - x) / lv < 0.003 for x in d1_levels):
            score += 20; why.append("ตรงโซน D1")
        elif any(abs(lv - x) / lv < 0.003 for x in w1_levels):
            score += 20; why.append("ตรงโซน W1")
        if pdh and abs(lv - pdh) / lv < 0.0015:
            score += 5; why.append("≈PDH")
        if pdl and abs(lv - pdl) / lv < 0.0015:
            score += 5; why.append("≈PDL")
        if any(abs(lv - r) / lv < 0.001 for r in rounds):
            score += 3; why.append("เลขกลม")
        bars_since, avg_bounce = _touch_recency_bounce(df, lv, side)   # UHAS #2 (display-only)
        bounce_pct, break_pct, n_tests = _break_bounce_stats(df, lv, side)  # A (display-only)
        return {"level": round(float(lv), 2), "side": side, "tf": tf, "touches": touches,
                "bars_since_touch": bars_since, "avg_bounce": avg_bounce,
                "bounce_pct": bounce_pct, "break_pct": break_pct, "n_tests": n_tests,
                "break_hold": _break_hold_status(df, lv, side),          # B (display-only)
                "strength": max(25, min(95, score)), "why": " · ".join(why)}

    meta  = [_one(lv, "R", "H4", h4_df) for lv in h4_sr.get("resistance", [])]
    meta += [_one(lv, "S", "H4", h4_df) for lv in h4_sr.get("support", [])]
    meta += [_one(lv, "R", "H1", h1_df) for lv in h1_sr.get("resistance", [])]
    meta += [_one(lv, "S", "H1", h1_df) for lv in h1_sr.get("support", [])]
    _tag_confluence(meta, fib_h4 or {}, fib_h1 or {})                    # C (display-only)
    return meta


def _check_bb_squeeze(df: pd.DataFrame, lookback: int = 10) -> bool:
    """
    คืน True ถ้า BB กำลัง squeeze (width ปัจจุบัน < 85% ของ width เฉลี่ย lookback bars)
    BB touch ระหว่าง squeeze มีความหมายกว่า touch ระหว่าง expansion
    """
    if "bb_upper" not in df.columns or "bb_mid" not in df.columns:
        return False
    bb_width = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"].replace(0, float("nan"))
    if len(bb_width.dropna()) < lookback + 1:
        return False
    current_w = float(bb_width.iloc[-1])
    avg_w     = float(bb_width.iloc[-lookback - 1:-1].mean())
    return avg_w > 0 and current_w < avg_w * 0.85


def scan_entry_setups(h4: dict, h1: dict, m15: dict,
                      h4_sr: dict, h1_sr: dict, key_lvl: dict,
                      d1_sr: dict | None = None, w1_sr: dict | None = None) -> dict:
    """
    สแกนหา entry setup จากทุก timeframe และ S/R
    คืน dict: setups (list), best_direction, best_score, confluence_count, h4_bias
    """
    price = h4["close"]
    setups: list[dict] = []

    # ── H4 Bias — multi-component (ไม่ใช้ EMA200 อย่างเดียว) ──
    # Component 1: EMA200 position (lagging แต่ยังต้องการ — long-term anchor)
    ema200_dist_pct = abs(price - h4["ema200"]) / h4["ema200"] if h4["ema200"] else 0
    ema200_bull = price > h4["ema200"]

    # Component 2: H4 EMA50 direction — EMA50 slope = ทิศทางกลางเร็วกว่า EMA200
    h4_df = h4.get("df")
    ema50_slope_bull = False
    if h4_df is not None and "ema50" in h4_df.columns and len(h4_df) >= 5:
        ema50_now  = float(h4_df["ema50"].iloc[-1])
        ema50_prev = float(h4_df["ema50"].iloc[-5])
        ema50_slope_bull = ema50_now > ema50_prev

    # Component 3: H1 structure — H1 EMA stack (more responsive)
    h1_df = h1.get("df")
    h1_ema_bull = h1["close"] > h1["ema20"] > h1["ema50"]
    h1_ema_bear = h1["close"] < h1["ema20"] < h1["ema50"]

    # Component 4: recent swing structure on H4 — higher highs / lower lows
    h4_struct_bull = False
    h4_struct_bear = False
    if h4_df is not None and len(h4_df) >= 20:
        recent_h4 = h4_df.tail(20)
        h4_high_now  = float(recent_h4["high"].iloc[-1])
        h4_high_prev = float(recent_h4["high"].iloc[-10])
        h4_low_now   = float(recent_h4["low"].iloc[-1])
        h4_low_prev  = float(recent_h4["low"].iloc[-10])
        h4_struct_bull = h4_high_now > h4_high_prev and h4_low_now > h4_low_prev
        h4_struct_bear = h4_high_now < h4_high_prev and h4_low_now < h4_low_prev

    # ── รวม score: BULLISH ≥ 3 component, BEARISH ≥ 3 component
    bull_score = sum([ema200_bull, ema50_slope_bull, h1_ema_bull, h4_struct_bull])
    bear_score = sum([not ema200_bull, not ema50_slope_bull, h1_ema_bear, h4_struct_bear])

    if bull_score >= 3:
        h4_bias = "BULLISH"
    elif bear_score >= 3:
        h4_bias = "BEARISH"
    elif ema200_dist_pct < 0.005 or (bull_score == bear_score):
        h4_bias = "SIDEWAYS"
    elif bull_score > bear_score:
        h4_bias = "BULLISH"
    else:
        h4_bias = "BEARISH"

    # ── 1. S/R Zone (H4 + H1) ────────────────────────────────
    zone     = price * SR_ZONE_PCT
    m15_bias = "BULLISH" if m15["close"] > m15["ema20"] else "BEARISH"

    # [C] Zone-direction context: AT resistance → bias SELL, AT support → bias BUY
    at_resistance = any(abs(price - r) <= zone for r in h4_sr["resistance"])
    at_support    = any(abs(price - s) <= zone for s in h4_sr["support"])

    # [B] รวม HTF levels สำหรับ confluence check
    htf_levels: list[float] = []
    if d1_sr:
        htf_levels += d1_sr.get("resistance", []) + d1_sr.get("support", [])
    if w1_sr:
        htf_levels += w1_sr.get("resistance", []) + w1_sr.get("support", [])

    h4_df_ref = h4.get("df")   # สำหรับ touch count

    h4_levels = (
        h4_sr["resistance"] + h4_sr["support"] +
        ([key_lvl["pdh"]] if key_lvl["pdh"] else []) +
        ([key_lvl["pdl"]] if key_lvl["pdl"] else []) +
        key_lvl["round_numbers"]
    )
    for lv in h4_levels:
        if abs(price - lv) <= zone:
            direction  = "SELL" if lv >= price else "BUY"
            m15_align  = (direction == "BUY" and m15_bias == "BULLISH") or \
                         (direction == "SELL" and m15_bias == "BEARISH")
            h1_struct  = _check_h1_structure(h1["df"], direction)
            base_score = 80 if m15_align else 65
            bonus_notes = []

            # [+] H1 structure bonus
            if h1_struct:
                base_score = min(100, base_score + 10)
                bonus_notes.append("H1_struct")

            # [A] Touch count bonus
            if h4_df_ref is not None:
                touches = _count_zone_touches(h4_df_ref, lv)
                tb = _touch_score_bonus(touches)
                if tb != 0:
                    base_score = max(0, min(100, base_score + tb))
                    bonus_notes.append(f"touch={touches}({'+' if tb>0 else ''}{tb})")

            # [B] HTF confluence bonus
            htf_match = any(abs(lv - hl) / lv < 0.003 for hl in htf_levels) if htf_levels else False
            if htf_match:
                base_score = min(100, base_score + 20)
                bonus_notes.append("HTF_confluence+20")

            # [C] Zone-direction lock: AT resistance favors SELL, AT support favors BUY
            if at_resistance and direction == "SELL":
                base_score = min(100, base_score + 15)
                bonus_notes.append("at_resistance+15")
            elif at_resistance and direction == "BUY":
                base_score = max(0, base_score - 20)
                bonus_notes.append("at_resistance-20")
            elif at_support and direction == "BUY":
                base_score = min(100, base_score + 15)
                bonus_notes.append("at_support+15")
            elif at_support and direction == "SELL":
                base_score = max(0, base_score - 20)
                bonus_notes.append("at_support-20")

            bonus_str = f" [{', '.join(bonus_notes)}]" if bonus_notes else ""
            setups.append({
                "type": "SR_ZONE", "tf": "H4", "direction": direction,
                "score": base_score, "level": lv,
                "note": (f"H4 S/R {lv:.2f} ({direction}) M15={'align' if m15_align else 'counter'}"
                         + bonus_str)
            })

    # ── 1b. H1 S/R Zone ──────────────────────────────────────
    h1_df_ref = h1.get("df")
    h1_levels = h1_sr["resistance"] + h1_sr["support"]
    for lv in h1_levels:
        if abs(price - lv) <= zone:
            direction  = "SELL" if lv >= price else "BUY"
            m15_align  = (direction == "BUY" and m15_bias == "BULLISH") or \
                         (direction == "SELL" and m15_bias == "BEARISH")
            h1_struct  = _check_h1_structure(h1["df"], direction)
            base_score = 72 if m15_align else 58
            bonus_notes = []

            if h1_struct:
                base_score = min(100, base_score + 8)
                bonus_notes.append("H1_struct")

            # [A] Touch count (H1 df)
            if h1_df_ref is not None:
                touches = _count_zone_touches(h1_df_ref, lv)
                tb = _touch_score_bonus(touches)
                if tb != 0:
                    base_score = max(0, min(100, base_score + tb))
                    bonus_notes.append(f"touch={touches}({'+' if tb>0 else ''}{tb})")

            # [B] HTF confluence (H1 ได้ bonus ครึ่งหนึ่ง)
            htf_match = any(abs(lv - hl) / lv < 0.003 for hl in htf_levels) if htf_levels else False
            if htf_match:
                base_score = min(100, base_score + 10)
                bonus_notes.append("HTF_confluence+10")

            # [C] Zone-direction lock
            at_res_h1 = any(abs(price - r) <= zone for r in h1_sr["resistance"])
            at_sup_h1 = any(abs(price - s) <= zone for s in h1_sr["support"])
            if at_res_h1 and direction == "SELL":
                base_score = min(100, base_score + 10)
                bonus_notes.append("at_res+10")
            elif at_res_h1 and direction == "BUY":
                base_score = max(0, base_score - 15)
                bonus_notes.append("at_res-15")
            elif at_sup_h1 and direction == "BUY":
                base_score = min(100, base_score + 10)
                bonus_notes.append("at_sup+10")
            elif at_sup_h1 and direction == "SELL":
                base_score = max(0, base_score - 15)
                bonus_notes.append("at_sup-15")

            bonus_str = f" [{', '.join(bonus_notes)}]" if bonus_notes else ""
            setups.append({
                "type": "SR_ZONE", "tf": "H1", "direction": direction,
                "score": base_score, "level": lv,
                "note": (f"H1 S/R {lv:.2f} ({direction}) M15={'align' if m15_align else 'counter'}"
                         + bonus_str)
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

    # ── 3. Bollinger Band H4 — ต้องมี BB squeeze ก่อน ───────
    # BB touch ระหว่าง expansion = momentum trade ไม่ใช่ reversal
    # BB touch หลัง squeeze = reversal setup มี edge จริง
    _h4_df    = h4.get("df")
    _bb_sqz   = _check_bb_squeeze(_h4_df) if _h4_df is not None else False
    _bb_score = 68 if _bb_sqz else 52   # squeeze → higher score

    if price <= h4["bb_lower"] * 1.001 and h4_bias != "BEARISH":
        setups.append({
            "type": "BB_LOWER", "tf": "H4", "direction": "BUY",
            "score": _bb_score, "level": h4["bb_lower"],
            "note": (f"BB Lower H4 ({h4['bb_lower']:.2f})"
                     + (" [SQUEEZE→reversal]" if _bb_sqz else " [expansion—weak]"))
        })
    if price >= h4["bb_upper"] * 0.999 and h4_bias != "BULLISH":
        setups.append({
            "type": "BB_UPPER", "tf": "H4", "direction": "SELL",
            "score": _bb_score, "level": h4["bb_upper"],
            "note": (f"BB Upper H4 ({h4['bb_upper']:.2f})"
                     + (" [SQUEEZE→reversal]" if _bb_sqz else " [expansion—weak]"))
        })

    # ── 4. EMA Pullback H1 ───────────────────────────────────
    # ราคา H1 กลับมาแตะ EMA20 + ต้องการ candle body ≥ 40% เพื่อยืนยัน bounce
    h1_ema20_dist = abs(h1["close"] - h1["ema20"]) / h1["ema20"] if h1["ema20"] else 1
    if h1_ema20_dist < EMA_TOUCH_PCT:
        _h1_df = h1.get("df")
        _h1_body_ok = False
        if _h1_df is not None and len(_h1_df) >= 1:
            _c = _h1_df.iloc[-1]
            _rng = float(_c["high"]) - float(_c["low"])
            _body = abs(float(_c["close"]) - float(_c["open"]))
            _h1_body_ok = _rng > 0 and (_body / _rng) >= 0.40

        if h4_bias == "BULLISH" and h1["close"] >= h1["ema20"] and _h1_body_ok:
            setups.append({
                "type": "EMA_PULLBACK", "tf": "H1", "direction": "BUY",
                "score": 60, "level": h1["ema20"],
                "note": f"H1 pullback EMA20 ({h1['ema20']:.2f}) Bullish + candle body OK"
            })
        elif h4_bias == "BEARISH" and h1["close"] <= h1["ema20"] and _h1_body_ok:
            setups.append({
                "type": "EMA_PULLBACK", "tf": "H1", "direction": "SELL",
                "score": 60, "level": h1["ema20"],
                "note": f"H1 pullback EMA20 ({h1['ema20']:.2f}) Bearish + candle body OK"
            })

    # ── 5. Structure Pullback H1 (แทน EMA_CROSS + MACD_CROSS) ──
    # EMA stack aligned (close > EMA20 > EMA50 = bull stack) ยืนยัน trend
    # + ราคา pullback มาแตะ EMA50 H1 (deeper pullback = more room)
    # + H1 structure ดี (higher lows / lower highs)
    # ดีกว่า EMA_CROSS/MACD_CROSS ตรงที่ไม่ใช่ lagging signal
    h1_ema50_dist = abs(h1["close"] - h1["ema50"]) / h1["ema50"] if h1["ema50"] else 1
    h1_bull_stack = h1["close"] > h1["ema20"] > h1["ema50"]
    h1_bear_stack = h1["close"] < h1["ema20"] < h1["ema50"]

    if h1_ema50_dist < EMA_TOUCH_PCT * 1.5:   # pullback ถึง EMA50 H1
        if h4_bias == "BULLISH" and h1_bull_stack:
            h1_struct = _check_h1_structure(h1["df"], "BUY")
            if h1_struct:
                setups.append({
                    "type": "STRUCTURE_PULLBACK", "tf": "H1", "direction": "BUY",
                    "score": 70, "level": h1["ema50"],
                    "note": (f"H1 bull stack pullback EMA50 ({h1['ema50']:.2f})"
                             " | higher lows confirmed")
                })
        elif h4_bias == "BEARISH" and h1_bear_stack:
            h1_struct = _check_h1_structure(h1["df"], "SELL")
            if h1_struct:
                setups.append({
                    "type": "STRUCTURE_PULLBACK", "tf": "H1", "direction": "SELL",
                    "score": 70, "level": h1["ema50"],
                    "note": (f"H1 bear stack pullback EMA50 ({h1['ema50']:.2f})"
                             " | lower highs confirmed")
                })

    # ── 7. RSI Extreme M15 — ต้องมี H1 structure สนับสนุน ────
    # RSI ที่ extreme เดียวๆ บน M15 fire บ่อยมาก และมักเป็น noise
    # เพิ่มเงื่อนไข: H1 ต้องสนับสนุนทิศทาง (EMA stack) ด้วย
    if m15["rsi"] < 30 and h4_bias == "BULLISH" and h1["close"] > h1["ema50"]:
        setups.append({
            "type": "RSI_OVERSOLD", "tf": "M15", "direction": "BUY",
            "score": 60, "level": m15["close"],
            "note": f"RSI M15={m15['rsi']:.1f} oversold | H4 BULL | H1 above EMA50"
        })
    elif m15["rsi"] > 70 and h4_bias == "BEARISH" and h1["close"] < h1["ema50"]:
        setups.append({
            "type": "RSI_OVERBOUGHT", "tf": "M15", "direction": "SELL",
            "score": 60, "level": m15["close"],
            "note": f"RSI M15={m15['rsi']:.1f} overbought | H4 BEAR | H1 below EMA50"
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

def calc_d1_trend(d1_df) -> str:
    """D1 trend แบบ deterministic — ใช้เฉพาะแท่งที่ 'ปิดแล้ว' (iloc[-2]; แท่งสุดท้ายกำลังก่อตัว)
    กติกาเดียวกับ replay 251 ไม้ (no-lookahead): close vs EMA20(D1) + slope EMA20 เทียบ 5 แท่ง.
    BULLISH = เหนือ EMA20 + slope ขึ้น | BEARISH = ใต้ + slope ลง | อื่นๆ = NEUTRAL (fail-open)"""
    try:
        if d1_df is None or "ema20" not in d1_df.columns or len(d1_df) < 27:
            return "NEUTRAL"
        c  = float(d1_df["close"].iloc[-2])
        e  = float(d1_df["ema20"].iloc[-2])
        ep = float(d1_df["ema20"].iloc[-7])
        if c > e and e > ep:
            return "BULLISH"
        if c < e and e < ep:
            return "BEARISH"
    except Exception:
        pass
    return "NEUTRAL"


def analyze_m5_pa() -> dict:
    """
    ดึง M5 data ตรวจ candle pattern / rejection (ใช้ใน Ready Mode เท่านั้น)
    คืน dict: available, close, rsi, direction, candle, prev_high, prev_low
    """
    from connectors.price_feed import get_ohlcv as _get
    m5_rates = _get(timeframe=mt5.TIMEFRAME_M5, count=30)
    if m5_rates is None:
        return {"available": False}
    m5 = calculate_indicators(m5_rates)
    candle = detect_candle_pattern(m5["df"])
    return {
        "available":  True,
        "close":      m5["close"],
        "prev_high":  m5["prev_high"],
        "prev_low":   m5["prev_low"],
        "rsi":        m5["rsi"],
        "direction":  "UP" if m5["close"] > m5["ema20"] else "DOWN",
        "candle":     candle,
    }


def analyze_chart() -> dict:
    logger.info("Agent 1: กำลังวิเคราะห์กราฟ...")

    # reset ก่อนทุก early-return/exception — ถ้า cycle นี้ fail ก่อนถึง API call
    # usage เก่าจะค้างให้ accounting นับซ้ำ (บัคเดียวกับ decision_maker/reporter)
    global _last_usage
    _last_usage = None

    h4_rates  = get_ohlcv(timeframe=mt5.TIMEFRAME_H4,  count=200)
    h1_rates  = get_ohlcv(timeframe=mt5.TIMEFRAME_H1,  count=100)
    m15_rates = get_ohlcv(timeframe=mt5.TIMEFRAME_M15, count=100)
    d1_rates  = get_ohlcv(timeframe=mt5.TIMEFRAME_D1,  count=60)
    w1_rates  = get_ohlcv(timeframe=mt5.TIMEFRAME_W1,  count=30)

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

    # D1 / W1 major zones
    d1_df   = calculate_indicators(d1_rates).get("df") if d1_rates is not None else None
    w1_df   = calculate_indicators(w1_rates).get("df") if w1_rates is not None else None
    d1_sr   = find_swing_levels(d1_df, window=3, max_levels=5) if d1_df is not None \
              else {"resistance": [], "support": []}
    w1_sr   = find_swing_levels(w1_df, window=2, max_levels=4) if w1_df is not None \
              else {"resistance": [], "support": []}
    htf_zone = detect_htf_zone(current, d1_sr, w1_sr)
    d1_trend = calc_d1_trend(d1_df)   # ป้อน HTF-direction block (decision gate 2e + pending)
    htf_sr_text = format_htf_sr_text(d1_sr, w1_sr, current)
    if htf_zone:
        logger.info(
            f"[HTF] ราคาอยู่ที่ {htf_zone['tf']} {htf_zone['zone_type']} "
            f"@ {htf_zone['level']} (ห่าง {htf_zone['dist_pct']}%)"
        )

    sr_text    = format_sr_text(h4_sr, h1_sr, key_lvl, current)
    all_levels = h4_sr["resistance"] + h4_sr["support"] + h1_sr["resistance"] + h1_sr["support"]
    sr_actions = detect_sr_action(m15["df"], h4_sr["resistance"] + h4_sr["support"] + h1_sr["resistance"] + h1_sr["support"])
    candle_pat = detect_candle_pattern(m15["df"])

    # SL = max(prev M15 wick, ATR floor จาก H4) — ทั้งสองทิศทาง
    h4_atr = _sane_atr(h4)   # #3 — clamp ATR เพี้ยน (thin market) ก่อนคำนวณ SL
    buy_sl_pips  = calc_sl_from_wick(m15, "BUY",  h4_atr)
    sell_sl_pips = calc_sl_from_wick(m15, "SELL", h4_atr)

    # Fibonacci retracement (H4 = major swing, H1 = minor swing)
    fib_h4  = calc_fibonacci(h4["df"],  lookback=80)
    fib_h1  = calc_fibonacci(h1["df"],  lookback=60)
    fib_text = _format_fib_text(fib_h4, "H4") + "\n" + _format_fib_text(fib_h1, "H1")

    # Momentum per timeframe
    mom_h4  = calc_momentum(h4,  h4["df"])
    mom_h1  = calc_momentum(h1,  h1["df"])
    mom_m15 = calc_momentum(m15, m15["df"])

    def _mom_str(m: dict) -> str:
        # ส่งเฉพาะ direction/strength (Python คำนวณแล้ว) + EMA align — rule ใช้แค่นี้.
        # raw RSI_slope/MACD_hist/ROC5/expanding ตัดออก (prompt ไม่อ้างถึง → ลด input token)
        return f"{m['direction']}_{m['strength']}  (EMA={m['ema_align']})"

    # Entry setup scanner
    scan         = scan_entry_setups(h4, h1, m15, h4_sr, h1_sr, key_lvl, d1_sr, w1_sr)
    setups_text  = _format_setups_text(scan)

    # SR action text
    if sr_actions:
        sr_action_text = "\n".join(
            f"  [{a['action']}] {a['zone']} {a['level']} → {a['direction']} | {a['note']}"
            for a in sr_actions
        )
    else:
        sr_action_text = "  ไม่มีสัญญาณ Rejection/Breakout"

    htf_alert = ""
    if htf_zone:
        htf_alert = (f"\n⚡ HTF MAJOR ZONE: ราคาอยู่ที่ {htf_zone['tf']} {htf_zone['zone_type']} "
                     f"@ {htf_zone['level']} (ห่าง {htf_zone['dist_pct']}%) — "
                     f"ระดับนี้มีนัยสำคัญสูงมาก ให้ bonus confidence ตามกฎ HTF Zone\n")

    user_message = f"""ราคาปัจจุบัน: Bid={price.get('bid')} / Ask={price.get('ask')}
{htf_alert}
{htf_sr_text}

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

วิเคราะห์ตามกฎที่กำหนด แล้ว **ขึ้นต้นคำตอบด้วยบล็อกสรุปนี้ก่อนเป็นอันดับแรกสุด** (plain text เท่านั้น —
ห้าม markdown, ห้ามใส่ ** หรือ #, ห้ามตาราง, ห้าม code fence — ระบบอ่านบล็อกนี้ด้วยเครื่อง ต้องมีครบทุกบรรทัด)
จากนั้นจะอธิบายเหตุผลสั้นๆ (ไม่เกิน 6 บรรทัด) ต่อท้ายก็ได้:

SIGNAL: BUY หรือ SELL หรือ NO_TRADE
CONFIDENCE: จำนวนเต็ม 0-100 (= FINAL SCORE)
TREND: BULLISH หรือ BEARISH หรือ SIDEWAYS
SR_ZONE: SUPPORT หรือ RESISTANCE หรือ NONE
SR_STRENGTH: STRONG หรือ NORMAL
ENTRY_TYPE: SR_ZONE หรือ ENGULFING หรือ STRUCTURE_PULLBACK หรือ BREAKOUT_RETEST หรือ EMA_PULLBACK หรือ MOMENTUM_BREAKOUT หรือ DOJI_AT_ZONE หรือ NONE"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,   # block-first summary + เหตุผลสั้น (เดิม 800 → report markdown ยาวถูก truncate ก่อนถึงสรุป → parse fail)
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    _last_usage = response.usage

    analysis_text = response.content[0].text
    logger.info(f"Chart result: {analysis_text[:200]}")

    # ── Fast-move (news-spike) detector — net M15 move ~45min, signed (+ = ขึ้น) ──
    # ใช้ใน decision_maker เป็น counter-spike guard: ห้ามเข้าสวนการสไปก์แรง (มักเป็นข่าว)
    _m15_df = m15.get("df") if isinstance(m15, dict) else None
    fast_move_pips = 0.0
    if _m15_df is not None and len(_m15_df) >= 4:
        try:
            _fm_now = float(_m15_df["close"].iloc[-1])
            _fm_ago = float(_m15_df["close"].iloc[-4])
            fast_move_pips = round((_fm_now - _fm_ago) / 0.01, 0)
        except Exception:
            fast_move_pips = 0.0

    # display direction สำหรับ retrace-entry (deterministic ก่อน LLM): rejection > candle bias
    _disp_dir = (sr_actions[0]["direction"] if sr_actions else
                 "BUY"  if candle_pat.get("bias") == "BULLISH" else
                 "SELL" if candle_pat.get("bias") == "BEARISH" else None)

    result = {
        "raw":           analysis_text,
        "signal":        "NO_TRADE",
        "confidence":    0,
        "sl_pips":       1000,
        "tp_pips":       1500,
        "buy_sl_pips":   buy_sl_pips,
        "sell_sl_pips":  sell_sl_pips,
        "fast_move_pips": fast_move_pips,
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
        "sr_meta":       _build_sr_meta(h4_sr, h1_sr, key_lvl, d1_sr, w1_sr,
                                        h4.get("df"), h1.get("df"), fib_h4, fib_h1),
        "liquidity_pools": find_liquidity_pools(h1.get("df"), h1.get("close")),  # UHAS #1 (display-only)
        "volume_profile": analyze_volume_profile(h1.get("df"), h1.get("close")),  # UHAS #3 (display-only)
        "retrace_entry":   suggest_retrace_entry(m15.get("df"), _disp_dir),        # GAP1 คลิป (display-only)
        "market_structure": classify_market_structure(h1.get("df")),              # GAP2 คลิป (display-only)
        "reversal_confirm": reversal_confirm_status(m15.get("df"), sr_actions),    # GAP3 คลิป (display-only)
        "key_levels":    key_lvl,
        "htf_zone":      htf_zone,   # None หรือ {"tf","level","zone_type","dist_pct"}
        "d1_trend":      d1_trend,   # BULLISH/BEARISH/NEUTRAL — จากแท่ง D1 ที่ปิดแล้วเท่านั้น
        "indicators":    {"h4":  {k: v for k, v in h4.items()  if k != "df"},
                          "h1":  {k: v for k, v in h1.items()  if k != "df"},
                          "m15": {k: v for k, v in m15.items() if k != "df"}},
    }

    for line in analysis_text.splitlines():
        if ":" not in line:
            continue
        raw_key, val = line.split(":", 1)
        # ทน markdown drift: LLM อาจตอบ "**SIGNAL:**" / "## SIGNAL" / "- SIGNAL"
        # → strip ตัวอักษร markdown ออกจาก key+val ก่อนเทียบ (เดิม exact match จึง parse fail = conf 0)
        key = raw_key.strip().strip("*#|>-•\t ").upper()
        val = val.strip().strip("*`").strip()
        if key == "SIGNAL":
            _sig = val.upper().split()[0] if val else ""
            if _sig in ("BUY", "SELL", "NO_TRADE"):
                result["signal"] = _sig
        elif key == "CONFIDENCE":
            m = re.search(r"\d+", val)   # รองรับ "93", "93/100", "93%"
            if m:
                result["confidence"] = int(m.group())
        elif key == "TREND":
            result["trend"] = val.split("—")[0].split("(")[0].split("|")[0].strip().upper()
        elif key == "SR_ZONE":
            result["sr_zone"] = val.split("—")[0].split("@")[0].strip().upper()
        elif key == "SR_STRENGTH":
            result["sr_strength"] = val.split("—")[0].strip().upper()
        elif key == "ENTRY_TYPE":
            result["entry_type"] = val.split("—")[0].split("(")[0].strip().upper()
        elif key == "MOMENTUM":
            result["momentum"] = val
        elif key == "FIB_LEVEL":
            result["fib_level"] = val

    # ── SL/TP คำนวณในโค้ด (deterministic) — LLM ไม่ต้องตอบแล้ว (42 compute-in-code) ──────
    # SL = buy/sell_sl_pips ที่คำนวณไว้แล้ว (= sl_rule), TP = next S/R min 2.0×SL (= tp_rule).
    # ลด output token ของ LLM + ตัด failure mode (LLM ตอบ SL/TP เพี้ยน/ขาด).
    _sig = result["signal"]
    if _sig in ("BUY", "SELL"):
        _sl = buy_sl_pips if _sig == "BUY" else sell_sl_pips
        result["sl_pips"] = float(_sl)
        result["tp_pips"] = float(compute_tp_pips(_sig, current, _sl, all_levels))
    # NO_TRADE: คง default (ไม่ถูกใช้)

    # ── EMA_PULLBACK toxicity gate (deterministic — ผลวิเคราะห์ 2026-06) ──────────
    # EMA_PULLBACK ที่ SL กว้าง (ATR สูง) หรือ confidence ต่ำ → ~0% WR.
    # บล็อกใน Python ไม่พึ่ง LLM (penalty ใน prompt ไม่ enforce). replay: +$2,981, block 7/514, 0 collateral.
    if result["entry_type"].strip().upper().startswith("EMA_PULLBACK") \
            and result["signal"] in ("BUY", "SELL"):
        _sl   = result.get("sl_pips") or 0
        _conf = result.get("confidence") or 0
        if _sl >= EMA_PULLBACK_MAX_SL or _conf < EMA_PULLBACK_MIN_CONF:
            logger.info(f"[GATE] EMA_PULLBACK→NO_TRADE  sl={_sl} conf={_conf} "
                        f"(limits sl<{EMA_PULLBACK_MAX_SL}, conf>={EMA_PULLBACK_MIN_CONF})")
            result["signal"] = "NO_TRADE"
            result["gate_block"] = f"ema_pullback sl={_sl}/conf={_conf}"

    _shadow_chart_call(user_message, result)   # A/B shadow (no-op ถ้า CHART_SHADOW ปิด)
    return result
