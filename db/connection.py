import os

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://trading:trading@localhost:5432/trading",
)


def get_conn():
    """คืน connection ใหม่ — caller ต้อง close() เอง"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def is_available() -> bool:
    """ตรวจว่า DB เชื่อมต่อได้มั้ย"""
    try:
        conn = get_conn()
        conn.close()
        return True
    except Exception:
        return False
