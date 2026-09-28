@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo.
  echo Start failed. Check logs\service.log and logs\service.err.log.
  pause
  exit /b 1
)
echo.
echo Service started. Opening the browser.
timeout /t 2 /nobreak >nul
