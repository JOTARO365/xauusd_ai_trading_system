"""
manage_api_keys.py — Owner tool สำหรับสร้าง/ลบ API keys ให้ user

รัน: python scripts/manage_api_keys.py

ต้องการ .env ที่มี SUPABASE_URL และ SUPABASE_KEY (หรือ SUPABASE_SERVICE_KEY)
"""
import sys, os, secrets
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    print(f"\n{'Label':<20} {'account_login':<15} {'active':<8} {'key[:12]...'}")
    print("-" * 70)
    for r in rows:
        status = "✓" if r["active"] else "✗"
        print(f"{(r.get('label') or '-'):<20} {r['account_login']:<15} {status:<8} {r['key'][:12]}...")


def create_key(account_login: int, label: str) -> str:
    key = secrets.token_urlsafe(32)
    _db().table("api_keys").insert({
        "key":           key,
        "account_login": account_login,
        "label":         label,
        "active":        True,
    }).execute()
    return key


def revoke_key(key_prefix: str):
    rows = _db().table("api_keys").select("key,label").execute().data
    matches = [r for r in rows if r["key"].startswith(key_prefix)]
    if not matches:
        print(f"ไม่พบ key ที่ขึ้นต้นด้วย '{key_prefix}'")
        return
    for r in matches:
        _db().table("api_keys").update({"active": False}).eq("key", r["key"]).execute()
        print(f"Revoked: {r.get('label')} ({r['key'][:16]}...)")


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
        prefix = input("พิมพ์ 8+ ตัวแรกของ key ที่จะ revoke: ").strip()
        revoke_key(prefix)

    elif choice == "q":
        return
    else:
        print("ไม่รู้จัก option")


if __name__ == "__main__":
    main()
