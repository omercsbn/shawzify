<#
.SYNOPSIS
    Run every SHAWZIFY test suite and report a single verdict.
#>
[CmdletBinding()]
param(
    [switch]$SkipRust,
    [switch]$SkipFrontend,
    [switch]$SkipPython,
    [switch]$Coverage
)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'engine/.venv/Scripts/python.exe'
$results = [ordered]@{}
$failed = $false

function Invoke-Suite {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "`n=== $Name" -ForegroundColor Cyan
    & $Body
    $ok = $LASTEXITCODE -eq 0
    $script:results[$Name] = if ($ok) { 'passed' } else { 'FAILED' }
    if (-not $ok) { $script:failed = $true }
}

if (-not $SkipPython) {
    if (-not (Test-Path $python)) { throw 'Run scripts/setup.ps1 first.' }
    Invoke-Suite 'Python (pytest)' {
        Push-Location (Join-Path $root 'engine')
        try {
            if ($Coverage) {
                & $python -m pytest -q --cov=shawzify_engine --cov-report=term-missing
            } else {
                & $python -m pytest -q
            }
        } finally { Pop-Location }
    }
    Invoke-Suite 'Python (ruff)' {
        Push-Location (Join-Path $root 'engine')
        try { & $python -m ruff check shawzify_engine tests } finally { Pop-Location }
    }
}

if (-not $SkipFrontend) {
    Invoke-Suite 'TypeScript (tsc)' {
        Push-Location (Join-Path $root 'apps/desktop')
        try { & npx tsc --noEmit } finally { Pop-Location }
    }
    Invoke-Suite 'TypeScript (vitest)' {
        Push-Location (Join-Path $root 'apps/desktop')
        try { & npx vitest run } finally { Pop-Location }
    }
}

if (-not $SkipRust) {
    if (Get-Command cargo -ErrorAction SilentlyContinue) {
        Invoke-Suite 'Rust (cargo test)' {
            Push-Location (Join-Path $root 'apps/desktop/src-tauri')
            try { & cargo test --quiet } finally { Pop-Location }
        }
    } else {
        Write-Host "`nSkipping Rust tests: cargo is not installed." -ForegroundColor Yellow
    }
}

Write-Host "`n=== Summary" -ForegroundColor Cyan
foreach ($entry in $results.GetEnumerator()) {
    $colour = if ($entry.Value -eq 'passed') { 'Green' } else { 'Red' }
    Write-Host ('  {0,-24} {1}' -f $entry.Key, $entry.Value) -ForegroundColor $colour
}

if ($failed) {
    Write-Host "`nSome suites failed." -ForegroundColor Red
    exit 1
}
Write-Host "`nAll suites passed." -ForegroundColor Green
