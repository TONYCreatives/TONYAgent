@echo off
REM ==========================================================================
REM  TONYAgent launcher
REM  Double-click this file to start the app.
REM ==========================================================================
setlocal

REM Always run from this file's own directory, so double-clicking works
REM regardless of the current working directory.
cd /d "%~dp0"

REM This machine's console defaults to cp949, which mangles or crashes on
REM non-ASCII output (the theme button uses moon/sun glyphs).
set PYTHONIOENCODING=utf-8

echo Starting TONYAgent...
echo.

REM Prefer the python launcher, then py, then python.
where python >nul 2>&1
if %ERRORLEVEL%==0 goto run_python
where py >nul 2>&1
if %ERRORLEVEL%==0 goto run_py
where python3 >nul 2>&1
if %ERRORLEVEL%==0 goto run_python3

echo [ERROR] Python was not found on PATH.
echo         Install Python 3.11+ and tick "Add python.exe to PATH".
echo.
pause
exit /b 1

:run_python
python -m tonyagent %*
goto done

:run_py
py -3 -m tonyagent %*
goto done

:run_python3
python3 -m tonyagent %*
goto done

:done
REM Only pause if the app exited abnormally, so a normal quit stays silent.
if %ERRORLEVEL%==0 goto end
echo.
echo [EXIT] TONYAgent stopped with code %ERRORLEVEL%.
pause

:end
endlocal
