# ============================================================
#  add_keywords_vm.ps1 — เติม X keyword เข้า .env บน VM (idempotent) + restart + verify
#  รัน (บน VM):  powershell -ExecutionPolicy Bypass -File scripts\add_keywords_vm.ps1
#  ออปชั่น:  -Keywords "Pezeshkian,Geneva"  -DryRun  -NoRestart
#
#  ทำไมต้องมี: ค่า X_KEYWORDS ใน .env "override code defaults ทั้งก้อน" (ไม่ merge)
#  → เปลี่ยน config.py/.env.example อย่างเดียวไม่พอ ต้องเติมที่ .env บน VM ด้วยแล้ว pm2 restart
#  (X_KEYWORDS ไม่ live-reload). .env เป็น gitignore → auto-deploy ไม่เขียนทับ
#
#  ปลอดภัย: backup ก่อนแก้, dedupe case-insensitive (รันซ้ำได้), รักษา comment ท้ายบรรทัด,
#           เขียน UTF-8 no BOM (คอมเมนต์ไทยไม่เพี้ยน)
# ============================================================
param(
    [string]$Keywords = "Pezeshkian,Geneva",  # คั่นด้วย comma — keyword ที่จะเติม
    [switch]$DryRun,                           # แสดงสิ่งที่จะแก้ แต่ไม่เขียนจริง
    [switch]$NoRestart                         # แก้ .env อย่างเดียว ไม่ pm2 restart
)
$ErrorActionPreference = "Stop"

$APP     = Split-Path -Parent $PSScriptRoot          # scripts/ -> repo root
$envFile = Join-Path $APP ".env"

function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [BAD]  $m" -ForegroundColor Red }
function Info($m) { Write-Host "  $m"        -ForegroundColor Gray }

Write-Host "`n=== Add X Keywords to VM .env ===" -ForegroundColor Cyan
Write-Host "env: $envFile"
Write-Host "to add: $Keywords`n"

if (-not (Test-Path $envFile)) { Bad ".env ไม่พบที่ $envFile — รันผิดเครื่อง?"; exit 1 }

$toAdd = $Keywords -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if (-not $toAdd) { Bad "ไม่มี keyword ให้เติม (-Keywords ว่าง)"; exit 1 }

# ── 1. backup ─────────────────────────────────────────────────
$stamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = "$envFile.bak.$stamp"
if (-not $DryRun) { Copy-Item $envFile $backup; Ok "backup -> $backup" }

# ── 2. แก้บรรทัด X_KEYWORDS (เติมเฉพาะที่ยังไม่มี, dedupe case-insensitive) ──
$lines = Get-Content $envFile -Encoding UTF8
$found = $false; $added = @(); $skipped = @()

$out = foreach ($line in $lines) {
    if ($line -match '^\s*X_KEYWORDS\s*=\s*([^#]*)(#.*)?$') {
        $found   = $true
        $valRaw  = $Matches[1]
        $comment = $Matches[2]   # อาจ $null
        $existing = $valRaw -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        $existingLower = $existing | ForEach-Object { $_.ToLower() }
        $merged = [System.Collections.Generic.List[string]]::new()
        $existing | ForEach-Object { $merged.Add($_) }
        foreach ($k in $toAdd) {
            if ($existingLower -contains $k.ToLower()) { $skipped += $k }
            else { $merged.Add($k); $added += $k }
        }
        $newVal = ($merged -join ',')
        if ($comment) { "X_KEYWORDS=$newVal  $comment" } else { "X_KEYWORDS=$newVal" }
    }
    else { $line }
}

if (-not $found) { Bad "ไม่เจอบรรทัด X_KEYWORDS ใน .env"; exit 1 }

if ($skipped) { Info "มีอยู่แล้ว (ข้าม): $($skipped -join ', ')" }
if (-not $added) { Ok "ทุก keyword มีอยู่แล้ว — ไม่มีอะไรต้องแก้"; if (-not $NoRestart) { Info "ข้าม restart (ไม่มีการเปลี่ยนแปลง)" }; exit 0 }
Write-Host "[added]" -ForegroundColor Yellow; Info ($added -join ', ')

if ($DryRun) { Write-Host "`n[DryRun] ไม่เขียนไฟล์จริง" -ForegroundColor Yellow; exit 0 }

# ── 3. เขียนกลับ UTF-8 no BOM ─────────────────────────────────
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($envFile, $out, $utf8NoBom)
Ok ".env เขียนใหม่แล้ว (UTF-8 no BOM)"

# ── 4. restart pm2 (X_KEYWORDS ไม่ live-reload — ต้อง restart) ──
if ($NoRestart) { Info "ข้าม restart (-NoRestart) — keyword ใหม่ยังไม่ทำงานจนกว่าจะ pm2 restart main" }
else {
    Write-Host "`n[restart] pm2 restart main" -ForegroundColor Cyan
    pm2 restart main | Out-Host
    pm2 save | Out-Null
    Ok "pm2 restart + save"
}

# ── 5. verify ─────────────────────────────────────────────────
Write-Host "`n=== Verify ===" -ForegroundColor Cyan
Get-Content $envFile -Encoding UTF8 | Select-String "^X_KEYWORDS" | ForEach-Object { Info "  $_" }

Write-Host "`n=== สรุป ===" -ForegroundColor Cyan
Ok "เติมแล้ว: $($added -join ', ')"
Info "ย้อนกลับได้: Copy-Item '$backup' '$envFile' -Force ; pm2 restart main"
