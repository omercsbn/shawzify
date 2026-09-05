<#
.SYNOPSIS
    Produce a Windows build of SHAWZIFY.
.DESCRIPTION
    Builds the frontend, then the Tauri bundle. The Python engine is not
    embedded by default: the model weights alone run to hundreds of megabytes,
    and bundling them would make a multi-gigabyte installer. Pass -BundlePython
    to produce a standalone engine directory with PyInstaller.
#>
[CmdletBinding()]
param(
    [switch]$BundlePython,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $root 'apps/desktop'
$python = Join-Path $root 'engine/.venv/Scripts/python.exe'

if (-not $SkipTests) {
    & (Join-Path $PSScriptRoot 'test.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; not building.' }
}

Write-Host "`n=== Frontend" -ForegroundColor Cyan
Push-Location $desktop
try {
    & npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }

if ($BundlePython) {
    Write-Host "`n=== Python engine (PyInstaller)" -ForegroundColor Cyan
    & $python -m pip install --disable-pip-version-check pyinstaller
    Push-Location (Join-Path $root 'engine')
    try {
        & $python -m PyInstaller --noconfirm --clean --onedir --name shawzify-engine `
            --collect-data shawzify_engine `
            --collect-all basic_pitch `
            --hidden-import shawzify_engine.server `
            (Join-Path $root 'engine/shawzify_engine/server.py')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    } finally { Pop-Location }
    Write-Host '  Engine bundled to engine/dist/shawzify-engine' -ForegroundColor Green
    Write-Host '  Model weights stay in the user cache and download on first use.' -ForegroundColor Green
}

Write-Host "`n=== Desktop bundle" -ForegroundColor Cyan
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw 'Rust is required to build the desktop app. Install it from https://rustup.rs.'
}
Push-Location $desktop
try {
    & npm run tauri:build
    if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed.' }
} finally { Pop-Location }

$bundle = Join-Path $root 'apps/desktop/src-tauri/target/release/bundle'
Write-Host "`nBuild complete." -ForegroundColor Green
if (Test-Path $bundle) {
    Get-ChildItem -Recurse -File $bundle -Include *.exe, *.msi | ForEach-Object {
        Write-Host "  $($_.FullName)  ($([math]::Round($_.Length / 1MB, 1)) MB)"
    }
}
