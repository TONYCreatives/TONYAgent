@echo off
REM ==========================================================================
REM  TONYAgent (prebuilt) launcher
REM
REM  Starts the built app. If the build is behind the source, it rebuilds
REM  first -- only the stages whose inputs changed -- and then starts it.
REM
REM  Use the two launchers for two different jobs:
REM
REM    Start TONYAgent (Prebuilt).bat   start what is built, rebuilding if it
REM                                     is behind. Everyday use.
REM    Start TONYAgent (Tauri).bat      rebuild everything from source, then run
REM
REM  Rebuilding is not a question. This file used to ask, and the default was
REM  No, so a double-click on a console that flashed and closed without the
REM  application ever appearing read as "the app starts and quits immediately"
REM  -- a crash report where nothing had crashed. It then stopped asking and
REM  merely warned, which was better and still wrong: the warning scrolls past
REM  while you are looking for the thing you just fixed.
REM
REM  A launcher that silently runs last week's binary is the failure worth
REM  guarding against, and warning about it is that same failure with extra
REM  steps. So the answer to "the build is behind" is to build, not to say so.
REM ==========================================================================
setlocal

cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

set "APP=app\src-tauri\target\release\tonyagent-app.exe"

REM --- what needs building? -------------------------------------------------
REM
REM The same question "Build TONYAgent.bat" asks, asked with the same script,
REM so the launcher cannot disagree with the builder about what is stale. The
REM answer is one stage name per line, and nothing at all when everything is
REM current -- so `if not defined` is the whole test.
REM
REM It lives in scripts\build_state.ps1 rather than inline here because the
REM batch parser counts parentheses even inside a backquoted command: a
REM brace-closed block like `if($x){ $x }` leaves it hunting for a closing
REM paren that is not there, and the file dies with "was unexpected at this
REM time" before the app is ever started. A script file has no such rule.
REM That was not a crash either; it was a launcher that flashed and closed.
set "STAGES="
for /f "usebackq delims=" %%S in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\build_state.ps1"`) do set "STAGES=%%S"

if not defined STAGES goto launch

echo Starting TONYAgent (prebuilt)...
echo.
echo The build is behind the source. Rebuilding what changed...
echo The Python core is re-frozen from scratch, so this can take a few minutes.
echo.

REM /q because this launcher has a window of its own to close: the pauses in
REM the build script are for someone who double-clicked it and needs to read
REM the output before it goes away.

REM The full path, not a quoted relative one. `call "Build TONYAgent.bat"`
REM does not find it: cmd reads a quoted first argument as something other
REM than a command to search for, and answers "is not recognized as an
REM internal or external command". Unquoted fails too, because the name has
REM a space in it. So the rebuild silently did not happen and the launcher
REM started the old build, which is the exact bug this file exists to fix.
call "%~dp0Build TONYAgent.bat" /q
if not "%ERRORLEVEL%"=="0" goto build_failed
goto launch

REM The old binary is deliberately still there. Losing the ability to run the
REM app at all is a worse outcome than running a build that is behind the
REM source, and the build script has already said so on its way out.
:build_failed
set "PREVIOUS=1"
echo.
echo [WARN] The rebuild failed, so what starts below is the previous build.
echo.
goto launch

:launch
if not exist "%APP%" goto no_build
start "" "%APP%"
if defined PREVIOUS goto launched_previous
echo Started. This window can be closed.
endlocal
exit /b 0

:launched_previous
echo Started the previous build, which is behind the source. This window
echo can be closed.
endlocal
exit /b 0

:no_build
echo.
echo [ERROR] There is nothing to start: %APP% does not exist and the rebuild
echo         did not produce one. Fix the error above and try again.
echo.
pause
endlocal
exit /b 1