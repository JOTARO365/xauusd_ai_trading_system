# Dashboard Design Audit — XAU/USD Gold Desk

Persona: senior product designer (fintech / trading terminals). Audited the live dashboard
(localhost:5050, DASHBOARD tab, 1440px) against professional information-design principles.
Verdict tiers: **P0** = looks broken / hurts trust, **P1** = friction & inconsistency, **P2** = polish.

---

## What already works (keep this)

- **Strong domain identity.** The dark "institutional trade desk" terminal with green/red semantics is
  the right world for a gold desk — it reads as a professional tool, not a toy.
- **Good top-of-page thesis.** The "Institutional Trade Desk Brief" with the big `STAND-DOWN` badge,
  SNAPSHOT / SIGNAL / ENTRY / STOP / TARGET / NET R:R is a genuine hero — the most important state is
  first and scannable.
- **Semantic color is mostly correct** (green profit / red loss), and badges (SYS/MANUAL, BUY/SELL,
  CLOSED·WIN/LOSS) encode state in *form*, not just text.
- **The execution-desk pipeline row** (Chart Watcher → Advisor → Risk → Decision → Reporter) is a lovely
  mental model made visible.

---

## P0 — fix first (erodes trust / reads as broken)

1. **One flat density — no altitude.** Almost every section is the same card, same weight, same size,
   stacked at the same rhythm. A trader can't triage "what needs me now" vs "reference". → Establish a
   3-level hierarchy: **(a) Now** (the brief + live position), **(b) Performance** (book + equity),
   **(c) Ledger** (trade history). Give (a) more size/contrast, dim (b)/(c).

2. **Accent green == profit green.** The brand accent, active-nav, section ticks, AND "profit" all use
   the same green. The eye can't separate "this is a UI chrome accent" from "this number made money."
   → Pick ONE accent that is NOT the P&L green (e.g. the existing gold/amber for chrome/active), and
   reserve green strictly for positive P&L. This single change de-muddies the whole page.

3. **The Win/Loss donut is disproportionate and alarming.** It's ~500px tall, mostly red, and dominates
   the fold more than the actual P&L. Visually it screams "you're losing" louder than the data warrants.
   → Shrink to ~220px, put it beside the equity curve as a peer, and label the center with the WR% number
   (42.7%) so the ring is a support, not the star.

4. **Empty/collecting states look like failures.** (The trigger for this audit.) Rows of "—" read as
   "broken", not "collecting". → Every data panel needs a deliberate empty state: a one-line "why"
   ("รอสัญญาณ TREND breakout" / "เก็บ 1/30 วัน") + a subtle progress affordance, never a grid of dashes.

---

## P1 — friction & inconsistency

5. **ALL-CAPS everywhere.** Section titles, labels, and values all shout (SNAPSHOT, SIGNAL, BOOK
   PERFORMANCE, PERFORMANCE CHARTS…). Uppercase is a *seasoning* — used on everything it flattens
   hierarchy and slows reading. → Keep uppercase only for small eyebrow labels (letter-spaced); make
   section titles Title Case at a larger size; values stay natural.

6. **Inconsistent card system.** Some cards carry a left-border accent stripe, some don't; corner radii
   and inner padding vary; the "brief" box, the checklist box, and the stat cards are three different
   visual languages. → Define ONE card token (radius, padding, border, optional left-stripe = "this is
   actionable") and apply it everywhere. Same problem → same shape.

7. **Currency & sign formatting drift.** Mix of `฿` and `THB`, `+412.40 ฿` vs `-341.76 THB`, and raw
   `+2253.82` in the ledger. → One money format (symbol side, decimals, thin-space grouping, signed
   color) as a helper used everywhere. Tabular figures so columns align.

8. **Watermark collision.** The "T7" logo sits *on top of* the equity line, occluding data. → Remove the
   on-chart watermark or move it to the panel header at low opacity.

9. **Trade-history table is a wall.** 500 rows, 10 columns, every row full-contrast. → Zebra/entry-time
   grouping by day, right-align all numerics with tabular figures, de-emphasize repeated MANUAL/TP text,
   and make the whole row's win/loss legible from the P&L color alone (drop the redundant WIN/LOSS chip
   or shrink it).

10. **Filter controls float without a home.** The four "All Sources / Directions / Statuses / Results"
    selects sit unlabeled above the table with a different visual style than everything else. → Group them
    in a toolbar attached to the table header, with a result count ("500 items · showing 25").

---

## P2 — polish

11. **Vertical rhythm.** Section gaps are uneven; introduce a consistent spacing scale (e.g. 8/16/24/40)
    and a hairline divider or generous whitespace between the three altitude bands.
12. **Neutral palette is a flat grey.** Bias the greys slightly toward the gold accent (warm charcoal) so
    the neutrals read as *chosen*, not default.
13. **Typography pairing.** It's near-mono everywhere. Keep mono for numbers/tables (great), but set
    section titles and prose in a humanist sans for contrast and faster reading.
14. **Sparkline in "Equity Trend" card** is nice — extend that treatment (tiny inline trends) to the book
    stat cards (P&L, WR) so each KPI carries its own direction at a glance.
15. **Accessibility:** verify red/green pass contrast on the near-black bg (the reds look muddy); never
    rely on color alone (you already use ▲▼/labels — keep that discipline everywhere).

---

## Specific to the two Shadow panels (audit trigger)

The panels **render correctly** — they show "collecting" because forward data just began (TSMOM 1/30
D1 bars; momentum logs nothing until a TREND breakout). Design fixes so they don't read as broken:

- **Progress, not emptiness:** TSMOM row → `collecting 1/30 วัน` with a thin 1/30 progress bar; matrix →
  a header line "ยังไม่มีสัญญาณ — momentum ยิงเฉพาะ TREND breakout" (done in code) plus a muted illustration/
  hint instead of a row of `—`.
- **Backtest vs forward must never blur:** the `backtest R` column is in-sample reference; label it
  explicitly (`in-sample ref`) and visually separate (lighter, italic) from the live forward columns so a
  viewer never mistakes it for realized results.
- **Badge as the hero:** `collecting / ready / dying` is the one thing a viewer should read first per row —
  make it a proper pill with color+icon, left-aligned near the symbol, not last.

---

## Suggested sequence

**Batch 1 (P0, ~half a day):** accent-vs-profit green split · shrink the donut · 3-band altitude ·
empty-state pattern. These four transform the first impression.
**Batch 2 (P1):** card-token unification · money formatter · caps discipline · table density.
**Batch 3 (P2):** rhythm, palette warmth, type pairing, sparklines, a11y pass.

Each batch is display-only (no trading-logic risk) and can ship behind the same dashboard the desk already runs.
