import os
from supabase import create_client, Client
from loguru import logger


def get_client() -> Client:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    return create_client(url, key)


def is_available() -> bool:
    try:
        get_client().table("trades").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def get_url() -> str:
    return os.getenv("SUPABASE_URL", "")
