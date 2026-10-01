# Print the full path to rc.exe, for the build script to point RC at.
#
# tauri-winres -- which builds the .rc file carrying the app's icon and version
# -- panics with "Are you sure you have RC.EXE in your $PATH" when it cannot
# find it, and it is the one part of the Tauri build that is not a Rust crate
# and so not found by cargo. It lives in the Windows SDK, which a terminal
# started from Explorer has never been told about: MSVC's own environment
# variables are set by a developer command prompt, and this build is started
# by double-clicking a .bat.
#
# That makes the failure a trap in both directions. The build works in a shell
# someone opened deliberately and fails in the one they double-clicked, and
# the panic names RC.EXE rather than the PATH, so the first thing to check is
# the wrong thing.
#
# It prints rather than setting $env:PATH on purpose. A child process cannot
# change its parent's environment, so a script that prepends to PATH and
# exits -- which is the obvious thing to write -- succeeds and achieves
# nothing at all. Printing the path and letting the caller set RC is the
# version that works, and it keeps the change scoped to the build script
# instead of leaking into whatever launched it.
#
# The caller sets RC rather than only putting the directory on PATH because
# that search was observed failing while `where rc.exe` had just succeeded in
# the same shell: the same build failed on some runs and passed on others with
# a PATH that demonstrably contained rc.exe both times. Naming the file
# removes the search from the picture instead of trying to keep it honest.
#
# Sorted by version so the newest SDK wins, and matching on the host
# architecture rather than hardcoding x64 -- an arm64 machine has the file in a
# different folder and would otherwise fail the same way for a different reason.

$ErrorActionPreference = 'SilentlyContinue'

$sdkBin = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
if (-not (Test-Path -LiteralPath $sdkBin)) {
    Write-Error "The Windows SDK is not installed at $sdkBin, so the app shell cannot be built. The frontend and the Python sidecar do not need it."
    exit 1
}

$arch = if ([System.Environment]::Is64BitOperatingSystem) { 'x64' } else { 'x86' }
$candidates = Get-ChildItem -LiteralPath $sdkBin -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^10\.\d+\.\d+\.\d+$' } |
    Sort-Object { [version]$_.Name } -Descending

foreach ($kit in $candidates) {
    $rc = Join-Path (Join-Path $kit.FullName $arch) 'rc.exe'
    if (Test-Path -LiteralPath $rc) {
        Write-Output $rc
        exit 0
    }
}

Write-Error "No rc.exe found under $sdkBin for $arch. The Windows SDK is installed but incomplete."
exit 1