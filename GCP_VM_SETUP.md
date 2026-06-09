# GCP VM Setup — รันบอทบน Google Cloud (Windows Server)

คู่มือ deploy XAUUSD AI Trading System บน **Google Cloud Compute Engine** (Windows Server VM)
ทำครั้งเดียวจบ → บอทรัน 24/7 ผ่าน PM2 + auto-deploy (git push แล้ว VM อัปเดตเองใน ~60 วิ)

> **ทำไมต้อง Windows VM?** `MetaTrader5` Python library ทำงานบน Windows เท่านั้น (ไม่มี native REST API)
> → ต้องรัน MT5 terminal + บอทบนเครื่อง Windows เดียวกัน

---

## ภาพรวมสิ่งที่จะได้

```
Google Cloud Compute Engine  (Windows Server 2022, e2-medium, ~$25–35/เดือน)
  ├─ MetaTrader 5 (XM)        ← เทรดจริง
  ├─ Python 3.11 + bot        ← main pipeline
  ├─ PM2 (3 processes)        ← main / dashboard / auto-deploy
  └─ Tailscale (private net)  ← เข้า dashboard ปลอดภัย (ไม่เปิด port สาธารณะ)
```

---

## สิ่งที่ต้องเตรียมก่อน

| ต้องมี | ใช้ทำอะไร |
|---|---|
| Google Cloud account + billing | สร้าง VM (มี free trial $300/90 วัน) |
| GitHub Personal Access Token (PAT) | clone repo ที่เป็น private — สร้างที่ github.com/settings/tokens (scope: `repo`) |
| MT5 (XM) login / password / server | บัญชีเทรดจริง |
| `ANTHROPIC_API_KEY` | Claude API |
| `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` | เขียน DB (service_role — ดู [SUPABASE.md](SUPABASE.md)) |
| `.env` จากเครื่องเดิม (ถ้ามี) | copy มาวางทั้งไฟล์เร็วสุด |

---

## ⚡ วิธีที่เร็วที่สุด — สร้าง VM ด้วยคำสั่งเดียว (แนะนำ)

ไม่ต้องนั่งคลิกใน Console ทีละหน้าก็ได้ครับ มีสคริปต์ `scripts/create_vm.sh` ที่รวบทุกอย่างไว้แล้ว
รันจาก **GCP Cloud Shell** (กดปุ่ม `>_` มุมขวาบนของ console จะเปิด terminal ที่มี `gcloud` และ login ไว้ให้พร้อม ไม่ต้องลงอะไรเพิ่ม)

```bash
# 1) เลือก project ที่จะใช้ (ถ้ายังไม่มีก็สร้างใน Console ก่อน แล้วเปิด billing)
gcloud config set project xauusd-bot

# 2) ดึง repo มาไว้ใน Cloud Shell
git clone https://github.com/JOTARO365/xauusd_ai_trading_system.git
cd xauusd_ai_trading_system

# 3) สั่งสร้าง VM
#    ตัวแรก = GitHub PAT (เอาไว้ให้ VM ดึง repo ตอนบูต)
#    ตัวที่สอง = IP ของคุณ/32 เพื่อล็อก RDP ให้เข้าได้คนเดียว
#    (หา IP ที่ whatismyip.com นะ อย่าเอา IP ของ Cloud Shell มาใส่)
bash scripts/create_vm.sh ghp_xxxxxxxx 1.2.3.4/32
```

สคริปต์ตัวนี้จัดการให้หมดตั้งแต่เปิด Compute Engine API, สร้าง VM `mt5-vm` (e2-medium, Windows Server 2022, สิงคโปร์, ดิสก์ 50 GB),
ตั้งรหัส Windows ให้ (user `trader` — **จำรหัสที่ขึ้นบนจอไว้ด้วย**) ไปจนถึงเปิด firewall RDP เฉพาะ IP ที่เราใส่
(ถ้าเว้นว่างมันจะถามยืนยันก่อน ไม่เผลอเปิดให้คนทั้งโลกเข้า)

ที่เด็ดคือมันฝัง startup script (`setup_vm_startup.ps1`) ไว้ พอ VM บูตขึ้นมาครั้งแรกจะลง Python 3.11, Git, MT5 ของ XM,
clone repo แล้ว `pip install` กับสร้างไฟล์ `.env` ให้เองทั้งหมด (เขียนแบบกันลงซ้ำ รีบูตกี่รอบก็ไม่ลงใหม่)

> ⚠️ repo จะไปอยู่ที่ **`C:\trading\xauusd_ai_trading_system`** (ไม่ใช่ `C:\` เฉยๆ) — path นี้ตรงกับที่ auto-deploy กับ autostart ใช้

รอประมาณ 5 นาทีให้ startup script ลงของเสร็จ (อยากดูว่าถึงไหนแล้วก็ RDP เข้าไปเปิด `C:\trading\setup.log` ดูได้)
จากนั้นเหลือทำเองแค่ 3 อย่าง — เปิด **MetaTrader 5** แล้ว login (ดูขั้นตอนที่ 8), เติมค่าจริงลงใน `.env` ที่
`C:\trading\xauusd_ai_trading_system\.env` (ขั้นตอนที่ 7) แล้วเปิด auto-start 24/7 ด้วยการรันคำสั่งนี้ใน PowerShell แบบ **Admin**:

```powershell
C:\trading\xauusd_ai_trading_system\scripts\autostart_vm.ps1
```

> ถึงสคริปต์จะล็อก RDP ให้แล้ว ก็อย่าลืมเช็กเรื่องความปลอดภัยซ้ำที่ขั้นตอนที่ 4 อยู่ดี — RDP ต้องเป็น IP คุณ/32
> และ dashboard (5050) ห้ามเปิดออก public เด็ดขาด ให้เข้าผ่าน Tailscale เท่านั้น (มีย้ำใน Security Checklist ท้ายหน้า)

อยากเข้าใจทีละขั้น หรือ startup script พลาดตรงไหน ก็ไล่ทำตาม **manual 10 ขั้นตอน** ด้านล่างได้เลย

---

## ขั้นตอนที่ 1 — สร้าง Project + เปิด Billing  *(manual — ข้ามได้ถ้าใช้วิธีเร็วด้านบน)*

1. เข้า [console.cloud.google.com](https://console.cloud.google.com)
2. บนแถบบน → **Select a project** → **New Project** → ตั้งชื่อ (เช่น `xauusd-bot`) → **Create**
3. เมนู ☰ → **Billing** → ผูกบัตร/เปิด free trial ($300 credit)

---

## ขั้นตอนที่ 2 — สร้าง VM (Compute Engine)

1. เมนู ☰ → **Compute Engine** → **VM instances** → (รอ enable API ครั้งแรก ~1 นาที) → **Create Instance**
2. ตั้งค่า:

   | Field | ค่าที่แนะนำ | เหตุผล |
   |---|---|---|
   | **Name** | `xauusd-vm` | |
   | **Region** | `asia-southeast1` (Singapore) | ใกล้ broker + Supabase (Singapore) → latency ต่ำ |
   | **Machine type** | `e2-medium` (2 vCPU, 4 GB) | พอสำหรับ MT5 + bot; เริ่มเล็กได้ |
   | **Boot disk** | **Windows Server 2022 Datacenter**, 50 GB SSD | MT5 ต้อง Windows |
   | **Firewall** | ❌ **อย่า**ติ๊ก "Allow HTTP/HTTPS traffic" | กัน dashboard หลุดสู่ public (ดูขั้นตอน 4) |

3. กด **Create** → รอ VM boot ~1–2 นาที

> 💡 **ประหยัด:** ตั้ง **VM scheduling** ให้ปิดตอนตลาดปิด (เสาร์-อาทิตย์) ได้ แต่ระวัง MT5 ต้อง re-login เมื่อเปิดใหม่

---

## ขั้นตอนที่ 3 — ตั้ง password + RDP เข้า VM

1. ที่ row ของ VM → ลูกศรข้าง **RDP** → **Set Windows password** → ตั้ง username/password → **Set** → จดไว้
2. กด **RDP** → ดาวน์โหลดไฟล์ `.rdp` → เปิดด้วย Remote Desktop (Windows) หรือ **Microsoft Remote Desktop** (Mac)
3. ใส่ password → เข้า desktop ของ VM ได้

---

## ขั้นตอนที่ 4 — Firewall & Security (สำคัญมาก ⚠️)

ค่า default ของ GCP เปิด RDP (3389) ให้ `0.0.0.0/0` (ทุกคนทั่วโลก) — **ต้องล็อกให้แคบ**

1. เมนู ☰ → **VPC network** → **Firewall**
2. หา rule `default-allow-rdp` → **Edit** → **Source IPv4 ranges** เปลี่ยนเป็น **IP ของคุณ/32** เท่านั้น
   (หา IP: ค้น Google ว่า "what is my ip" → ใส่ `<your_ip>/32`)
3. **dashboard (port 5050) — ห้ามเปิดสู่ public เด็ดขาด** (ไม่มี auth, ปิด/แก้ trade ได้)
   → ใช้ **Tailscale** แทน: ลง Tailscale ทั้งบน VM และเครื่องคุณ → เข้า `http://<tailscale-ip>:5050` ผ่าน private network

| Port | ต้องเปิดให้ใคร |
|---|---|
| 3389 (RDP) | **IP คุณเท่านั้น** (`/32`) — ห้าม `0.0.0.0/0` |
| 5050 (dashboard) | **ไม่เปิด firewall เลย** → เข้าผ่าน Tailscale |

---

## ขั้นตอนที่ 5 — รัน setup script (Python + Git + MT5 + clone + deps)

ใน VM:

1. แก้ `scripts/setup_vm.ps1` แค่บรรทัดเดียว — ใส่ GitHub token (ค่า `$DEST` ตั้งเป็น `C:\trading` ไว้ให้แล้ว ไม่ต้องแตะ):
   ```powershell
   $GH_TOKEN = "ghp_xxxxxxxx"   # GitHub PAT
   $DEST     = "C:\trading"     # clone ลง C:\trading\xauusd_ai_trading_system (path เดียวกับ auto-deploy/autostart)
   ```
2. เปิด **PowerShell แบบ Run as Administrator**
3. โหลด script (ถ้ายังไม่มี repo) — clone ด้วยมือก่อน หรือวางเนื้อหา `setup_vm.ps1` ทั้งไฟล์:
   ```powershell
   git clone https://ghp_xxxx@github.com/JOTARO365/xauusd_ai_trading_system.git C:\trading\xauusd_ai_trading_system
   cd C:\trading\xauusd_ai_trading_system
   powershell -ExecutionPolicy Bypass -File scripts\setup_vm.ps1
   ```

script จะลง: **Python 3.11**, **Git**, **MT5 (XM)**, `pip install -r requirements.txt`, สร้าง `.env` จาก template

> ⚠️ ถ้า MT5 โหลดอัตโนมัติไม่ได้ → ลงเองจาก [xm.com/mt5](https://www.xm.com/mt5)

---

## ขั้นตอนที่ 6 — ลง Node.js + PM2 (process manager)

`setup_vm.ps1` **ไม่ได้**ลง PM2 — ต้องลงเองเพราะระบบรันผ่าน PM2 (`ecosystem.config.js`)

ใน PowerShell (Admin):
```powershell
# 1) Node.js LTS (มี npm)
winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
# (ปิด-เปิด PowerShell ใหม่ให้ PATH อัปเดต)

# 2) PM2
npm install -g pm2

# 3) ให้ PM2 รันตอน VM boot (Windows) — ใช้ pm2-installer
#    https://github.com/jessety/pm2-installer  (วิธี Windows ที่เสถียรสุด)
#    หรือสร้าง Scheduled Task รัน "pm2 resurrect" ตอน startup
```

---

## ขั้นตอนที่ 7 — ตั้งค่า `.env`

```powershell
notepad C:\trading\xauusd_ai_trading_system\.env
```

วางค่าจริง (เร็วสุด = copy `.env` เครื่องเดิมมาทั้งไฟล์) — จุดที่ต้องมี:
```env
ANTHROPIC_API_KEY=sk-ant-...
MT5_LOGIN=xxxxxxx
MT5_PASSWORD=xxxxxxx
MT5_SERVER=XMGlobal-MT5 13

# DB — owner mode ใช้ service_role (bypass RLS) ดู SUPABASE.md
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...

DRY_RUN=false
```

> 🔒 `.env` อยู่ใน `.gitignore` — ไม่ถูก commit, ไม่ sync ผ่าน auto-deploy
> การแก้ config ทีหลังใช้ `scripts/apply_vm_config.ps1` หรือแก้มือ + `pm2 restart main`

---

## ขั้นตอนที่ 8 — เปิด MT5 ครั้งแรก (สำคัญ)

MT5 Python library เชื่อมได้เฉพาะ terminal ที่ **เคยเปิดและ login แล้ว**

1. เปิด **MetaTrader 5** บน VM → login ด้วย MT5_LOGIN/PASSWORD/SERVER เดียวกับ `.env`
2. ดูว่ามุมขวาล่างขึ้นสถานะเชื่อมต่อ (มีตัวเลข ping) → ปล่อย terminal เปิดทิ้งไว้
3. **Tools → Options → Expert Advisors** → ติ๊ก "Allow algorithmic trading"

---

## ขั้นตอนที่ 9 — สตาร์ทด้วย PM2

```powershell
cd C:\trading\xauusd_ai_trading_system
pm2 start ecosystem.config.js   # รัน main + dashboard + auto-deploy
pm2 save                        # บันทึก process list ไว้ resurrect ตอน boot
pm2 ls                          # ดูสถานะ — ต้องเห็น 3 ตัว online
```

3 processes ที่รัน:
| ชื่อ | ไฟล์ | หน้าที่ |
|---|---|---|
| `main` | pm2_main.js | บอทเทรด (pipeline หลัก) |
| `dashboard` | pm2_dashboard.js | web dashboard :5050 |
| `auto-deploy` | pm2_autodeploy.js | เช็ก git ทุก 60 วิ → pull + restart อัตโนมัติ |

---

## ขั้นตอนที่ 10 — ตรวจว่ารันจริง

```powershell
pm2 logs main --lines 50                                  # ดู log สด
powershell -ExecutionPolicy Bypass -File scripts\health_check.ps1   # เช็ก 5 อย่าง
```

`health_check.ps1` เช็ก: process, liveness (`bot_status.json` สด), MT5 connect, dashboard, token cost วันนี้
→ ขึ้น `[OK] ระบบรันปกติ` = สำเร็จ

---

## Ops Cheatsheet (ใช้บ่อย)

```powershell
pm2 ls                         # สถานะทุก process
pm2 logs main                  # log บอท (Ctrl+C ออก)
pm2 restart main               # restart บอท (เช่น หลังแก้ .env)
pm2 restart all                # restart ทุกตัว
pm2 stop main                  # หยุดบอท (dashboard ยังรัน)
pm2 monit                      # หน้า monitor realtime

# แก้ config บน VM อย่างปลอดภัย (backup .env + restart + verify):
powershell -File scripts\apply_vm_config.ps1 -PerLot "278" -Shadow "true"
```

**Auto-deploy ทำงานยังไง:** push ขึ้น `main` → ภายใน 60 วิ VM `git fetch` เจอ commit ใหม่ → `git stash` (กัน local change) → `git pull` → `pm2 restart main dashboard` → log ที่ `logs\auto_deploy.log`
→ **แก้ code แค่ push ก็พอ** ไม่ต้อง RDP เข้าไป (ยกเว้นแก้ `.env` ที่ไม่ sync)

---

## Security Checklist (ก่อนปล่อยรันจริง)

- [ ] RDP (3389) จำกัด source เป็น **IP คุณ/32** — ไม่ใช่ `0.0.0.0/0`
- [ ] Dashboard (5050) **ไม่เปิด firewall** → เข้าผ่าน **Tailscale** เท่านั้น
- [ ] `.env` ใช้ `SUPABASE_SERVICE_KEY` (ไม่ใช่ anon key เปล่า — จะโดน RLS deny)
- [ ] `.env` ไม่เคยถูก commit (เช็ก `git status` ต้องไม่เห็น `.env`)
- [ ] Windows password แข็งแรง + เปิด auto-update
- [ ] GitHub PAT ที่ใช้ clone → จำกัด scope แค่ `repo` และ revoke ได้ถ้าหลุด

---

## Troubleshooting

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `pm2` ไม่รู้จัก | Node ลงแล้วแต่ PATH ยังไม่อัปเดต → ปิด-เปิด PowerShell ใหม่ |
| บอทขึ้น MT5 connect fail | MT5 terminal ไม่ได้เปิด/ไม่ได้ login → กลับไปขั้นตอน 8 |
| `bot_status.json` ไม่อัปเดต > 20 นาที | ตลาดปิด (ปกติ) หรือบอทค้าง → `pm2 logs main` ดู error |
| auto-deploy ไม่ pull | `auto_deploy.ps1` derive repo จากตำแหน่งตัวเอง (`$PSScriptRoot\..`) — ทำงานได้ทุก path; ถ้าไม่ pull เช็ก `git fetch` เข้าเน็ตได้ไหม + ดู `logs\auto_deploy.log` |
| เขียน DB ไม่ได้หลังเปิด RLS | `.env` ยังใช้ anon key → เปลี่ยนเป็น `SUPABASE_SERVICE_KEY` (ดู [SUPABASE.md](SUPABASE.md)) |
| Thai/อักขระใน log เพี้ยน | PowerShell 5.1 อ่าน UTF-8 no-BOM เป็น ANSI → ไฟล์ `.ps1` ต้องเป็น UTF-8 BOM |

---

## ค่าใช้จ่ายโดยประมาณ

| รายการ | USD/เดือน |
|---|---|
| e2-medium (24/7) | ~$25–35 |
| Boot disk 50 GB SSD | ~$8 |
| Network egress (เล็กน้อย) | ~$1–3 |
| **รวม** | **~$35–45/เดือน** (มี free trial $300 ครอบ ~6 เดือนแรก) |

> ลดได้: ปิด VM ตอนตลาดปิด (เสาร์-อาทิตย์) ด้วย instance schedule → ประหยัด ~28%
