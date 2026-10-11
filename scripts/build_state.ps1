# Decide whether the frontend build actually has to run.
#
# There is one stage now, and that is the change this file records:
#
#   1  vite build   app/src/**, app/index.html  ->  app/dist/
#
# The Rust shell and the frozen Python sidecar are gone. The window is
# `python -m tonyagent.window`, which *reads* app/dist/ at runtime instead of
# embedding it, so the frontend is the only thing with a build step at all --
# there is nothing to link, nothing to freeze, and no cargo, no `rc.exe` and no
# Windows SDK anywhere in the chain. A one-character edit to a React file now
# costs a two-second `vite build` instead of a PyInstaller freeze plus a Rust
# relink, which is what made the old three-stage version worth writing in the
# first place.
#
# The staleness question is still worth asking, and for the reason it always was:
# a launcher that silently runs last week's bundle is the failure worth guarding
# against, and "is the output older than the newest input" has one answer rather
# than being a guess.
#
# Outputs one line per stale stage and nothing for a fresh one, so the caller can
# read it straight into a loop. A missing output counts as stale, always: that is
# what makes the first run after a clean checkout do the build.

param(
    # Repository root. Defaults to the parent of this script's directory.
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

# --- what the stage reads, and the single file that proves it ran -----------
#
# Compared against one sentinel rather than a count of files, so the answer is
# "is the output newer than the newest input" -- a question with one answer,
# instead of a per-file walk on every launch.
$Stages = @(
    [pscustomobject]@{
        Name   = 'frontend'
        Inputs = @('app\src', 'app\index.html', 'app\package.json', 'app\vite.config.ts')
        Output = 'app\dist\index.html'
    }
)

function Get-NewestInput {
    param([string[]]$Paths)

    # Derived files are not inputs. Python's __pycache__ was the one that used to
    # matter: running the test suite rewrites .pyc files under src/, which made a
    # stage look stale after every pytest run and re-froze 45 MB of Python to
    # pick up changes nobody had made. src/ is not an input any more, but the
    # same trap is one directory away -- node_modules is rewritten by any
    # install, and app/.tmp/ is rewritten by the test suite itself.
    $derived = '\\(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|\.git|\.tmp)\\'

    $newest = $null
    foreach ($path in $Paths) {
        $full = Join-Path $Root $path
        if (-not (Test-Path -LiteralPath $full)) { continue }
        $item = Get-Item -LiteralPath $full
        # A directory's own timestamp says when its entries changed, but a file
        # written inside it does not always update it, so recurse.
        $found = if ($item.PSIsContainer) {
            Get-ChildItem -LiteralPath $full -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch $derived }
        }
        else {
            $item
        }
        foreach ($file in $found) {
            if (-not $newest -or $file.LastWriteTime -gt $newest) { $newest = $file.LastWriteTime }
        }
    }
    return $newest
}

$stale = @()

foreach ($stage in $Stages) {
    $outputPath = if ([System.IO.Path]::IsPathRooted($stage.Output)) {
        $stage.Output
    }
    else {
        Join-Path $Root $stage.Output
    }

    # A missing output is stale by definition: nothing has been built yet.
    if (-not (Test-Path -LiteralPath $outputPath)) {
        $stale += $stage.Name
        continue
    }

    $outputTime = (Get-Item -LiteralPath $outputPath).LastWriteTime
    $inputTime = Get-NewestInput -Paths $stage.Inputs

    # No inputs at all is not a reason to skip. It means the path list has
    # drifted from the tree, and the safe answer to that is to build.
    if ($inputTime -and $inputTime -gt $outputTime) {
        $stale += $stage.Name
    }
}

# Reported in build order, which is also dependency order, so the caller can read
# the list top to bottom and know what runs in what sequence.
foreach ($name in $stale) {
    Write-Output $name
}
