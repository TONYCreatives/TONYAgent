# Throwaway: where the two windows actually are, in logical and physical pixels.
#
# Needed because a capture taken at the wrong origin silently produces a strip of
# black with a sliver of app in it, which reads as a layout measurement when it is
# really a coordinate error.
param([string]$Process = "tonyagent-app")

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint processId);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left, Top, Right, Bottom; }
}
'@

# PER_MONITOR_AWARE_V2, so GetWindowRect returns physical pixels and the numbers
# can be handed straight to shot_screen.ps1.
[void][Win]::SetProcessDpiAwarenessContext([IntPtr](-4))

# Copied into a script-scope variable because `$using:` does not reach a delegate
# invoked from EnumWindows -- it is only valid across a remoting boundary.
$script:wanted = $Process

$results = @()
$callback = [Win+EnumProc] {
  param($handle, $state)
  # Not $pid: PowerShell makes that name read-only, and the assignment throws
  # before EnumWindows ever reaches the window.
  $owner = [uint32]0
  [void][Win]::GetWindowThreadProcessId($handle, [ref]$owner)
  $proc = (Get-Process -Id $owner -ErrorAction SilentlyContinue).ProcessName
  if ($proc -eq $script:wanted -and [Win]::IsWindowVisible($handle)) {
    $title = New-Object System.Text.StringBuilder 256
    [void][Win]::GetWindowText($handle, $title, 256)
    $rect = New-Object Win+RECT
    [void][Win]::GetWindowRect($handle, [ref]$rect)
    $script:results += [pscustomobject]@{
      Handle   = $handle
      Left     = $rect.Left
      Top      = $rect.Top
      Right    = $rect.Right
      Bottom   = $rect.Bottom
      Width    = $rect.Right - $rect.Left
      Height   = $rect.Bottom - $rect.Top
      Title    = $title.ToString()
    }
  }
  return $true
}
[void][Win]::EnumWindows($callback, [IntPtr]::Zero)

$results | ForEach-Object {
  "{0}  physical ({1},{2}) .. ({3},{4})  {5}x{6}  css {7}x{8}  [{9}]" -f `
    $_.Handle, $_.Left, $_.Top, $_.Right, $_.Bottom, $_.Width, $_.Height,
    [int]($_.Width / 1.75), [int]($_.Height / 1.75), $_.Title
}