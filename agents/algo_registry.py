"""agents/algo_registry.py — Batch B (T-02): registry of deterministic shadow algos.

An algo maps (symbol, bars, ctx) → VirtualOrder | None. NO LLM, NO order, NO price prediction:
entry is a real closed-bar price, SL/TP are pip offsets computed from data — CORE INVARIANT preserved.
The multi-pair shadow engine (T-04) iterates ALGO_REGISTRY × eligible pairs × SHADOW switch state.

v1 ships ONE validated algo: `regime_momentum` — a thin wrapper over the existing, live-proven
regime router (regime_shadow.compute_shadow_signal → regime_lib momentum_breakout in TREND). No new
strategy is introduced here; a new non-XAUUSD algo is Batch D, only after shadow evidence proves out.

Frozen interfaces — docs/ARCHITECTURE_batchB.md §4.1/§4.2.
"""
from agents.regime_shadow import compute_shadow_signal

# gold-complex universe (mirror connectors/pair_collector.COLLECT) — the pairs an algo may be eligible for
UNIVERSE = ["XAUUSD", "XAGUSD", "XAUEUR", "XAUJPY", "AUDUSD", "EURUSD", "USDCHF", "USDJPY"]


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


ALGO_REGISTRY = {a.algo_id: a for a in (RegimeMomentumAlgo(),)}


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
