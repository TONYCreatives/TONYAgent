@echo off
REM ==========================================================================
REM  TONYAgent installer build
REM
REM  One command from a checkout to build\installer\TONYAgent-<version>.msi:
REM
REM    1. npm run build        the frontend the window serves
REM    2. PyInstaller          host and core frozen into TONYAgent.exe
REM    3. WiX                  that directory packaged as an MSI
REM
REM  This is a wrapper around scripts\build_installer.ps1 and nothing else. The
REM  work, the checks and the reasons are there; this exists so the build is a
REM  double-click like the other one, and so the window does not vanish before
REM  the error can be read.
REM
REM  Arguments are passed straight through, so the fast paths work from here:
REM
REM    "Build Installer.bat" -SkipFrontend -SkipFreeze    repackage only
REM
REM  Prerequisites, both installed once:
REM
REM    python -m pip install pyinstaller
REM    dotnet tool install --global wix --version 5.0.2
REM
REM  **WiX 5, not 7.** WiX 7 refuses to run until you accept its Open Source
REM  Maintenance Fee EULA, which is a licensing decision and not a build step.
REM  WiX 5 is the same authoring schema and asks for nothing.
REM
REM  Keep this file's line endings CRLF. cmd.exe resolves goto labels by byte
REM  offset and an LF-only batch file loses them, which is the same trap the
REM  other build script records.
REM ==========================================================================
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_installer.ps1" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [ERROR] The installer build failed. See the message above.
    echo.
    pause
    exit /b %RC%
)

echo.
pause
exit /b 0
