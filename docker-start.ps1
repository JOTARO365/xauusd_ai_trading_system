# Refresh PATH so Node.js / PM2 are available after MSI install
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + $env:Path

Write-Host "=== XAUUSD AI Trading System ===" -ForegroundColor Cyan
Write-Host "Node  : $(node --version)"
Write-Host "PM2   : $(pm2 --version)"
Write-Host "Python: $(python --version)"
Write-Host "=================================" -ForegroundColor Cyan

# pm2-runtime keeps PM2 in foreground (no daemon) — correct for Docker
pm2-runtime start ecosystem.config.js
