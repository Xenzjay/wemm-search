@echo off
setlocal
cd /d "%~dp0.."
echo.
echo [WeMM Search] First-time setup
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. Check the error above.
  pause
  exit /b 1
)
echo.
echo Setup complete.
pause
