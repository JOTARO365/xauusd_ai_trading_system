"""scripts/refresh_public_site.py — one-shot: regen public snapshot → commit → push (gh-pages redeploy).

รันชั่วโมงละครั้งผ่าน pm2 (app 'public-refresh', cron_restart). ต้องรันบน **เครื่องเทรด** (มี MT5)
— GitHub Action ทำไม่ได้ (ubuntu runner ไม่มี MT5). ปลอดภัยกับบอท: อ่าน MT5 read-only (copy_rates/
symbol_info) คนละ process กับ main.py.

history สะอาด: snapshot ต่อเนื่องใช้ commit --amend + push --force-with-lease (rolling 1 commit),
เว้นแต่ HEAD เป็น commit โค้ดจริง → เปิด snapshot commit ใหม่. push เฉพาะเมื่อ site/data/api/ เปลี่ยนจริง.
"""
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MARKER = "chore(public): hourly snapshot refresh"


def _git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=_ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} -> {r.returncode}: {r.stderr.strip()[:200]}")
    return r


def main():
    os.chdir(_ROOT)
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    # 1) regen snapshot (fail-soft ต่อ endpoint; MT5 ต่อ = data สด)
    print("[refresh] export snapshot…")
    import scripts.export_dashboard_static as ex  # noqa: E402
    ex.main()
    # 2) stage เฉพาะ data ของ public (ไม่แตะ code / working-dir อื่น)
    _git("add", "site/data/api/")
    if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("[refresh] ไม่มีการเปลี่ยนแปลง — ข้าม commit")
        return
    # 3) rolling commit: amend ถ้า HEAD เป็น snapshot เดิม, ไม่งั้นเปิดใหม่
    last = _git("log", "-1", "--format=%s", check=False).stdout.strip()
    if last.startswith(_MARKER):
        _git("commit", "--amend", "-m", _MARKER)
        push = _git("push", "--force-with-lease", "origin", "HEAD", check=False)
    else:
        _git("commit", "-m", _MARKER)
        push = _git("push", "origin", "HEAD", check=False)
    if push.returncode == 0:
        print("[refresh] pushed — gh-pages จะ redeploy เอง")
    else:
        print(f"[refresh] push fail (ลองใหม่ชั่วโมงหน้า): {push.stderr.strip()[:160]}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from dotenv import load_dotenv
    load_dotenv(override=True)
    main()
