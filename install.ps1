# Install ko-paper on Windows (PowerShell 5.1+).
#   irm https://raw.githubusercontent.com/maenjh/ko-paper/main/install.ps1 | iex
# Options are environment variables, so they also work through `irm | iex`:
#   $env:KOPAPER_WITH = "claude-code"   also install Claude Code (for Claude subscribers)
#   $env:KOPAPER_WITH = "codex"         also install Codex CLI (for ChatGPT subscribers; needs Node.js)
#   $env:KOPAPER_AGENTS = "claude" | "codex" | "all"   install the skill only for that agent
#
# What it does (same as install.sh):
#   - installs uv if missing, clones the repo to ~\.ko-paper\src (re-running updates it)
#   - copies the skill into Claude Code (~\.claude\skills) and/or Codex ($CODEX_HOME\skills) when present
#   - puts a `ko-paper` command in ~\.local\bin: no arguments opens the web UI, or `ko-paper translate a.pdf`
#   - checks BabelDOC and the translation backend (Claude Code or Codex, logged in)
# ASCII only: Windows PowerShell 5.1 misreads UTF-8 files without a BOM.

function Install-KoPaper {
    $ErrorActionPreference = 'Stop'
    $Repo = if ($env:KOPAPER_REPO) { $env:KOPAPER_REPO } else { 'https://github.com/maenjh/ko-paper.git' }
    $Ref = if ($env:KOPAPER_REF) { $env:KOPAPER_REF } else { 'main' }
    $Src = if ($env:KOPAPER_SRC) { $env:KOPAPER_SRC } else { Join-Path $HOME '.ko-paper\src' }
    $BinDir = Join-Path $HOME '.local\bin'
    $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
    $ClaudeSkills = Join-Path $HOME '.claude\skills'
    $CodexSkills = Join-Path $CodexHome 'skills'
    $env:PATH = "$BinDir;$env:PATH"

    function Need($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
    function Run([string]$what, [scriptblock]$block) {
        & $block
        if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
    }

    if (-not (Need 'git')) { throw 'git is required. Install it with: winget install --id Git.Git -e   then open a new PowerShell window.' }

    if (-not (Need 'uv')) {
        Write-Host '-> installing uv (https://docs.astral.sh/uv/)'
        Run 'uv install' { powershell -NoProfile -ExecutionPolicy ByPass -c 'irm https://astral.sh/uv/install.ps1 | iex' }
    }

    if ($env:KOPAPER_WITH -eq 'claude-code' -and -not (Need 'claude')) {
        Write-Host '-> installing Claude Code'
        Run 'Claude Code install' { powershell -NoProfile -ExecutionPolicy ByPass -c 'irm https://claude.ai/install.ps1 | iex' }
    }
    if ($env:KOPAPER_WITH -eq 'codex' -and -not (Need 'codex')) {
        if (-not (Need 'npm')) { throw 'Codex needs Node.js. Install it with: winget install --id OpenJS.NodeJS.LTS -e   then open a new PowerShell window and re-run.' }
        Write-Host '-> installing Codex CLI'
        Run 'Codex install' { npm install -g '@openai/codex' }
    }

    if (Test-Path (Join-Path $Src '.git')) {
        Write-Host "-> updating $Src"
        Run 'git fetch' { git -C $Src fetch --depth 1 --quiet origin $Ref }
        Run 'git checkout' { git -C $Src checkout --quiet --force FETCH_HEAD }
    } else {
        Write-Host "-> downloading ko-paper into $Src"
        New-Item -ItemType Directory -Force (Split-Path $Src) | Out-Null
        Run 'git clone' { git clone --depth 1 --branch $Ref --quiet $Repo $Src }
    }

    # UTF-8 without BOM, so the bash wrapper (Git Bash) reads it too.
    function Write-Marker($dir) { [IO.File]::WriteAllText((Join-Path $dir '.kopaper-home'), $Src) }
    # Lets `ko-paper update` (which runs the script in $Src) know this copy came from the installer.
    Write-Marker (Join-Path $Src 'skills\ko-paper')

    # Skills: the agents picked by KOPAPER_AGENTS, else those chosen at first install, else every agent found.
    $wantClaude = $env:KOPAPER_AGENTS -in @('claude', 'all')
    $wantCodex = $env:KOPAPER_AGENTS -in @('codex', 'all')
    if (-not ($wantClaude -or $wantCodex)) {
        $wantClaude = Test-Path (Join-Path $ClaudeSkills 'ko-paper\.kopaper-home')
        $wantCodex = Test-Path (Join-Path $CodexSkills 'ko-paper\.kopaper-home')
    }
    if (-not ($wantClaude -or $wantCodex)) {
        $wantClaude = (Test-Path (Join-Path $HOME '.claude')) -or (Need 'claude')
        $wantCodex = (Test-Path $CodexHome) -or (Need 'codex')
    }

    function Install-Skill($skillsDir) {
        $dest = Join-Path $skillsDir 'ko-paper'
        New-Item -ItemType Directory -Force $skillsDir | Out-Null
        if ((Test-Path $dest) -and -not (Test-Path (Join-Path $dest '.kopaper-home'))) {
            $backup = "$dest.backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
            Write-Host "  existing $dest is not ours; moving it to $backup"
            Move-Item $dest $backup
        }
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        Copy-Item -Recurse (Join-Path $Src 'skills\ko-paper') $dest
        Write-Marker $dest
        Write-Host "  skill installed: $dest"
    }
    if ($wantClaude) { Install-Skill $ClaudeSkills }
    if ($wantCodex) { Install-Skill $CodexSkills }

    # Launcher. cmd reads .cmd files in the OEM code page, so refer to the home folder by variable, not by name.
    New-Item -ItemType Directory -Force $BinDir | Out-Null
    $wrapper = Join-Path $Src 'skills\ko-paper\scripts\kopaper.ps1'
    if ($wrapper.StartsWith($HOME)) { $wrapper = '%USERPROFILE%' + $wrapper.Substring($HOME.Length) }
    $launcher = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$wrapper`" %*`r`n"
    [IO.File]::WriteAllText((Join-Path $BinDir 'ko-paper.cmd'), $launcher, [Text.Encoding]::ASCII)
    Write-Host "  command installed: $(Join-Path $BinDir 'ko-paper.cmd')"

    # Puts ~\.local\bin on the user PATH for new windows (uv's own installer usually did already).
    $userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
    if (-not ($userPath -split ';' -contains $BinDir)) {
        try { uv tool update-shell *> $null } catch { }  # best effort; PS 5.1 may raise on redirected stderr
        Write-Host '  Note: open a new PowerShell window so the ko-paper command is found.'
    }

    Write-Host ''
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Src 'skills\ko-paper\scripts\kopaper.ps1') doctor
    $ok = $LASTEXITCODE -eq 0
    Write-Host ''
    if ($ok) {
        Write-Host '[ok] ko-paper is installed.'
        Write-Host '  Open the web UI:      ko-paper'
        Write-Host '  Translate from shell: ko-paper translate $HOME\Downloads\paper.pdf'
        if ($wantClaude -or $wantCodex) { Write-Host '  In Claude Code / Codex (restart it first), ask it to translate a paper PDF.' }
    } else {
        Write-Host '[!] ko-paper is downloaded but not ready yet. Fix the [x] line above, then run: ko-paper doctor'
        if (-not (Need 'claude') -and -not (Need 'codex')) {
            Write-Host '  Translation runs on your own Claude or ChatGPT subscription through its command-line tool:'
            Write-Host '    Claude subscribers:  $env:KOPAPER_WITH="claude-code"; irm https://raw.githubusercontent.com/maenjh/ko-paper/main/install.ps1 | iex'
            Write-Host '    ChatGPT subscribers: $env:KOPAPER_WITH="codex"; irm https://raw.githubusercontent.com/maenjh/ko-paper/main/install.ps1 | iex'
        }
        throw 'ko-paper is not ready yet (see above).'
    }
}

# A function, so `irm | iex` never runs `exit` in the user's window and a failure stays a readable error.
Install-KoPaper
