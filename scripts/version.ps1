<#
.SYNOPSIS
    Read or set the SHAWZIFY version in every place it is written.
.DESCRIPTION
    The version lives in five files. Setting it by hand means eventually
    shipping an installer whose About box disagrees with its filename, so this
    script writes all five and refuses to leave them inconsistent.

    Run with no arguments to check the current state.
.EXAMPLE
    scripts\version.ps1            # report
    scripts\version.ps1 0.2.0      # set
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$targets = @(
    @{
        Path    = Join-Path $root 'engine/pyproject.toml'
        Pattern = '(?m)^version = "([^"]+)"'
        Format  = 'version = "{0}"'
    },
    @{
        Path    = Join-Path $root 'engine/shawzify_engine/version.py'
        Pattern = '(?m)^APP_VERSION = "([^"]+)"'
        Format  = 'APP_VERSION = "{0}"'
    },
    @{
        Path    = Join-Path $root 'apps/desktop/package.json'
        Pattern = '(?m)^  "version": "([^"]+)",'
        Format  = '  "version": "{0}",'
    },
    @{
        Path    = Join-Path $root 'apps/desktop/src-tauri/Cargo.toml'
        Pattern = '(?m)^version = "([^"]+)"'
        Format  = 'version = "{0}"'
    },
    @{
        Path    = Join-Path $root 'apps/desktop/src-tauri/tauri.conf.json'
        Pattern = '(?m)^  "version": "([^"]+)",'
        Format  = '  "version": "{0}",'
    }
)

function Get-Current($target) {
    $text = Get-Content -Raw -Path $target.Path
    $match = [regex]::Match($text, $target.Pattern)
    if (-not $match.Success) { throw "No version found in $($target.Path)" }
    return $match.Groups[1].Value
}

if (-not $Version) {
    $found = @{}
    foreach ($t in $targets) {
        $current = Get-Current $t
        $found[$current] = $true
        Write-Host ('  {0,-14} {1}' -f $current, (Resolve-Path -Relative $t.Path))
    }
    if ($found.Keys.Count -gt 1) {
        Write-Host "`nThe version disagrees between files. Run: scripts\version.ps1 <version>" -ForegroundColor Red
        exit 1
    }
    Write-Host "`nAll five agree." -ForegroundColor Green
    exit 0
}

if ($Version -notmatch '^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$') {
    throw "'$Version' is not a semantic version (expected e.g. 0.2.0 or 1.0.0-rc.1)."
}

foreach ($t in $targets) {
    $before = Get-Current $t
    $text = Get-Content -Raw -Path $t.Path
    $updated = [regex]::Replace($text, $t.Pattern, ($t.Format -f $Version), 1)
    # Preserve the file's own line endings; a wholesale rewrite would churn the diff.
    Set-Content -Path $t.Path -Value $updated -NoNewline
    $relative = Resolve-Path -Relative $t.Path
    if ($before -eq $Version) {
        Write-Host "  = $relative (already $Version)"
    } else {
        Write-Host "  → $relative  $before -> $Version" -ForegroundColor Green
    }
}

Write-Host ''
Write-Host 'Now update CHANGELOG.md, then:' -ForegroundColor Cyan
Write-Host "  git commit -am `"Release $Version`""
Write-Host "  git tag -a v$Version -m `"SHAWZIFY $Version`""
Write-Host '  git push && git push --tags'
Write-Host ''
Write-Host 'If this release changes what the engine produces for identical input,' -ForegroundColor Yellow
Write-Host 'bump the relevant algorithm version in engine/shawzify_engine/version.py too.' -ForegroundColor Yellow
