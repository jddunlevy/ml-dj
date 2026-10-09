# Launch the prototype. Two different demos live in here.
#
#   .\demo.ps1              # synthetic fixture (the one the previews were made from)
#   .\demo.ps1 030749Z      # 8 events, 4 skips - the skips are loud, no candidate pool
#   .\demo.ps1 142116Z      # 17 events, 6 skips - flat reading, HAS a candidate pool
#   .\demo.ps1 150121Z      # 20 events, 4 skips - coherent reading, no candidate pool
#   .\demo.ps1 -Live        # follow a running capture - THIS is the stage demo
#
# A session with no candidate pool still runs; "what i'd play next" falls back to the
# synthetic pool, so do not read it as a real recommendation for that session.
#
# -Live is only the screen. It needs two processes already running, each in its own terminal:
#
#     .venv\Scripts\python.exe -m mldj capture --label demo
#     .venv\Scripts\python.exe -m mldj live
#
# and the queue write is a fourth command, run at the moment you want it:
#
#     .venv\Scripts\python.exe -m mldj next --dry-run   # prints the pick, queues nothing
#     .venv\Scripts\python.exe -m mldj next             # writes it to Spotify
#
# Start the capture FRESH before presenting. A session carrying earlier skips scores far
# lower than a clean one, and the engine will decline rather than queue on a dead vector.

param(
    [string]$Session = "",
    [switch]$Live,
    [int]$Port = 7788
)

$R = "C:\Program Files\R\R-4.5.3\bin\Rscript.exe"
if (-not (Test-Path $R)) { Write-Error "Rscript not found at $R"; exit 1 }

if ($Live -and $Session -ne "") {
    Write-Error "-Live follows the running capture; a named session is a replay of a finished one. Pick one."
    exit 1
}

# These are process-level environment variables and they SURVIVE between runs in the same
# shell. Every branch below therefore sets or clears all three - otherwise a -Live run leaves
# MLDJ_LIVE set, and the next replay run silently polls files nothing is writing any more.
if ($Live) {
    $liveSession = "data/live/session.json"
    if (-not (Test-Path $liveSession)) {
        Write-Error "no $liveSession - start 'mldj live' first, and 'mldj capture' before that"
        exit 1
    }
    $age = [int]((Get-Date) - (Get-Item $liveSession).LastWriteTime).TotalSeconds
    if ($age -gt 30) {
        Write-Host "warning: $liveSession last changed $age s ago - is 'mldj live' still running?" `
            -ForegroundColor Yellow
    }
    $env:MLDJ_SESSION    = $liveSession
    $env:MLDJ_CANDIDATES = "data/live/candidates.json"
    $env:MLDJ_LIVE       = "1"
    Write-Host "session: LIVE - following the running capture" -ForegroundColor Green
}
elseif ($Session -ne "") {
    $export = "data/exports/dj-20260930T$Session.json"
    $cands  = "data/candidates/dj-20260930T$Session.json"
    if (-not (Test-Path $export)) {
        Write-Error "no export at $export - available:"
        Get-ChildItem data/exports/*.json | ForEach-Object { "  " + $_.Name }
        exit 1
    }
    $env:MLDJ_SESSION = $export
    Remove-Item Env:\MLDJ_LIVE -ErrorAction SilentlyContinue
    if (Test-Path $cands) {
        $env:MLDJ_CANDIDATES = $cands
        Write-Host "session: $Session  (real candidate pool)" -ForegroundColor Green
    } else {
        Remove-Item Env:\MLDJ_CANDIDATES -ErrorAction SilentlyContinue
        Write-Host "session: $Session  (NO candidate pool - 'what i'd play next' is synthetic)" `
            -ForegroundColor Yellow
    }
}
else {
    Remove-Item Env:\MLDJ_SESSION    -ErrorAction SilentlyContinue
    Remove-Item Env:\MLDJ_CANDIDATES -ErrorAction SilentlyContinue
    Remove-Item Env:\MLDJ_LIVE       -ErrorAction SilentlyContinue
    Write-Host "session: synthetic fixture" -ForegroundColor Cyan
}

Write-Host "http://127.0.0.1:$Port   (ctrl-c to stop)"
& $R -e "shiny::runApp('.', port=$Port, launch.browser=TRUE, host='127.0.0.1')"
