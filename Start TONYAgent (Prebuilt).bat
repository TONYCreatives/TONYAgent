@echo off
REM ==========================================================================
REM  TONYAgent (prebuilt) launcher
REM
REM  Launches the already-built release binary. Nothing is rebuilt, so it
REM  starts in about a second instead of the minute-plus that "Start TONYAgent
REM  (Tauri).bat" spends compiling the frontend, the Rust shell and the Python
REM  core on every launch.
REM
REM  Use the two launchers for two different jobs:
REM
REM    Start TONYAgent (Prebuilt).bat   run what is built -- everyday use
REM    Start TONYAgent (Tauri).bat      rebuild from source, then run
REM
REM  After changing Python or React code, run "Build TONYAgent.bat" once, and
REM  use this file from then on.
REM ==========================================================================
setlocal

cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

set "APP=app\src-tauri\target\release\tonyagent-app.exe"

echo Starting TONYAgent (prebuilt)...
echo.

if not exist "%APP%" goto no_build

REM --- is the build older than the source? -----------------------------------
REM
REM A launcher that silently runs last week's binary is the failure this
REM guards: you fix a bug, double-click, and the bug is still there. Comparing
REM timestamps is a heuristic -- it cannot know whether a given edit reached the
REM build -- but it catches the ordinary case, which is the one that wastes
REM time.
REM
REM PowerShell does the comparison because doing it in batch means string-
REM comparing date formats, which is wrong in a different way per locale.
set "NEWEST="
for /f "usebackq delims=" %%N in (`powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$app=(Get-Item -LiteralPath '%APP%').LastWriteTime; ^
   $roots=@('src','app\src','app\src-tauri\src','app\src-tauri\tauri.conf.json'); ^
   $files=foreach($r in $roots){ if(Test-Path -LiteralPath $r){ Get-ChildItem -LiteralPath $r -Recurse -File -ErrorAction SilentlyContinue } }; ^
   $newest=$files | Where-Object { $_.Extension -in '.py','.tsx','.ts','.css','.rs' -or $_.Name -eq 'tauri.conf.json' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1; ^
   if($newest -and $newest.LastWriteTime -gt $app){ $newest.FullName }"`) do set "NEWEST=%%N"

if not defined NEWEST goto launch

echo [WARN] The source is newer than the build.
echo        Newest source: %NEWEST%
echo.
echo        You are about to run an older build. That is fine if you have not
echo        changed anything since the last "Build TONYAgent.bat".
echo.
set /p "ANSWER=Start the existing build anyway? [y/N] "
if /i not "%ANSWER%"=="y" (
    echo.
    echo Not starting. Run "Build TONYAgent.bat" to rebuild from source.
    pause
    endlocal
    exit /b 0
)
echo.

:launch
start "" "%APP%"
echo Started. This window can be closed.
endlocal
exit /b 0

:no_build
echo [INFO] No release build found yet.
echo.
echo        The first run builds once and takes a few minutes. After that, this
echo        launcher starts in about a second.
echo.
set /p "ANSWER=Build it now? [Y/n] "
if /i "%ANSWER%"=="n" (
    echo Skipped. Nothing was started.
    endlocal
    exit /b 0
)

pushd app
call npm run build
if not %ERRORLEVEL%==0 (
    popd
    echo [ERROR] The frontend build failed. See the output above.
    goto fail
)
popd

python scripts\build_sidecar.py
if not %ERRORLEVEL%==0 (
    echo [ERROR] The sidecar build failed. See the output above.
    goto fail
)

pushd app
call npm run tauri:build
if not %ERRORLEVEL%==0 (
    popd
    echo [ERROR] The app build failed. See the output above.
    goto fail
)
popd

if not exist "%APP%" (
    echo [ERROR] The build finished but %APP% is not there.
    goto fail
)
echo.
start "" "%APP%"
echo Started. This window can be closed.
endlocal
exit /b 0

:fail
echo.
pause
exit /b 1