import json as _json
import os
import urllib.parse as _uparse
import urllib.request as _ureq

from supabase import create_client, Client
from loguru import logger


def _service_key() -> str:
    """service_role ก่อน, fallback SUPABASE_KEY (เพื่อ backward-compat ตอน rollout)."""
    return os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY", "")


def get_client() -> Client:
    """Owner/server client — ใช้ service_role ถ้ามี (bypass RLS) ไม่งั้น fallback anon.
    ใช้โดย owner bot + owner dashboard บนเครื่องที่เชื่อถือได้เท่านั้น."""
    url = os.getenv("SUPABASE_URL", "")
    return create_client(url, _service_key())


def get_user_client(access_token: str) -> Client:
    """Per-user client สำหรับชั้น web (Phase 2) — anon key + JWT ของ user.
    RLS จะเห็น auth.uid() จาก JWT → query ได้เฉพาะ account ที่ผูกใน user_accounts."""
    url  = os.getenv("SUPABASE_URL", "")
    anon = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY", "")
    client = create_client(url, anon)
    client.postgrest.auth(access_token)   # ส่ง Bearer JWT ไปกับทุก query
    return client


# ── Proxy mode (user machine — ไม่มี Supabase key, คุยผ่าน API proxy) ─────────────
def proxy_mode() -> bool:
    return bool(os.getenv("TRADING_API_URL") and os.getenv("TRADING_API_KEY"))


def _proxy_base() -> str:
    return os.getenv("TRADING_API_URL", "").rstrip("/")


def proxy_get(endpoint: str, params: dict | None = None, timeout: int = 20) -> dict:
    """GET ไปยัง API proxy พร้อม X-Api-Key. raise ถ้าพลาด (caller จับเอง)."""
    url = f"{_proxy_base()}/{endpoint}"
    if params:
        url += "?" + _uparse.urlencode(params)
    req = _ureq.Request(url, headers={"X-Api-Key": os.getenv("TRADING_API_KEY", "")}, method="GET")
    with _ureq.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read().decode())


def proxy_post(endpoint: str, data: dict, timeout: int = 20) -> dict:
    """POST JSON ไปยัง API proxy พร้อม X-Api-Key. raise ถ้าพลาด."""
    body = _json.dumps(data).encode()
    req  = _ureq.Request(
        f"{_proxy_base()}/{endpoint}", data=body,
        headers={"Content-Type": "application/json", "X-Api-Key": os.getenv("TRADING_API_KEY", "")},
        method="POST",
    )
    with _ureq.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read().decode())


def is_available() -> bool:
    """proxy mode → เช็ค /health; owner mode → ยิง query เบาๆ."""
    if proxy_mode():
        try:
            return bool(proxy_get("health", timeout=8).get("status") == "ok")
        except Exception:
            return False
    try:
        get_client().table("trades").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def get_url() -> str:
    return os.getenv("SUPABASE_URL", "")
