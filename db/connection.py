import os
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


def is_available() -> bool:
    try:
        get_client().table("trades").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def get_url() -> str:
    return os.getenv("SUPABASE_URL", "")
