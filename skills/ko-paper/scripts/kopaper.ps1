# Run kopaper from this checkout on Windows (PowerShell 5.1+), setting it up on first use.
#   kopaper.ps1 doctor            check prerequisites, install what can be installed
#   kopaper.ps1 update            pull the latest ko-paper and refresh installed skills
#   kopaper.ps1 translate a.pdf   any other arguments go to the kopaper CLI
#   kopaper.ps1                   no arguments: open the web UI in the browser
# ASCII only: Windows PowerShell 5.1 misreads UTF-8 files without a BOM.
$ErrorActionPreference = 'Stop'

# Find the checkout: $env:KOPAPER_HOME, else the path install.ps1 wrote, else the repo this script sits in.
$Marker = Join-Path $PSScriptRoot '..\.kopaper-home'
if ($env:KOPAPER_HOME) { $Root = $env:KOPAPER_HOME }
elseif (Test-Path $Marker) { $Root = [IO.File]::ReadAllText((Resolve-Path $Marker).Path).Trim() }  # UTF-8 (Korean user names)
else { $Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path }

$env:PATH = (Join-Path $HOME '.local\bin') + ';' + $env:PATH  # uv tool installs babeldoc here
if (-not $env:KOPAPER_DATA) { $env:KOPAPER_DATA = Join-Path $HOME '.ko-paper\data' }
$env:PYTHONUTF8 = '1'  # Korean text in logs and glossaries, whatever the console code page

function Need($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Fail($msg) { [Console]::Error.WriteLine("[x] $msg"); exit 1 }

# Backend: Claude Code if it is installed, otherwise Codex. KOPAPER_BACKEND overrides.
if (-not $env:KOPAPER_BACKEND) {
    if (Need 'claude') { $env:KOPAPER_BACKEND = 'claude-code' }
    elseif (Need 'codex') { $env:KOPAPER_BACKEND = 'codex' }
}

function Setup {
    if (-not (Need 'uv')) { Fail 'uv is missing. Run: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"' }
    switch ($env:KOPAPER_BACKEND) {
        'claude-code' { if (-not (Need 'claude')) { Fail 'KOPAPER_BACKEND=claude-code but the claude CLI is missing' } }
        'codex' { if (-not (Need 'codex')) { Fail 'KOPAPER_BACKEND=codex but the codex CLI is missing' } }
        'anthropic-api' { }
        { -not $_ } { Fail 'neither Claude Code (claude) nor Codex (codex) is installed; install and log in to one' }
        default { Fail "unknown KOPAPER_BACKEND=$($env:KOPAPER_BACKEND) (claude-code, codex, anthropic-api)" }
    }
    if (-not (Need 'babeldoc') -and -not $env:KOPAPER_BABELDOC_BIN) {
        [Console]::Error.WriteLine('-> installing BabelDOC (uv tool install babeldoc)')
        uv tool install babeldoc
        if ($LASTEXITCODE -ne 0) { Fail 'uv tool install babeldoc failed' }
    }
    # Always sync: after an update the editable install has new code but maybe not its new dependencies.
    Push-Location $Root
    try { uv sync --quiet --inexact } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Fail "uv sync failed in $Root" }
}

function LoggedIn {
    $ErrorActionPreference = 'Continue'  # PS 5.1 turns redirected native stderr into errors under 'Stop'
    switch ($env:KOPAPER_BACKEND) {
        # An API key in the environment also works, so don't send the user to a browser login for nothing.
        'claude-code' { if ($env:ANTHROPIC_API_KEY) { return $true }; claude auth status *> $null; return $LASTEXITCODE -eq 0 }
        'codex' { if ($env:OPENAI_API_KEY) { return $true }; codex login status *> $null; return $LASTEXITCODE -eq 0 }
        default { return $true }
    }
}

$cmd = if ($args.Count -gt 0) { $args[0] } else { '' }

if ($cmd -eq 'update') {
    # Only for copies made by install.ps1: it force-checks-out $Root, which must not hit a dev checkout.
    if ((Test-Path $Marker) -and (Test-Path (Join-Path $Root 'install.ps1')) -and (Test-Path (Join-Path $Root '.git'))) {
        $env:KOPAPER_SRC = $Root
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'install.ps1')
        exit $LASTEXITCODE
    }
    Fail 'not installed by install.ps1; re-run it, or update the plugin with /plugin'
}

if ($cmd -eq 'doctor') {
    Setup
    if (-not (LoggedIn)) {
        if ($env:KOPAPER_BACKEND -eq 'claude-code') { Fail 'Claude Code is installed but not logged in. Run: claude auth login' }
        Fail 'Codex is installed but not logged in. Run: codex login'
    }
    Write-Output "[ok] kopaper ready  root=$Root  data=$($env:KOPAPER_DATA)"
    Write-Output "  backend:  $($env:KOPAPER_BACKEND)"
    exit 0
}

$kp = Join-Path $Root '.venv\Scripts\kopaper.exe'
if (-not (Test-Path $kp) -or -not (Need 'babeldoc')) { Setup }
$rest = if ($args.Count -gt 0) { $args } else { @('serve', '--open') }
& $kp @rest
exit $LASTEXITCODE
