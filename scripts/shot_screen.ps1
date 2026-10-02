# Capture a rectangle of the screen to a PNG.
#
# Why this exists: matching TONYAgent's window to Freebuff's is a visual
# judgement, and the only way to make it one is to put the two windows in the
# same image. `PrintWindow` is not the way to get there -- it is unreliable for
# a WebView2 window and returns bands of unpainted black -- so this copies the
# screen, which is what the user is actually looking at anyway.
#
# The capture is at *physical* pixels. This process is DPI-unaware by default,
# which makes `CopyFromScreen` take and return logical pixels -- so on this
# machine (1.75 scale) a capture came out 1655x990 for a window that is really
# 2879x1799, and every measurement taken off it was out by that factor. A 204px
# sidebar was really 307px. Opting into PER_MONITOR_AWARE_V2 first is what makes
# a screenshot readable as a stylesheet.
#
# Usage:
#   powershell -NoProfile -File scripts/shot_screen.ps1 -X -2880 -Y 0 -W 1646 -H 981 -Out .shots/compare.png
param(
  [Parameter(Mandatory = $true)][int]$X,
  [Parameter(Mandatory = $true)][int]$Y,
  [Parameter(Mandatory = $true)][int]$W,
  [Parameter(Mandatory = $true)][int]$H,
  [Parameter(Mandatory = $true)][string]$Out
)

Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class DpiAware {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
'@
# -4 is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2. Set before any GDI call, or
# it fails and the capture silently comes back at logical size again.
if (-not [DpiAware]::SetProcessDpiAwarenessContext([IntPtr](-4))) {
  [void][DpiAware]::SetProcessDPIAware()
}

$bitmap = New-Object System.Drawing.Bitmap $W, $H
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
  # CopyFromScreen, not a handle: whatever is on screen at those coordinates,
  # which for a side-by-side comparison is the thing being compared.
  $graphics.CopyFromScreen($X, $Y, 0, 0, (New-Object System.Drawing.Size $W, $H))
  $directory = Split-Path -Parent $Out
  if ($directory -and -not (Test-Path $directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
  }
  $bitmap.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Output "wrote $Out ($W x $H from $X,$Y)"
}
finally {
  $graphics.Dispose()
  $bitmap.Dispose()
}
