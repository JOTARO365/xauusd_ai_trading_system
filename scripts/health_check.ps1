# ============================================================
#  health_check.ps1 — เช็กว่า bot "รันจริง" มั้ย (ไม่ใช่แค่ process เปิด)
#  รัน:  powershell -ExecutionPolicy Bypass -File scripts\health_check.ps1
#  เช็ก 5 อย่าง: process/task, liveness, MT5+activity, dashboard, token cost
#  exit code 0 = ปกติ, 1 = เจอปัญหา (ใช้กับ monitoring/cron ได้)
# ============================================================

$ErrorActionPreference = "Continue"
$APP  = Split-Path -Parent $PSScriptRoot        # scripts/ -> repo root
$LOGS = Join-Path $APP "logs"
$issues = 0

function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [BAD]  $m" -ForegroundColor Red }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Info($m) { Write-Host "  $m"        -ForegroundColor Gray }

Write-Host "`n=== XAUUSD Bot Health Check ===" -ForegroundColor Cyan
Write-Host "app: $APP`n"

# ── 1. Process / PID lock ─────────────────────────────────────
Write-Host "[1] Process" -ForegroundColor Cyan
$pidFile = Join-Path $LOGS "bot.pid"
if (Test-Path $pidFile) {
    $botPid = (Get-Content $pidFile -Raw).Trim()
    $proc = Get-Process -Id ([int]$botPid) -ErrorAction SilentlyContinue
    if ($proc) { Ok "bot process running (PID $botPid)" }
    else { Bad "PID file=$botPid แต่หา process ไม่เจอ (bot ตายแต่ lock ค้าง)"; $issues++ }
} else {
    Bad "ไม่มี logs/bot.pid — bot ยังไม่เคยรัน หรือถูกหยุด"; $issues++
}

$tasks = Get-ScheduledTask -TaskName "XAUUSD-*" -ErrorAction SilentlyContinue
if ($tasks) {
    foreach ($t in $tasks) {
        if ($t.State -eq "Running") { Ok "task $($t.TaskName) = Running" }
        else { Warn "task $($t.TaskName) = $($t.State)" }
    }
}

# ── 2. Liveness — bot_status.json อัปเดตสดมั้ย ────────────────
Write-Host "`n[2] Liveness (bot_status.json)" -ForegroundColor Cyan
$statusFile = Join-Path $LOGS "bot_status.json"
if (Test-Path $statusFile) {
    try {
        $st  = Get-Content $statusFile -Raw | ConvertFrom-Json
        $upd = [datetime]$st.updated_at
        $age = [int]((Get-Date) - $upd).TotalMinutes
        if ($age -le 20)      { Ok   "updated $age min ago — cycle #$($st.cycle), decision=$($st.decision)" }
        elseif ($age -le 60)  { Warn "updated $age min ago — อาจช้า/ตลาดเงียบ" }
        else                  { Bad  "updated $age min ago — bot ค้าง/ไม่ทำงาน (ควร < 20 min)"; $issues++ }
    } catch { Bad "อ่าน bot_status.json ไม่ได้: $_"; $issues++ }
} else {
    Warn "ยังไม่มี bot_status.json — รอ AI cycle แรก (หรือตลาดปิด)"
}

# ── 3. MT5 connection + activity (system.log) ─────────────────
Write-Host "`n[3] MT5 + activity (system.log)" -ForegroundColor Cyan
$logFile = Join-Path $LOGS "system.log"
if (Test-Path $logFile) {
    $tail = Get-Content $logFile -Tail 80 -ErrorAction SilentlyContinue
    $lastConn = $tail | Select-String "เชื่อมต่อ MT5 สำเร็จ|MT5 หลุด" | Select-Object -Last 1
    if ($lastConn -and $lastConn -match "หลุด") { Warn "log ล่าสุดแจ้ง MT5 หลุด — กำลัง reconnect?" }
    elseif ($lastConn)                          { Ok "MT5 connected (จาก log)" }
    $lastCycle = $tail | Select-String "CYCLE_TIME|Next interval" | Select-Object -Last 1
    if ($lastCycle) { Info "last activity: $($lastCycle.Line.Trim())" }
    else            { Warn "ไม่เห็น cycle activity ใน 80 บรรทัดล่าสุด" }
    $sleep = $tail | Select-String "ตลาดปิด|รอ .* นาที" | Select-Object -Last 1
    if ($sleep) { Info "หมายเหตุ: ตลาดอาจปิดอยู่ (bot sleep ปกติ)" }
} else {
    Bad "ไม่มี system.log"; $issues++
}

# ── 4. Dashboard (port 5050) ──────────────────────────────────
Write-Host "`n[4] Dashboard (port 5050)" -ForegroundColor Cyan
try {
    $resp = Invoke-WebRequest "http://localhost:5050" -UseBasicParsing -TimeoutSec 8
    if ($resp.StatusCode -eq 200) { Ok "dashboard ตอบ 200" }
    else { Warn "dashboard ตอบ status $($resp.StatusCode)" }
} catch { Bad "dashboard ไม่ตอบ (port 5050) — ไม่ได้รัน?"; $issues++ }

# ── 5. Token cost วันนี้ vs budget ────────────────────────────
Write-Host "`n[5] Token cost วันนี้" -ForegroundColor Cyan
$acctFile = Join-Path $LOGS "accounting.json"
if (Test-Path $acctFile) {
    try {
        $ac    = Get-Content $acctFile -Raw | ConvertFrom-Json
        $today = (Get-Date).ToString("yyyy-MM-dd")
        $day   = $ac.daily.$today
        if ($day) {
            $usd  = [math]::Round($day.total_cost_usd, 3)
            $thb  = [math]::Round($usd * 36, 0)
            $line = "วันนี้: `$$usd (~$thb THB) | $($day.cycles) cycles | $($day.trades) trades"
            if ($thb -le 300) { Ok "$line — อยู่ใน budget 300฿" }
            else { Warn "$line — เกิน budget 300฿" }
        } else { Info "ยังไม่มีข้อมูล cost วันนี้" }
    } catch { Warn "อ่าน accounting.json ไม่ได้" }
} else {
    Info "ยังไม่มี accounting.json"
}

# ── สรุป ──────────────────────────────────────────────────────
Write-Host "`n=== สรุป ===" -ForegroundColor Cyan
if ($issues -eq 0) {
    Write-Host "  [OK] ระบบรันปกติ" -ForegroundColor Green
    exit 0
} else {
    Write-Host "  [!!] เจอ $issues ปัญหา — ดูบรรทัด [BAD] ด้านบน" -ForegroundColor Red
    exit 1
}
