#!/usr/bin/env python
"""scripts/build_confirm_combos.py — สร้าง confirm_gate_combos.json (evidence-based) จาก confirm_tf_matrix.json.

confirm gate live (CONFIRM_GATE=true) ถ้า allowlist ว่าง = apply ทุก combo — แต่ควร apply **เฉพาะ (algo,pair)
ที่ backtest พิสูจน์ว่า confirm ช่วย (Δexp_R > 0)** ที่ best-TF ของ algo นั้น ไม่งั้นบางคู่ confirm อาจไม่ช่วย/ตัดฟรี.

allowlist = combo ที่ best-TF confirm ให้ dR>0 + n≥MIN_APPLY (ไม่ใช่ noise).
+ ธง validated_live = combo ที่ confirm-ON ผ่านเกณฑ์ live เข้ม (exp_R>0 · t≥2 · OOS≥0 · n≥80) = candidate ขึ้น live.

รัน: python scripts/build_confirm_combos.py   (เขียน data/confirm_gate_combos.json)
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
MATRIX = os.path.join(_ROOT, "data", "confirm_tf_matrix.json")
OUT = os.path.join(_ROOT, "data", "confirm_gate_combos.json")
MIN_APPLY = 25          # confirm-ON ต้องมีอย่างน้อยกี่ไม้ ถึงเชื่อว่า dR ไม่ใช่ noise
STRICT_N = 80


def main():
    from agents import confirm_gate as CF
    with open(MATRIX, encoding="utf-8") as f:
        rows = json.load(f)["rows"]

    combos = []; live_cand = []; detail = []
    for r in rows:
        algo = r["algo"]; pair = r["pair"]
        tf = CF.BEST_TF_BY_ALGO.get(algo)
        if not tf:                                     # algo ที่ไม่ confirm (fade/conf15m)
            continue
        d = (r.get("tf") or {}).get(tf)
        if not d:
            continue
        dR = d.get("dR"); n = d.get("n", 0)
        if dR is not None and dR > 0 and n >= MIN_APPLY:
            combos.append(f"{algo}|{pair}")
            row = {"combo": f"{algo}|{pair}", "tf": tf, "dR": dR, "on_expR": d.get("on_expR"),
                   "on_t": d.get("on_t"), "on_oos": d.get("on_oos"), "n": n}
            detail.append(row)
            if (d.get("on_expR", 0) > 0 and d.get("on_t", 0) >= 2.0
                    and d.get("on_oos", 0) >= 0 and n >= STRICT_N):
                live_cand.append(f"{algo}|{pair}")

    combos.sort(); live_cand.sort()
    out = {"note": "confirm gate apply เฉพาะ combo นี้ (best-TF confirm ให้ Δexp_R>0, n≥%d). ว่าง=apply ทุก combo." % MIN_APPLY,
           "criteria": "dR>0 · n≥%d (apply) · +t≥2·OOS≥0·expR>0·n≥%d (validated_live)" % (MIN_APPLY, STRICT_N),
           "combos": combos, "validated_live": live_cand,
           "detail": sorted(detail, key=lambda x: -x["dR"])}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"confirm allowlist: {len(combos)} combo (dR>0, n≥{MIN_APPLY}) → {OUT}\n")
    for row in out["detail"]:
        star = "  ⭐ผ่านเกณฑ์ live" if row["combo"] in live_cand else ""
        print(f"  {row['combo']:32s} {row['tf']} dR {row['dR']:+.3f} "
              f"expR {row['on_expR']:+.3f} t {row['on_t']:+.2f} n {row['n']}{star}")
    print(f"\nvalidated_live (confirm ดันข้ามเกณฑ์): {live_cand or '(ไม่มี — confirm ช่วยแต่ยังไม่ถึง t≥2/n≥80)'}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
