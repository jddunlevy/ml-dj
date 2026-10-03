# Launch the prototype on a chosen session. Demo path only - no network, no live mode.
#
#   .\demo.ps1              # synthetic fixture (the one the previews were made from)
#   .\demo.ps1 030749Z      # 8 events, 4 skips - the skips are loud, no candidate pool
#   .\demo.ps1 142116Z      # 17 events, 6 skips - flat reading, HAS a candidate pool
#   .\demo.ps1 150121Z      # 20 events, 4 skips - coherent reading, no candidate pool
#
# A session with no candidate pool still runs; "what i'd play next" falls back to the
# synthetic pool, so do not read it as a real recommendation for that session.

param(
    [string]$Session = "",
    [int]$Port = 7788
)

$R = "C:\Program Files\R\R-4.5.3\bin\Rscript.exe"
if (-not (Test-Path $R)) { Write-Error "Rscript not found at $R"; exit 1 }

if ($Session -ne "") {
    $export = "data/exports/dj-20260930T$Session.json"
    $cands  = "data/candidates/dj-20260930T$Session.json"
    if (-not (Test-Path $export)) {
        Write-Error "no export at $export - available:"
        Get-ChildItem data/exports/*.json | ForEach-Object { "  " + $_.Name }
        exit 1
    }
    $env:MLDJ_SESSION = $export
    if (Test-Path $cands) {
        $env:MLDJ_CANDIDATES = $cands
        Write-Host "session: $Session  (real candidate pool)" -ForegroundColor Green
    } else {
        Remove-Item Env:\MLDJ_CANDIDATES -ErrorAction SilentlyContinue
        Write-Host "session: $Session  (NO candidate pool - 'what i'd play next' is synthetic)" `
            -ForegroundColor Yellow
    }
} else {
    Remove-Item Env:\MLDJ_SESSION    -ErrorAction SilentlyContinue
    Remove-Item Env:\MLDJ_CANDIDATES -ErrorAction SilentlyContinue
    Write-Host "session: synthetic fixture" -ForegroundColor Cyan
}

Write-Host "http://127.0.0.1:$Port   (ctrl-c to stop)"
& $R -e "shiny::runApp('.', port=$Port, launch.browser=TRUE, host='127.0.0.1')"
