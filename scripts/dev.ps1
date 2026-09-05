<#
.SYNOPSIS
    Launch SHAWZIFY in development mode.
.DESCRIPTION
    Starts the Vite dev server and the Tauri shell together. The Python engine
    is spawned by the shell as a child process, so there is nothing else to run.
.EXAMPLE
    scripts/dev.ps1
.EXAMPLE
    scripts/dev.ps1 -Open assets/demo/demo.wav
.EXAMPLE
    scripts/dev.ps1 -Cli convert assets/demo/demo.mid --tab
#>
[CmdletBinding()]
param(
    [string]$Open,        # a file to open on launch
    [switch]$Cli,         # run the CLI instead of the desktop app
    [switch]$Engine,      # run only the engine sidecar, for protocol debugging
    [switch]$Release,     # run the compiled release binary instead of vite+tauri
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'engine/.venv/Scripts/python.exe'
$desktop = Join-Path $root 'apps/desktop'

if (-not (Test-Path $python)) { throw 'Run scripts/setup.ps1 first.' }
$env:SHAWZIFY_ROOT = $root

if ($Engine) {
    Write-Host 'Engine sidecar on stdin/stdout. Send one JSON request per line; Ctrl+C to stop.'
    Write-Host '  {"id":1,"method":"ping"}'
    & $python -u -m shawzify_engine.server
    exit $LASTEXITCODE
}

if ($Cli) {
    & $python -m shawzify_engine.cli @Rest
    exit $LASTEXITCODE
}

$arguments = @()
if ($Open) { $arguments += (Resolve-Path $Open).Path }

if ($Release) {
    $exe = Join-Path $root 'apps/desktop/src-tauri/target/release/shawzify.exe'
    if (-not (Test-Path $exe)) { throw 'No release build found. Run scripts/build.ps1 first.' }
    & $exe @arguments
    exit $LASTEXITCODE
}

Push-Location $desktop
try {
    Write-Host 'Starting SHAWZIFY (Vite + Tauri). The first run compiles Rust, which takes a few minutes.'
    if ($arguments.Count -gt 0) {
        & npm run tauri:dev -- -- -- @arguments
    } else {
        & npm run tauri:dev
    }
} finally {
    Pop-Location
}
