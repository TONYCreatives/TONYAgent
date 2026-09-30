# Print the newest source file when it is newer than the build.
#
# This used to be a PowerShell one-liner inside a `for /f` loop in the launcher,
# which never worked. The batch parser counts parentheses even inside a
# backquoted command, so a brace-closed PowerShell block like `if($x){ $x }`
# leaves it looking for a closing paren that is not there, and the whole file
# dies with a bare "was unexpected at this time" before the application is ever
# started. The launcher that flashes and closes was this, not a crash.
#
# A script file has no such rule: batch only parses its own lines.
#
# Prints the full path of the newest source file, or nothing when the build is
# current. The caller decides what to do about it.

param(
    [Parameter(Mandatory = $true)]
    [string]$AppExe
)

$roots = @(
    'src',
    'app\src',
    'app\src-tauri\src',
    'app\src-tauri\tauri.conf.json'
)

$app = (Get-Item -LiteralPath $AppExe).LastWriteTime

$files = foreach ($root in $roots) {
    if (Test-Path -LiteralPath $root) {
        Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue
    }
}

$newest = $files |
    Where-Object {
        $_.Extension -in '.py', '.tsx', '.ts', '.css', '.rs' -or
        $_.Name -eq 'tauri.conf.json'
    } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($newest -and $newest.LastWriteTime -gt $app) {
    $newest.FullName
}
