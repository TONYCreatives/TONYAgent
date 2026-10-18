# Publish a release: tag it, build the installer, attach it to the release.
#
# **This is the other half of the update check.** `core/update.py` reads
# `/releases/latest`, so a release is what the app finds -- and the pieces that
# have to agree are the version in `__init__.py`, the tag, the MSI's
# `ProductVersion` and the asset name. They all come from one number here for
# the same reason they do in the build: a release whose tag says one thing and
# whose installer says another is an update the app offers and cannot install.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\release.ps1 -DryRun
#
# Prerequisites:
#   gh, authenticated once with `gh auth login` (or GH_TOKEN in the environment)
#   the installer toolchain -- see `Build Installer.bat`
#
# **The tag must be numeric.** `v0.2.0` and not `v0.2.0-beta` as a *tag*: the
# MSI's ProductVersion is the first three fields of this number and Windows
# Installer compares nothing else, so a prerelease tag would produce an
# installer that claims to be a version it is not. Mark the release a
# prerelease with the flag instead -- GitHub excludes those from
# `/releases/latest`, which is exactly the behaviour the app wants.

[CmdletBinding()]
param(
    # Everything except the publish. Prints what it would do.
    [switch]$DryRun,
    # Mark the release a prerelease. The tag stays numeric either way.
    [switch]$Prerelease,
    # Notes from a file rather than the editor `gh` opens.
    [string]$NotesFile
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step([string]$message) { Write-Host ''; Write-Host "== $message" -ForegroundColor Cyan }
function Fail([string]$message) { Write-Host ''; Write-Host "[ERROR] $message" -ForegroundColor Red; exit 1 }

# --- the version, from the one place it is written down ---------------------
$initPy = Join-Path $root 'src\tonyagent\__init__.py'
$versionLine = Select-String -Path $initPy -Pattern '^\s*__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $versionLine) { Fail "no __version__ found in $initPy" }
$version = $versionLine.Matches[0].Groups[1].Value
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    Fail "the tag must be numeric x.y.z, and __init__.py says '$version'. Mark a prerelease with -Prerelease, not in the number."
}
$tag = "v$version"
$msi = Join-Path $root "build\installer\TONYAgent-$version.msi"

Step "Releasing $tag"

# --- the tree has to be the thing being released ----------------------------
# A release built from a dirty tree is a release nobody can reproduce from the
# tag, which defeats the point of tagging at all.
$dirty = git status --porcelain
if ($dirty) {
    Fail @"
The working tree has uncommitted changes, so the tag would not describe what
was built:

$dirty
"@
}

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'master' -and $branch -ne 'main') {
    Write-Host "  note: releasing from '$branch' rather than master" -ForegroundColor Yellow
}

# --- the installer ----------------------------------------------------------
if (-not (Test-Path -LiteralPath $msi)) {
    Step 'Building the installer (none found for this version)'
    if ($DryRun) {
        Write-Host "  would run: scripts\build_installer.ps1"
    } else {
        & (Join-Path $PSScriptRoot 'build_installer.ps1')
        if ($LASTEXITCODE -ne 0) { Fail 'the installer build failed' }
    }
} else {
    Write-Host "  using $msi"
}

if (-not $DryRun -and -not (Test-Path -LiteralPath $msi)) {
    Fail "no installer at $msi after the build"
}

# --- the tag ----------------------------------------------------------------
$existing = (git tag --list $tag).Trim()
if ($existing) {
    Write-Host "  tag $tag already exists; leaving it where it is"
} elseif ($DryRun) {
    Write-Host "  would tag $tag"
} else {
    git tag -a $tag -m "TONYAgent $version"
    if ($LASTEXITCODE -ne 0) { Fail "could not create $tag" }
    Write-Host "  tagged $tag"
}

# --- publish ----------------------------------------------------------------
# `gh` rather than a hand-rolled API call: it already knows about tokens,
# redirects and the asset upload, and it is one dependency rather than a script
# that has to reimplement all three.
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Fail @'
gh was not found on PATH. Install it once:

    winget install --id GitHub.cli

then authenticate with `gh auth login`.
'@
}

$releaseArgs = @('release', 'create', $tag, $msi, '--title', "TONYAgent $version")
if ($Prerelease) { $releaseArgs += '--prerelease' }
if ($NotesFile) { $releaseArgs += @('--notes-file', $NotesFile) } else { $releaseArgs += '--generate-notes' }
# Idempotent: re-running after a failed upload should fix the release rather
# than refuse because it already exists.
$releaseArgs += '--clobber'

if ($DryRun) {
    Write-Host ''
    Write-Host "would run: gh $($releaseArgs -join ' ')" -ForegroundColor Yellow
    Write-Host "would push: git push origin $branch $tag"
    exit 0
}

Step 'Pushing the branch and the tag'
git push origin $branch
if ($LASTEXITCODE -ne 0) { Fail 'could not push the branch' }
git push origin $tag
if ($LASTEXITCODE -ne 0) { Fail 'could not push the tag' }

Step 'Publishing the release'
& gh @releaseArgs
if ($LASTEXITCODE -ne 0) { Fail 'gh could not create the release' }

Write-Host ''
Write-Host "Released $tag with $(Split-Path -Leaf $msi)" -ForegroundColor Green
Write-Host ''
Write-Host 'The app reads /releases/latest, which ignores prereleases and drafts,'
Write-Host 'so this becomes the version every installed copy is offered.'
