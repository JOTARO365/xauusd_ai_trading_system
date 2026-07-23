"""scripts/sync_env_example.py — regenerate .env.example from the real .env, redacting secrets.

Makes .env.example mirror the live operating config (REGIME_LIVE, TSMOM_LIVE, lot/threshold flags,
SHADOW_*, etc) EXACTLY — so a fresh clone runs the same algo mode — while replacing every credential
value with a placeholder (never commit real secrets). Comments/blank lines are preserved verbatim.

Run: python scripts/sync_env_example.py   → overwrites .env.example (commit it; .env stays gitignored)
"""
import os
import re

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV = os.path.join(_BASE, ".env")
_EXAMPLE = os.path.join(_BASE, ".env.example")

# keys whose VALUE is a secret / machine-identifying → redact to a placeholder
_SECRET_EXACT = {"MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "DATABASE_URL", "SUPABASE_URL",
                 "SUPABASE_KEY", "X_USERNAME", "X_PASSWORD", "X_EMAIL"}
_SECRET_SUBSTR = ("KEY", "PASSWORD", "SECRET", "TOKEN", "APIKEY", "CREDENTIAL")


def _is_secret(key):
    k = key.upper()
    if "KEYWORD" in k:                                     # X_KEYWORDS etc = not secret
        return False
    if k in _SECRET_EXACT:
        return True
    return any(s in k for s in _SECRET_SUBSTR)


def _redact_line(raw):
    """Return (line, kind): kind in {'secret','mirror','keep'}. Redacts secret assignments even inside
    comments (a real key must never survive in a comment)."""
    body = raw.lstrip()
    commented = body.startswith("#")
    probe = body.lstrip("#").strip() if commented else raw
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", probe)
    if not m:
        return raw, "keep"                                # pure comment / blank / non-assignment
    key, val = m.group(1), m.group(2)
    if _is_secret(key) and val.strip() and not val.strip().endswith("_here"):
        repl = f"{key}=your_{key.lower()}_here"
        return (("# " + repl) if commented else repl), "secret"
    return raw, ("keep" if commented else "mirror")


def main():
    if not os.path.exists(_ENV):
        print("no .env — nothing to sync"); return
    out, redacted, mirrored = [], 0, 0
    with open(_ENV, encoding="utf-8") as f:
        for line in f:
            newline, kind = _redact_line(line.rstrip("\n"))
            out.append(newline)
            if kind == "secret":
                redacted += 1
            elif kind == "mirror":
                mirrored += 1
    header = ["# ============================================================",
              "# .env.example — mirror ของ .env จริง (operating config เปิด algo ครบ), secret ถูก redact",
              "#   cp .env.example .env  แล้วกรอก secret จริง (คีย์ที่ลงท้าย _here)",
              "#   regen: python scripts/sync_env_example.py",
              "# ============================================================", ""]
    with open(_EXAMPLE, "w", encoding="utf-8") as f:
        f.write("\n".join(header + out) + "\n")
    print(f".env.example synced: {mirrored} operating values mirrored, {redacted} secrets redacted")


if __name__ == "__main__":
    main()
