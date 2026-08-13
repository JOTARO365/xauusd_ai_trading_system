#!/usr/bin/env python
"""scripts/enforce_shadow_policy.py — combo exp_R<0 → บังคับ SHADOW (เก็บ stat), ไม่แตะตัวบวก (user 2026-08-13).

นโยบาย: algo ที่ยัง "ลบ" (exp_R<0) ไม่ควรเทรดจริง แต่ **ไม่ปิด (OFF)** — เปิด SHADOW เก็บ data ไว้ปรับให้บวกในอนาคต.
เกณฑ์ใช้ **exp_R sign** (ไม่ใช่ group tag) — cdc exp_R+0.98 แต่ group −EV เพราะ n<80 = ถือว่าบวก ไม่โดน downgrade.

ปลอดภัย: **downgrade-only** — LIVE(ลบ)→SHADOW หรือ OFF(ลบ)→SHADOW เท่านั้น. **ไม่เคย upgrade→LIVE** (เงินจริง = user คุมเอง).
ตัวบวก: ไม่แตะ (คงสถานะเดิม). ไม่ set OFF.

รัน dry (ดูก่อน): python scripts/enforce_shadow_policy.py
apply จริง:        python scripts/enforce_shadow_policy.py --apply
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
BR = os.path.join(_ROOT, "data", "backtest_results.json")


def main():
    apply = "--apply" in sys.argv
    from agents import shadow_switches as sw
    with open(BR, encoding="utf-8") as f:
        results = json.load(f)["results"]

    changes = []                                           # (combo, from, to, exp_R)
    keep_pos = 0; no_data = 0
    for r in results:
        algo = r.get("algo"); pair = r.get("pair"); exp = r.get("exp_R")
        if not algo or not pair or pair in ("—", "XAU~XAG"):
            continue
        if exp is None:
            no_data += 1; continue
        cur = sw.state_of(algo, pair)                      # LIVE/SHADOW/OFF (default SHADOW)
        if exp < 0:                                        # ลบ → ต้อง SHADOW (เก็บ stat)
            if cur != sw.SHADOW:
                changes.append((f"{algo}:{pair}", cur, sw.SHADOW, exp))
        else:
            keep_pos += 1                                  # บวก → ไม่แตะ

    print(f"exp_R<0 ที่ต้อง → SHADOW: {len(changes)} combo · บวก(ไม่แตะ): {keep_pos} · no-data: {no_data}\n")
    for combo, frm, to, exp in sorted(changes, key=lambda x: x[3]):
        flag = "  ⚠️ LIVE→SHADOW" if frm == sw.LIVE else "  OFF→SHADOW" if frm == sw.OFF else ""
        print(f"  {combo:30s} {frm:6s} -> {to:6s}  (exp_R {exp:+.3f}){flag}")

    if not changes:
        print("ไม่มี combo ต้องเปลี่ยน (ตัวลบ SHADOW อยู่แล้ว)."); return
    if not apply:
        print(f"\n[DRY] ยังไม่เขียน. apply จริง: python scripts/enforce_shadow_policy.py --apply"); return
    algo_id = pair = None
    n = 0
    for combo, frm, to, exp in changes:
        algo_id, pair = combo.split(":")
        try:
            sw.set_state(algo_id, pair, to); n += 1
        except Exception as e:
            print(f"  set_state fail {combo}: {e}")
    print(f"\n✅ เขียนแล้ว {n} combo → SHADOW (downgrade-only, ตัวบวกไม่แตะ, ไม่มี OFF).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
