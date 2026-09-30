@echo off
REM ==========================================================================
REM  TONYAgent build-once script
REM
REM  Produces the release binary that "Start TONYAgent (Prebuilt).bat" runs.
REM  Run this after changing Python or React code; the launcher itself never
REM  builds, which is the whole point of having a prebuilt path.
REM
REM  Three stages, each producing something the next one needs:
REM
REM    1. app/dist      the React bundle. `vite build` alone is not enough to
REM                     see a change in the app -- the Rust binary embeds
REM                     dist/, so it has to go through tauri in stage 3.
REM    2. the sidecar   the frozen Python core (~45 MB), which Tauri spawns.
REM    3. the app       the Rust shell with dist/ and the sidecar baked in.
REM
REM  Stages 1 and 3 are the slow ones; expect a few minutes from cold.
REM ==========================================================================
setlocal

cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo [1/3] Building the frontend...
echo.
pushd app
call npm run build
if not %ERRORLEVEL%==0 (
    popd
    echo [ERROR] The frontend build failed. See the output above.
    goto fail
)
popd
echo.

echo [2/3] Building the Python core sidecar...
echo.
python scripts\build_sidecar.py
if not %ERRORLEVEL%==0 (
    echo [ERROR] The sidecar build failed. See the output above.
    goto fail
)
echo.

echo [3/3] Building the app (the slow one)...
echo.
REM rustup registers cargo in the USER path, which a process started from
REM Explorer sometimes does not inherit.
if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

pushd app
call npm run tauri:build
if not %ERRORLEVEL%==0 (
    popd
    echo [ERROR] The app build failed. See the output above.
    goto fail
)
popd

echo.
echo Done. Start it with "Start TONYAgent (Prebuilt).bat".
echo.
pause
endlocal
exit /b 0

:fail
echo.
pause
exit /b 1