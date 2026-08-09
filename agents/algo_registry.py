"""agents/algo_registry.py — Batch B (T-02): registry of deterministic shadow algos.

An algo maps (symbol, bars, ctx) → VirtualOrder | None. NO LLM, NO order, NO price prediction:
entry is a real closed-bar price, SL/TP are pip offsets computed from data — CORE INVARIANT preserved.
The multi-pair shadow engine (T-04) iterates ALGO_REGISTRY × eligible pairs × SHADOW switch state.

v1 ships ONE validated algo: `regime_momentum` — a thin wrapper over the existing, live-proven
regime router (regime_shadow.compute_shadow_signal → regime_lib momentum_breakout in TREND). No new
strategy is introduced here; a new non-XAUUSD algo is Batch D, only after shadow evidence proves out.

Frozen interfaces — docs/ARCHITECTURE_batchB.md §4.1/§4.2.
"""
from datetime import datetime, timezone

import numpy as np

from agents.regime_shadow import compute_shadow_signal, _MIN_BARS
import regime_lib as R    # regime_shadow ใส่ scripts/ ลง sys.path แล้ว → import ได้

# full universe (mirror connectors/pair_collector.COLLECT) — the instruments an algo may be eligible for
UNIVERSE = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "AUDUSD", "EURUSD", "GBPUSD", "USDCHF", "USDJPY",
            "BTCUSD", "WTIUSD"]


class Algo:
    """Base contract. Subclasses set the class attrs and implement evaluate().

    evaluate(symbol, bars, ctx) -> VirtualOrder dict | None
      bars = (high, low, close, times)  — float/int arrays, newest last (times = unix epoch)
      ctx  = optional cross-pair context (data/pair_context.json); may be ignored
      returns None on stand-down (no signal this bar).
    """
    algo_id: str = ""
    version: int = 1
    klass: str = "scalp"                 # "scalp"→ promotion needs n≥100 ; "swing"→ n≥20
    eligible_pairs: list = UNIVERSE
    timeframe: str = "H1"                 # bars ที่ evaluate ต้องการ — caller (MSE/shadow_engine) ดึงตาม tf นี้
    mgmt: str = "managed"                 # การจัดการไม้: "managed"=BE+trailing (SL/TP) · "tsmom_flip"=ปิดเมื่อสัญญาณกลับ

    def evaluate(self, symbol, bars, ctx=None, point=None):
        raise NotImplementedError


class RegimeMomentumAlgo(Algo):
    """Donchian momentum-breakout in a TREND regime — the existing validated router, symbol-agnostic
    (all indicator math runs on the passed arrays; only pip conversion is symbol-specific and handled
    downstream by shadow_resolve's `point`). klass="scalp": momentum fires ~per-H1-bar in TREND, so it
    accumulates fast and earns the STRICTER n≥100 promotion bar (fewer false promotions)."""
    algo_id = "regime_momentum"
    version = 1
    klass = "scalp"
    eligible_pairs = UNIVERSE

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        rec = compute_shadow_signal(high, low, close, times, point=point)
        if not rec:
            return None                                  # not enough bars / no regime
        sig = rec.get("signal")
        if not sig or sig.get("algo") != "momentum_breakout":
            return None                                  # stand-down (not TREND, or no breakout)
        from agents import algo_pair_config as _apc       # per-pair tune SL/RR (BRK = global, ผ่าน compute_shadow_signal)
        _sl_atr = float(_apc.get(self.algo_id, symbol, "SL_ATR", R.ATR_SL))
        _rr = float(_apc.get(self.algo_id, symbol, "RR", R.RR))
        _slp = sig["sl_pips"] * (_sl_atr / R.ATR_SL) if R.ATR_SL else sig["sl_pips"]   # scale SL ตาม per-pair ATR mult
        return {
            "algo_id": self.algo_id,
            "symbol":  symbol,
            "dir":     sig["dir"],
            "entry":   rec["close"],                     # real closed-bar price (n-2), same as executor/journal
            "sl_pips": round(_slp),
            "tp_pips": round(_slp * _rr),
            "regime":  rec["regime"],
            "bar_ts":  rec["bar_ts"],                    # dedup key: one signal per (algo,symbol,bar)
            "klass":   self.klass,
        }


class MeanReversionAlgo(Algo):
    """RANGE z-score fade (regime_lib.algo_mean_reversion) — เข้าเฉพาะ regime=RANGE. cut จาก live (P2 −EV OOS)
    แต่ shadow ไว้เก็บ data ว่ากำไรใน RANGE/คู่ไหนบ้าง. symbol-param ผ่าน point (pip ต่อคู่)."""
    algo_id = "mean_reversion"
    version = 1
    klass = "scalp"
    eligible_pairs = UNIVERSE

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        n = len(close)
        if n < _MIN_BARS:
            return None
        er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
        volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
        i = n - 2                                          # last CLOSED bar (เหมือน momentum)
        if R.detect_regime(er[i], adx_v[i], volpct[i]) != "RANGE":
            return None                                    # mean-reversion เข้าเฉพาะ RANGE
        sig = R.algo_mean_reversion(i, close, atr_v, point=point)
        if not sig:
            return None
        bar_ts = None
        try:
            from datetime import datetime, timezone
            bar_ts = datetime.fromtimestamp(int(times[i]), timezone.utc).isoformat()
        except Exception:
            return None
        return {
            "algo_id": self.algo_id, "symbol": symbol, "dir": sig["dir"],
            "entry": float(close[i]), "sl_pips": sig["sl_pips"], "tp_pips": sig["tp_pips"],
            "regime": "RANGE", "bar_ts": bar_ts, "klass": self.klass,
        }


class TSMOMDailyAlgo(Algo):
    """Time-Series Momentum รายวัน (D1) — ensemble majority vote ของ sign(close[i]−close[i−L]) L=63/126/252
    (มิเรอร์ agents.tsmom_manager._signal + scripts.tsmom_pairs_screen). ไม่มี TP → **exit-on-flip**
    (ถือจนสัญญาณกลับ) + disaster SL 3×ATR(D1). timeframe=D1, mgmt=tsmom_flip.

    eligible = UNIVERSE − XAUUSD: ทองมี tsmom_manager (TSMOM_LIVE) เทรดอยู่แล้ว → ตัดออกกันเทรดซ้ำ.
    klass=swing: D1 ยิง ~รายวัน N น้อย → promotion bar n≥20."""
    algo_id = "tsmom_d1"
    version = 1
    klass = "swing"
    timeframe = "D1"
    mgmt = "tsmom_flip"
    eligible_pairs = [p for p in UNIVERSE if p != "XAUUSD"]
    LOOKBACKS = (21, 63, 126)          # user 08-07: เพิ่ม short-horizon (เดิม 63/126/252 ช้าไป ขายสวนของสดๆ)
    CONFIRM_LB = 21                    # short-term ต้องเห็นด้วย ไม่งั้น stand-down (backtest: BTC t0.89→1.76, WTI −EV→+EV)
    SL_ATR = 3.0

    def _lookbacks(self):
        import config as _c
        raw = getattr(_c, "TSMOM_LOOKBACKS", None)
        if raw:
            try:
                v = tuple(int(x) for x in str(raw).split(",") if x.strip())
                if v:
                    return v
            except Exception:
                pass
        return self.LOOKBACKS

    def _confirm_lb(self):
        import config as _c
        try:
            return int(getattr(_c, "TSMOM_CONFIRM_LB", self.CONFIRM_LB) or 0)
        except Exception:
            return self.CONFIRM_LB

    def _pair_lbs(self, symbol):
        """per-pair lookbacks override (algo_pair_config) → global → default. รับ list หรือ 'a,b,c'."""
        from agents import algo_pair_config as _apc
        raw = _apc.get(self.algo_id, symbol, "lookbacks", None)
        if raw:
            try:
                v = tuple(int(x) for x in (raw if isinstance(raw, (list, tuple)) else str(raw).split(",")))
                if v:
                    return v
            except Exception:
                pass
        return self._lookbacks()

    def signal_dir(self, close, i, confirm=False, lookbacks=None, confirm_lb=None):
        """ensemble vote ที่บาร์ i (closed) → 'BUY'/'SELL'/None(FLAT). confirm=True → short-term gate.
        lookbacks/confirm_lb: override (per-pair/per-combo); None → config/default."""
        votes = 0
        for L in (lookbacks or self._lookbacks()):
            if i - L >= 0:
                votes += int(np.sign(close[i] - close[i - L]))
        d = "BUY" if votes > 0 else ("SELL" if votes < 0 else None)
        cf = confirm_lb if confirm_lb is not None else self._confirm_lb()
        if confirm and d and cf and i - cf >= 0:
            s = np.sign(close[i] - close[i - cf])
            if (s > 0 and d == "SELL") or (s < 0 and d == "BUY"):
                return None                                # short-term สวน → stand-down (ไม่เข้าสวนของสดๆ)
        return d

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        n = len(close)
        from agents import algo_pair_config as _apc            # per-pair tune (default=global)
        _lbs = (ctx or {}).get("lookbacks") or self._pair_lbs(symbol)   # per-pair/combo override หรือ config
        _cf = _apc.get(self.algo_id, symbol, "CONFIRM_LB", None)
        _cf = int(_cf) if _cf is not None else None
        _sl_atr = float(_apc.get(self.algo_id, symbol, "SL_ATR", self.SL_ATR))
        if n < max(_lbs) + 5 or not point:
            return None
        i = n - 2                                          # บาร์ปิดล่าสุด (D1 default; H4 ถ้า override)
        direction = self.signal_dir(close, i, confirm=True, lookbacks=_lbs, confirm_lb=_cf)   # per-pair confirm
        if direction is None:
            return None
        # ข่าว + ตัวเลขเศรษฐกิจ (user 08-07): sentiment คุมทิศ — ไม่เข้าสวน sentiment แรง (gold-specific score)
        try:
            if symbol and symbol.upper().startswith("XAU"):
                from agents.sentiment_bias import compute as _sbias
                from agents.sentiment_score import get_score
                _s = _sbias(direction, (get_score() or {}).get("score", 0))
                if _s.get("block"):
                    return None                            # sentiment (ข่าว+econ) สวนแรง → stand-down
        except Exception:
            pass
        atr = R.atr(high, low, close)
        av = float(atr[i]) if atr[i] == atr[i] else 0.0    # NaN guard
        if av <= 0:
            return None
        try:
            from datetime import datetime, timezone
            bar_ts = datetime.fromtimestamp(int(times[i]), timezone.utc).isoformat()
        except Exception:
            return None
        return {
            "algo_id": self.algo_id, "symbol": symbol, "dir": direction,
            "entry": float(close[i]), "sl_pips": (_sl_atr * av) / point, "tp_pips": 0.0,   # 0 = no-TP (exit-on-flip)
            "regime": "TSMOM", "bar_ts": bar_ts, "klass": self.klass,
        }


class MomentumFVGAlgo(Algo):
    """SMC candidate (IMPROVED momentum) — momentum_breakout + FVG confluence filter.
    เข้าเมื่อ momentum ให้สัญญาณ TREND *และ* มี Fair-Value-Gap (imbalance 3 แท่ง) หนุนทิศ
    ภายใน FVG_LOOKBACK แท่งล่าสุด. FVG = gap-only (bars ไม่มี open): bull low[j]>high[j-2] / bear high[j]<low[j-2].

    ⚠️ SHADOW-ONLY: backtest (scripts/smc_backtest.py) = in-sample ดีขึ้นแต่ไม่รอด OOS (window bias) →
    ไม่มี edge พิสูจน์แล้ว. เปิด shadow เพื่อเก็บ forward-OOS เทียบ regime_momentum เฉยๆ. ไม่ live."""
    algo_id = "regime_momentum_fvg"
    version = 1
    klass = "scalp"
    eligible_pairs = UNIVERSE
    FVG_LOOKBACK = 6

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        rec = compute_shadow_signal(high, low, close, times, point=point)
        if not rec:
            return None
        sig = rec.get("signal")
        if not sig or sig.get("algo") != "momentum_breakout":
            return None
        n = len(close); i = n - 2
        d = sig["dir"]; ok = False
        for j in range(max(2, i - self.FVG_LOOKBACK), i + 1):     # FVG confluence หนุนทิศ
            if d == "BUY" and low[j] > high[j - 2]:
                ok = True; break
            if d == "SELL" and high[j] < low[j - 2]:
                ok = True; break
        if not ok:
            return None                                          # ไม่มี FVG หนุน → ข้าม (นี่คือ "filter")
        return {
            "algo_id": self.algo_id, "symbol": symbol, "dir": d,
            "entry": rec["close"], "sl_pips": sig["sl_pips"], "tp_pips": sig["tp_pips"],
            "regime": rec["regime"], "bar_ts": rec["bar_ts"], "klass": self.klass,
        }


class SweepReversalAlgo(Algo):
    """SMC candidate (NEW algo) — liquidity-sweep reversal: fade การ sweep prior-day H/L
    ที่ปิดกลับเข้าใน เฉพาะ regime NEUTRAL/RANGE (ไม่ fade TREND). SL เลยปลาย sweep + BUF×ATR, TP = RR×SL.
    prior-day H/L คำนวณจากแท่ง H1 เอง (bucket UTC วันก่อนหน้า) — causal, ไม่ต้องพึ่ง D1.

    ⚠️ SHADOW-ONLY: backtest = −EV (WR สูง/RR ต่ำ = กับดัก; fade สู้ cascade). เปิด shadow เก็บ forward
    เพื่อยืนยัน/หักล้าง. ไม่ live."""
    algo_id = "sweep_reversal"
    version = 1
    klass = "scalp"
    eligible_pairs = UNIVERSE
    BUF_ATR = 0.5
    RR = 1.5

    def _prior_day_hl(self, high, low, times, i):
        """H/L ของวัน UTC ก่อนหน้าล่าสุด (ปิดแล้ว) จากแท่ง H1. คืน (pdh, pdl) หรือ (None,None)."""
        di = datetime.fromtimestamp(int(times[i]), timezone.utc).date()
        pdh = pdl = None; prev_date = None
        for j in range(i - 1, max(-1, i - 300), -1):
            dj = datetime.fromtimestamp(int(times[j]), timezone.utc).date()
            if dj >= di:
                continue
            if prev_date is None:
                prev_date = dj
            if dj == prev_date:
                pdh = high[j] if pdh is None else max(pdh, high[j])
                pdl = low[j] if pdl is None else min(pdl, low[j])
            else:
                break                                            # ข้ามไปวันก่อนหน้านั้น → พอ
        return pdh, pdl

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        n = len(close)
        if n < _MIN_BARS or not point:
            return None
        er = R.efficiency_ratio(close); adx_v = R.adx(high, low, close)
        volpct = R.vol_percentile(close); atr_v = R.atr(high, low, close)
        i = n - 2
        reg = R.detect_regime(er[i], adx_v[i], volpct[i])
        if reg not in ("NEUTRAL", "RANGE"):                      # ไม่ fade ใน TREND
            return None
        av = float(atr_v[i]) if atr_v[i] == atr_v[i] else 0.0
        if av <= 0:
            return None
        pdh, pdl = self._prior_day_hl(high, low, times, i)
        if pdh is None or pdl is None:
            return None
        d = swept = None
        if high[i] > pdh and close[i] < pdh:
            d, swept = "SELL", high[i]
        elif low[i] < pdl and close[i] > pdl:
            d, swept = "BUY", low[i]
        if d is None:
            return None
        sign = 1 if d == "BUY" else -1
        from agents import algo_pair_config as _apc            # per-pair tune (default=global)
        _buf = float(_apc.get(self.algo_id, symbol, "BUF_ATR", self.BUF_ATR))
        _rr = float(_apc.get(self.algo_id, symbol, "RR", self.RR))
        sl_pips = abs(float(close[i]) - (swept - sign * _buf * av)) / point
        if sl_pips <= 0:
            return None
        try:
            bar_ts = datetime.fromtimestamp(int(times[i]), timezone.utc).isoformat()
        except Exception:
            return None
        return {
            "algo_id": self.algo_id, "symbol": symbol, "dir": d,
            "entry": float(close[i]), "sl_pips": sl_pips, "tp_pips": sl_pips * _rr,
            "regime": reg, "bar_ts": bar_ts, "klass": self.klass,
        }


class MacroMomAlgo(Algo):
    """Macro-aligned momentum (research 08-07) — Donchian breakout + DXY-proxy(EURUSD) ยืนยันทิศ, ไม่มี TREND gate.
    แก้ 2 ปัญหา: (1) เข้า ณ จุดสำคัญ = breakout (2) ไม่สวน macro/sentiment = เข้าเฉพาะทิศที่ DXY หนุน
    (DXY ลง=EURUSD ขึ้น→ทอง BUY). backtest gold H4: exp_R+0.073 t1.23 OOS+0.14 (gold momentum เดิม −0.09 → พลิก +EV).
    + gold sentiment gate (ข่าว/econ). timeframe H4. เข้าเฉพาะ XAU (macro driver ตรง). run ผ่าน MSE (own magic)."""
    algo_id = "macro_momentum"
    version = 1
    klass = "swing"
    timeframe = "H4"
    mgmt = "managed"                                   # BE + trailing (เหมือน momentum)
    eligible_pairs = UNIVERSE                          # ทุกคู่ (backtest แล้ว; +EV=XAU/BTC → LIVE, ที่เหลือ SHADOW)
    BRK = 20
    MLB = 24                                           # macro momentum lookback (บาร์ H4)
    SL_ATR = 1.5
    RR = 2.0
    MACRO = "EURUSD"                                   # DXY-inverse proxy

    def _fetch_macro(self, times, macro_logical=None):
        """macro close align ตาม timestamp (live MT5). macro_logical = driver ต่อคู่ (structural). คืน np.array หรือ None."""
        try:
            import MetaTrader5 as mt5
            from connectors.pair_collector import _broker_map
            brk = (_broker_map() or {}).get(macro_logical or self.MACRO, macro_logical or self.MACRO)
            r = mt5.copy_rates_from_pos(brk, mt5.TIMEFRAME_H4, 0, max(2000, len(times) + 50))
            if r is None or len(r) < self.MLB + 5:
                return None
            emap = {int(t): float(c) for t, c in zip(r["time"], r["close"])}
            return np.array([emap.get(int(t), np.nan) for t in times], float)
        except Exception:
            return None

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        n = len(close)
        if n < max(self.BRK, self.MLB) + 5 or not point:
            return None
        i = n - 2                                          # แท่ง H4 ปิดล่าสุด
        atr = R.atr(high, low, close); av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            return None
        from agents import algo_pair_config as _apc         # per-pair tune (default=global)
        brk = int(_apc.get(self.algo_id, symbol, "BRK", self.BRK))
        mlb = int(_apc.get(self.algo_id, symbol, "MLB", self.MLB))
        sl_atr = float(_apc.get(self.algo_id, symbol, "SL_ATR", self.SL_ATR))
        rr = float(_apc.get(self.algo_id, symbol, "RR", self.RR))
        px = float(close[i]); hh = float(high[i - brk:i].max()); ll = float(low[i - brk:i].min())
        d = "BUY" if px > hh else ("SELL" if px < ll else None)   # Donchian breakout = จุดสำคัญ
        if d is None:
            return None
        macro_logical, msign = R.macro_for(symbol)         # structural driver ต่อคู่ (XAUJPY→USDJPY, XAUEUR→EURUSD−)
        macro = (ctx or {}).get("macro_close")
        if macro is None:
            macro = self._fetch_macro(times, macro_logical)   # live fetch (per-pair)
        if macro is None or len(macro) <= i or macro[i] != macro[i] or macro[i - mlb] != macro[i - mlb]:
            return None
        md = "BUY" if msign * (macro[i] - macro[i - mlb]) > 0 else "SELL"   # USD-factor direction ต่อคู่
        if d != md:                                        # breakout สวน macro → stand-down (ไม่สวน sentiment โครงสร้าง)
            return None
        try:                                               # ข่าว/econ sentiment (gold) — ไม่สวน sentiment สด
            from agents.sentiment_bias import compute as _sb
            from agents.sentiment_score import get_score
            if _sb(d, (get_score() or {}).get("score", 0)).get("block"):
                return None
        except Exception:
            pass
        try:
            from datetime import datetime, timezone
            bar_ts = datetime.fromtimestamp(int(times[i]), timezone.utc).isoformat()
        except Exception:
            return None
        slp = round(self.SL_ATR * av / point)
        return {"algo_id": self.algo_id, "symbol": symbol, "dir": d, "entry": px,
                "sl_pips": slp, "tp_pips": round(slp * self.RR), "regime": "MACRO",
                "bar_ts": bar_ts, "klass": self.klass}


class ConfluenceVol15m(Algo):
    """15m confluence + order-flow (research 08-07): 15m Donchian breakout เข้าเฉพาะเมื่อ
    H1 trend + H4 trend + macro(DXY) ตรงทิศ**ทั้งหมด** + tick-volume surge (order-flow หนุน).
    selective สุด (5 เงื่อนไข) = กรอง noise ที่ฆ่า scalp ทุกตัว. backtest gold M15: exp_R+0.035 OOS+0.199
    (confluence เฉยๆ −EV → เติม volume พลิก +EV). fire ~166/ปี = small-TF ที่ถี่. gold-only (DXY driver ตรง)."""
    algo_id = "confluence_15m"
    version = 1
    klass = "scalp"
    timeframe = "M15"
    mgmt = "managed"
    eligible_pairs = UNIVERSE                          # ทุกคู่ (backtest แล้ว; +EV=XAU/BTC → LIVE, ที่เหลือ SHADOW)
    BRK = 12
    RR = 2.0
    SL_ATR = 1.0
    VK = 1.5                                            # volume surge (× median)
    MACRO = "EURUSD"

    def _ctx_live(self, symbol):
        """ทิศ H1/H4 (EMA50 slope) + macro(DXY) momentum + volume surge ของ **คู่ที่เทรด** (ไม่ hardcode ทอง).
        macro = EURUSD (DXY-proxy) เสมอ. คืน dict หรือ None."""
        try:
            import MetaTrader5 as mt5
            from connectors.pair_collector import _broker_map
            bm = _broker_map() or {}
            brk = bm.get(symbol, symbol); eb = bm.get(self.MACRO, self.MACRO)

            def _slope(sym_or_broker, tf):
                r = mt5.copy_rates_from_pos(sym_or_broker, tf, 0, 120)
                if r is None or len(r) < 60:
                    return 0
                c = r["close"].astype(float)
                k = 2 / 51; e = c[0]
                es = []
                for v in c:
                    e = v * k + e * (1 - k); es.append(e)
                return 1 if es[-2] > es[-5] else -1 if es[-2] < es[-5] else 0
            h1 = _slope(brk, mt5.TIMEFRAME_H1); h4 = _slope(brk, mt5.TIMEFRAME_H4)
            em = mt5.copy_rates_from_pos(eb, mt5.TIMEFRAME_M15, 0, 60)
            mac = 0
            if em is not None and len(em) >= 26:
                ec = em["close"].astype(float); mac = 1 if ec[-2] > ec[-26] else -1
            mv = mt5.copy_rates_from_pos(brk, mt5.TIMEFRAME_M15, 0, 260)
            vsurge = False
            if mv is not None and len(mv) >= 210:
                tv = mv["tick_volume"].astype(float); med = float(np.median(tv[-201:-1])) or 1
                vsurge = tv[-2] >= self.VK * med and tv[-2] <= 2.0 * med   # surge แต่ไม่ใช่ข่าว (spike สุด)
            return {"h1": h1, "h4": h4, "mac": mac, "vsurge": vsurge}
        except Exception:
            return None

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        n = len(close)
        if n < max(self.BRK, 50) + 5 or not point:
            return None
        i = n - 2
        # session filter (gold-only): เทรดเฉพาะ NY/London (ทองวิ่ง) ตัด Asian chop → exp_R ~1.7× + OOS ดีขึ้น (backtest 08-07).
        # BTC/crypto = 24/7 ไม่กรอง. config CONF15M_SESSION="13-21" (UTC); ว่าง=ทุกชม.
        from agents import algo_pair_config as _apc            # per-pair tune (default=global)
        brk = int(_apc.get(self.algo_id, symbol, "BRK", self.BRK))
        sl_atr = float(_apc.get(self.algo_id, symbol, "SL_ATR", self.SL_ATR))
        rr = float(_apc.get(self.algo_id, symbol, "RR", self.RR))
        if symbol and symbol.upper().startswith("XAU"):
            import config as _cfg
            sess = str(_apc.get(self.algo_id, symbol, "session",
                                getattr(_cfg, "CONF15M_SESSION", "13-21")) or "").strip()
            if sess and "-" in sess:
                try:
                    lo_h, hi_h = (int(x) for x in sess.split("-"))
                    from datetime import datetime, timezone
                    hr = datetime.fromtimestamp(int(times[i]), timezone.utc).hour
                    if not (lo_h <= hr < hi_h):
                        return None
                except Exception:
                    pass
        atr = R.atr(high, low, close); av = float(atr[i]) if atr[i] == atr[i] else 0.0
        if av <= 0:
            return None
        px = float(close[i]); hh = float(high[i - brk:i].max()); ll = float(low[i - brk:i].min())
        d = "BUY" if px > hh else ("SELL" if px < ll else None)     # 15m breakout = จุดสำคัญ
        if d is None:
            return None
        cx = ctx if (ctx and "h1" in ctx) else self._ctx_live(symbol)
        if not cx:
            return None
        sign = 1 if d == "BUY" else -1
        if cx["h1"] != sign or cx["h4"] != sign or cx["mac"] != sign or not cx["vsurge"]:
            return None                                    # ต้อง H1+H4+macro+volume ตรงหมด (order-flow confluence)
        try:
            from datetime import datetime, timezone
            bar_ts = datetime.fromtimestamp(int(times[i]), timezone.utc).isoformat()
        except Exception:
            return None
        slp = round(sl_atr * av / point)
        return {"algo_id": self.algo_id, "symbol": symbol, "dir": d, "entry": px,
                "sl_pips": slp, "tp_pips": round(slp * rr), "regime": "CONF15M",
                "bar_ts": bar_ts, "klass": self.klass}


ALGO_REGISTRY = {a.algo_id: a for a in (
    RegimeMomentumAlgo(), MeanReversionAlgo(), TSMOMDailyAlgo(),
    MomentumFVGAlgo(), SweepReversalAlgo(), MacroMomAlgo(), ConfluenceVol15m(),
)}
# sr_fade (S/R Book fade) ถูก CUT 2026-08-07: backtest −EV ทุกคู่/ทุก variant (t−4..−22, OOS ลบ) —
# naive S/R fade ไม่มี edge (เหมือน mean_reversion). หลักฐาน: scripts/sr_fade_backtest.py


def get(algo_id):
    """Algo instance for an id, or None."""
    return ALGO_REGISTRY.get(algo_id)


def combos(universe=None):
    """All (algo_id, symbol) pairs the registry can shadow, intersected with `universe` if given."""
    uni = set(universe) if universe else None
    out = []
    for aid, algo in ALGO_REGISTRY.items():
        for sym in algo.eligible_pairs:
            if uni is None or sym in uni:
                out.append((aid, sym))
    return out


if __name__ == "__main__":
    print("ALGO_REGISTRY:")
    for aid, a in ALGO_REGISTRY.items():
        print(f"  {aid} v{a.version} klass={a.klass} eligible={len(a.eligible_pairs)} pairs")
    print(f"combos (full universe): {len(combos())}")
