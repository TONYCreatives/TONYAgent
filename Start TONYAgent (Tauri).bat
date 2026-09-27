@echo off
REM ==========================================================================
REM  TONYAgent (Tauri) launcher
REM
REM  Double-click to start the Tauri + React UI. For the older Tkinter UI,
REM  use "Start TONYAgent.bat" instead -- that one is unchanged.
REM
REM  The Tauri app is three moving parts, and any of them missing produces a
REM  window that opens and then says "disconnected" with no other symptom:
REM
REM    1. a frontend        (app/, built by Vite)
REM    2. a Rust shell      (app/src-tauri, built by cargo)
REM    3. a Python sidecar  (the frozen core, built by PyInstaller)
REM
REM  So this script checks all three before launching, and builds the sidecar
REM  if it is absent. The sidecar is a ~45 MB build product and is gitignored;
REM  a fresh clone will not have one.
REM ==========================================================================
setlocal

REM Always run from this file's own directory, so double-clicking works
REM regardless of the current working directory.
cd /d "%~dp0"

REM This machine's console defaults to cp949, which mangles or crashes on
REM non-ASCII output.
set PYTHONIOENCODING=utf-8

echo Starting TONYAgent (Tauri)...
echo.

REM --- prerequisites ---------------------------------------------------------
REM Checked explicitly rather than letting each tool fail in turn: the
REM resulting errors ("'cargo' is not recognized") do not say which of the
REM three prerequisites is missing, and the sidecar build is slow enough that
REM discovering it late is annoying.

where python >nul 2>&1
if not %ERRORLEVEL%==0 goto no_python

where node >nul 2>&1
if not %ERRORLEVEL%==0 goto no_node

where npm >nul 2>&1
if not %ERRORLEVEL%==0 goto no_node

where cargo >nul 2>&1
if not %ERRORLEVEL%==0 goto try_cargo_path

goto have_tools

:no_python
echo [ERROR] Python was not found on PATH.
echo         Install Python 3.11+ and tick "Add python.exe to PATH".
goto fail

:no_node
echo [ERROR] Node.js / npm was not found on PATH.
echo         Install Node.js 18+ from https://nodejs.org
goto fail

REM rustup registers cargo in the USER path, which a process started from
REM Explorer sometimes does not inherit. Add the default location rather than
REM failing when the tool is in fact installed.
:try_cargo_path
if exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
    set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    goto have_tools
)
echo [ERROR] cargo was not found on PATH.
echo         Install Rust from https://rustup.rs, and the Visual C++ build
echo         tools -- Tauri links a native Windows binary and cannot build
echo         without them.
goto fail

:have_tools

REM --- sidecar ---------------------------------------------------------------
REM Matched by wildcard because the filename carries a target triple
REM (tonyagent-core-x86_64-pc-windows-msvc.exe) that differs per machine.
REM
REM This only checks for existence. If you change the Python core, delete the
REM exe and run this again -- there is no cheap way to detect staleness here.
if exist "app\src-tauri\binaries\tonyagent-core-*.exe" goto have_sidecar

echo [SETUP] Building the core sidecar (one time, about a minute)...
echo.
python scripts\build_sidecar.py
if not %ERRORLEVEL%==0 (
    echo.
    echo [ERROR] The sidecar build failed. See the output above.
    goto fail
)
echo.

:have_sidecar

REM --- launch ----------------------------------------------------------------
REM `tauri dev` rather than `tauri build`: it rebuilds the frontend on launch,
REM so this reflects the current source instead of a stale bundle. Note that
REM `vite build` on its own is NOT enough to see a change in the app -- the Rust
REM binary embeds dist/, so it has to go through tauri.
cd app
call npm run tauri:dev
set EXITCODE=%ERRORLEVEL%
cd ..

if %EXITCODE%==0 goto end

echo.
echo [EXIT] TONYAgent stopped with code %EXITCODE%.
goto fail

:fail
echo.
pause
exit /b 1

:end
endlocal
