<#
.SYNOPSIS
    Build the Tsumugin Workbench desktop sidecar (V2c C1, ADR-0001) and stage it where the
    Tauri shell consumes it (desktop/src-tauri/binaries/).

.DESCRIPTION
    1. Checks frontend/dist exists (or builds it with -BuildFrontend).
    2. Runs `uv run pyinstaller desktop/sidecar/sidecar.spec` (one-dir build, output at
       desktop/sidecar/dist/tsumugin-workbench-sidecar/).
    3. Copies the output into desktop/src-tauri/binaries/, renaming the launcher exe to
       include the target triple (tsumugin-workbench-sidecar-<triple>.exe). PyInstaller
       one-dir builds require the exe and its dependency folder (_internal/) to sit in the
       SAME directory to run — so both are staged flat under binaries/ (splitting the exe out
       under Tauri's externalBin naming convention alone would strand _internal and break the
       sidecar; see desktop/README.md "production sidecar packaging").
    4. tauri.conf.json's `bundle.resources` (`{"binaries": "sidecar"}`) picks up this whole
       directory. Rust side (`src-tauri/src/lib.rs`) spawns
       `resource_dir()/sidecar/tsumugin-workbench-sidecar-<triple>.exe` directly via
       std::process::Command — not via tauri-plugin-shell's externalBin/sidecar() API, which
       assumes a single relocatable binary and doesn't fit a multi-file one-dir payload well
       (see README for the tradeoff).

.PARAMETER TargetTriple
    Target triple suffix for the staged exe name. Defaults to the `rustc -vV` host triple.

.PARAMETER BuildFrontend
    Run `cd frontend && npm run build` first (default assumes frontend/dist is already built).

.PARAMETER SkipPyInstaller
    Skip re-running PyInstaller and just re-stage the existing
    desktop/sidecar/dist/tsumugin-workbench-sidecar/ output (useful when only the staging step
    needs to be re-verified).

.EXAMPLE
    pwsh desktop/sidecar/build_sidecar.ps1
    pwsh desktop/sidecar/build_sidecar.ps1 -BuildFrontend
#>
[CmdletBinding()]
param(
    [string]$TargetTriple,
    [switch]$BuildFrontend,
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$FrontendDist = Join-Path $RepoRoot "frontend\dist"
$SidecarDir = Join-Path $RepoRoot "desktop\sidecar"
$SpecPath = Join-Path $SidecarDir "sidecar.spec"
$DistOut = Join-Path $SidecarDir "dist\tsumugin-workbench-sidecar"
$BuildOut = Join-Path $SidecarDir "build"
$BinariesDir = Join-Path $RepoRoot "desktop\src-tauri\binaries"

Write-Host "=== Tsumugin Workbench sidecar build (V2c C1) ===" -ForegroundColor Cyan

# --- 1. frontend/dist -------------------------------------------------------

if ($BuildFrontend) {
    Write-Host "--- npm run build (frontend) ---" -ForegroundColor Cyan
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $FrontendDist)) {
    throw "frontend/dist not found ($FrontendDist). Run 'cd frontend; npm run build' first, or pass -BuildFrontend."
}

# --- 2. PyInstaller (one-dir) ------------------------------------------------

if (-not $SkipPyInstaller) {
    Write-Host "--- uv run pyinstaller (one-dir) ---" -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        uv run pyinstaller $SpecPath --noconfirm --distpath (Join-Path $SidecarDir "dist") --workpath $BuildOut
        if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $DistOut)) {
    throw "PyInstaller output not found ($DistOut). Check the build log above."
}
$ExeSrc = Join-Path $DistOut "tsumugin-workbench-sidecar.exe"
if (-not (Test-Path $ExeSrc)) {
    throw "sidecar exe not found ($ExeSrc)."
}

# --- 3. target triple ---------------------------------------------------

if (-not $TargetTriple) {
    $hostLine = (rustc -vV) -split "`n" | Where-Object { $_ -match "^host:\s*(\S+)" }
    if (-not $hostLine) { throw "Could not detect host triple from 'rustc -vV'. Pass -TargetTriple explicitly." }
    $TargetTriple = ($hostLine -replace "^host:\s*", "").Trim()
}
Write-Host "target triple: $TargetTriple" -ForegroundColor Cyan

# --- 4. stage desktop/src-tauri/binaries/ -----------------------------------

Write-Host "--- staging desktop/src-tauri/binaries/ ---" -ForegroundColor Cyan
if (Test-Path $BinariesDir) {
    Remove-Item $BinariesDir -Recurse -Force
}
New-Item -ItemType Directory -Path $BinariesDir | Out-Null

# Dependency payload copied as-is.
Copy-Item (Join-Path $DistOut "_internal") (Join-Path $BinariesDir "_internal") -Recurse

# Launcher exe copied with the target-triple suffix, flat alongside _internal/ (same
# directory is required for the PyInstaller one-dir launcher to find its dependencies).
$ExeName = "tsumugin-workbench-sidecar-$TargetTriple.exe"
$ExeDst = Join-Path $BinariesDir $ExeName
Copy-Item $ExeSrc $ExeDst

$sizeBytes = (Get-ChildItem $BinariesDir -Recurse | Measure-Object -Property Length -Sum).Sum
$sizeMb = [math]::Round($sizeBytes / 1MB, 1)

Write-Host ""
Write-Host "=== done ===" -ForegroundColor Green
Write-Host "  exe:  $ExeDst"
Write-Host "  size: $sizeMb MB ($BinariesDir)"
Write-Host ""
Write-Host "Smoke test (standalone):"
Write-Host "  & `"$ExeDst`" --port 8770"
Write-Host "  curl http://127.0.0.1:8770/api/state"
