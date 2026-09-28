@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
  echo Usage: backup.bat "backup-folder"
  echo Example: backup.bat "E:\Backups\wemm-search"
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup.ps1" "%~1"
echo.
pause
