# S/R Zone-Mapping Logic Review — `agents/zone_mapper.py`

Reviewer: `sr-logic-reviewer` | Date: 2026-07-14 | Scope: read-only
Under review: `agents/zone_mapper.py` (NEW) vs consumed producer `agents/chart_watcher.py`
and mirrored math in `agents/pending_manager.py`.

Hand-traced with live values from `logs/bot_status.json` (current XAU = 4123.77).
Every claim below quotes `file:line` and is traced against the actual code.

---

## Verdict summary

No CONFIRMED bugs. Box math is an **exact** mirror of `pending_manager`, units are
correct, dist_pct sign/nearest logic is correct, all edge cases fail-soft (never raise),
consumed field names match what `chart_watcher` emits, and no datetime is introduced.
Two low-severity NEEDS-VERIFICATION notes (both benign for XAUUSD) below.

---

## CONFIRMED findings

### C1 — Box math parity is EXACT [CONFIRMED, severity: none / PASS]
`zone_mapper._build_box` (`zone_mapper.py:61-92`) vs
`pending_manager.manage_range_pending` (`pending_manager.py:714-749`).

Side-by-side of every step:

| step | pending_manager | zone_mapper | match |
|------|-----------------|-------------|-------|
| res filter/sort | `sorted([r for r in ... if r > current])` `:717` | `sorted([r for r in ... if r > current])` `:68` | yes |
| sup filter/sort | `sorted([s ... if s < current], reverse=True)` `:718` | same `:69` | yes |
| PDH merge | `if pdh and pdh > current: res_list = sorted(set(res_list + [round(pdh,2)]))` `:722-723` | same `:72-73` | yes |
| PDL merge | `... reverse=True` `:724-725` | same `:74-75` | yes |
| both-sides guard | `if not res_list or not sup_list: ... return 0` `:727-729` | `... valid=False, "no bounds both sides"` `:77-79` | yes (skip vs valid=False, same semantics) |
| bounds pick | `upper=res_list[0]; lower=sup_list[0]` `:731-732` | same `:81` | yes |
| width_pips | `round(range_width / point)` `:735` | `round(width / _POINT)` `:83` | yes (see V1) |
| MIN_WIDTH | `MIN_WIDTH_PIPS = 2000` `:738-739` | `_MIN_BOX_WIDTH_PIPS = 2000` `:20,85` | yes |
| ATR guard | `if h4_atr > 0 and h4_atr > range_width * 0.60` `:745` | `if h4_atr > 0 and h4_atr > width * _ATR_WIDTH_FRAC` (0.60) `:21,88` | yes |

Both read the SAME combined-TF `chart_data["sr_zones"]` (`chart_watcher.py:1544`
sets it to `h4_sr + h1_sr`), so no sorting/merge divergence is possible.

Hand-trace on live data (current = 4123.77):
- resistance `[4202.99,4221.07,4246.26,4369.27,4382.2,4143.97]` → `res_list = [4143.97,4202.99,4221.07,4246.26,4369.27,4382.2]`
- support `[4121.6,4023.87,3960.15,3942.28,4119.73,4100.28]` → `sup_list = [4121.6,4119.73,4100.28,4023.87,3960.15,3942.28]`
- pdh=4115.53 (NOT > current → res unchanged); pdl=3942.28 (< current, already present → sup unchanged)
- `upper=4143.97`, `lower=4121.6`, `width=22.37`, `width_pips=round(2237.0)=2237`
- 2237 ≥ 2000 → passes width guard; ATR guard fires iff h4_atr > 13.42 (likely, given gold H4 ATR)

Both modules yield IDENTICAL `upper/lower/width_pips` and the same guard decision. **Parity confirmed.**

### C2 — Units correct (1 pip = 1 point = 0.01) [CONFIRMED, PASS]
`_POINT = 0.01` (`:19`); `width_pips = round(width / _POINT)` (`:83`) converts price-delta →
pips. `_dist_pct` (`:24-28`) returns a *percent* `(level-current)/current*100`, correctly
named `dist_pct` (not pips) — no pips/points/price confusion anywhere.

### C3 — dist_pct sign + nearest selection correct [CONFIRMED, PASS]
`_dist_pct` (`:24-28`): level above current → positive, below → negative. Matches spec (+above / -below).
`_nearest` (`:52-58`): `"R"` → `z["side"]=="R" and z["level"]>current`, `"S"` → `side=="S" and level<current`,
then `min(..., key=abs(dist_pct))`. Distance-sorted, correct side filtering.
Trace: nearest R = 4143.97 (0.49% above, closest R > 4123.77); nearest S = 4121.6 (0.05% below, closest S < 4123.77). Correct.

### C4 — Edge cases all fail-soft, never raise [CONFIRMED, PASS]
- `chart_data` not dict OR `current` falsy → early empty-but-valid map (`:108-111`).
- empty/missing `sr_meta` → `for m in sr_meta or []` (`:34`) → empty ladder → `_nearest` returns `None`.
- missing `level` → `if lv is None: continue` (`:35-36`).
- `level == current` → excluded from both nearest sides (strict `>` / `<`), still listed in ladder with dist_pct 0. Benign.
- `current = 0` → `_dist_pct` guards `if not current: return 0.0` (`:26-27`); `build_zone_map` returns early anyway.
- missing `sr_zones`/`key_levels` → `.get(...) or {}` (`:64-65`); `_build_box` with no bounds → `valid=False, "no bounds both sides"` (`:77-79`).
No `raise` path exists in the module.

### C5 — Consumed field names match producer [CONFIRMED, PASS]
`chart_watcher._build_sr_meta._one` (`:893-897`) emits per entry:
`level, side, tf, touches, strength, why` (+bars_since_touch/avg_bounce/… display extras).
`confluence` is added conditionally by `_tag_confluence` (`:857-858`) as a dict `{"with","count"}`.
`zone_mapper._build_ladder` (`:38-47`) reads `level, tf, side, strength, touches, confluence, why` — all present.
`confluence` is read via `bool(m.get("confluence"))` (`:45`) → `True` when the dict exists, `False`/absent → `False`. No crash, no silent-empty.

Container keys consumed by zone_mapper vs emitted by chart_watcher `result` dict:
- `sr_meta` `:1546` ✓ · `sr_zones{resistance,support}` `:1544-1545` ✓ · `key_levels{pdh,pdl}` `:1550` ✓ · `htf_zone` `:1551` ✓ · `indicators.h4.atr` `:1553` ✓ (same path pending_manager reads at `:704`).
(Note: `bot_status.json` nests these under `"zones"`, but that is the dashboard status file — the live `chart_data` passed to zone_mapper is the top-level `result` dict, whose keys match. No mismatch.)

### C6 — No datetime introduced [CONFIRMED, PASS]
`zone_mapper.py` imports only `from __future__ import annotations` (`:17`). No `datetime`/`time`
import, no timestamp construction anywhere. Confirmed — no naive-time surface added.

---

## NEEDS-VERIFICATION (low severity — benign for XAUUSD)

### V1 — Point size hardcoded 0.01 vs pending_manager's live `info.point` [NEEDS-VERIFICATION, severity: low]
`zone_mapper.py:19,83` uses constant `_POINT = 0.01`. `pending_manager.py:703` uses
`point = info.point if info else 0.01` (live MT5 symbol point). For XAUUSD `info.point == 0.01`,
so they agree in practice and the trace above is exact. They would only diverge if the broker's
gold point differed from 0.01 (not the case here; module docstring `:10` explicitly fixes gold=0.01).
Fix (optional): none required for gold; if ever generalized, source the point from the same place.

### V2 — Box parity depends on caller passing the same `current` [NEEDS-VERIFICATION, severity: low]
`pending_manager` derives `current` internally (`:694-697`: h4 close, else tick bid). `zone_mapper`
takes `current` as a parameter (`:95`). Bounds selection (`res_list[0]`/`sup_list[0]`) is sensitive to
`current`, so exact parity holds only if the graph node feeds zone_mapper the SAME `current`
pending_manager would compute. Not a defect in zone_mapper; a wiring contract to honor when the node is added.

---

## Clean areas (explicit)
- Box math parity: exact (C1).
- Units / pip conversion: correct (C2).
- dist_pct sign and nearest R/S selection: correct (C3).
- Fail-soft on empty/missing/zero inputs: holds, never raises (C4).
- Consumed field-name shape vs producer: matches, no silent-empty (C5).
- No datetime / naive-time added (C6).

Observation (not a bug): the ladder mixes H4 and H1; `nearest.resistance` on live data is
4143.97 — an H1 level with strength 40 (weak). Nearest is by pure distance per spec; any
strength/TF preference is a downstream specialist decision, out of this module's scope.

---

## Verdict
**Safe to proceed to TrendSpecialist: YES** — no confirmed defects; box math mirrors
`pending_manager` exactly; only two low-severity wiring notes (point source, shared `current`).
