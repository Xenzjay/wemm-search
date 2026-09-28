@echo off
setlocal
cd /d "%~dp0.."
echo.
echo [WeMM Search] Downloading WeMM-Embedding-2B
echo The first download may take a while.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0download-model.ps1"
if errorlevel 1 (
  echo.
  echo Model download failed.
  pause
  exit /b 1
)
echo.
echo Model downloaded and enabled.
pause
