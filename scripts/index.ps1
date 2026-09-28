$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$status = Join-Path $ProjectRoot "scripts\status.ps1"
if (-not (Test-Path (Join-Path $ProjectRoot "data\service.pid"))) {
    & (Join-Path $ProjectRoot "scripts\start.ps1")
}
$mode = if ($args -contains "--initial") { "initial" } else { "incremental" }
Invoke-RestMethod -Uri "http://127.0.0.1:8876/api/index" -Method Post -ContentType "application/json" -Body (@{ mode = $mode } | ConvertTo-Json)
Write-Host "已提交 $mode 索引任务。打开管理页面查看进度。" -ForegroundColor Green
