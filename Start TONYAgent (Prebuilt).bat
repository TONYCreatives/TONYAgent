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
REM It only *says* so. It does not ask. This used to stop and read a y/N, and
REM the default was No, so a double-click on a console that flashed and closed
REM without the application ever appearing read as "the app starts and quits
REM immediately" -- a crash report in a place where nothing had crashed.
REM Anyone who wants the source rebuilt runs "Build TONYAgent.bat"; asking a
REM second time is what made this feel broken.
REM
REM The comparison itself lives in scripts\newest_source.ps1, not inline here.
REM It used to be a PowerShell one-liner inside this for-loop and it never ran
REM once: the batch parser counts parentheses even inside a backquoted command,
REM so a brace-closed block like `if($x){ $x }` leaves it hunting for a
REM closing paren that is not there, and the file dies with "was unexpected at
REM this time" before the app is started. A script file has no such rule.
set "NEWEST="
for /f "usebackq delims=" %%N in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\newest_source.ps1" -AppExe "%APP%"`) do set "NEWEST=%%N"

if not defined NEWEST goto launch

REM Plain `goto`, not `if defined NEWEST ( ... )`. Quoted text inside a
REM parenthesised block is read as the block's own delimiters, and a file that
REM does not parse fails silently enough to look like the launcher doing
REM nothing at all.
echo [WARN] The source is newer than the build. Running the older build.
echo        Newest source: %NEWEST%
echo        To pick the source up, run Build TONYAgent.bat once.
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