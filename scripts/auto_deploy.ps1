# Derive repo root from this script's own location (<repo>\scripts\auto_deploy.ps1)
# so it works at any install path — C:\trading\xauusd_ai_trading_system (create_vm.sh)
# or the legacy C:\xauusd_ai_trading_system — without a hardcoded constant.
$REPO = Split-Path $PSScriptRoot -Parent
$LOG  = "$REPO\logs\auto_deploy.log"

function Write-Log {
    param($msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts  $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line
}

Write-Log "=== auto_deploy started ==="

while ($true) {
    try {
        Set-Location $REPO
        git fetch origin main 2>&1 | Out-Null
        $local  = (git rev-parse HEAD).Trim()
        $remote = (git rev-parse origin/main).Trim()

        if ($local -ne $remote) {
            Write-Log "New commit $($remote.Substring(0,7)) -- pulling..."

            # Stash VM-local modifications (e.g. ecosystem.config.js auto-deploy block)
            # so git pull doesn't fail on uncommitted changes
            $stashOut = git stash 2>&1 | Out-String
            $didStash = $stashOut -notmatch "No local changes to save"
            if ($didStash) { Write-Log "  stash: $($stashOut.Trim())" }

            git pull origin main 2>&1 | ForEach-Object { Write-Log "  git: $_" }

            if ($didStash) {
                $popOut = git stash pop 2>&1 | Out-String
                Write-Log "  stash pop: $($popOut.Trim())"
            }

            Write-Log "Restarting PM2..."
            pm2 restart main dashboard 2>&1 | ForEach-Object { Write-Log "  pm2: $_" }
            pm2 save 2>&1 | Out-Null
            Write-Log "Deploy complete."
        }
    } catch {
        Write-Log "ERROR: $_"
    }

    Start-Sleep -Seconds 60
}
