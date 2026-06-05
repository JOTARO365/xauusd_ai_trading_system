# run_update_regime.ps1
# Invoked by Task Scheduler (weekly). Runs the macro-regime updater and logs the
# result to logs/regime_update.log. No secrets here - the API key lives in .env.
# ASCII-only on purpose (PowerShell 5.1 mis-parses non-ASCII .ps1 without a BOM).

$proj = Split-Path -Parent $PSScriptRoot     # repo root (scripts/..)
Set-Location $proj
$env:PYTHONUTF8 = "1"

$logDir = Join-Path $proj "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "regime_update.log"
$ts  = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Run python with native-stderr capture; don't let EAP=Stop throw on native stderr.
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$out  = (& python scripts/update_regime.py 2>&1 | Out-String)
$code = $LASTEXITCODE
$ErrorActionPreference = $prev

$status = if ($code -eq 0) { "OK" } else { "FAIL (exit=$code)" }
Add-Content -Path $log -Value "[$ts] $status`r`n$out" -Encoding utf8
if ($code -ne 0) { exit 1 }
