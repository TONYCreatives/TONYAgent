@echo off
REM ==========================================================================
REM  TONYAgent launcher
REM
REM  Starts TONYAgent. Two frontends, one file:
REM
REM      Start TONYAgent (Prebuilt).bat           the terminal UI   (default)
REM      Start TONYAgent (Prebuilt).bat window    the desktop app
REM
REM  The desktop shortcut runs this with no arguments, so double-clicking it
REM  opens the terminal UI.
REM
REM  There used to be two launchers, and the difference between them was which
REM  of three build stages each was willing to skip. There is one stage now --
REM  see scripts\build_state.ps1 -- so "rebuild everything" and "rebuild what
REM  changed" are the same instruction, and a second file would only be a second
REM  thing to keep in step. "Start TONYAgent (Tauri).bat" went with the Rust it
REM  was named after.
REM
REM  Rebuilding is not a question. This file used to ask, and the default was
REM  No, so a double-click on a console that flashed and closed without the
REM  application ever appearing read as "the app starts and quits immediately"
REM  -- a crash report where nothing had crashed. It then stopped asking and
REM  merely warned, which was better and still wrong: the warning scrolls past
REM  while you are looking for the thing you just fixed.
REM
REM  A launcher that silently runs last week's bundle is the failure worth
REM  guarding against, and warning about it is that same failure with extra
REM  steps. So the answer to "the build is behind" is to build, not to say so.
REM
REM  Those two frontends are not a split by build stage, which is why they did
REM  not become two files. They differ in something a build cannot express: the
REM  desktop app needs a frontend bundle and a GUI toolkit, and the terminal UI
REM  needs neither -- it is pure Python from the checkout, so there is nothing to
REM  rebuild and nothing to be behind. Only the window path asks. The terminal
REM  path starts in about a second instead of after a build.
REM ==========================================================================
setlocal

cd /d "%~dp0"
REM Both, not just the first. `PYTHONIOENCODING` covers stdout and stderr;
REM `PYTHONUTF8` puts the interpreter itself in UTF-8 mode, which is what the
REM files on disk are read with. The interface draws box rules and a middle dot,
REM so a console on a legacy code page does not just look wrong -- it raises.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM The host imports `tonyagent`, which lives in src/. Set here rather than
REM relying on an editable install: a fresh clone has no .pth file, and the
REM failure mode is an ImportError in a console that is about to close.
set "PYTHONPATH=%~dp0src"

if /i not "%~1"=="window" goto tui

REM --- what needs building? -------------------------------------------------
REM
REM The same question "Build TONYAgent.bat" asks, asked with the same script, so
REM the launcher cannot disagree with the builder about what is stale. The answer
REM is one stage name per line, and nothing at all when everything is current --
REM so `if not defined` is the whole test.
REM
REM It lives in scripts\build_state.ps1 rather than inline here because the batch
REM parser counts parentheses even inside a backquoted command: a brace-closed
REM block like `if($x){ $x }` leaves it hunting for a closing paren that is not
REM there, and the file dies with "was unexpected at this time" before the app is
REM ever started. A script file has no such rule. That was not a crash either; it
REM was a launcher that flashed and closed.
set "STAGES="
for /f "usebackq delims=" %%S in (`powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\build_state.ps1"`) do set "STAGES=%%S"

if "%STAGES%"=="" goto launch

echo The frontend is behind the source. Rebuilding it...
echo.

REM /q because this launcher has a window of its own to close: the pause in the
REM build script is for someone who double-clicked it and needs to read the
REM output before it goes away.
REM
REM The full path, not a quoted relative one. `call "Build TONYAgent.bat"` does
REM not find it: cmd reads a quoted first argument as something other than a
REM command to search for, and answers "is not recognized as an internal or
REM external command". Unquoted fails too, because the name has a space in it. So
REM the rebuild silently did not happen and the launcher started the old build,
REM which is the exact bug this file exists to fix.
call "%~dp0Build TONYAgent.bat" /q
if not "%ERRORLEVEL%"=="0" goto build_failed
goto launch

REM The old bundle is deliberately still there. Losing the ability to run the app
REM at all is a worse outcome than running a build that is behind the source, and
REM the build script has already said so on its way out.
:build_failed
set "PREVIOUS=1"
echo.
echo [WARN] The rebuild failed, so what opens below is the previous build.
echo.
goto launch

REM --- launch ---------------------------------------------------------------
REM Two checks before detaching, because the app is started with `start` and a
REM failure after that point goes to a console nobody is looking at. These are
REM the two failures that actually happen, and both are one line to fix.
:launch
if not exist "app\dist\index.html" goto no_frontend

python -c "import webview" >nul 2>&1
if not "%ERRORLEVEL%"=="0" goto no_pywebview

echo Starting TONYAgent...
echo.
REM `start ""` and not a bare call: the window is its own process, so this
REM console can be closed immediately. A bare call would block here, and closing
REM the console would then take the app down with it -- a launcher that kills the
REM thing it launched.
REM
REM `pythonw` rather than `python`, and that is the difference between one window
REM and two. `python` is a console-subsystem program, so `start` gives it a *new
REM console* -- measured, not assumed: the app owned a visible
REM `PseudoConsoleWindow` beside its own form for its whole life. `pythonw` is
REM the same interpreter with no console at all, which is what an app opened from
REM a shortcut should look like. The host notices and writes its own log to a
REM file instead -- see `_log_without_a_console` in host.py.
start "" pythonw -m tonyagent.window

if defined PREVIOUS echo [WARN] This is the previous build, because the rebuild failed.
echo Started. This window can be closed.
endlocal
exit /b 0

:no_frontend
echo.
echo [ERROR] There is no built frontend, so there is nothing to put in the window.
echo         Run "Build TONYAgent.bat", then try again.
echo.
pause
endlocal
exit /b 1

:no_pywebview
echo.
echo [ERROR] The window library is not installed.
echo         Run:  pip install pywebview
echo.
pause
endlocal
exit /b 1

REM --- the terminal UI ------------------------------------------------------
REM
REM Reached by `goto` from the top, so everything above this line is the window
REM path and every one of its exits has already returned.
:tui
where python >nul 2>&1
if not "%ERRORLEVEL%"=="0" goto no_python

REM Checked rather than left to fail. `--tui` below asks for the full-screen
REM interface by name, and `main()` treats not getting it as an error rather
REM than quietly falling back to the line REPL -- which is right for a flag and
REM wrong for a desktop shortcut, where the difference between "it started" and
REM "it started as something else" is a window you did not ask for.
python -c "import textual" >nul 2>&1
if not "%ERRORLEVEL%"=="0" goto no_terminal_extra

echo Starting TONYAgent in this window. Close it, or press Ctrl-P for the palette.
echo.
REM No `start`, and that is the whole difference between the two frontends in
REM one line. `start ""` hands the program a *new* console and returns at once,
REM which is right for a GUI app that detaches and for nothing else: a
REM full-screen interface draws into the console it is attached to, so starting
REM one here opened a second window and closed this one -- taking the interface
REM down with it before it had drawn a frame.
python -m tonyagent.cli --tui
set "RC=%ERRORLEVEL%"

REM The window path ends here and closes. This one must not. `pause` is not
REM politeness: it is the only thing between an exception and a console that
REM flashes and vanishes, which reads as a crash where nothing crashed -- the
REM exact failure the header of this file is about. The code is printed first
REM because the pause eats the scrollback on some consoles.
echo.
if "%RC%"=="0" (echo TONYAgent closed normally.) else (echo TONYAgent exited with code %RC%.)
echo Press any key to close this window.
pause >nul
endlocal
exit /b %RC%

:no_python
echo.
echo [ERROR] Python is not on PATH, so there is nothing to run TONYAgent with.
echo.
pause
endlocal
exit /b 1

:no_terminal_extra
echo.
echo [ERROR] The terminal interface needs Textual, which is not installed:
echo         Run:  pip install -e ".[terminal]"
echo.
pause
endlocal
exit /b 1
