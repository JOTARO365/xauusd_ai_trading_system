# cwayinvestment channel — distilled knowhow (context-firewall map-reduce)

Source: https://www.youtube.com/@cwayinvestment · distilled via youtube-to-knowhow (transcripts stayed in throwaway subagents). Target: XAUUSD algo system. Each clip = 1 firewall subagent.

**Meta-finding:** the channel content LARGELY CONFIRMS this project's existing discipline (drift-null/OOS/multiple-testing/look-ahead/Deflated-Sharpe, minimal-AI invariant, no-gold-edge, risk>entry, token-ROI). Genuinely NEW material is a handful of techniques + one strategic direction. Most clips → fold into existing skills (quant-systematic-trading, quant-sat, ai-loop-engineering), NOT new skills.

---

## 🟢 THE big strategic nugget — stat-arb on the gold complex
From **"เทรดแบบ Quant"** (4ztRlVesFns, stat-arb practitioner interview): monetize "gold has no DIRECTIONAL edge" by trading the **SPREAD** (market-neutral mean-reversion), not direction.
- ⚠️ **XAU/XAG specifically = already dead** (our cointegration.json: corr0.82 ADF−2.14 tradeable:false, [[pairs-xau-xag-not-cointegrated]]). So NOT gold/silver.
- Candidates NOT yet tested: gold vs gold-miners (GDX/GDXJ/NEM), gold-in-another-currency (XAUUSD vs XAUEUR/XAUJPY spread), gold vs other safe-haven.
- Techniques (fold into quant-systematic-trading):
  - **cointegration is the gate, correlation only a scanner** (spread stationarity through time, not co-movement)
  - **OLS hedge ratio (beta), never 1:1**; re-estimate on regime shift
  - **distribution-shape regime monitor**: spread histogram unimodal=tradeable, bimodal appearing=regime break→refit/drop (cheap, 0-token, NEW)
  - **out-of-distribution exit**: spread leaves historical support → flatten (no stats backing)
  - **VaR-based stop** (tail of spread dist) alongside structural-SL
  - **asymptotic-arb breadth**: DD controlled by N independent pairs (~50), not by tightening one stop — edge = count of independent bets
  - **amplitude > round-trip cost gate**: pretty reversion untradeable if swing < spread+commission (killed our M1 scalp too)
  - **1/SD (inverse-vol) sizing** as simple optimal; Kelly only for alpha
- **Route:** memory note (project direction) + fold techniques into quant-systematic-trading. Must pass drift-null vs equal-weight/random-pair benchmark before live.

---

## 🟢 Validation / testing additions (fold → quant-systematic-trading + quant-auditor)
From AI-eval clips (ox6GHbBseKw, GElQV3i0-oE) + HPO clip (6zCpxOkk97Q):
- **Synthetic-path Monte-Carlo stress** (Heston/stochastic-vol paths, injected vol ~25-30%, drift, 2000+ steps) — survival in NEVER-OBSERVED regimes. Genuinely beyond our real-history OOS/PBO/purged-CV. **NEW, highest-value test add.**
- **CVaR (conditional VaR / tail loss)** as a robustness gate — we don't use it. NEW.
- **Sortino / Recovery-Factor / Profit-Factor / SQN** in metrics panel (downside-focused; asymmetric-SL gold trades → downside-σ more honest than Sharpe). Complements our t-stat/DSR.
- **Pre-declared downside budget as pass anchor** — judge vs tolerance declared BEFORE the test, not vs zero. (matches our drift-null "right benchmark" lesson)
- **"Earn the right to optimize"** — no HPO run until base passes drift-null+OOS; optimize on a SEPARATE/synthetic slice (not the dev set); log trial-count (50=demo,200-300 real,1000 synthetic) as overfit signal. NEW anti-snooping discipline.
- **HPO = Optuna/TPE joint multi-param** (not one-at-a-time sweeps); objective = Sortino/CVaR/min-DD; **tune RISK+EXIT params, not entry** (= our thesis edge=discipline+risk).

## 🟢 AI-agent architecture (mostly CONFIRMS our design)
From OytXNomxIvQ, 9u_YmHLNyhM(pending), ox6GHbBseKw, pAyWhmk1_hw, vEu8M2K3UHc, f8_v6Ct6WA0(pending):
- **Two-tier: dumb algo robots (fast loop) + AI supervisor (slow cron, hourly)** — AI never in fast path, never decides entry. = our algo-router-log-only + token-ROI. CONFIRMS.
- **AI action space = reduce-only / de-risk** (cut size, halt, hedge — never increase/promote). = independent validation of our demote-only + ALGO_ROUTER_ALLOW_PROMOTE=false. ⚠️ their demo WRITES live config in a closed LLM loop = exactly our roster-drift trap; DO NOT adopt write-back.
- **eval rubric as a reusable SKILL** (fixed checklist, strategy = swappable class) = our quant-auditor formalized.
- **numbers via forced-API skill + code-exec, NEVER LLM web-scrape** (LLM fabricates prices) = our compute-in-code rule. CONFIRMS.
- **grounding skill for low-training-data targets** (e.g. MQL5) — inject domain doc, don't one-shot.

## 🟡 Loop engineering (fold → ai-loop-engineering)
From rMJMgzNxiyg: escalation-rate WITH memory-of-failure (narrow search, not just grow); baseline-skip stopping (re-score live, do nothing if still passes); weekly-journal maintenance loop (live trade_registry as feedback gate); single/double/triple-loop escalation ladder (param-tune → strategy-class switch → rewrite). "optimize risk/survival envelope not entry" = matches finding.

## 🔴 Off-thesis / confirmations (note-only, NO skill)
- **Grid (vM1B_ekRycg, CWVQOL6cdSs, GRID playlist)** = martingale/no-SL; presenter's own examples are blowups. CONFIRMS iron-rule "no grid". 1 nugget: broker/counterparty-failure risk (a risk category we don't track — single-MT5 today).
- **Fibonacci (jWVUniqX7m8)** = source ITSELF says naked-fib low WR, not edge; anchor = look-ahead trap. CONFIRMS chart-pattern no-edge.
- **Loss psychology (t__kJahlBkA)** = 90% human; algo already removes emotion. 1 nugget: tag loss trades by error-pattern in loss_adaptive journal (segment toxic setups).
- **Cross-sectional momentum (Hkj9Xi3os7Q)** = weak fit (our universe ~8 too small/diverse); backtestable but likely fails equal-weight-null. Fold quant-systematic-trading.

---

## Routing decision (pending owner approval)
- **NO new skills** — nearly every clip folds into existing (quant-systematic-trading / quant-sat / ai-loop-engineering / quant-auditor).
- **Extend quant-systematic-trading**: stat-arb techniques + synthetic-stress/CVaR/Sortino + HPO-gating.
- **Extend quant-auditor** (agent): synthetic Monte-Carlo stress + CVaR gate + pre-declared downside budget.
- **Extend ai-loop-engineering**: escalation-with-memory + baseline-skip + triple-loop ladder.
- **Memory**: stat-arb-on-gold-complex candidate direction (NOT XAU/XAG — dead).

## 🟢 STRONGEST adopt signal — synthetic-data cross-check (4 independent clips)
Appears in 6zCpxOkk97Q, ox6GHbBseKw, GElQV3i0-oE, 9u_YmHLNyhM = the channel's #1 repeated technique we DON'T have: after backtest/optimize on real history, RE-RUN on **synthetic price paths** (GBM/Heston/stochastic-vol, parameterized weekly-vol + drift, regime-switch segments) → confirm edge survives NEVER-OBSERVED regimes. Our validation only resamples real history (OOS/PBO/purged-CV). This directly attacks our #1 weakness (window-bias / real-vs-fit edge). **Adopt: add synthetic-path stress to the validation battery.**

## 🟢 Code/workflow hygiene (fold → note/QUICKREF)
- **3-file split: backtest / optimize / trade** — the trade binary carries ONLY final params, zero backtest code (prevents dev change touching live logic). 9u_YmHLNyhM, vEu8M2K3UHc.
- **CLI-wrapper + per-engine reference .md** so the agent drives backtests via CLI (not inline codegen = token/memory guard). 9u_YmHLNyhM. = our compute-in-code/token-ROI.
- **AI-as-maintainer** (live robot = plain algo, AI only reads trade journal → issues reduce-only management policy) = independent confirmation of our minimal-AI + loss_adaptive design. OytXNomxIvQ, 9u_YmHLNyhM.
- **web_news hardening**: source-tier allowlist + recency-lock ("current data only") + cite-or-drop per number. AZdeiHiSg6Y, rYSCWZVNCfg, M-W5q0gMiZs.
- **research-paper library + digest skill** (arXiv search → PDF→markdown digest listing "ideas to develop next" + data/tools used) — persistent edge-source library for mining. 9u_YmHLNyhM, Am7l0QIwgpM (= our book-to-skill/youtube-to-knowhow pattern).

## 🟢 Net-new from Advance + Strategies playlists
- **FRED via pandas-datareader** = free source for gold's cleanest driver AlphaVantage lacks natively: real rates **DFII10** (10y TIPS) + breakeven inflation **T10YIE**. Context/risk-shape (not alpha). → QUICKREF data-source note.
- **TA-Lib** = go-to lib for algorithmic candlestick-pattern detection IF ever backtesting patterns (CDLDOJI/CDLHAMMER/CDLENGULFING...). ⚠️ prior=no edge; ~60 patterns = heavy multiple-testing → need Deflated-Sharpe. Backtest-hypothesis note only.
- **Disposition effect** (retail sells winners/holds losers) = documented inefficiency → **supports the momentum/trend-continuation thesis** (underreaction). Mild support for our tsmom/momentum direction. Not a new algo.
- **Elder Triple Screen (MTF#2)**: one testable entry SHAPE = HTF-momentum-accel-up (weekly MACD-hist ROC>0) + LTF-dip-resuming (Elder BearPower<0 & rising) + micro-breakout (high>prior high), buy-only. Backtest-hypothesis (⚠️ its no-SL/%-target exits violate iron rule — use our structural-SL). Log, don't build.
- **odds↔probability** P=odds/(1+odds) — minor, only if we ingest market-implied odds (we don't).
- **Camarilla / Alligator / Williams%R / Ichimoku / MTF#1 / trend-following / snowball / supply-demand** = all level/indicator/trend families = **drift-null prior = no gold edge** (same class as our rejected S/R, fib, zone tests). Camarilla pivots ARE causal-computable but "random constant offset from prior close = same result". Snowball's only keeper = add-to-winner(ok) vs add-to-loser(martingale,forbidden) — already our stance. Confirm-rejected; do NOT re-mine.
- **Grid family** (grid/zone-recovery/momentum-grid/cascading): off-thesis martingale/no-SL; presenters' OWN examples are blowups; iron-rule forbids. 1 keeper: vol-scaled zone WIDTH (ATR/ADR/stdev) = display/gate-width only, we already have ATR. + broker/counterparty-failure risk (new risk category, single-MT5 today).
- **Psychology family** (bias/overconfidence/disposition/endowment/error-patterns): algo removes emotion by design; all fold to existing guards (loss_adaptive, structural-SL, news-dampener). 1 keeper: **tag loss trades by error-pattern in loss_adaptive journal** (segment toxic setups). overconfidence→confidence-calibration guard (we have calibration).

## ✅ FINAL ROUTING (apply on approval)
1. **Extend `quant-systematic-trading` skill** (the main additive home): synthetic-path Monte-Carlo stress · CVaR/Sortino/Recovery/Profit-Factor/SQN metrics · pre-declared downside budget · "earn-the-right-to-optimize" HPO gating (pre-screen + separate/synthetic slice + trial-count) · gold-complex stat-arb techniques (cointegration-gate, OLS-hedge, distribution-shape regime monitor, out-of-dist exit, breadth, amplitude>cost, 1/SD sizing) · odds↔prob.
2. **Extend `quant-auditor` agent**: add synthetic Monte-Carlo stress + CVaR gate + pre-declared-downside-budget verdict.
3. **Extend `ai-loop-engineering` skill**: escalation-with-memory-of-failure · baseline-skip stopping · weekly-journal maintenance loop · single/double/triple escalation ladder · optimize-risk-envelope-not-entry.
4. **QUICKREF/note**: FRED real-rate source · web_news source-tiering+recency-lock+cite-or-drop · 3-file split (backtest/optimize/trade) · CLI-wrapper+ref-md · TA-Lib pointer · broker-failure risk category · data-only MT5 safety mode.
5. **Memory**: stat-arb-on-gold-complex candidate direction (NOT XAU/XAG — dead; try gold-miners/XAU-cross) + "cway channel: confirm-rejected chart/grid families, do-not-re-mine".
6. **Backtest hypotheses logged** (not built): Elder-Triple-Screen shape, candlestick via TA-Lib, cross-sectional momentum — all need drift-null first, prior=likely fail.
**NO NEW SKILLS** — every subagent independently concluded fold-into-existing.

## Status
Playlist 1 GenAI (15) DONE + 4ztRlVesFns DONE. As9Ym1fKHMg = no transcript (skip).
Consensus across ALL subagents: NO new skills; fold into existing + notes. Value concentrated in ~4 clips (stat-arb 4ztRlVesFns, AI-eval synthetic-stress ox6GHbBseKw/GElQV3i0-oE, HPO-gating 6zCpxOkk97Q).
**ALL 5 playlists COMPLETE** (~40 unique clips distilled via firewall subagents). No-transcript (skipped): As9Ym1fKHMg, W4YefSX2_U4 (MT4-Linux), zRKO_eKW1A4 (Ichimoku); Hl3SC5HMafM (Supply/Demand) = members-only paywall.
Verdict unchanged & reinforced across all: NO new skills; every clip folds into existing skills / confirms our discipline / off-thesis. Value concentrated in ~4 clips (stat-arb, synthetic-stress ×4, HPO-gating, FRED real-rates). Psychology playlist = algo already removes emotion (all guards exist); Strategies playlist = all level/indicator/trend families = chart-pattern no-edge prior (confirm-rejected, do-not-mine); GRID playlist = martingale off-thesis (iron-rule confirmed by presenters' own blowups).
