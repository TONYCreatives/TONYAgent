# Decide which build stages actually have to run.
#
# The build is three stages that each consume the previous one's output:
#
#   1  vite build   app/src/**            -> app/dist/
#   2  sidecar      src/**, sidecar.spec  -> app/src-tauri/binaries/
#   3  tauri build  everything above      -> app/src-tauri/target/release/tonyagent-app.exe
#
# The build script used to run all three unconditionally, and there is no
# incremental step anywhere in the chain: PyInstaller re-freezes the whole of
# Python into a 45 MB executable from scratch every time, and vite re-bundles
# the whole frontend. So a one-character edit to a React file costs the same as
# a rewrite of the core, and the usual response is to stop rebuilding and start
# running whatever is already there -- which is how a launcher ends up
# silently serving last week's build.
#
# This script answers the question the launcher needs answered: for each stage,
# is any of its inputs newer than the thing it produces? A stage whose inputs
# are all older than its output has nothing to do, and saying so out loud is
# what makes the skip visible rather than a guess.
#
# Outputs one line per stale stage and nothing for a fresh one, so the caller
# can read it straight into a loop. A missing output counts as stale, always:
# that is what makes the first run after a clean build_state do the lot.

param(
    # Repository root. Defaults to the parent of this script's directory.
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

# --- what each stage reads, and the single file that proves it ran ---------
#
# Compared against one sentinel per stage rather than a count of files, so the
# answer is "is the output newer than the newest input" -- a question with one
# answer, instead of a per-file walk on every launch.
$Stages = @(
    [pscustomobject]@{
        Name   = 'frontend'
        Inputs = @('app\src', 'app\index.html', 'app\package.json', 'app\vite.config.ts')
        Output = 'app\dist\index.html'
    },
    [pscustomobject]@{
        Name   = 'sidecar'
        Inputs = @('src', 'pyproject.toml', 'scripts\sidecar.spec', 'docker')
        # The triple-suffixed name Tauri looks for; the target is read off the
        # host, so a hardcoded one would go stale on another machine.
        Output = (Get-ChildItem -LiteralPath (Join-Path $Root 'app\src-tauri\binaries') -Filter 'tonyagent-core-*' -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName)
    },
    [pscustomobject]@{
        Name   = 'app'
        # app\dist and app\src-tauri\binaries are inputs, not bystanders, and
        # for the same reason: tauri.conf.json points frontendDist at the first
        # and externalBin at the second, so stage 3 folds both into the binary
        # rather than reading them at runtime. Leaving them out makes a skipped
        # stage 3 dangerous in two ways that a sources-only comparison cannot
        # see -- a frontend or sidecar rebuild that nothing has embedded yet,
        # and a stage 3 that failed once after either was rebuilt, leaving an
        # old .exe newer than every file in src-tauri and therefore "fresh",
        # forever.
        Inputs = @('app\dist', 'app\src-tauri\binaries', 'app\src-tauri\src', 'app\src-tauri\tauri.conf.json', 'app\src-tauri\Cargo.toml', 'app\src-tauri\build.rs', 'app\src-tauri\capabilities')
        Output = 'app\src-tauri\target\release\tonyagent-app.exe'
    }
)

function Get-NewestInput {
    param([string[]]$Paths)

    # Derived files are not inputs. Python's __pycache__ is the one that
    # matters: running the test suite rewrites .pyc files under src/, which
    # made the sidecar look stale after every pytest run, so every launch
    # re-froze 45 MB of Python to pick up changes nobody had made. Measured,
    # not assumed -- the newest "source" was core\__pycache__\conversations.pyc.
    $derived = '\\(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|node_modules|\.git)\\'

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
    $outputPath = if ([System.IO.Path]::IsPathRooted($stage.Output)) { $stage.Output } else { Join-Path $Root $stage.Output }

    if (-not $outputPath -or -not (Test-Path -LiteralPath $outputPath)) {
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

# A stale earlier stage implies a stale app, and the reason is not a timestamp.
#
# Stage 3 consumes the outputs of both other stages rather than reading their
# sources, so rebuilding one of them without relinking leaves the shell serving
# yesterday's work:
#
#   * frontend -- tauri.conf.json sets beforeBuildCommand to `npm run build`,
#     so `tauri build` re-bundles the frontend on its way to embedding
#     app/dist/ in the Rust binary. Running the frontend stage alone produces a
#     newer app/dist/ that nothing has embedded yet.
#
#   * sidecar -- the frozen core in app/src-tauri/binaries/ is not what the app
#     runs. `tauri build` is what copies it next to the exe as
#     tonyagent-core.exe, which is the path Tauri spawns and the copy the
#     installers carry. Observed, not theorised: after a sidecar-only run the
#     file in binaries/ was minutes old and the one next to the exe was a day
#     old, and the script had said the build was finished.
#
# So "app" is reported whenever anything upstream of it is stale. It is the
# honest answer rather than the reassuring one.
if ($stale -notcontains 'app' -and ($stale -contains 'frontend' -or $stale -contains 'sidecar')) {
    $stale += 'app'
}

# Reported in build order, which is also dependency order, so the caller can
# read the list top to bottom and know what runs in what sequence.
foreach ($name in $stale) {
    Write-Output $name
}
