# ============================================================
#  setup_vm_startup.ps1 — GCP Windows "startup script" (รันเองตอนบูต)
#  ใส่เป็น metadata: windows-startup-script-ps1
#  ทำงานเป็น SYSTEM แบบ non-interactive → ติดตั้งทุกอย่างให้อัตโนมัติ
#    Python 3.11 + Git + MT5(XM) + clone repo + pip install + seed .env
#  GitHub token อ่านจาก metadata key 'gh-token' (ส่งตอน gcloud create)
#  log: C:\trading\setup.log   (ดู progress ได้)
#  *** เหลือทำเองหลัง RDP: login MT5, เติม .env, รัน python main.py ***
# ============================================================

$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path "C:\trading" | Out-Null
Start-Transcript -Path "C:\trading\setup.log" -Append
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$REPO_URL = "https://github.com/JOTARO365/xauusd_ai_trading_system.git"
$DEST     = "C:\trading"

# อ่าน GitHub token จาก instance metadata
function Get-Meta($key) {
    try {
        return (Invoke-RestMethod -Headers @{'Metadata-Flavor'='Google'} `
          -Uri "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$key")
    } catch { return $null }
}
$GH_TOKEN = Get-Meta "gh-token"

function Step($m) { Write-Host "`n=== $m ($(Get-Date -Format HH:mm:ss)) ===" }

# NB: GCP รัน startup script นี้ "ทุกครั้งที่ VM boot" → ทุก step มี guard
#     เช็คว่าลงแล้วหรือยัง เพื่อไม่ re-download/re-install ซ้ำทุก reboot
$PY      = "C:\Program Files\Python311\python.exe"
$GIT     = "C:\Program Files\Git\cmd\git.exe"
$REPO    = "$DEST\xauusd_ai_trading_system"

# 1) Python 3.11
Step "Python 3.11"
if (Test-Path $PY) {
    Write-Host "  already installed — skip"
} else {
    $py = "$env:TEMP\python311.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $py
    Start-Process -Wait -FilePath $py -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0"
}

# 2) Git
Step "Git"
if (Test-Path $GIT) {
    Write-Host "  already installed — skip"
} else {
    $git = "$env:TEMP\git.exe"
    Invoke-WebRequest "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe" -OutFile $git
    Start-Process -Wait -FilePath $git -ArgumentList "/VERYSILENT /NORESTART"
}

$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path","User") + ";C:\Program Files\Git\cmd"

# 3) MetaTrader 5 (XM) — path ของ XM ไม่แน่นอน → guard ด้วย marker file
Step "MetaTrader 5 (XM)"
$mt5Marker = "$DEST\.mt5_installed"
if (Test-Path $mt5Marker) {
    Write-Host "  marker found — skip"
} else {
    $mt5 = "$env:TEMP\xm_mt5setup.exe"
    try {
        Invoke-WebRequest "https://download.xmglobal.com/cdn/mt5/xmglobal5setup.exe" -OutFile $mt5
        Start-Process -Wait -FilePath $mt5 -ArgumentList "/auto"
        Set-Content -Path $mt5Marker -Value (Get-Date -Format o) -Encoding utf8
    } catch { Write-Host "! XM MT5 auto-download failed — ลงเองหลัง RDP จาก xm.com/mt5" }
}

# 4) Clone repo
Step "Clone repo"
if (Test-Path $REPO) {
    Write-Host "  repo exists — skip clone"
} elseif ($GH_TOKEN) {
    $auth = $REPO_URL -replace "https://", "https://$GH_TOKEN@"
    git clone $auth $REPO
} else {
    Write-Host "! ไม่มี gh-token ใน metadata — clone ไม่ได้ ต้อง clone เองหลัง RDP"
}

# 5) pip install — guard ด้วย marker (ไม่ re-pip ทุก boot)
#    ถ้าอัปเดต requirements ทีหลัง: ลบ C:\trading\.deps_installed แล้ว reboot หรือ pip เอง
Step "pip install"
$depMarker = "$DEST\.deps_installed"
if (Test-Path $depMarker) {
    Write-Host "  deps already installed — skip (ลบ .deps_installed ถ้าต้องการ re-install)"
} elseif (Test-Path "$REPO\requirements.txt") {
    Set-Location $REPO
    & $PY -m pip install --upgrade pip
    & $PY -m pip install -r requirements.txt
    if (!(Test-Path ".env")) { Copy-Item ".env.example" ".env" }
    Set-Content -Path $depMarker -Value (Get-Date -Format o) -Encoding utf8
}

Step "DONE — เหลือ RDP เข้าไป: login MT5, เติม .env, รัน python main.py"
Stop-Transcript
