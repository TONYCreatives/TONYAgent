# Make the shortcut that opens the app.
#
# A `.lnk` rather than telling someone to double-click the `.bat`, because a
# shortcut carries the app's own icon and a description, and it can point at the
# launcher without the launcher having to know where it is. The file it writes is
# gitignored: it holds an absolute path to *this* checkout, so it is a fact about
# one machine rather than about the project.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1 `
#       -Destination "$env:USERPROFILE\Desktop"

param(
    # Where to put it. The repository root by default, beside the launcher.
    [string]$Destination = (Split-Path -Parent $PSScriptRoot),
    [string]$Name = 'TONYAgent.lnk',
    # Which frontend the shortcut opens. `window` is the desktop app. Pass an
    # empty string for the launcher's own default, which is the terminal.
    [string]$Arguments = 'window'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'Start TONYAgent (Prebuilt).bat'
# The logo, not `app\icons\icon.ico`. They are the same mark and differ only in
# the ground: the app icon keeps the blue-to-violet tile because a taskbar slot
# is a square competing with other squares, while the shortcut wears the logo --
# the mark on black. Both are generated from one geometry by
# `scripts\gen_icons.py`, so neither can drift from the other or from the window.
$icon = Join-Path $root 'logo\tonyagent-logo.ico'

foreach ($needed in @($launcher, $icon)) {
    if (-not (Test-Path -LiteralPath $needed)) {
        Write-Error "missing: $needed"
        exit 1
    }
}

if (-not (Test-Path -LiteralPath $Destination)) {
    Write-Error "no such destination: $Destination"
    exit 1
}

$target = Join-Path $Destination $Name
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($target)

# The launcher rather than `pythonw -m tonyagent.window`, and that is the point:
# the launcher is what rebuilds the frontend when it is behind and checks that
# `pywebview` is installed before it starts anything. A shortcut straight to the
# interpreter would be a second, worse entry point that skipped both.
$shortcut.TargetPath = $launcher
# `window`, because the launcher's no-argument default is the terminal
# interface. Everything the comment above describes -- the rebuild when the
# frontend is behind, and the `pywebview` pre-flight -- lives on the window path
# and is skipped by the terminal one, so a shortcut that passed no argument
# would not be doing what this file exists to do. The launcher's default is
# right for a `cmd` window someone opened on purpose; a double-click on an icon
# is asking for the app.
$shortcut.Arguments = $Arguments
# The launcher's own `cd /d "%~dp0"` handles the working directory, but this is
# what the shortcut's Properties sheet shows, and leaving it blank shows the
# Windows directory instead.
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'TONYAgent - a local AI agent'
$shortcut.Save()

Write-Output "created $target"
Write-Output "  target: $launcher"
Write-Output "  icon:   $icon"
