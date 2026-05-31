# ============================================================
#  apply_vm_config.ps1 — แก้ .env บน VM (NNLB USD-canonical + CHART_SHADOW) + restart + verify
#  รัน (บน VM):  powershell -ExecutionPolicy Bypass -File scripts\apply_vm_config.ps1
#  ออปชั่น:  -PerLot 278  -Shadow true  -DryRun  -NoRestart
#
#  ปลอดภัย: backup .env ก่อนแก้, แก้เฉพาะค่าที่ระบุ, รักษา UTF-8 (คอมเมนต์ไทยไม่เพี้ยน),
#           .env เป็น gitignore → ไม่โดน auto-deploy เขียนทับ
# ============================================================
param(
    [string]$PerLot = "278",      # NNLB_EQUITY_PER_LOT (USD) — 278 ×36 ≈ 10,008฿
    [string]$Shadow = "true",     # CHART_SHADOW
    [switch]$DryRun,              # แสดงสิ่งที่จะแก้ แต่ไม่เขียนจริง
    [switch]$NoRestart           # แก้ .env อย่างเดียว ไม่ pm2 restart
)
$ErrorActionPreference = "Stop"

$APP     = Split-Path -Parent $PSScriptRoot          # scripts/ -> repo root
$envFile = Join-Path $APP ".env"

function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [BAD]  $m" -ForegroundColor Red }
function Info($m) { Write-Host "  $m"        -ForegroundColor Gray }

Write-Host "`n=== Apply VM Config ===" -ForegroundColor Cyan
Write-Host "env: $envFile"
Write-Host "target: NNLB_EQUITY_PER_LOT=$PerLot | CHART_SHADOW=$Shadow`n"

if (-not (Test-Path $envFile)) { Bad ".env ไม่พบที่ $envFile — รันผิดเครื่อง?"; exit 1 }

# ── 1. backup ─────────────────────────────────────────────────
$stamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "$envFile.bak.$stamp"
if (-not $DryRun) { Copy-Item $envFile $backup; Ok "backup -> $backup" }

# ── 2. แก้ทีละบรรทัด (รักษา comment เดิม) ─────────────────────
$lines = Get-Content $envFile -Encoding UTF8
$foundPerLot = $false; $foundShadow = $false; $changes = @()

$out = foreach ($line in $lines) {
    if ($line -match '^\s*NNLB_EQUITY_PER_LOT\s*=\s*([^#\s]+)(.*)$') {
        $foundPerLot = $true
        if ($Matches[1] -ne $PerLot) { $changes += "NNLB_EQUITY_PER_LOT: $($Matches[1]) -> $PerLot" }
        "NNLB_EQUITY_PER_LOT=$PerLot$($Matches[2])"
    }
    elseif ($line -match '^\s*CHART_SHADOW\s*=\s*([^#\s]+)(.*)$') {
        $foundShadow = $true
        if ($Matches[1] -ne $Shadow) { $changes += "CHART_SHADOW: $($Matches[1]) -> $Shadow" }
        "CHART_SHADOW=$Shadow$($Matches[2])"
    }
    else { $line }
}

if (-not $foundPerLot) { Bad "ไม่เจอบรรทัด NNLB_EQUITY_PER_LOT — เช็ก .env ว่ามี NNLB block มั้ย"; exit 1 }
if (-not $foundShadow) {
    $out += "CHART_SHADOW=$Shadow"
    $changes += "CHART_SHADOW: (ไม่มี) -> $Shadow (เพิ่มบรรทัดใหม่)"
}

if (-not $changes) { Ok "ค่าตรงตามเป้าอยู่แล้ว — ไม่มีอะไรต้องแก้" }
else { Write-Host "[changes]" -ForegroundColor Yellow; $changes | ForEach-Object { Info $_ } }

if ($DryRun) { Write-Host "`n[DryRun] ไม่เขียนไฟล์จริง" -ForegroundColor Yellow; exit 0 }

# ── 3. เขียนกลับแบบ UTF-8 ไม่มี BOM (กันคอมเมนต์ไทยเพี้ยน / กัน BOM ต้นไฟล์) ──
if ($changes) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($envFile, $out, $utf8NoBom)
    Ok ".env เขียนใหม่แล้ว (UTF-8 no BOM)"
}

# ── 4. restart pm2 ────────────────────────────────────────────
if ($NoRestart) { Info "ข้าม restart (-NoRestart)"; }
else {
    Write-Host "`n[restart] pm2 restart main" -ForegroundColor Cyan
    pm2 restart main | Out-Host
    pm2 save | Out-Null
    Ok "pm2 restart + save"
}

# ── 5. verify ─────────────────────────────────────────────────
Write-Host "`n=== Verify ===" -ForegroundColor Cyan
Info "ค่าใน .env ตอนนี้:"
Get-Content $envFile -Encoding UTF8 | Select-String "^NNLB_EQUITY_PER_LOT|^NNLB_BASE_EQUITY|^CHART_SHADOW" | ForEach-Object { Info "  $_" }

$log = Join-Path $APP "logs\system.log"
if ((-not $NoRestart) -and (Test-Path $log)) {
    Write-Host "`n  รอ cycle แรก (~20 วิ) แล้วดู [NNLB]/[SHADOW] ใน log..." -ForegroundColor Gray
    Start-Sleep -Seconds 20
    $tail = Get-Content $log -Tail 60 -ErrorAction SilentlyContinue
    $nnlb = $tail | Select-String "\[NNLB\]" | Select-Object -Last 1
    if ($nnlb) { Ok "NNLB: $($nnlb.Line.Trim())" } else { Info "ยังไม่เห็น [NNLB] — รอ order cycle (ปกติถ้าตลาดเงียบ)" }
    $shd  = $tail | Select-String "\[SHADOW\]" | Select-Object -Last 1
    if ($shd)  { Ok "SHADOW: $($shd.Line.Trim())" } else { Info "ยังไม่เห็น [SHADOW] — รอ full AI cycle" }
}

Write-Host "`n=== สรุป ===" -ForegroundColor Cyan
Ok "เสร็จ — เช็กว่า [NNLB] base ≈ 36 (ไม่ใช่ 360000) = ค่าถูกโหลด"
Info "ย้อนกลับได้: Copy-Item '$backup' '$envFile' -Force ; pm2 restart main"
Info "ปิด shadow เมื่อพอ: .\scripts\apply_vm_config.ps1 -Shadow false"
