$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "data\service.pid"
$Url = "http://127.0.0.1:8876"
if (Test-Path $PidFile) {
    $pidValue = Get-Content $PidFile -ErrorAction SilentlyContinue
    $process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "运行中：PID=$pidValue，管理页面 $Url" -ForegroundColor Green
        try { Invoke-RestMethod "$Url/api/status" | ConvertTo-Json -Depth 6 } catch { Write-Warning "服务尚未响应。" }
        exit 0
    }
}
Write-Host "未运行。" -ForegroundColor Yellow
