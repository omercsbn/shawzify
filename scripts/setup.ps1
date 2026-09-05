<#
.SYNOPSIS
    Prepare a machine to run SHAWZIFY from source.
.DESCRIPTION
    Checks prerequisites, creates the Python virtual environment, installs both
    dependency trees, verifies FFmpeg, and reports GPU status. Safe to re-run.
#>
[CmdletBinding()]
param(
    [switch]$SkipMl,      # skip torch / demucs / basic-pitch (much faster, fewer features)
    [switch]$Cpu,         # install the CPU-only build of PyTorch
    [switch]$SkipYouTube, # skip yt-dlp (no YouTube or Spotify link support)
    [switch]$Force        # recreate the virtual environment from scratch
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$engine = Join-Path $root 'engine'
$desktop = Join-Path $root 'apps/desktop'
$venv = Join-Path $engine '.venv'
$python = Join-Path $venv 'Scripts/python.exe'

function Write-Step($text) { Write-Host "`n=== $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  [ok] $text" -ForegroundColor Green }
function Write-Note($text) { Write-Host "  [!]  $text" -ForegroundColor Yellow }
function Have($name) { $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }

Write-Host 'SHAWZIFY setup' -ForegroundColor White
Write-Host "Repository: $root"

# -- prerequisites -------------------------------------------------------
Write-Step 'Checking prerequisites'

if (-not (Have 'node')) {
    throw 'Node.js 18+ is required. Install it from https://nodejs.org and re-run.'
}
$nodeVersion = (node --version).TrimStart('v')
if ([int]($nodeVersion.Split('.')[0]) -lt 18) {
    throw "Node.js 18+ is required (found $nodeVersion)."
}
Write-Ok "Node $nodeVersion"

if (Have 'cargo') {
    Write-Ok "Rust $((rustc --version).Split(' ')[1])"
} else {
    Write-Note 'Rust was not found. The engine and CLI will work; the desktop app will not build.'
    Write-Note 'Install it from https://rustup.rs and re-run this script.'
}

# -- python --------------------------------------------------------------
Write-Step 'Python environment'

if ($Force -and (Test-Path $venv)) {
    Write-Host '  Removing the existing virtual environment...'
    Remove-Item -Recurse -Force $venv
}

$useUv = Have 'uv'
if (-not (Test-Path $python)) {
    if ($useUv) {
        Write-Host '  Creating the virtual environment with uv (Python 3.12)...'
        & uv venv --python 3.12 $venv
    } else {
        $launcher = $null
        foreach ($candidate in @('py -3.12', 'py -3.11', 'py -3.10', 'python')) {
            $parts = $candidate.Split(' ')
            if (Have $parts[0]) { $launcher = $candidate; break }
        }
        if (-not $launcher) {
            throw 'Python 3.10+ is required. Install it from https://python.org and re-run.'
        }
        Write-Host "  Creating the virtual environment with '$launcher'..."
        $parts = $launcher.Split(' ')
        if ($parts.Length -gt 1) { & $parts[0] $parts[1] -m venv $venv } else { & $parts[0] -m venv $venv }
    }
}
if (-not (Test-Path $python)) { throw "The virtual environment was not created at $venv." }
Write-Ok ((& $python --version) -join ' ')

function Install-Packages {
    param([string[]]$Packages)
    if ($useUv) {
        $env:VIRTUAL_ENV = $venv
        & uv pip install @Packages
    } else {
        & $python -m pip install --disable-pip-version-check @Packages
    }
    if ($LASTEXITCODE -ne 0) { throw "Installing $($Packages -join ' ') failed." }
}

Write-Step 'Core engine dependencies'
Install-Packages @('-e', "$engine[dev]")
Install-Packages @('librosa')
Write-Ok 'numpy, scipy, librosa, mido, soundfile, ffmpeg, pytest, hypothesis'

if ($SkipMl) {
    Write-Note 'Skipped ML dependencies: stem separation and Basic Pitch will be unavailable.'
    Write-Note 'The built-in CQT and pYIN transcribers still work.'
} else {
    Write-Step 'Machine-learning dependencies (a few hundred MB)'
    if ($Cpu) {
        Install-Packages @('torch', 'torchaudio', '--index-url', 'https://download.pytorch.org/whl/cpu')
    } else {
        Write-Host '  Installing PyTorch with CUDA support. Pass -Cpu for the CPU-only build.'
        Install-Packages @('torch', 'torchaudio', '--index-url', 'https://download.pytorch.org/whl/cu126')
    }
    Install-Packages @('demucs')
    # basic-pitch declares a TensorFlow dependency that its ONNX runtime path
    # does not need, and TensorFlow has no wheels for Python 3.12+. Install the
    # package without its declared dependencies, then add what it really imports.
    Install-Packages @('--no-deps', 'basic-pitch')
    Install-Packages @('onnxruntime', 'pretty_midi', 'resampy', 'mir_eval')
    Install-Packages @('sounddevice')
    Write-Ok 'torch, demucs, basic-pitch (ONNX), sounddevice'
}

Write-Step 'Optional: YouTube support'
if ($SkipYouTube) {
    Write-Note 'Skipped. Local files, MIDI and Spotify metadata still work.'
} else {
    # Deliberately a separate step: yt-dlp breaks whenever the site changes, so
    # users should be able to update it on its own schedule.
    Install-Packages @('yt-dlp')
    Write-Ok 'yt-dlp installed. Keep it updated with: pip install -U yt-dlp'
}

# -- ffmpeg --------------------------------------------------------------
Write-Step 'FFmpeg'
$probe = 'from shawzify_engine.audio.ffmpeg import find_ffmpeg;i=find_ffmpeg();print(("ok|"+str(i.source)+"|"+str(i.version)) if i.available else "missing")'
$ffmpegReport = & $python -c $probe
if ($ffmpegReport -like 'ok|*') {
    $parts = $ffmpegReport.Split('|')
    Write-Ok "$($parts[2]) (via $($parts[1]))"
} else {
    Write-Note 'FFmpeg was not found, so MP3 and M4A decoding will not work.'
    Write-Note 'The imageio-ffmpeg package normally supplies one; try re-running with -Force.'
}

# -- gpu -----------------------------------------------------------------
Write-Step 'Hardware acceleration'
$gpu = & $python -c 'import json;from shawzify_engine.stems import gpu_info;print(json.dumps(gpu_info()))' 2>$null
if ($gpu) {
    $info = $gpu | ConvertFrom-Json
    if ($info.cuda) {
        Write-Ok "CUDA available - $($info.device)"
    } else {
        Write-Note 'No CUDA device found. SHAWZIFY will run on the CPU (slower stem separation).'
    }
} else {
    Write-Note 'PyTorch is not installed, so stem separation is unavailable.'
}

# -- javascript ----------------------------------------------------------
Write-Step 'Desktop dependencies'
Push-Location $desktop
try {
    & npm install --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
} finally {
    Pop-Location
}
Write-Ok 'Frontend packages installed'

# -- demo ----------------------------------------------------------------
Write-Step 'Demo material'
& $python -m shawzify_engine.cli demo --out-dir (Join-Path $root 'assets/demo') --quiet
Write-Ok 'assets/demo/demo.mid, demo.wav, demo.shawzin.txt'

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host '  scripts/dev.ps1    launch the desktop app'
Write-Host '  scripts/dev.ps1 -Cli web   the same interface in a browser'
Write-Host '  scripts/test.ps1   run every test suite'
Write-Host '  scripts/build.ps1  produce a Windows installer'
Write-Host ''
Write-Host 'Or convert something right now:'
Write-Host '  scripts/dev.ps1 -Cli convert assets/demo/demo.wav'
