<#
.SYNOPSIS
  Auto-resume a pending Claude Code coding task as soon as the usage limit comes back.

.DESCRIPTION
  Runs `claude -p --continue` in headless mode on a retry loop. While the usage
  limit is still active the API rejects the call quickly (almost no token cost),
  so the script simply waits and retries. The moment the limit resets the call
  succeeds, the task is continued, and the loop stops.

  No need to know the exact reset time.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\auto_resume_claude.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\auto_resume_claude.ps1 -RetryMinutes 10 -MaxHours 24
#>
param(
    # What Claude should do once the limit is back. Keep ASCII here; Claude will
    # read Thai files (continue.md) on its own.
    [string]$Prompt = "Resume the pending coding task. Read .claude/context/continue.md first, then continue where it left off.",

    # How often to retry while still rate-limited (minutes).
    [int]$RetryMinutes = 15,

    # Safety cap so the loop cannot run forever (hours).
    [int]$MaxHours = 12
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot          # project root (parent of scripts\)
Set-Location $repo
$log = Join-Path $repo ".claude\auto_resume.log"

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Host $line
}

Write-Log "=== auto_resume started (retry every $RetryMinutes min, max $MaxHours h) ==="

$deadline = (Get-Date).AddHours($MaxHours)
$attempt  = 0

while ((Get-Date) -lt $deadline) {
    $attempt++
    Write-Log "attempt #$attempt : running claude --continue ..."

    # Capture combined output. claude prints the limit message to stdout/stderr.
    $out = & claude -p $Prompt --continue --dangerously-skip-permissions 2>&1 | Out-String
    $code = $LASTEXITCODE

    # Detect a rate-limit / usage-limit rejection in the output.
    $limited = $out -match "(?i)(usage limit|rate limit|limit reached|resets at|too many requests|429|overloaded)"

    if (-not $limited -and $code -eq 0) {
        Write-Log "SUCCESS (exit 0). Output below:"
        Add-Content -Path $log -Value $out -Encoding utf8
        Write-Log "=== auto_resume done ==="
        exit 0
    }

    if ($limited) {
        Write-Log "still limited -> waiting $RetryMinutes min. (snippet: $(($out -split "`n")[0]))"
    } else {
        Write-Log "non-limit error (exit $code) -> waiting $RetryMinutes min. (snippet: $(($out -split "`n")[0]))"
    }

    Start-Sleep -Seconds ($RetryMinutes * 60)
}

Write-Log "=== auto_resume gave up after $MaxHours h ==="
exit 1
