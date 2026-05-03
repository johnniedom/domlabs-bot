<#
.SYNOPSIS
    Install domlabs-bot via pipx with clean output (no pipx emojis).

.DESCRIPTION
    Wraps `pipx install` so the user sees a clean completion message instead
    of pipx's default `done! ✨ 🌟 ✨`. Also auto-installs pipx if missing.

.PARAMETER Init
    After install, immediately run `domlabs-bot init`.

.PARAMETER Path
    Source path to install from. Defaults to the directory this script lives
    in, so running `.\setup.ps1` from a fresh git clone just works.

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -Init
#>
[CmdletBinding()]
param(
    [switch]$Init,
    [string]$Path = (Split-Path -Parent $PSCommandPath)
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "  $msg" -ForegroundColor DarkGray
}

function Write-Banner($msg) {
    $bar = "─" * 60
    Write-Host ""
    Write-Host $bar
    Write-Host "  $msg"
    Write-Host $bar
    Write-Host ""
}

# --- 1. Ensure pipx is available ----------------------------------------

if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
    Write-Banner "pipx not found — installing it first"
    Write-Step "python -m pip install --user pipx"
    python -m pip install --user pipx 2>&1 | Out-Null
    Write-Step "python -m pipx ensurepath"
    python -m pipx ensurepath 2>&1 | Out-Null
    Write-Host ""
    Write-Host "  pipx is installed but its scripts directory may not be on PATH yet." -ForegroundColor Yellow
    Write-Host "  If 'domlabs-bot' doesn't resolve after this script finishes," -ForegroundColor Yellow
    Write-Host "  open a new terminal and try again." -ForegroundColor Yellow
    Write-Host ""
}

# --- 2. Run pipx install, filter pipx's emoji line out as it streams ----

Write-Banner "Installing domlabs-bot from $Path"

# Force UTF-8 so emoji-bearing lines come through intact and our regex matches.
$prevEnc = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Always invoke pipx via `python -m pipx` — works regardless of PATH state.
& python -m pipx install -e $Path --force 2>&1 | ForEach-Object {
    $line = "$_"
    # Skip pipx's celebration line. The emojis live on this single line, so
    # dropping it kills them all.
    if ($line -match '^\s*done!') { return }
    Write-Step $line
}
$exitCode = $LASTEXITCODE

[Console]::OutputEncoding = $prevEnc

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "  Install failed (exit code $exitCode)." -ForegroundColor Red
    exit $exitCode
}

# --- 3. Clean completion banner -----------------------------------------

Write-Banner "domlabs-bot installed."

if ($Init) {
    & domlabs-bot init
} else {
    Write-Host "  Next:  domlabs-bot init"
    Write-Host "         (or .\setup.ps1 -Init to chain straight into setup)"
    Write-Host ""
}
