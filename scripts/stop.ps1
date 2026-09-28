$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "data\service.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "Service is not running."
    exit 0
}

$pidValue = Get-Content $PidFile -ErrorAction SilentlyContinue
if ($pidValue) {
    $process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id ([int]$pidValue) -Force
        Write-Host "WeMM Search stopped. PID=$pidValue"
    } else {
        Write-Host "The process has already exited."
    }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
