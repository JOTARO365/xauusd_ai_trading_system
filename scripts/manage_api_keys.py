"""
manage_api_keys.py — Owner tool สำหรับสร้าง/ลบ API keys ให้ user

รัน: python scripts/manage_api_keys.py

ต้องการ .env ที่มี SUPABASE_URL และ SUPABASE_KEY (หรือ SUPABASE_SERVICE_KEY)
"""
import sys, os, secrets, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _hash(raw: str) -> str:
    """sha256 hex — DB เก็บแค่ hash ของ key (กัน DB หลุดแล้ว key ใช้ได้)."""
    return hashlib.sha256(raw.encode()).hexdigest()

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

def _db():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY ไม่มีใน .env")
        sys.exit(1)
    return create_client(url, key)


def list_keys():
    rows = _db().table("api_keys").select("*").order("created_at").execute().data
    if not rows:
        print("ยังไม่มี API key ใดๆ")
        return
    print(f"\n{'Label':<20} {'account_login':<15} {'active':<8} {'hash[:12]...'}")
    print("-" * 70)
    for r in rows:
        status = "✓" if r["active"] else "✗"
        print(f"{(r.get('label') or '-'):<20} {r['account_login']:<15} {status:<8} {r['key'][:12]}...")


def create_key(account_login: int, label: str) -> str:
    raw = secrets.token_urlsafe(32)
    _db().table("api_keys").insert({
        "key":           _hash(raw),     # เก็บแค่ hash — raw แสดงให้ owner ครั้งเดียว
        "account_login": account_login,
        "label":         label,
        "active":        True,
    }).execute()
    return raw


def revoke_key(label: str):
    # owner ไม่มี raw key แล้ว (เก็บแค่ hash) → revoke ด้วย label
    rows = _db().table("api_keys").select("key,label,account_login").execute().data
    matches = [r for r in rows if (r.get("label") or "") == label]
    if not matches:
        print(f"ไม่พบ key ที่ label = '{label}'")
        return
    for r in matches:
        _db().table("api_keys").update({"active": False}).eq("key", r["key"]).execute()
        print(f"Revoked: {r.get('label')} (login {r.get('account_login')})")


def main():
    print("\n=== API Key Manager ===")
    print("1) ดู keys ทั้งหมด")
    print("2) สร้าง key ใหม่")
    print("3) Revoke key")
    print("q) ออก")

    choice = input("\nเลือก: ").strip().lower()

    if choice == "1":
        list_keys()

    elif choice == "2":
        login = input("MT5 account_login ของ user: ").strip()
        if not login.isdigit():
            print("ต้องเป็นตัวเลข")
            return
        label = input("ชื่อ user (label): ").strip()
        key = create_key(int(login), label)
        print(f"\n✅ สร้างสำเร็จ!")
        print(f"   ส่งให้ user ใส่ใน .env :")
        print(f"   TRADING_API_KEY={key}")

    elif choice == "3":
        label = input("พิมพ์ label ของ key ที่จะ revoke: ").strip()
        revoke_key(label)

    elif choice == "q":
        return
    else:
        print("ไม่รู้จัก option")


if __name__ == "__main__":
    main()
