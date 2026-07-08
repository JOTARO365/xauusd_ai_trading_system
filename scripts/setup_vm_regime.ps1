# setup_vm_regime.ps1  (run ONCE on the VM)
#
# 1) writes ALPHAVANTAGE_API_KEY into .env (so update_regime.py can fetch data)
# 2) installs the MCP servers the VM is missing (alphavantage + youtube), user scope
# 3) registers a DAILY Task Scheduler job that refreshes macro_regime.md
#
# The API key is passed in (-ApiKey) and never stored in git. ASCII-only file.
#
# Example:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_vm_regime.ps1 -ApiKey YOURKEY
#   powershell -ExecutionPolicy Bypass -File scripts\setup_vm_regime.ps1 -ApiKey YOURKEY -Time 06:30

param(
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [string]$Time = "07:00",
    [string]$TaskName = "XAUUSD-UpdateRegime"
)
$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot
Set-Location $proj

# 1) ensure ALPHAVANTAGE_API_KEY in .env --------------------------------------
$envFile = Join-Path $proj ".env"
if (Test-Path $envFile) {
    if (Select-String -Path $envFile -Pattern "ALPHAVANTAGE_API_KEY" -Quiet) {
        Write-Host "[env] .env already has ALPHAVANTAGE_API_KEY (left as-is)"
    } else {
        Add-Content -Path $envFile -Value "`r`nALPHAVANTAGE_API_KEY=$ApiKey" -Encoding utf8
        Write-Host "[env] added ALPHAVANTAGE_API_KEY to .env"
    }
} else {
    Write-Warning "[env] .env not found - copy .env.example to .env first, then re-run"
}

# 2) install MCP servers (idempotent) -----------------------------------------
function Ensure-Mcp([string]$name, [string[]]$addArgs) {
    $list = (& claude mcp list 2>&1) -join "`n"
    if ($list -match "(?m)^\s*$([regex]::Escape($name))\s*:") {
        Write-Host "[mcp] '$name' already installed"
        return
    }
    & claude mcp add @addArgs
    if ($?) { Write-Host "[mcp] installed '$name'" } else { Write-Warning "[mcp] failed to install '$name'" }
}
Ensure-Mcp "alphavantage" @("--transport","http","--scope","user","alphavantage","https://mcp.alphavantage.co/mcp?apikey=$ApiKey")
Ensure-Mcp "youtube"      @("--scope","user","youtube","--","npx","-y","@sinco-lab/mcp-youtube-transcript")

# 3) register DAILY Task Scheduler job ----------------------------------------
# cycle #12: weekly -> daily so MACRO_AUTO (DATA + auto CATALYSTS + sentiment) stays
# fresh. Uses ~3-6 of the 25/day AV quota; fail-soft when quota spent (lines omitted).
$runner  = Join-Path $proj "scripts\run_update_regime.ps1"
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "Refresh macro_regime.md from Alpha Vantage (XAUUSD bot)" | Out-Null
Write-Host "[task] '$TaskName' registered: every Monday at $Time"
Write-Host "Done. Test now with:  powershell -ExecutionPolicy Bypass -File scripts\run_update_regime.ps1"
