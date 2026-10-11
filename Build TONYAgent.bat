@echo off
REM ==========================================================================
REM  TONYAgent build-once script
REM
REM  Produces app\dist\, which is what the window reads when it opens.
REM
REM  One stage, because there is one build step left:
REM
REM    app/dist   the React bundle, by Vite.
REM
REM  There used to be three -- the bundle, a frozen Python core, and a Rust shell
REM  that embedded both -- and most of this file existed to explain why the third
REM  one was not optional. It is gone. `python -m tonyagent.window` reads
REM  app/dist/ at runtime, so a `vite build` is now the whole build: no cargo, no
REM  PyInstaller, no `rc.exe`, no Windows SDK, and nothing that takes minutes.
REM
REM  Only the stale stage runs. scripts\build_state.ps1 answers "is this stage's
REM  output older than its inputs" and this script runs the stages that fail it,
REM  printing which those are so a skip is visible rather than a guess.
REM
REM  A failing stage leaves the existing bundle alone. That is the point: if the
REM  build breaks, there is still a build to run, and "the build is broken" is a
REM  completely different afternoon from "there is nothing to launch".
REM
REM  Keep this file's line endings CRLF. cmd.exe resolves goto labels by byte
REM  offset and an LF-only batch file loses them: the symptom is "The system
REM  cannot find the batch label specified" for a stage that ran minutes ago.
REM ==========================================================================
setlocal enabledelayedexpansion

REM /q drops the pause, for callers that run this unattended -- the launcher,
REM which has a window of its own to close and no reader standing in front of it.
REM Everything else, including every message, is unchanged: a caller that
REM redirects output still sees it all.
set "QUIET="
if /i "%~1"=="/q" set "QUIET=1"

cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

REM ----------------------------------------------------------- prerequisites
where node >nul 2>&1
if not %ERRORLEVEL%==0 goto no_node
where npm >nul 2>&1
if not %ERRORLEVEL%==0 goto no_node

set "STAGES="
for /f "usebackq delims=" %%S in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\build_state.ps1"`) do set "STAGES=!STAGES! %%S"
REM One space, not nothing: the "is there anything to do" test below compares
REM against a single space, and an empty string would quietly skip it.
if not defined STAGES set "STAGES= "

echo.
echo Checking what needs building...
echo.
if "!STAGES!"==" " goto up_to_date

echo Building:!STAGES!
echo.
if "!STAGES:frontend=!"=="!STAGES!" goto up_to_date
goto build_frontend

REM ------------------------------------------------------------- the one stage
:build_frontend
echo [1/1] Building the frontend...
echo.
pushd app
call npm run build
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
if not exist "app\dist\index.html" goto fail
if not defined QUIET echo Start it with "Start TONYAgent (Prebuilt).bat".
goto finish_ok

REM ------------------------------------------------------- missing Node
:no_node
echo.
echo [ERROR] Node.js / npm was not found on PATH.
echo         Install Node.js 18+ from https://nodejs.org
echo.
goto fail_end

:fail
echo.
echo [ERROR] The build failed. See the output above.
echo.
if not exist "app\dist\index.html" goto no_previous
echo         The previous bundle is still in place, so an earlier version of
echo         the app still runs. Nothing has been overwritten.
goto fail_end

:no_previous
echo         There is no previous bundle, so there is nothing to run yet.
echo         Fix the error above and run this again.

:fail_end
if not defined QUIET pause
endlocal
exit /b 1

:finish_ok
if not defined QUIET pause
endlocal
exit /b 0
