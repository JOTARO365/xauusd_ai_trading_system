# PM2 startup script — runs at system boot via Task Scheduler
Set-Location C:\xauusd_ai_trading_system

# Wait for network to be ready
Start-Sleep -Seconds 10

# Resurrect saved PM2 process list
$env:PATH = "C:\Program Files\nodejs;$env:USERPROFILE\AppData\Roaming\npm;$env:PATH"
& pm2 resurrect
& pm2 save
