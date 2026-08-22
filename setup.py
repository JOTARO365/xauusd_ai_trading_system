"""setup.py — one-shot bootstrap for a fresh machine.

Run once after `git pull`:   python setup.py
Does everything a fresh checkout needs, then prints how to start the bot + dashboard.
Does NOT start the live bot (that is your controlled action — real money).

Steps: Python check → pip install -r requirements.txt → sync .env → runtime dirs → verify MT5
       → broker symbol map (probe, prefer trade_mode=FULL) → regen backtest ต่อโบรก (SKIP_BACKTEST ข้ามได้).
.env handling:
  (1) sync_env  — เพิ่มคีย์ใหม่จาก .env.example (ไม่ทับค่าเดิม) → fresh pull ได้คีย์ครบ
  (2) apply_shared — เขียนทับ config ที่ทีมใช้ร่วม (.env.shared) เฉพาะค่าที่ต่าง · **secret ไม่แตะ**
      (api key / MT5 / twitter / DB) · backup .env.bak · print diff → collaborator รัน setup แล้ว config ตรง owner
Idempotent + safe to re-run.
"""
import os
import shutil
import subprocess
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_OK, _WARN, _ERR = "  [OK] ", "  [!]  ", "  [X]  "


def step(n, title):
    print(f"\n-- {n}. {title} " + "-" * max(0, 46 - len(title)))


def _env_keys(path):
    """set ของ KEY ที่มีอยู่ใน env file (ข้าม comment/บรรทัดว่าง)."""
    keys = set()
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                s = ln.strip()
                if s and not s.startswith("#") and "=" in s:
                    keys.add(s.split("=", 1)[0].strip())
    except OSError:
        pass
    return keys


def _example_kv_lines(path):
    """list ของ (KEY, raw_line) เฉพาะบรรทัด KEY=value ใน .env.example (เก็บ inline comment + ลำดับเดิม)."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                s = ln.strip()
                if s and not s.startswith("#") and "=" in s:
                    out.append((s.split("=", 1)[0].strip(), ln.rstrip("\n")))
    except OSError:
        pass
    return out


# คีย์ที่ "ห้ามเขียนทับ" ต่อให้อยู่ใน .env.shared (secret/per-account) — api key, MT5, twitter, DB
_SECRET_HINTS = ("API_KEY", "PASSWORD", "LOGIN", "SERVER", "TOKEN", "SECRET",
                 "SUPABASE", "TRADING_API", "ANTHROPIC", "GEMINI", "DATABASE_URL",
                 "X_USERNAME", "X_EMAIL", "MT5")


def _is_secret(key):
    ku = key.upper()
    return any(h in ku for h in _SECRET_HINTS)


def _clean_val(raw):
    """ค่าหลัง '=' → ตัด inline comment (' #...') + quotes + ช่องว่าง (ให้เทียบค่าได้ตรง)."""
    v = raw.split(" #", 1)[0] if " #" in raw else raw
    return v.strip().strip('"').strip("'")


def apply_shared(env, shared):
    """บังคับ config ที่ทีมใช้ร่วม (.env.shared) → เขียนทับ .env เฉพาะคีย์ที่ค่า **ต่างกัน**.
    ⚠️ secret (api/MT5/twitter/DB) ไม่แตะ (กัน _is_secret). backup .env → .env.bak ก่อนเขียน.
    คืน list ของ (key, old, new) ที่เปลี่ยน (ว่าง = ตรงกันหมด/ไม่มีไฟล์)."""
    smap = {}                                            # key → (clean_value, fullline) เฉพาะ non-secret
    for k, line in _example_kv_lines(shared):
        if not _is_secret(k):
            smap[k] = (_clean_val(line.split("=", 1)[1]), line)
    if not smap:
        return []
    with open(env, encoding="utf-8") as f:
        lines = f.readlines()
    changed, seen, out = [], set(), []
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in smap:
                seen.add(k)
                cur, (newval, newline) = _clean_val(s.split("=", 1)[1]), smap[k]
                if cur != newval:
                    changed.append((k, cur, newval))
                    out.append(newline + "\n")
                    continue
        out.append(ln if ln.endswith("\n") else ln + "\n")
    missing = [(k, v[1]) for k, v in smap.items() if k not in seen]
    if not (changed or missing):
        return []
    shutil.copy(env, env + ".bak")                       # backup ก่อนแก้ (กู้ได้)
    if missing:
        from datetime import date
        out.append(f"\n# --- {date.today().isoformat()}: config จาก .env.shared (setup.py) ---\n")
        for k, line in missing:
            out.append(line + "\n")
            changed.append((k, "(ไม่มี)", _clean_val(line.split("=", 1)[1])))
    with open(env, "w", encoding="utf-8") as f:
        f.writelines(out)
    return changed


def _write_env_key(env, key, value):
    """เพิ่ม/แทน KEY=value ใน .env (แทนบรรทัดเดิมถ้ามี, ไม่งั้น append). ไม่แตะบรรทัดอื่น."""
    try:
        with open(env, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        lines = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s and not s.startswith("#") and s.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}\n"
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    with open(env, "w", encoding="utf-8") as f:
        f.writelines(lines)


def ask_broker_symbols(env):
    """interactive: list candidate BTC/น้ำมัน จาก MT5 → ให้เลือก → เขียน BROKER_SYM_* ลง .env.
    ข้ามเงียบถ้า non-TTY (กัน hang) / MT5 ต่อไม่ได้ / key มีใน .env แล้ว. คืน list คีย์ที่เขียน."""
    if not sys.stdin.isatty():
        print(_WARN + "non-interactive — ข้ามถาม BTC/น้ำมัน (ตั้ง BROKER_SYM_WTIUSD/BTCUSD ใน .env เองได้)")
        return []
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            print(_WARN + f"MT5 ต่อไม่ได้ ({mt5.last_error()}) — login MT5 ก่อน แล้วรัน setup ใหม่เพื่อเลือก symbol")
            return []
    except Exception:
        print(_WARN + "MetaTrader5 import ไม่ได้ — ข้าม")
        return []
    names = [s.name for s in (mt5.symbols_get() or [])]
    have = _env_keys(env)
    probe_map = {}                                        # logical ที่ probe จับได้แล้ว (universe_probe.json) → ไม่ต้องถามซ้ำ
    try:
        import json as _json
        pj = _json.load(open(os.path.join(_BASE, "data", "universe_probe.json"), encoding="utf-8"))
        probe_map = pj.get("instruments", {})
    except Exception:
        pass
    _MONTHS = tuple(f"-{m}" for m in ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                      "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))
    # accept=token ที่รับ · prefer=token ที่ดันขึ้น #1 (ตัวจริง) · exclude=ตัด noise (หุ้นน้ำมัน/brent/futures/crypto อื่น)
    wanted = [
        ("BTCUSD", dict(accept=("BTC", "BITCOIN"), prefer=("USD",),
                        exclude=("ETH", "LTC", "XRP", "BCH", "ADA")), "Bitcoin (BTC)"),
        ("WTIUSD", dict(accept=("WTI", "USOIL", "XTI", "OIL", "CRUDE"),
                        prefer=("WTI", "USOIL", "XTI", "OILCASH", "CRUDE"),
                        exclude=("BRENT", "UKOIL") + _MONTHS), "น้ำมัน (WTI/USOIL)"),
    ]
    written = []
    for logical, spec, label in wanted:
        key = f"BROKER_SYM_{logical}"
        if key in have or (probe_map.get(logical) or {}).get("broker_symbol"):
            print(_OK + f"{logical} mapped แล้ว (.env/probe) — ข้าม")
            continue
        acc, pref, exc = spec["accept"], spec["prefer"], spec["exclude"]
        matched = {n for n in names if any(t in n.upper() for t in acc)
                   and not any(x in n.upper() for x in exc)}

        def _full(n):                                    # broker เปิดเทรด symbol นี้ไหม (FULL) — ดันตัว tradeable ขึ้นก่อน
            try:
                inf = mt5.symbol_info(n)
                return bool(inf and inf.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL)
            except Exception:
                return False
        # rank: tradeable(FULL) ก่อน → prefer token → สั้นสุด (กันเลือกตัว feed-only ที่โบรกปิดเทรด)
        cands = sorted(matched, key=lambda n: (not _full(n), not any(p in n.upper() for p in pref), len(n)))[:9]
        if not cands:
            print(_WARN + f"{label}: ไม่พบใน broker นี้ (อาจไม่มีคู่นี้) — ข้าม")
            continue
        print(f"\n  {label} — เลือก symbol ของ {logical}:")
        for i, c in enumerate(cands, 1):
            print(f"    {i}) {c}" + ("  [เทรดได้]" if _full(c) else "  [ปิดเทรด/feed-only]"))
        print("    0) ข้าม (ไม่เทรดคู่นี้)")
        try:
            ans = input("  พิมพ์เลข หรือชื่อ symbol เอง (Enter=ข้าม): ").strip()
        except EOFError:
            break
        if not ans or ans == "0":
            continue
        chosen = cands[int(ans) - 1] if (ans.isdigit() and 1 <= int(ans) <= len(cands)) else ans
        _write_env_key(env, key, chosen)
        written.append(f"{key}={chosen}")
        print(_OK + f"เขียน {key}={chosen} ลง .env")
    try:
        mt5.shutdown()
    except Exception:
        pass
    return written


def sync_env(env, example):
    """เพิ่มคีย์ใหม่จาก .env.example → .env (ไม่ทับค่าเดิม, append ท้ายเท่านั้น). idempotent.
    คืน (added_keys, secret_keys) — secret = คีย์ที่ค่า placeholder ยังต้องกรอกเอง."""
    have = _env_keys(env)
    missing = [(k, line) for k, line in _example_kv_lines(example) if k not in have]
    if not missing:
        return [], []
    from datetime import date
    with open(env, "a", encoding="utf-8") as f:
        f.write(f"\n# --- {date.today().isoformat()}: {len(missing)} คีย์เพิ่มโดย setup.py (sync จาก .env.example) ---\n")
        for _k, line in missing:
            f.write(line + "\n")
    added = [k for k, _ in missing]
    secret = [k for k, line in missing if line.split("=", 1)[1].strip().endswith("_here")]
    return added, secret


def main():
    os.chdir(_BASE)
    print("=" * 60)
    print("  XAUUSD AI Trading System — fresh-machine setup")
    print("=" * 60)
    problems = []

    # 1. Python version
    step(1, "Python version")
    v = sys.version_info
    if v < (3, 9):
        print(_ERR + f"Python {v.major}.{v.minor} — need >= 3.9"); problems.append("python-version")
    else:
        print(_OK + f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")

    # 2. dependencies
    step(2, "Install dependencies (requirements.txt)")
    req = os.path.join(_BASE, "requirements.txt")
    if not os.path.exists(req):
        print(_ERR + "requirements.txt missing"); problems.append("requirements-missing")
    else:
        rc = subprocess.call([sys.executable, "-m", "pip", "install", "-r", req])
        if rc == 0:
            print(_OK + "dependencies installed")
        else:
            print(_ERR + f"pip install failed (exit {rc})"); problems.append("pip-install")

    # 3. .env  (existing → sync คีย์ใหม่จาก .env.example โดยไม่ทับค่าเดิม / missing → copy)
    step(3, "Environment file (.env)")
    env, example = os.path.join(_BASE, ".env"), os.path.join(_BASE, ".env.example")
    if os.path.exists(env):
        if os.path.exists(example):
            added, secret = sync_env(env, example)
            if added:
                print(_WARN + f".env sync — เพิ่ม {len(added)} คีย์ใหม่: " + ", ".join(added))
                if secret:
                    print(f"         ⚠️ ต้องกรอกค่าเอง (secret): " + ", ".join(secret))
                    problems.append("env-new-secrets")
            else:
                print(_OK + ".env present + คีย์ครบตาม .env.example (ไม่มีคีย์ใหม่)")
            # config ทีมใช้ร่วม (.env.shared) → เขียนทับ .env เฉพาะค่าที่ต่าง (secret ไม่แตะ)
            shared = os.path.join(_BASE, ".env.shared")
            if os.path.exists(shared):
                changed = apply_shared(env, shared)
                if changed:
                    print(_WARN + f".env config sync จาก .env.shared — {len(changed)} คีย์เปลี่ยน (backup: .env.bak):")
                    for k, old, new in changed:
                        print(f"         {k}: {old} → {new}")
                else:
                    print(_OK + "config ตรงกับ .env.shared แล้ว (ไม่มีอะไรเปลี่ยน)")
        else:
            print(_OK + ".env already present (no .env.example to sync)")
    elif os.path.exists(example):
        shutil.copy(example, env)
        shared = os.path.join(_BASE, ".env.shared")
        if os.path.exists(shared):
            apply_shared(env, shared)                    # ใส่ config ทีมทันที (secret ยัง placeholder)
        print(_WARN + "created .env from .env.example — YOU MUST fill in secrets:")
        print("         MT5_LOGIN / MT5_PASSWORD / MT5_SERVER, ANTHROPIC_API_KEY,")
        print("         SUPABASE_URL / SUPABASE_KEY (or DATABASE_URL)")
        problems.append("env-needs-secrets")
    else:
        print(_ERR + "no .env and no .env.example"); problems.append("env-missing")

    # 4. runtime directories
    step(4, "Runtime directories")
    for d in ("logs", "logs/shadow", "data", "data/pairs", "docs/reports"):
        os.makedirs(os.path.join(_BASE, d), exist_ok=True)
    print(_OK + "logs/ · logs/shadow/ · data/ · data/pairs/ · docs/reports/ ready")

    # 5. MT5 connectivity (informational — needs the terminal running + logged in)
    step(5, "MetaTrader5 terminal (informational)")
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            acc = mt5.account_info()
            if acc:
                print(_OK + f"MT5 connected — login {acc.login} · {acc.server} · "
                      f"balance {acc.balance:,.2f} {acc.currency}")
            else:
                print(_WARN + "MT5 initialized but no account — log in to the terminal")
            mt5.shutdown()
        else:
            print(_WARN + f"MT5 not connected ({mt5.last_error()}) — open + log in to the MT5 terminal, "
                  "and set MT5_* in .env")
    except ImportError:
        print(_WARN + "MetaTrader5 not importable — is pip install done? (Windows-only package)")
    except Exception as e:
        print(_WARN + f"MT5 check skipped: {e}")

    # 6. broker symbol map — probe symbol ของ "โบรกเกอร์เครื่องนี้" (ชื่อต่างกัน: GOLD#/OILCash# vs XAUUSD/USOIL)
    step(6, "Broker symbol map (multi-symbol BTC/WTI/…)")
    probe_json = os.path.join(_BASE, "data", "universe_probe.json")
    if os.path.exists(probe_json):
        print(_OK + "universe_probe.json มีแล้ว (เปลี่ยนโบรกเกอร์ → ลบไฟล์นี้ + รัน setup ใหม่)")
    else:
        rc = subprocess.call([sys.executable, os.path.join("scripts", "probe_universe.py")])
        if rc == 0 and os.path.exists(probe_json):
            print(_OK + "ตรวจ symbol โบรกเกอร์นี้แล้ว → data/universe_probe.json")
        else:
            print(_WARN + "probe ไม่สำเร็จ (MT5 ยัง login ไหม?) — multi-symbol (BTC/WTI) ยังไม่ทำงาน "
                  "(ทองยังเทรดได้ผ่าน SYMBOL). รันภายหลัง: python scripts/probe_universe.py")
            problems.append("broker-symbol-probe")
    # BTC/น้ำมัน ชื่อต่างโบรกเกอร์เยอะ → ถามให้เลือกจาก symbol จริง แล้วเขียน BROKER_SYM_* ลง .env (interactive)
    if os.path.exists(env):
        ask_broker_symbols(env)

    # 7. broker-specific backtest — regen shadow_backtest.json ต่อ symbol ของโบรกนี้
    #    (committed = ของ owner; โบรกอื่น symbol/ประวัติต่าง → dashboard Shadow Matrix/algo-selector จะตรงเมื่อ regen)
    step(7, "Backtest per broker (Shadow Matrix / algo-selector)")
    if os.environ.get("SKIP_BACKTEST"):
        print(_WARN + "SKIP_BACKTEST set — ข้าม (รันเอง: python scripts/shadow_backtest_managed.py && "
              "python scripts/tsmom_backtest_pairs.py && python scripts/backtest_all.py)")
    else:
        connected = False
        try:
            import MetaTrader5 as mt5
            connected = bool(mt5.initialize())
            if connected:
                mt5.shutdown()
        except Exception:
            connected = False
        if connected:
            print("     regen backtest ต่อโบรกนี้ (~2-3 นาที · read-only 0 order)…")
            for scr in ("shadow_backtest_managed.py", "tsmom_backtest_pairs.py", "backtest_all.py",
                        "sr_gate_backtest.py", "cointegration_scan.py"):
                rc = subprocess.call([sys.executable, os.path.join("scripts", scr)])
                print((_OK if rc == 0 else _WARN) + f"{scr} " + ("เสร็จ" if rc == 0 else f"exit {rc}"))
            # cointegration_scan.py → data/cointegration.json (ADF/Hurst/half-life ทุกคู่) = Cointegration Monitor
            #   ต่อโบรกนี้; fresh clone ไม่มีไฟล์ → panel ขึ้น "กำลัง scan" จนกว่าจะ gen. NaN-sanitized (browser-safe)
            # backtest_all.py → data/backtest_results.json = matrix ทุก algo×คู่ (+EV/−EV) ที่ dashboard tab Analytics อ่าน
            # sr_gate_backtest.py → data/sr_gate_combos.json = combo ที่ S/R entry gate ผ่าน validation (regen ต่อโบรกนี้)
            # portfolio_replay.py → equity curve รวมทั้งระบบ (ระบบปัจจุบันทำเงินเท่าไรบน history) — โชว์อย่างเดียว
            print("     portfolio replay (system equity บน history)…")
            subprocess.call([sys.executable, os.path.join("scripts", "portfolio_replay.py")])
            # NOTE 2026-08-22: smc_backtest.py (regime_momentum_fvg + sweep_reversal candidates) ถูกถอด
            #   ออกจาก bootstrap — ทั้งสอง algo CUT ใน AUDIT #5 (registry 9→4). backtest_all.py ด้านบน
            #   ครอบ matrix ที่ยังใช้อยู่แล้ว.
        else:
            print(_WARN + "MT5 ยังไม่ต่อ — backtest คู่อื่น (Shadow Matrix) ใช้ของ owner ไปก่อน. ภายหลัง: "
                  "python scripts/shadow_backtest_managed.py && python scripts/tsmom_backtest_pairs.py && "
                  "python scripts/backtest_all.py")

    # summary + next steps
    print("\n" + "=" * 60)
    if problems:
        print("  Setup finished with items to address:")
        for p in problems:
            print(f"    - {p}")
        print("  Fix the above (esp. .env secrets + MT5 login), then re-run: python setup.py")
    else:
        print("  Setup complete.")
    print("\n  Start the bot + dashboard (separate terminals):")
    print(f"    {os.path.basename(sys.executable)} main.py")
    print(f"    {os.path.basename(sys.executable)} dashboard/app.py      # dashboard on http://localhost:5050")
    print("=" * 60)


if __name__ == "__main__":
    try:                                     # Thai-locale consoles are cp874 — force UTF-8 so output never crashes
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
