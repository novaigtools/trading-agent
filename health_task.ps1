# Hourly dead-man's switch — called by Windows Task Scheduler.
# Deliberately does NO git pull/push: this task must keep working even when the
# repo, the network, or the bot itself is broken. That is the entire point of it.
# Usage: powershell -ExecutionPolicy Bypass -File health_task.ps1

$RepoDir = "C:\Users\amalr\trading-agent"
$Python  = "C:\Users\amalr\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$LogDir  = Join-Path $RepoDir "logs"
$LogFile = Join-Path $LogDir "health.log"

Set-Location $RepoDir
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 2MB)) {
    Move-Item -Force $LogFile "$LogFile.old"
}

function Log($msg) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content -Path $LogFile -Value "[$ts UTC] $msg" -Encoding utf8
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

& $Python health_check.py 2>&1 | ForEach-Object { Log $_ }
$exit = $LASTEXITCODE

if ($exit -ne 0) {
    Log "*** HEALTH CHECK FAILED (exit $exit) - see logs/ALERTS.log ***"
}
else {
    Log "Health check passed."
}
