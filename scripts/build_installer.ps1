# Build the installer: one command from a checkout to a TONYAgent.msi.
#
# Three stages, and each one is a hard prerequisite of the next:
#
#   1. `npm run build`   -- the frontend the window serves.
#   2. PyInstaller       -- host and core frozen into one TONYAgent.exe.
#   3. WiX               -- that directory packaged as an MSI, with a Start
#                           Menu entry, a desktop shortcut and an uninstaller.
#
# **A failure stops the run.** There is no partial installer here: an MSI built
# from a stale frontend or a half-frozen bundle installs cleanly and then fails
# on the user's machine, which is the one failure nobody can debug from the
# stack trace they get. So every stage is checked, and the checks are the
# toolchain's own exit codes rather than a file-exists guess afterwards.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_installer.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_installer.ps1 `
#       -SkipFrontend -SkipFreeze        # repackage the existing bundle
#
# Output:
#   build\installer\TONYAgent-<version>.msi

[CmdletBinding()]
param(
    # Reuse the existing app\dist instead of running Vite again.
    [switch]$SkipFrontend,
    # Reuse the existing frozen bundle instead of running PyInstaller again.
    # This is the fast path when only the WiX source has changed.
    [switch]$SkipFreeze,
    # Where the MSI is written. Defaults beside the other build output.
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Join-Path $root 'build\installer' }
$dist = Join-Path $OutputDir 'dist'
$bundle = Join-Path $dist 'TONYAgent'

function Step([string]$message) {
    Write-Host ''
    Write-Host "== $message" -ForegroundColor Cyan
}

function Fail([string]$message) {
    Write-Host ''
    Write-Host "[ERROR] $message" -ForegroundColor Red
    exit 1
}

# --- the version, from the one place it is written down ---------------------
# Read rather than passed in: a version that has to be typed twice is a version
# that disagrees with itself, and an MSI whose ProductVersion does not match the
# program it installs breaks the upgrade path in a way nothing reports.
#
# **From `__init__.py`, not `pyproject.toml`.** The version used to be a literal
# in both, and this script read the wrong one of the two. `pyproject.toml` is now
# dynamic and points at the module, which is also what the app itself reports --
# so the tag, the MSI and the running program cannot disagree.
$initPy = Join-Path $root 'src\tonyagent\__init__.py'
$versionLine = Select-String -Path $initPy -Pattern '^\s*__version__\s*=\s*"([^"]+)"' |
    Select-Object -First 1
if (-not $versionLine) { Fail "no __version__ found in $initPy" }
$version = $versionLine.Matches[0].Groups[1].Value
if ($version -notmatch '^\d+\.\d+\.\d+') {
    Fail "the MSI needs a numeric x.y.z version, and __init__.py says '$version'"
}
# Windows Installer compares only the first three fields, so the fourth is
# dropped rather than refused: `0.1.0.dev1` is installed as 0.1.0.
$msiVersion = ($version -split '\.')[0..2] -join '.'

# --- 1. the frontend --------------------------------------------------------
if (-not $SkipFrontend) {
    Step 'Building the frontend'
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Fail 'npm was not found on PATH. Install Node.js 18+ from https://nodejs.org'
    }
    Push-Location (Join-Path $root 'app')
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { Fail 'the frontend build failed' }
    } finally { Pop-Location }
} else {
    Step 'Skipping the frontend build (-SkipFrontend)'
}

$index = Join-Path $root 'app\dist\index.html'
if (-not (Test-Path -LiteralPath $index)) {
    Fail "no built frontend at $index. Run without -SkipFrontend, or run ``npm run build`` in app\."
}

# --- 2. the frozen program --------------------------------------------------
if (-not $SkipFreeze) {
    Step 'Freezing the program (PyInstaller)'
    $pyi = & python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Fail 'PyInstaller is not installed. Run: python -m pip install pyinstaller'
    }
    Write-Host "  PyInstaller $pyi"
    # `--clean` each time: a stale Analysis cache is how a frozen build ends up
    # carrying a module that was deleted from the source an hour ago.
    & python -m PyInstaller `
        --noconfirm --clean `
        --distpath $dist `
        --workpath (Join-Path $OutputDir 'work') `
        (Join-Path $root 'packaging\TONYAgent.spec')
    if ($LASTEXITCODE -ne 0) { Fail 'PyInstaller failed' }
} else {
    Step 'Skipping the freeze (-SkipFreeze)'
}

$exe = Join-Path $bundle 'TONYAgent.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    Fail "no frozen executable at $exe. Run without -SkipFreeze."
}

# --- 3. the installer -------------------------------------------------------
Step "Building the MSI (WiX) as version $msiVersion"
$wix = Get-Command wix -ErrorAction SilentlyContinue
if (-not $wix) {
    Fail @'
WiX was not found on PATH. Install it as a dotnet tool:

    dotnet tool install --global wix

and make sure %USERPROFILE%\.dotnet\tools is on PATH.
'@
}

$icon = Join-Path $root 'logo\tonyagent-logo.ico'
if (-not (Test-Path -LiteralPath $icon)) { Fail "the installer's icon is missing: $icon" }

$msi = Join-Path $OutputDir "TONYAgent-$msiVersion.msi"
if (Test-Path -LiteralPath $msi) { Remove-Item -LiteralPath $msi -Force }

& wix build `
    (Join-Path $root 'packaging\TONYAgent.wxs') `
    -arch x64 `
    -d "ProductVersion=$msiVersion" `
    -d "BuildDir=$bundle" `
    -d "IconPath=$icon" `
    -o $msi
if ($LASTEXITCODE -ne 0) { Fail 'WiX failed to build the MSI' }

# --- what was made, and how big --------------------------------------------
$size = [math]::Round((Get-Item -LiteralPath $msi).Length / 1MB, 1)
Write-Host ''
Write-Host "Installer: $msi  ($size MB)" -ForegroundColor Green
Write-Host "Program:   $exe"
Write-Host ''
Write-Host 'Installs to Program Files with a Start Menu entry, a desktop shortcut'
Write-Host 'and an uninstaller. Installing needs an administrator, which Windows'
Write-Host 'asks for when the MSI is opened.'
