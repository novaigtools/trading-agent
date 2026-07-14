# Trading bot task runner - called by Windows Task Scheduler.
# Usage: powershell -ExecutionPolicy Bypass -File bot_task.ps1 -Mode scan|monitor
# Syncs state with GitHub before and after each run so the Pages dashboard
# and the cloud SL/TP backstop always see current state.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("scan", "monitor")]
    [string]$Mode
)

$RepoDir = "C:\Users\amalr\trading-agent"
$Python  = "C:\Users\amalr\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$LogDir  = Join-Path $RepoDir "logs"
$LogFile = Join-Path $LogDir "$Mode.log"

Set-Location $RepoDir
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

# Rotate log if over 2 MB
if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 2MB)) {
    Move-Item -Force $LogFile "$LogFile.old"
}

function Log($msg) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss")
    # -Encoding utf8: without it PS5.1 writes cp1252 and the bot's em-dashes and
    # box-drawing characters land in the log as mojibake ("G??").
    Add-Content -Path $LogFile -Value "[$ts UTC] $msg" -Encoding utf8
}

Log "=== $Mode run started ==="

# Pull latest state (cloud backstop may have committed while laptop was off).
# Commit any stray local state first so rebase never fails on a dirty tree.
git add risk_state.json trades.csv 2>$null
git diff --staged --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "Local state snapshot before $Mode run" --quiet
    Log "Committed stray local state changes."
}
git pull --rebase --autostash --quiet 2>&1 | ForEach-Object { Log "pull: $_" }

# Run the bot (UTF-8 so emoji/unicode output can't crash on cp1252 console)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$script = if ($Mode -eq "scan") { "run_once.py" } else { "sl_monitor.py" }
& $Python $script 2>&1 | ForEach-Object { Log $_ }
$exit = $LASTEXITCODE
if ($exit -ne 0) {
    # run_once.py exits 1 when every decision call failed — the bot is NOT trading.
    # This line is what health_check.py and a human skimming the log will latch onto.
    Log "*** FAILURE: $script exited with code $exit - THE BOT MAY NOT BE TRADING ***"
    Log "*** Check the DEAD/DEGRADED banner above. If an LLM outage is to blame, set BRAIN_MODE=rules in .env ***"
}
else {
    Log "$script exited with code $exit"
}

# Push state changes so dashboard + cloud backstop stay in sync
git add risk_state.json trades.csv 2>$null
git diff --staged --quiet
if ($LASTEXITCODE -ne 0) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm 'UTC'")
    git commit -m "Bot state update ($Mode) $stamp" --quiet
    $pushed = $false
    foreach ($i in 1..3) {
        git push --quiet 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
        Log "Push failed, rebase + retry ($i/3)..."
        git pull --rebase --autostash --quiet 2>&1 | Out-Null
    }
    if ($pushed) { Log "State pushed to GitHub." } else { Log "WARNING: push failed after 3 retries - will sync next run." }
}
else {
    Log "No state changes to push."
}

Log "=== $Mode run finished ==="
