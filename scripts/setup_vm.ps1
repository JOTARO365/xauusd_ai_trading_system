# ============================================================
#  setup_vm.ps1 — ติดตั้ง XAUUSD AI Trading System บน Windows VM
#  ใช้กับ: Windows Server 2022 (GCP e2-medium 4GB) เครื่องเปล่า
#  วิธีรัน:
#    1) RDP เข้า VM
#    2) เปิด PowerShell แบบ Run as Administrator
#    3) วางทั้งสคริปต์นี้ แล้ว Enter
#  ทำให้: Python 3.11 + Git + MT5(XM) + clone bot + pip install + .env
# ============================================================

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── CONFIG: แก้ 1 บรรทัดนี้ก่อนรัน ───────────────────────────
$GH_TOKEN = "PASTE_GITHUB_TOKEN_HERE"   # GitHub PAT (repo เป็น private) — สร้างที่ github.com/settings/tokens
$REPO_URL = "https://github.com/JOTARO365/xauusd_ai_trading_system.git"
$DEST     = "C:\trading"
# ─────────────────────────────────────────────────────────────

function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }

New-Item -ItemType Directory -Force -Path $DEST | Out-Null

# 1) Python 3.11 ---------------------------------------------------
Step "1/6" "Installing Python 3.11 ..."
$py = "$env:TEMP\python311.exe"
Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $py
Start-Process -Wait -FilePath $py -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0"

# 2) Git ----------------------------------------------------------
Step "2/6" "Installing Git ..."
$git = "$env:TEMP\git.exe"
Invoke-WebRequest "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe" -OutFile $git
Start-Process -Wait -FilePath $git -ArgumentList "/VERYSILENT /NORESTART"

# refresh PATH ในเซสชันนี้ (Python + Git เพิ่งลง)
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path","User") + ";C:\Program Files\Git\cmd"

# 3) MetaTrader 5 (XM Global) -------------------------------------
Step "3/6" "Installing MetaTrader 5 (XM) ..."
$mt5 = "$env:TEMP\xm_mt5setup.exe"
try {
    Invoke-WebRequest "https://download.xmglobal.com/cdn/mt5/xmglobal5setup.exe" -OutFile $mt5
} catch {
    Write-Host "  ! โหลด XM MT5 อัตโนมัติไม่ได้ — ลงเองจาก https://www.xm.com/mt5 ทีหลังได้" -ForegroundColor Yellow
    $mt5 = $null
}
if ($mt5) { Start-Process -Wait -FilePath $mt5 -ArgumentList "/auto" }

# 4) Clone repo ---------------------------------------------------
Step "4/6" "Cloning bot repo ..."
$authUrl = $REPO_URL -replace "https://", "https://$GH_TOKEN@"
git clone $authUrl "$DEST\xauusd_ai_trading_system"
Set-Location "$DEST\xauusd_ai_trading_system"

# 5) Python dependencies -----------------------------------------
Step "5/6" "Installing Python dependencies ..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 6) .env ---------------------------------------------------------
Step "6/6" "Preparing .env ..."
if (!(Test-Path ".env")) { Copy-Item ".env.example" ".env" }

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " เสร็จ! ขั้นต่อไป:" -ForegroundColor Green
Write-Host "   1) แก้ .env ใส่ค่าจริง (MT5_LOGIN/PASSWORD/SERVER, ANTHROPIC_API_KEY," -ForegroundColor Green
Write-Host "      SUPABASE_URL/KEY ฯลฯ) — เร็วสุดคือ copy เนื้อหา .env เครื่องเดิมมาวางทั้งหมด" -ForegroundColor Green
Write-Host "   2) เปิด MT5 (XM) ครั้งแรก แล้ว login บัญชีให้ติด (terminal ต้องเคยรัน)" -ForegroundColor Green
Write-Host "   3) รันบอท:  python main.py" -ForegroundColor Green
Write-Host "      รัน dashboard:  python dashboard\app.py   (เปิด http://<VM-IP>:5050)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
notepad ".env"
