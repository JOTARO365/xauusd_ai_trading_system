# Gate-Integration Audit — Specialist Agents Feature (flag `SPECIALIST_ENABLED`, default OFF)

Auditor: gate-integration-auditor · Scope: how the newly-wired specialist-agents feature
integrates with `decision_maker` gates. Read-only. Every claim below is quoted `file:line`
and traced against the live code. Severity is never inflated.

Files traced:
`config.py`, `agents/trading_graph.py`, `agents/decision_maker.py`, `agents/zone_mapper.py`,
`agents/specialist_common.py`, `agents/trend_specialist.py`, `agents/range_specialist.py`,
`agents/specialist_router.py`, plus negative-grep over `agents/pending_manager.py`,
`agents/swing_manager.py`, `agents/mt5_connector.py`, `connectors/`.

---

## CONFIRMED FINDINGS (clean / verified)

### C1 — Flag-OFF: `node_specialist` is a true passthrough — CLEAN · [CONFIRMED]
`trading_graph.py:317-318` | `if not getattr(_cfg, "SPECIALIST_ENABLED", False): return {}`
Why: LangGraph merges the returned dict into state; `{}` merges nothing, so `chart_data`
is untouched and no key is added. The only OFF-path cost is one extra no-op node visit per
cycle (the graph always routes `chart → specialist → advisor`, `:382-383`) — a `getattr`
check that returns `{}`. Zero state change, zero prompt change, zero token change. Severity: none.

### C2 — Flag-OFF: `spec_line` empty ⇒ prompt byte-identical — CLEAN · [CONFIRMED]
`decision_maker.py:874-879` | `spec_line = ""` then guarded by
`if getattr(_cfg, "SPECIALIST_ENABLED", False):`
`decision_maker.py:888` | `{regime_line}{spec_line}`
Why: when OFF, `spec_line` stays `""`, so the f-string interpolation `{regime_line}{spec_line}`
renders exactly `{regime_line}` — no leading newline, no trailing text. The composed
`user_message` (`:881-890`) is byte-for-byte identical to the pre-feature prompt. Severity: none.

### C3 — Advisory-only: no gate / floor / cap / SL-TP touched — CLEAN · [CONFIRMED]
`_run_gates` spans `decision_maker.py:324`+; grep for `spec` across the whole module returns
ONLY `:874,876,878,888` — all inside the prompt-building block, which executes AFTER
`_run_gates` has already run and validated `direction`. The specialist writes two brand-new
keys only — `chart_data["zone_map"]` and `chart_data["spec_route"]` (`trading_graph.py:330`) —
and no gate reads either key. The confidence floor (`:640-669`, `62`), daily cap
(`config.py:216` `MAX_TRADES_PER_DAY=6`), SL/TP selection (`:928-929`, `:949-959`), and the
anti-fade / HTF / streak gates (`:460-461,564,701-702`) are all unchanged and never reference
specialist data. Severity: none.

### C4 — No new LLM/agent call — CLEAN · [CONFIRMED]
`zone_mapper.py:17`, `specialist_common.py:8`, `trend_specialist.py:22-24`,
`range_specialist.py:17-19`, `specialist_router.py:16-20` | imports are only `__future__` and
sibling specialist modules — no `anthropic`, no `llm`, no `invoke`, no `requests`.
`trading_graph.py:319-330` `node_specialist` calls only `build_zone_map` + `route` (pure Python).
The advisory rides the SINGLE existing `decision_maker` call (`decision_maker.py:899`
`raw_out = _llm.invoke(...)`). Net new LLM calls: 0. Module headers advertise "0 tokens"
(`specialist_router.py:4`, `trend_specialist.py:3`) and the code matches. Severity: none.

### C5 — Gate-conflict (flag-ON): specialist candidate cannot bypass `_run_gates` — CLEAN · [CONFIRMED]
The only production consumer of `spec_route` is `decision_maker.py:876`
`_top = (chart_data.get("spec_route") or {}).get("top")`, used solely to build advisory text
(`:878-879`). It is never assigned to `decision`, `direction`, `conf`, or any order field.
The direction the gates validate comes from the chart signal, and `:921-924` is a fail-safe that
forces SKIP if Claude's returned direction ≠ the gate-validated `direction`. The router itself
does NOT gate or place orders (`specialist_router.py:6-8`), and both candidate producers return
plain dicts (`trend_specialist.py:76-86`, `range_specialist.py:33-43`) with no execution path.
No path lets a specialist candidate force EXECUTE or a direction. Severity: none.

### C6 — No-bypass scope respected (design §5.2) — CLEAN · [CONFIRMED]
Negative grep for `zone_mapper|specialist|spec_route|zone_map|SPECIALIST_ENABLED` over
`agents/pending_manager.py`, `agents/swing_manager.py`, `agents/mt5_connector.py`, and
`connectors/**` returns NO matches. The feature did not wire into the pending / zone-reentry /
swing order paths — phase-1 stays market-order-advisory only, as designed. Severity: none.

### C7 — Graph integrity — CLEAN · [CONFIRMED]
`trading_graph.py:382-383` | `g.add_edge("chart","specialist")` + `g.add_edge("specialist","advisor")`
Edges are a correct linear insert of `chart → specialist → advisor`; the previous
`chart → advisor` behavior is preserved (specialist is a passthrough when OFF, additive when ON).
`node_specialist`'s body is fully wrapped `try/except` (`:319-333`) whose `except` returns `{}`
(`:331-333`), and its internal guards (`:322-326`) also return `{}` on missing data — so a raise
inside `build_zone_map`/`route` cannot break the cycle; the graph still reaches `advisor → …→ END`.
Severity: none.

### C8 — Flag-ON enrichment is purely additive to chart_data — CLEAN · [CONFIRMED]
`trading_graph.py:330` | `return {"chart_data": {**cd, "zone_map": zm, "spec_route": spec}}`
Why: spreads all existing `chart_data` keys unchanged and only ADDS `zone_map` + `spec_route`.
No downstream gate/order key is overwritten. Severity: none.

---

## NEEDS-VERIFICATION / MINOR HARDENING (flag-ON only — none block flag-OFF)

### V1 — `spec_line` builder uses `[]` subscripts, not `.get()` — LOW · [CONFIRMED as latent, not a live bug]
`decision_maker.py:878-879` |
`spec_line = (f"...{_top['tf']} {_top['direction']} Q{_top['quality']} ({_top['specialist']}) — {_top['reason']}")`
Why: this block is NOT wrapped in try/except (unlike `node_specialist`). It hard-subscripts five
keys. Traced against BOTH candidate producers — `trend_specialist.py:76-86` and
`range_specialist.py:33-43` — every candidate dict always contains `tf`, `direction`, `quality`,
`specialist`, `reason`. So NO `KeyError` is possible with today's code; this is a latent fragility,
not a live defect. If a future producer omits a key, this would raise inside `decision_maker` and
(unlike the graph node) is not fail-soft. Recommend `.get()` or a try-guard before flipping ON.
Severity: LOW (hardening only).

### V2 — `current` parity contract for `build_zone_map` (flag-ON) — LOW · [NEEDS-VERIFICATION]
`trading_graph.py:324` | `current = (ind.get("m15") or {}).get("close") or (ind.get("h1") or {}).get("close")`
Why: the pre-existing S/R review (`docs/reviews/sr-logic-review.md:100-103`) flags that exact
S/R parity with `pending_manager` holds only if the node feeds `zone_mapper` the SAME `current`
value `pending_manager` would compute (h4 close, else tick bid). Here the node uses m15/h1 close.
This affects only the ADVISORY zone_map/quality when ON (never a gate), so it cannot mislead a
gate — but if flag-ON candidates are later promoted to anything load-bearing, confirm this
`current` source matches the intended reference. Severity: LOW, advisory-only today.

---

## Clean-area summary
- Flag-OFF behavior change: NONE (C1, C2). Prompt byte-identical; state untouched.
- Gates / floor 62 / cap 6 / SL-TP / anti-fade: UNTOUCHED (C3, C5).
- New LLM/token cost: ZERO (C4).
- Order-path bypass (pending/swing/mt5/connectors): NONE (C6).
- Graph cycle safety: INTACT, fail-soft (C7).

---

## GO / NO-GO

**GO — keep the feature wired with `SPECIALIST_ENABLED` default OFF.** With the flag OFF the
feature is a proven no-op: `node_specialist` returns `{}` (`trading_graph.py:317-318`), `spec_line`
is `""` (`decision_maker.py:874`), the Claude prompt is byte-identical, and no gate, threshold,
cap, SL/TP, or order path is touched. Zero added tokens. Safe on a live-money system.

**Before flipping `SPECIALIST_ENABLED=true`, the following must hold:**
1. Harden `decision_maker.py:878-879` — switch the five `_top[...]` subscripts to `.get()` or
   wrap the block in try/except so a malformed candidate cannot raise inside `decision_maker`
   (V1). Not a live bug today, but the block is not fail-soft.
2. Confirm the `current` source at `trading_graph.py:324` matches the reference `pending_manager`
   uses, per `sr-logic-review.md:100-103` (V2) — advisory-only today, but nail it down before ON.
3. Re-affirm design §5.2 stays true: ON must remain advisory-text-only into the existing
   decision_maker call. The auditor found no path where a specialist candidate forces EXECUTE or a
   direction (C5) — keep it that way; any future promotion of `spec_route` beyond prompt text
   requires a fresh gate-integration audit.
