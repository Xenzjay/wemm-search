$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PidFile = Join-Path $ProjectRoot "data\service.pid"
$LogFile = Join-Path $ProjectRoot "logs\service.out.log"
$ErrorFile = Join-Path $ProjectRoot "logs\service.err.log"
$Port = 8876
$Url = "http://127.0.0.1:$Port"

if (-not (Test-Path $VenvPython)) {
    throw "未找到虚拟环境，请先运行 .\scripts\setup.ps1"
}
if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
        Write-Host "服务已经运行，PID=$oldPid" -ForegroundColor Yellow
        Start-Process $Url
        exit 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

$process = Start-Process -FilePath $VenvPython -ArgumentList "-u", "app\main.py" -WorkingDirectory $ProjectRoot -RedirectStandardOutput $LogFile -RedirectStandardError $ErrorFile -PassThru -WindowStyle Hidden
$process.Id | Set-Content $PidFile
Start-Sleep -Milliseconds 800
if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
    throw "服务启动失败，请查看 logs\service.out.log"
}
$ready = $false
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    try {
        $response = Invoke-WebRequest "$Url/api/status" -UseBasicParsing -TimeoutSec 1
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    throw "服务进程已启动但 API 未就绪，请查看 logs\service.log 和 logs\service.err.log"
}
Write-Host "WeMM Search 已启动，PID=$($process.Id)" -ForegroundColor Green
Write-Host "管理页面：$Url"
Start-Process $Url
