# ============================================================
#  autostart_vm.ps1 — ตั้งให้ bot + dashboard รัน 24/7 อัตโนมัติ
#  รันครั้งเดียวบน VM (PowerShell as Administrator) หลัง setup_vm.ps1 + แก้ .env เสร็จ
#  จะสร้าง Scheduled Task 2 ตัวที่ start ตอนบูตเครื่อง (ทนต่อ VM reboot)
# ============================================================

$ErrorActionPreference = "Stop"
$APP = "C:\trading\xauusd_ai_trading_system"
$PY  = "C:\Program Files\Python311\python.exe"
if (!(Test-Path $PY)) { $PY = (Get-Command python).Source }

# log ออกไฟล์ ดูย้อนหลังได้
New-Item -ItemType Directory -Force -Path "$APP\logs" | Out-Null

function New-BotTask($name, $script, $log) {
    $action  = New-ScheduledTaskAction -Execute $PY -Argument $script -WorkingDirectory $APP
    # MT5 เป็น GUI — ต้องรันในเซสชันที่ login แล้ว (At log on) ไม่ใช่ At startup
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERNAME"
    # restart อัตโนมัติถ้า task ตาย
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
                  -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    # Interactive = มี desktop ให้ MT5 (สำคัญ!)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest -LogonType Interactive
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "  [OK] task '$name' -> $script" -ForegroundColor Green
}

Write-Host "Registering scheduled tasks ..." -ForegroundColor Cyan
New-BotTask "XAUUSD-Bot"       "main.py"          "bot"
New-BotTask "XAUUSD-Dashboard" "dashboard\app.py" "dashboard"

Write-Host "`nเริ่มทันที (ไม่ต้องรอ reboot):" -ForegroundColor Cyan
Start-ScheduledTask -TaskName "XAUUSD-Bot"
Start-ScheduledTask -TaskName "XAUUSD-Dashboard"

Write-Host "`n*** สำคัญ: เปิด AUTO-LOGON เพื่อให้ MT5 มี desktop ตอน VM reboot ***" -ForegroundColor Magenta
Write-Host "   รันคำสั่งนี้ (แทน <PWD> ด้วยรหัส Windows ของ user นี้):" -ForegroundColor Magenta
Write-Host '   $k="HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"' -ForegroundColor Gray
Write-Host '   Set-ItemProperty $k AutoAdminLogon 1; Set-ItemProperty $k DefaultUserName $env:USERNAME; Set-ItemProperty $k DefaultPassword "<PWD>"' -ForegroundColor Gray
Write-Host "   (ไม่งั้น task At-log-on จะไม่ start จนกว่าจะ RDP เข้าไป login เอง)" -ForegroundColor Magenta

Write-Host "`nคำสั่งจัดการ:" -ForegroundColor Yellow
Write-Host "  หยุด : Stop-ScheduledTask -TaskName XAUUSD-Bot"
Write-Host "  สถานะ: Get-ScheduledTask -TaskName XAUUSD-*"
Write-Host "  log  : Get-Content $APP\logs\system.log -Tail 50 -Wait"
