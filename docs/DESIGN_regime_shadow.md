# DESIGN — Minimal-AI Regime Router, SHADOW mode

**status:** P-shadow (flag-OFF, add-only). **owner directive 2026-07-19:** "ยกเครื่อง entry ตาม design ใหม่"
→ เลือกทาง **Framework + shadow** (ไม่เอาเงินจริงเสี่ยงกับ algo ที่ P2 พิสูจน์แล้ว −EV).

## Why shadow (ไม่ flip live)
P2 gauntlet (`scripts/regime_backtest.py`) พิสูจน์แล้วว่า entry algos ปัจจุบัน (Donchian breakout, z-score fade)
**ไม่มี directional edge** บนทอง H1 (−EV ทุก cost). ดังนั้นเรา **สร้าง framework ใหม่เต็ม** แต่รัน shadow:
log ว่า "จะเข้าไม้ไหน" ไปข้างหน้าบน live data → เก็บ track record → validate → **แล้วค่อย flip เมื่อเจอ entry ที่มี edge**.
นี่คือ rollout discipline (skill quant-systematic-trading): design → collect unbiased data → validate → shadow → enable.

## Architecture (SELECTION / EXECUTION split — CORE INVARIANT)
```
[H1 bars จาก MT5]  →  regime_lib: ER/ADX/vol → detect_regime → REGIME_ALGO → route() → signal|STAND-DOWN
                         (deterministic ทั้งหมด — entry ไม่ prediction, ไม่มี LLM)
                                              ↓
                       logs/regime_shadow.jsonl  (0 order, 0 LLM)
```
- **EXECUTION (entry) = deterministic** จาก data ล้วน (regime_lib). SHADOW MVP คำนวณที่ **bar ปิดล่าสุด** ต่อ cycle
  (dedup ต่อ H1 bar). per-tick realtime = งานตอน flip live (fast loop) — ยังไม่ทำใน shadow.
- **SELECTION (regime) = deterministic** ใน shadow (ER/ADX/vol). **LLM regime override (sentiment ข่าวใหม่ +
  ตัวเลขเศรษฐกิจ) = event-driven, เพิ่มทีหลัง (P3)** — ตอนนี้ยังไม่เรียก LLM (0 token).

## Files (add-only, mirror SPECIALIST_SHADOW)
| ไฟล์ | ทำอะไร | แตะ live? |
|------|--------|-----------|
| `agents/regime_shadow.py` | engine: fetch H1 bars (`price_feed.get_ohlcv`) → `regime_lib.route()` → append log | ไม่ (นอก decision path) |
| `config.py` | flag `REGIME_SHADOW` (default False) + reload_config | flag เท่านั้น |
| `agents/trading_graph.py` | `node_regime_shadow` (gated, return {} = 0 influence) ต่อจาก `specialist` | node ใหม่ ไม่เปลี่ยน routing เดิม |
| `logs/regime_shadow.jsonl` | output (ต่อ H1 bar: regime, signal, features) | — |

## Log schema (per H1 bar)
```json
{"ts":"<utc now>","bar_ts":"<bar close utc>","regime":"TREND|RANGE|RISK-OFF|NEUTRAL",
 "close":3300.5,"er":0.4,"adx":27.1,"volpct":0.6,"atr":4.2,
 "signal":{"algo":"momentum_breakout","dir":"BUY","sl_pips":600,"tp_pips":1200} }   // null = STAND-DOWN
```
forward-labeling (P-next): replay bar ต่อจาก bar_ts → SL/TP hit ไหนก่อน (intrabar) → win/loss → track record จริงบน live-forward.

## Safety / invariants
- **flag OFF (default) = ระบบเดิม 0 เปลี่ยน.** Kill switch = `REGIME_SHADOW=false` (live-reload).
- **0 LLM, 0 order, return {}** — เหมือน SPECIALIST_SHADOW. fail-soft ทุกจุด (MT5 ล่ม → skip เงียบ).
- ไม่แตะ `_run_gates`, money mgmt, decision_maker, entry จริง, prompts.
- extra cost = 1 MT5 `copy_rates` call ต่อ full cycle (ไม่มี token).

## Path to flip live (ยังไม่ทำ — ต้อง validate ก่อน)
1. เก็บ shadow ~2-4 สัปดาห์ → forward-label → วัด EV จริงบน live-forward.
2. ถ้า/เมื่อ เจอ entry ที่มี edge (event-reaction/cross-asset/vol — ผ่าน gauntlet) → เสียบแทน route().
3. flip: per-tick executor + LLM regime (event-driven) → DRY_RUN → enable ทีละส่วน (most-confident first).
เกี่ยว: `docs/DESIGN_minimal_ai_regime_router.md` · `scripts/regime_lib.py` · `scripts/regime_backtest.py`.
