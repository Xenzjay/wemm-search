@echo off
setlocal
cd /d "%~dp0.."
set "MODE="
if /i "%~1"=="--initial" set "MODE=--initial"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0index.ps1" %MODE%
if errorlevel 1 (
  echo.
  echo Index job submission failed.
  pause
  exit /b 1
)
echo.
echo Index job submitted. Check the web page for progress.
pause
