"""setup.py — one-shot bootstrap for a fresh machine.

Run once after `git pull`:   python setup.py
Does everything a fresh checkout needs, then prints how to start the bot + dashboard.
Does NOT start the live bot (that is your controlled action — real money).

Steps: Python check → pip install -r requirements.txt → ensure .env (from .env.example) →
create runtime dirs → verify MT5 terminal connectivity (informational). Idempotent + safe to re-run.
"""
import os
import shutil
import subprocess
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
_OK, _WARN, _ERR = "  [OK] ", "  [!]  ", "  [X]  "


def step(n, title):
    print(f"\n── {n}. {title} " + "─" * max(0, 46 - len(title)))


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

    # 3. .env
    step(3, "Environment file (.env)")
    env, example = os.path.join(_BASE, ".env"), os.path.join(_BASE, ".env.example")
    if os.path.exists(env):
        print(_OK + ".env already present (not overwritten)")
    elif os.path.exists(example):
        shutil.copy(example, env)
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
    main()
