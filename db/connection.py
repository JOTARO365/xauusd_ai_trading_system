import os

import psycopg2
from psycopg2.extras import RealDictCursor

_DEFAULT_URL = "postgresql://trading:trading@localhost:5433/trading"


def get_conn():
    """คืน connection ใหม่ — อ่าน DATABASE_URL ทุกครั้งที่เรียก เพื่อให้รับค่าจาก load_dotenv()"""
    url = os.getenv("DATABASE_URL", _DEFAULT_URL)
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def is_available() -> bool:
    """ตรวจว่า DB เชื่อมต่อได้มั้ย"""
    try:
        conn = get_conn()
        conn.close()
        return True
    except Exception:
        return False


def get_url() -> str:
    return os.getenv("DATABASE_URL", _DEFAULT_URL)
