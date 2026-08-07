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
        return {
            "algo_id": self.algo_id,
            "symbol":  symbol,
            "dir":     sig["dir"],
            "entry":   rec["close"],                     # real closed-bar price (n-2), same as executor/journal
            "sl_pips": sig["sl_pips"],
            "tp_pips": sig["tp_pips"],
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
    LOOKBACKS = (63, 126, 252)
    SL_ATR = 3.0

    def signal_dir(self, close, i):
        """ensemble vote ที่บาร์ i (closed) → 'BUY'/'SELL'/None(FLAT). ใช้ทั้ง entry + flip-exit."""
        votes = 0
        for L in self.LOOKBACKS:
            if i - L >= 0:
                votes += int(np.sign(close[i] - close[i - L]))
        return "BUY" if votes > 0 else ("SELL" if votes < 0 else None)

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        n = len(close)
        if n < max(self.LOOKBACKS) + 5 or not point:
            return None
        i = n - 2                                          # บาร์ D1 ปิดล่าสุด (เหมือน momentum/mean_rev)
        direction = self.signal_dir(close, i)
        if direction is None:
            return None
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
            "entry": float(close[i]), "sl_pips": (self.SL_ATR * av) / point, "tp_pips": 0.0,   # 0 = no-TP (exit-on-flip)
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
        sl_pips = abs(float(close[i]) - (swept - sign * self.BUF_ATR * av)) / point
        if sl_pips <= 0:
            return None
        try:
            bar_ts = datetime.fromtimestamp(int(times[i]), timezone.utc).isoformat()
        except Exception:
            return None
        return {
            "algo_id": self.algo_id, "symbol": symbol, "dir": d,
            "entry": float(close[i]), "sl_pips": sl_pips, "tp_pips": sl_pips * self.RR,
            "regime": reg, "bar_ts": bar_ts, "klass": self.klass,
        }


ALGO_REGISTRY = {a.algo_id: a for a in (
    RegimeMomentumAlgo(), MeanReversionAlgo(), TSMOMDailyAlgo(),
    MomentumFVGAlgo(), SweepReversalAlgo(),
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
