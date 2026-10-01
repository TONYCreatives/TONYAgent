@echo off
REM ==========================================================================
REM  TONYAgent build-once script
REM
REM  Produces the release binary that "Start TONYAgent (Prebuilt).bat" runs.
REM
REM  Three stages, each producing something the next one needs:
REM
REM    1. app/dist      the React bundle. `vite build` alone is not enough to
REM                     see a change in the app -- the Rust binary embeds
REM                     dist/, so it has to go through tauri in stage 3.
REM    2. the sidecar   the frozen Python core (~45 MB), which Tauri spawns.
REM    3. the app       the Rust shell with dist/ and the sidecar baked in.
REM
REM  Only the stale stages run. Nothing in the chain is incremental -- PyInstaller
REM  re-freezes the whole of Python every time -- so a one-character edit to a
REM  React file used to cost the same as a rewrite of the core. scripts
REM  \build_state.ps1 answers "is this stage's output older than its inputs" and
REM  this script runs only the stages that fail it, printing which those are so
REM  a skip is visible rather than a guess.
REM
REM  A failing stage leaves the existing binary alone. That is the point: if the
REM  build breaks, there is still a build to run, and "the build is broken" is
REM  a completely different afternoon from "there is nothing to launch".

REM  Keep this file's line endings CRLF. cmd.exe resolves goto labels by byte
REM  offset and an LF-only batch file loses them: the symptom is "The system
REM  cannot find the batch label specified" for a stage that ran minutes ago.
REM ==========================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

REM rustup registers cargo in the USER path, which a process started from
REM Explorer sometimes does not inherit.
if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

REM RC.EXE, for the same reason and with more force: tauri-winres panics
REM without it. It lives in the Windows SDK, which nothing here has ever been
REM told about -- MSVC's environment is set by a developer command prompt, and
REM this is a double-click. The failure reads as a broken build rather than a
REM missing PATH, because the panic names the file and not the reason.
REM
REM The helper prints the path instead of setting it: a child process cannot
REM change its parent's environment, so a script that prepends to PATH and
REM exits succeeds and achieves nothing.
REM
REM RC is set as well as PATH, and that redundancy is the point. Left to search
REM PATH for itself, the resource compiler was found on some runs and not on
REM others -- including runs where `where rc.exe` had answered a moment
REM earlier in the same shell. Naming the file takes the search out of it.
set "RC="
for /f "usebackq delims=" %%R in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\find_windows_sdk.ps1"`) do set "RC=%%R"
if not defined RC goto no_sdk
for %%D in ("%RC%") do set "PATH=%%~dpD;%PATH%"

set "STAGES="
for /f "usebackq delims=" %%S in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\build_state.ps1"`) do set "STAGES=!STAGES! %%S"
REM One space, not nothing: the "is there anything to do" test below compares
REM against a single space, and an empty string would quietly skip it.
if not defined STAGES set "STAGES= "

REM ---------------------------------------------------------------- need one?
REM The stage list is read with ! not % on every line that uses it. % is
REM substituted when a line is parsed, and the line right after a `for /f` can
REM be parsed before the loop has filled the variable in -- which is how this
REM printed an empty "Building:" line and then, three lines later, dispatched
REM on a list that was not empty at all.
echo.
echo Checking what needs building...
echo.
if "!STAGES!"==" " goto up_to_date

echo Building:!STAGES!
echo.
if "!STAGES:frontend=!"=="!STAGES!" goto no_frontend
goto build_frontend

:no_frontend
if "!STAGES:sidecar=!"=="!STAGES!" goto no_sidecar
goto build_sidecar

:no_sidecar
if "!STAGES:app=!"=="!STAGES!" goto up_to_date
goto build_app

REM --------------------------------------------------------------- stage one
:build_frontend
echo [1/3] Building the frontend...
echo.
pushd app
call npm run build
set "BUILD_RC=%ERRORLEVEL%"
popd
if not "%BUILD_RC%"=="0" goto fail
if not "!STAGES!"=="!STAGES:sidecar=!" goto build_sidecar
if not "!STAGES!"=="!STAGES:app=!" goto build_app
goto done

REM --------------------------------------------------------------- stage two
:build_sidecar
echo [2/3] Building the Python core sidecar. This one freezes all of Python
echo      into a single executable, so it is the slow one when it runs.
echo.
python scripts\build_sidecar.py
if not "%ERRORLEVEL%"=="0" goto fail
if not "!STAGES!"=="!STAGES:app=!" goto build_app
goto done

REM ------------------------------------------------------------- stage three
:build_app
echo [3/3] Building the app shell...
echo.
REM Already established above; checked again here because it costs nothing and
REM this is the one stage that cannot work without it.
if not exist "%RC%" goto no_sdk
pushd app
call npm run tauri:build
set "BUILD_RC=%ERRORLEVEL%"
popd
if not "%BUILD_RC%"=="0" goto fail
goto done

REM ----------------------------------------------------------------- verify
:up_to_date
echo Everything is up to date. Nothing to build.
echo.
goto verify

:done
echo.
echo Build finished.
echo.

:verify
if not exist "app\src-tauri\target\release\tonyagent-app.exe" goto fail
echo Start it with "Start TONYAgent (Prebuilt).bat".
echo.
pause
endlocal
exit /b 0

REM ------------------------------------------------------- missing SDK
:no_sdk
echo.
echo [ERROR] rc.exe could not be found, so the app shell cannot be built.
echo        It ships with the Windows SDK, which this machine does not
echo        appear to have, or has only part of. Install "Windows SDK for
echo        Desktop C++" from the Visual Studio Installer, or build from a
echo        Developer Command Prompt where the SDK is already on PATH.
echo.
echo        The frontend and the Python sidecar do not need it.
echo.
pause
endlocal
exit /b 1

:fail
echo.
echo [ERROR] The build failed. See the output above.
echo.
if exist "app\src-tauri\target\release\tonyagent-app.exe" (
    echo         The previous build is still in place, so an earlier version of
    echo         the app still runs. Nothing has been overwritten.
    echo.
) else (
    echo         There is no previous build, so there is nothing to run yet.
    echo         Fix the error above and run this again.
    echo.
)
pause
endlocal
exit /b 1
