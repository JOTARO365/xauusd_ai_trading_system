"""setup.py — one-shot bootstrap for a fresh machine.

Run once after `git pull`:   python setup.py
Does everything a fresh checkout needs, then prints how to start the bot + dashboard.
Does NOT start the live bot (that is your controlled action — real money).

Steps: Python check → pip install -r requirements.txt → sync .env → create runtime dirs → verify MT5.
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
