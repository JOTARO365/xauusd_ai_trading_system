"""
evidence_entry_reference.py — STANDALONE REFERENCE IMPLEMENTATION (flag-OFF, illustrative).

Design of record: docs/DESIGN_evidence_based_entry.md

============================  READ THIS FIRST  ============================
  * This module is IMPORTED BY NOTHING. It is not wired into the live pipeline.
  * It places NO orders, reads NO MT5, starts/stops NOTHING, changes NO gate,
    money-management, SL, TP, or prompt. It is a design artifact only.
  * The weights below are ILLUSTRATIVE, NOT FITTED. With `EvidenceWeights.fitted
    = False` (the default) the decision function DELIBERATELY falls back to the
    conservative falling-knife veto, so that — copied as-is — it can only ever
    BLOCK / STAND-DOWN, never ALLOW more than the crude counter_spike guard.
    Real weights + tau come from the labelled counter-spike replay (design §5, §7).
  * Architecture (design §1.5): the AI SELECTS an entry ALGORITHM; it does not
    guess a price. This file implements the precondition + EV scorer for ONE
    algorithm in the library — `support-bounce` — the one the counter_spike
    heuristic currently mishandles. `decide_support_bounce()` returns
    SELECT_SUPPORT_BOUNCE | STAND_DOWN, never an order.
==========================================================================

Pure functions over a `bot_status`-shaped dict (see logs/bot_status.json).
No third-party imports; standard library only. Run `python evidence_entry_reference.py`
for a self-contained demo on synthetic input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────────────
#  Tunable parameters — the ONLY place fitted numbers plug in (design §5)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class EvidenceWeights:
    """Weights/offsets for the log-odds scorer. ALL VALUES BELOW ARE ILLUSTRATIVE.

    `fitted` MUST be set True only by loading values produced by the validated
    replay fit (design §5.2/§5.3). Until then the decision path stays conservative.
    """
    fitted: bool = False          # gate: False => conservative veto only (no new ALLOWs)

    # evidence weights (log-odds shifts). Signs reflect the design's semantics;
    # magnitudes are placeholders pending the ridge-logistic fit.
    w_news: float = 1.40          # adverse news pushes P(bounce) DOWN (applied to a signed feature)
    w_rev: float = 1.00           # reversal_confirm in favour pushes UP
    w_mom: float = 0.90           # momentum alignment
    w_fast: float = 0.50          # overshoot magnitude (bounded, one feature — NOT the gate)
    w_vol: float = 0.20           # tick-volume tilt (weak proxy, lowest weight)
    b0: float = 0.0               # global calibration offset

    # decision threshold. HARD FLOOR = breakeven implied by RR (design §5.3):
    # for RR=2, EV>0 requires P>1/3, so tau must be >= 1/3. Operating value is
    # swept on the validation set; 0.55 here is a placeholder above the floor.
    tau: float = 0.55
    rr_floor: float = 2.0         # iron rule — RR >= 2 (MONEY_MANAGEMENT["min_rr_ratio"])

    # zone bounce prior — Beta(alpha,beta) smoothing (design §3).
    beta_prior_strength: float = 2.0    # k: prior pseudo-counts
    global_bounce_rate: float = 0.50    # p0: fallback base rate when zone data is thin/absent

    # news trust gates (mirror config.NEWS_GATE_OPPOSE / NEWS_GATE_MIN_N semantics)
    news_min_n: int = 3
    news_min_abs_score: float = 40.0
    news_max_age_min: float = 180.0     # window_min in news_impact.json
    news_half_life_min: float = 120.0   # freshness decay


# ─────────────────────────────────────────────────────────────────────────────
#  Feature extraction (design §2) — pure, from a bot_status-shaped dict
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Features:
    """Decision-time feature vector for a `support-bounce` BUY candidate.

    All fields are read from data the bot already emits — zero new AI calls."""
    news_signed: float = 0.0        # F1xF2: adverse<0 / supportive>0, freshness-decayed, gated
    reversal: float = 0.0           # F3: +1 confirmed-in-favour / -1 confirmed-against / 0
    mom_align: float = 0.0          # F4: [-1,+1] momentum vote (m15/h1 vs trade dir)
    zone_prior: float = 0.5         # F5: Beta-smoothed empirical P(bounce) at nearest zone
    zone_n_tests: int = 0           # supporting count for the prior (for the veto's "low prior" test)
    fast_signed: float = 0.0        # F6: tanh(fast/500), signed toward trade dir
    vol_tilt: float = 0.0           # F7: +1 supportive / -1 adverse (tick-vol proxy)
    rr: float = 0.0                 # plan.tp_pips / plan.sl_pips
    news_adverse_confirmed: bool = False   # veto term: fresh, strong, against the trade


def _news_age_min(updated: str | None, now: datetime) -> float | None:
    if not updated:
        return None
    try:
        ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None


def extract_news(news_impact: dict | None, direction: str, w: EvidenceWeights,
                 now: datetime) -> tuple[float, bool]:
    """F1xF2. Returns (signed_freshness_weighted_news, adverse_confirmed_flag).

    Convention: positive = argues bounce in trade direction, negative = argues knife.
    Fail-safe: missing/stale/thin news => (0.0, False) for the score, but a MISSING
    news feed is treated as 'uncertain, not all-clear' by the veto path (see decide)."""
    agg = (news_impact or {}).get("aggregate") or {}
    try:
        score = float(agg.get("score", 0.0))
        n = int(agg.get("n_scored", 0))
    except (TypeError, ValueError):
        return 0.0, False
    if n < w.news_min_n or abs(score) < w.news_min_abs_score:
        return 0.0, False
    age = _news_age_min((news_impact or {}).get("updated"), now)
    if age is None or age > w.news_max_age_min:
        return 0.0, False
    fresh = math.exp(-age / max(w.news_half_life_min, 1.0))       # F2 decay in [0,1]
    # score>0 == bullish gold. For a BUY: bullish supports (+), bearish is adverse (-).
    signed = (score / 100.0) * fresh
    if direction == "SELL":
        signed = -signed
    adverse_confirmed = signed < 0 and abs(score) >= w.news_min_abs_score and fresh > 0.25
    return signed, adverse_confirmed


def extract_reversal(signals: dict | None, direction: str) -> float:
    """F3. +1 if reversal_confirm confirmed in the trade direction, -1 if confirmed
    against, 0 otherwise."""
    rc = (signals or {}).get("reversal_confirm") or {}
    if rc.get("status") != "confirmed":
        return 0.0
    return 1.0 if rc.get("direction") == direction else -1.0


def extract_momentum(momentum_tf: dict | None, direction: str) -> float:
    """F4. Weighted vote of m15/h1 momentum vs the trade direction, in [-1, +1].
    m15 STRONG carries more weight; still-adverse momentum drives toward a knife."""
    mom = momentum_tf or {}
    want = "UP" if direction == "BUY" else "DOWN"
    m15 = mom.get("m15") or {}
    h1 = mom.get("h1") or {}

    def _vote(tf: dict, strong_w: float, weak_w: float) -> float:
        d = tf.get("direction")
        if d not in ("UP", "DOWN"):
            return 0.0
        weight = strong_w if tf.get("strength") == "STRONG" else weak_w
        return weight if d == want else -weight

    raw = _vote(m15, 0.6, 0.3) + _vote(h1, 0.4, 0.2)
    return max(-1.0, min(1.0, raw))


def _nearest_support_zone(sr_meta: list | None, price: float) -> dict | None:
    """Nearest support ('S') zone at/below price. Falls back to nearest 'S' by distance."""
    supports = [z for z in (sr_meta or []) if z.get("side") == "S" and z.get("level")]
    if not supports:
        return None
    below = [z for z in supports if float(z["level"]) <= price]
    pool = below or supports
    return min(pool, key=lambda z: abs(float(z["level"]) - price))


def extract_zone_prior(sr_meta: list | None, price: float,
                       w: EvidenceWeights) -> tuple[float, int]:
    """F5. Beta-smoothed empirical bounce probability at the nearest support zone
    (design §3). Returns (p_bounce, n_tests). Thin/absent data => shrinks to p0."""
    z = _nearest_support_zone(sr_meta, price)
    if not z:
        return w.global_bounce_rate, 0
    n = int(z.get("n_tests") or 0)
    bp = z.get("bounce_pct")
    if bp is None or n <= 0:
        return w.global_bounce_rate, n
    bounces = round(float(bp) / 100.0 * n)
    # Beta(alpha,beta) with prior mean p0 and strength k => data-efficient shrinkage.
    alpha = w.beta_prior_strength * w.global_bounce_rate
    beta = w.beta_prior_strength * (1.0 - w.global_bounce_rate)
    p = (bounces + alpha) / (n + alpha + beta)
    return max(1e-4, min(1 - 1e-4, p)), n


def extract_fast(fast_move_pips: float | None, direction: str) -> float:
    """F6. Bounded, signed overshoot. tanh keeps a 5000p spike from dominating.
    Sign is + when the fast move is *toward* the trade dir (already moved our way),
    - when it is against (a drop under a BUY = the classic counter_spike case)."""
    fast = float(fast_move_pips or 0.0)
    signed = fast if direction == "BUY" else -fast
    return math.tanh(signed / 500.0)


def extract_vol(volume_profile: dict | None, direction: str) -> float:
    """F7. Tick-volume tilt vs trade dir. Proxy only — lowest weight in the model."""
    tilt = (volume_profile or {}).get("tilt")
    if tilt == "buy":
        return 1.0 if direction == "BUY" else -1.0
    if tilt == "sell":
        return 1.0 if direction == "SELL" else -1.0
    return 0.0


def extract_rr(plan: dict | None, direction: str) -> float:
    """RR = tp_pips / sl_pips (iron-rule constraint, not a scored feature)."""
    plan = plan or {}
    sl_key = "buy_sl_pips" if direction == "BUY" else "sell_sl_pips"
    sl = float(plan.get(sl_key) or plan.get("sell_sl_pips") or plan.get("buy_sl_pips") or 0.0)
    tp = float(plan.get("tp_pips") or 0.0)
    return (tp / sl) if sl > 0 else 0.0


def build_features(bot_status: dict, news_impact: dict | None, direction: str,
                   w: EvidenceWeights, now: datetime | None = None) -> Features:
    """Assemble the full decision-time feature vector from a bot_status-shaped dict."""
    now = now or datetime.now(timezone.utc)
    market = bot_status.get("market") or {}
    zones = bot_status.get("zones") or {}
    signals = bot_status.get("signals") or {}
    price = float((bot_status.get("price_info") or {}).get("bid")
                  or (bot_status.get("price_info") or {}).get("ask") or 0.0)

    news_signed, news_adv = extract_news(news_impact, direction, w, now)
    zone_p, zone_n = extract_zone_prior(zones.get("sr_meta"), price, w)

    return Features(
        news_signed=news_signed,
        reversal=extract_reversal(signals, direction),
        mom_align=extract_momentum(market.get("momentum_tf"), direction),
        zone_prior=zone_p,
        zone_n_tests=zone_n,
        fast_signed=extract_fast(market.get("fast_move_pips"), direction),
        vol_tilt=extract_vol(bot_status.get("volume_profile"), direction),
        rr=extract_rr(bot_status.get("plan"), direction),
        news_adverse_confirmed=news_adv,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Model — Bayesian log-odds scorer (design §4)
# ─────────────────────────────────────────────────────────────────────────────
def _logit(p: float) -> float:
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def p_bounce(f: Features, w: EvidenceWeights) -> float:
    """P(bounce) = sigmoid( logit(zone_prior)  <- offset (design §4)
                          + w_news*news + w_rev*rev + w_mom*mom
                          + w_fast*fast + w_vol*vol + b0 ).

    The zone prior enters as an OFFSET (already a probability we trust); the weighted
    terms are learned *corrections* to it. Interpretable: each term is an additive
    shift in log-odds you can read per decision."""
    logodds = (
        _logit(f.zone_prior)
        + w.w_news * f.news_signed
        + w.w_rev * f.reversal
        + w.w_mom * f.mom_align
        + w.w_fast * f.fast_signed
        + w.w_vol * f.vol_tilt
        + w.b0
    )
    return _sigmoid(logodds)


def expected_value(p: float, rr: float) -> float:
    """EV in R units: win pays +rr, loss pays -1 (fixed SL). Selector ranks on this."""
    return p * rr - (1.0 - p) * 1.0


def is_falling_knife(f: Features, w: EvidenceWeights) -> bool:
    """The evidence-convicted veto (design §4). ALL FOUR must hold — a real knife:
       adverse news confirmed AND no reversal in favour AND momentum still adverse
       AND zone bounce prior below the global base rate."""
    return (
        f.news_adverse_confirmed
        and f.reversal <= 0.0
        and f.mom_align < 0.0
        and f.zone_prior < w.global_bounce_rate
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Decision — algorithm selector for `support-bounce` (design §1.5, §4)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Decision:
    action: str                       # "SELECT_SUPPORT_BOUNCE" | "STAND_DOWN"
    p_bounce: float
    ev_R: float
    reason: str
    features: Features = field(repr=False, default=None)


def decide_support_bounce(bot_status: dict, news_impact: dict | None, direction: str,
                          w: EvidenceWeights | None = None,
                          now: datetime | None = None) -> Decision:
    """Selector for the `support-bounce` algorithm. Returns SELECT or STAND_DOWN.

    STAND_DOWN is the principled, evidence-based replacement for the crude
    counter_spike block. SELECT does NOT mean 'trade' — in the real system it hands
    the candidate back to the UNCHANGED downstream gates (design §6). This function
    never places an order.

    Safety invariants:
      * RR < rr_floor            -> STAND_DOWN (iron rule).
      * falling-knife veto true  -> STAND_DOWN (the guard's instinct, now by evidence).
      * weights NOT fitted       -> conservative mode: only the veto/RR block; no
                                    probabilistic ALLOW is issued (cannot be looser
                                    than the crude guard until validated).
    """
    w = w or EvidenceWeights()
    f = build_features(bot_status, news_impact, direction, w, now)

    # Iron-rule RR gate first — unconditional.
    if f.rr < w.rr_floor:
        return Decision("STAND_DOWN", p_bounce(f, w), 0.0,
                        f"RR {f.rr:.2f} < {w.rr_floor} (iron rule)", f)

    # Fail-safe: a MISSING/stale news feed is 'uncertain', never 'all-clear'. If we
    # have no trustworthy news AND no positive confirmation from PA/momentum, we do
    # not manufacture confidence — treat as knife-risk present.
    no_news_trust = (f.news_signed == 0.0)
    no_positive_pa = (f.reversal <= 0.0 and f.mom_align <= 0.0)

    p = p_bounce(f, w)
    ev = expected_value(p, f.rr)

    if is_falling_knife(f, w):
        return Decision("STAND_DOWN", p, ev,
                        "falling-knife veto: adverse news + no reversal + momentum "
                        "down + low bounce prior", f)

    # Conservative mode: until weights are fitted+validated, never issue a new ALLOW.
    if not w.fitted:
        return Decision("STAND_DOWN", p, ev,
                        "weights NOT fitted -> conservative mode (no ALLOW until "
                        "replay-validated; behaves no looser than crude guard)", f)

    if no_news_trust and no_positive_pa:
        return Decision("STAND_DOWN", p, ev,
                        "no trustworthy news and no PA/momentum confirmation "
                        "-> stand down (uncertain != all-clear)", f)

    if p >= w.tau and ev > 0.0:
        return Decision("SELECT_SUPPORT_BOUNCE", p, ev,
                        f"P(bounce)={p:.2f} >= tau {w.tau} and EV={ev:+.2f}R > 0 "
                        f"(zone_prior={f.zone_prior:.2f}, n={f.zone_n_tests})", f)

    return Decision("STAND_DOWN", p, ev,
                    f"P(bounce)={p:.2f} < tau {w.tau} or EV={ev:+.2f}R <= 0", f)


# ─────────────────────────────────────────────────────────────────────────────
#  __main__ — self-contained demo on synthetic bot_status-shaped input
# ─────────────────────────────────────────────────────────────────────────────
def _demo() -> None:
    now = datetime(2026, 7, 17, 17, 0, 0, tzinfo=timezone.utc)

    # Synthetic snapshot A: a DIP-BUY that should be ALLOWED once fitted —
    # bullish news, reversal confirmed BUY, momentum up, price at a proven A-grade
    # support (bounce_pct 100 / 7 tests), RR ~2.4. The crude guard would BLOCK this
    # if the drop were >=500p; the evidence says 'support-bounce', not 'knife'.
    dip = {
        "price_info": {"bid": 3960.20, "ask": 3960.40},
        "market": {
            "trend": "BULLISH", "d1_trend": "BEARISH", "fast_move_pips": -640.0,
            "momentum_tf": {"m15": {"direction": "UP", "strength": "STRONG"},
                            "h1": {"direction": "UP", "strength": "STRONG"},
                            "h4": {"direction": "UP", "strength": "MODERATE"}},
        },
        "zones": {"sr_meta": [
            {"side": "S", "level": 3960.15, "n_tests": 7, "bounce_pct": 100,
             "grade": "A", "score": 94, "bars_since_touch": 1},
            {"side": "R", "level": 4034.0, "n_tests": 6, "bounce_pct": 33},
        ]},
        "signals": {"reversal_confirm": {"status": "confirmed", "direction": "BUY"}},
        "volume_profile": {"tilt": "buy"},
        "plan": {"buy_sl_pips": 500, "sell_sl_pips": 500, "tp_pips": 1200.0},
    }
    news_bull = {"updated": "2026-07-17T16:50:27Z", "window_min": 180,
                 "aggregate": {"score": 100, "n_scored": 5}}

    # Synthetic snapshot B: a genuine FALLING KNIFE that should STAND DOWN —
    # bearish news, no reversal, momentum still down, a worn support (bounce_pct 20).
    knife = {
        "price_info": {"bid": 4028.50, "ask": 4028.70},
        "market": {
            "trend": "BEARISH", "d1_trend": "BEARISH", "fast_move_pips": -900.0,
            "momentum_tf": {"m15": {"direction": "DOWN", "strength": "STRONG"},
                            "h1": {"direction": "DOWN", "strength": "STRONG"},
                            "h4": {"direction": "DOWN", "strength": "STRONG"}},
        },
        "zones": {"sr_meta": [
            {"side": "S", "level": 4025.0, "n_tests": 10, "bounce_pct": 20,
             "grade": "C", "score": 45, "bars_since_touch": 0},
        ]},
        "signals": {"reversal_confirm": {"status": "none"}},
        "volume_profile": {"tilt": "sell"},
        "plan": {"buy_sl_pips": 500, "sell_sl_pips": 500, "tp_pips": 1200.0},
    }
    news_bear = {"updated": "2026-07-17T16:50:27Z", "window_min": 180,
                 "aggregate": {"score": -85, "n_scored": 6}}

    fitted = EvidenceWeights(fitted=True)     # pretend a validated fit was loaded
    unfitted = EvidenceWeights(fitted=False)  # default ship-state

    print("=" * 78)
    print("evidence_entry_reference.py - DEMO (illustrative weights, NOT fitted)")
    print("=" * 78)
    for label, status, news in (("DIP-BUY (should ALLOW once fitted)", dip, news_bull),
                                ("FALLING KNIFE (should STAND DOWN)", knife, news_bear)):
        print(f"\n### {label}")
        for wlabel, w in (("ship-state (fitted=False)", unfitted),
                          ("hypothetical fitted", fitted)):
            d = decide_support_bounce(status, news, "BUY", w=w, now=now)
            print(f"  [{wlabel:26}] {d.action:22} "
                  f"P={d.p_bounce:.2f} EV={d.ev_R:+.2f}R :: {d.reason}")

    print("\nNote: ship-state ALWAYS returns STAND_DOWN (conservative); it also stands "
          "\ndown a true knife by veto. It can never be looser than the crude guard "
          "\nuntil weights are replay-validated (design sec 8, 9).")


if __name__ == "__main__":
    _demo()
