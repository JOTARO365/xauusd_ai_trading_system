"""agents/algo_registry.py — Batch B (T-02): registry of deterministic shadow algos.

An algo maps (symbol, bars, ctx) → VirtualOrder | None. NO LLM, NO order, NO price prediction:
entry is a real closed-bar price, SL/TP are pip offsets computed from data — CORE INVARIANT preserved.
The multi-pair shadow engine (T-04) iterates ALGO_REGISTRY × eligible pairs × SHADOW switch state.

Frozen interfaces — docs/ARCHITECTURE_batchB.md §4.1/§4.2.

⚠️ 2026-08-22 — AUDIT #5 (Fable, docs/AUDIT_quant.md L549-711) CUT 5 algos ใต้ battery ใหม่
   (drift-null + driftless synthetic-stress + cost×2 + multiple-testing). ลองแก้ทุกตัวก่อนลบ — fix fail หมด:
     - mean_reversion      : −0.070 t−3.55 · forward −0.466 · BUY-only fix cost×2 −0.100
     - regime_momentum_fvg : sign พลิกตาม window · FVG filter value≈0 บน base ที่ null แล้ว (#4)
     - sweep_reversal      : −0.056 t−1.91 (fade WR-trap) · BUY-only fix cost×2 −0.116
     - confluence_15m      : +0.076 t0.69 ตาย cost×2 · BUY leg (ตัวเดียว live ยอม)=−EV · long-only fix −0.088
     - pullback_buy        : claim t3.88 = stat bug (นับ overlap เป็นอิสระ; dedup t1.65) · trigger p0.570 ไม่มี info
   เหลือ 4: regime_momentum / tsmom_d1 / macro_momentum (LIVE, AUDIT #4 = beta/drift-harvest ไม่ใช่ alpha แต่ user
   คง live) + cdc_zone (SHADOW, declared beta — promote ผ่าน forward n≥20 vs drift benchmark เท่านั้น).
"""
from datetime import datetime, timezone

import numpy as np

from agents.regime_shadow import compute_shadow_signal, _MIN_BARS
import regime_lib as R    # regime_shadow ใส่ scripts/ ลง sys.path แล้ว → import ได้

# full universe (mirror connectors/pair_collector.COLLECT) — the instruments an algo may be eligible for
UNIVERSE = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "AUDUSD", "EURUSD", "GBPUSD", "USDCHF", "USDJPY",
            "BTCUSD", "WTIUSD"]


def _season_block(symbol, direction, times, i):
    """gold seasonal gate (structural, flag SEASONALITY_GATE): True=entry สวน seasonal แรง → block. XAU only."""
    try:
        import config as _c
        if not getattr(_c, "SEASONALITY_GATE", False):
            return False
        from agents import seasonality as _sz
        mo = datetime.fromtimestamp(int(times[i]), timezone.utc).month
        return _sz.blocks(symbol, direction, mo)
    except Exception:
        return False


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
        if _season_block(symbol, sig["dir"], times, len(close) - 2):
            return None                                   # ทอง: ไม่สวน seasonal แรง
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
        if _season_block(symbol, direction, times, i):     # ทอง: ไม่สวน seasonal แรง
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
        if _season_block(symbol, direction, times, i):     # ทอง (XAUEUR/XAUJPY): ไม่สวน seasonal แรง
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
        if _season_block(symbol, d, times, i):             # ทอง: ไม่สวน seasonal แรง
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
        slp = round(sl_atr * av / point)                   # per-pair SL_ATR (bug fix: เดิมใช้ self.SL_ATR = override ตาย)
        return {"algo_id": self.algo_id, "symbol": symbol, "dir": d, "entry": px,
                "sl_pips": slp, "tp_pips": round(slp * rr), "regime": "MACRO",   # per-pair RR (bug fix: เดิม self.RR)
                "bar_ts": bar_ts, "klass": self.klass}


class CDCZoneAlgo(Algo):
    """CDC Action Zone (อ.โฉลก สัมพันธารักษ์) — trend-follow ถือยาว (let winners run).
    close→EMA2→Fast EMA12 / Slow EMA26. เข้าตาม zone (bull=BUY), ออกเมื่อ zone พลิก (mgmt=cdc_flip,
    ไม่มี TP). long-only default (CDC_DIR_MODE; SELL leg −EV เหมือน algo อื่น). D1. disaster SL 2×ATR (Turtle 2N).
    eligible = gold-complex + BTC (backtest ดีสุด).

    ⚠️ 2026-08-22 AUDIT #5: reproduce claim (n48 +0.945 t2.01) แต่ = **declared BETA ไม่ใช่ alpha** —
    random-long matched null +0.549R p0.105 · driftless survival 58% (0 timing) · drop-best-2 t1.46 · full-window
    p0.015 ตาย ≥30-trial Šidák. W1-CDC-bull gate = beta ที่ดีกว่า (t2.78 รอด cost×2) แต่ยังไม่ผ่าน trials/driftless.
    → คง SHADOW เก็บ forward; promote ผ่าน forward n≥20 vs **drift benchmark** เท่านั้น (ห้าม zero-null). klass=swing."""
    algo_id = "cdc_zone"
    version = 1
    klass = "swing"
    timeframe = "D1"
    mgmt = "cdc_flip"
    eligible_pairs = ["XAUUSD", "XAUEUR", "BTCUSD"]
    SL_ATR = 2.0

    def _dir_mode(self):
        import config as _c
        return str(getattr(_c, "CDC_DIR_MODE", "long")).lower()

    def evaluate(self, symbol, bars, ctx=None, point=None):
        high, low, close, times = bars
        n = len(close)
        if n < 40 or not point:
            return None
        i = n - 2                                          # บาร์ปิดล่าสุด (D1)
        fast, slow = R.cdc_zone(close)
        direction = "BUY" if fast[i] > slow[i] else ("SELL" if self._dir_mode() == "both" else None)
        if direction is None:
            return None
        import config as _c                                # โฉลก entry: เข้าตอน "ย่อ" ในเทรนด์ ไม่ไล่ราคา
        _pb = float(getattr(_c, "CDC_PULLBACK_MIN", 0.005) or 0.0)   # validated: pullback t1.99→2.05, RSI พังของดี
        _lb = int(getattr(_c, "CDC_PULLBACK_LB", 20) or 20)
        if _pb > 0 and i >= _lb:
            if direction == "BUY" and close[i] > float(high[i - _lb:i].max()) * (1 - _pb):
                return None                                # ยังไม่ย่อพอจาก high ล่าสุด → รอจุดเข้าดีกว่า
            if direction == "SELL" and close[i] < float(low[i - _lb:i].min()) * (1 + _pb):
                return None
        if _season_block(symbol, direction, times, i):     # ทอง: ไม่สวน seasonal แรง
            return None
        try:                                               # gold: ไม่เข้าสวน sentiment (ข่าว+econ) แรง
            if symbol and symbol.upper().startswith("XAU"):
                from agents.sentiment_bias import compute as _sbias
                from agents.sentiment_score import get_score
                if _sbias(direction, (get_score() or {}).get("score", 0)).get("block"):
                    return None
        except Exception:
            pass
        atr = R.atr(high, low, close)
        av = float(atr[i]) if atr[i] == atr[i] else 0.0
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
            "regime": "CDC", "bar_ts": bar_ts, "klass": self.klass,
        }


ALGO_REGISTRY = {a.algo_id: a for a in (
    RegimeMomentumAlgo(), TSMOMDailyAlgo(), MacroMomAlgo(), CDCZoneAlgo(),
)}
# CUT log (backtest หลักฐาน = docs/AUDIT_quant.md):
#   sr_fade            2026-08-07 : −EV ทุกคู่/variant (t−4..−22) — naive S/R fade ไม่มี edge (scripts/sr_fade_backtest.py)
#   mean_reversion     2026-08-22 : AUDIT #5 −0.070 t−3.55 · forward −0.466 (RANGE z-fade ไม่มี edge)
#   regime_momentum_fvg 2026-08-22: AUDIT #5 sign พลิกตาม window · FVG filter value≈0 บน base null (#4)
#   sweep_reversal     2026-08-22 : AUDIT #5 −0.056 t−1.91 (fade WR-trap สู้ cascade ไม่ได้)
#   confluence_15m     2026-08-22 : AUDIT #5 +0.076 t0.69 ตาย cost×2 · BUY leg (live) = −EV
#   pullback_buy       2026-08-22 : AUDIT #5 claim t3.88 = stat bug (overlap นับอิสระ; dedup t1.65) · trigger p0.570


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
