$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

Write-Host "WeMM Search setup: $ProjectRoot" -ForegroundColor Cyan
foreach ($dir in @("config", "data", "cache", "logs", "models")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot $dir) | Out-Null
}

if (-not (Test-Path $Python)) {
    py -3.12 -m venv $Venv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
& $Python -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

$config = Join-Path $ProjectRoot "config\config.json"
if (-not (Test-Path $config)) {
    Copy-Item (Join-Path $ProjectRoot "config\config.json") $config
}

try {
    if (-not (Get-NetFirewallRule -DisplayName "WeMM Search 8876" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "WeMM Search 8876" -Direction Inbound -Protocol TCP -LocalPort 8876 -Action Allow -Profile Private | Out-Null
    }
} catch {
    Write-Warning "未能自动创建防火墙规则，请以管理员 PowerShell 手动放行 TCP 8876。"
}

$desktop = [Environment]::GetFolderPath("Desktop")
function New-Shortcut($name, $target) {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $desktop "$name.lnk"))
        $shortcut.TargetPath = $target
        $shortcut.Arguments = ""
        $shortcut.WorkingDirectory = $ProjectRoot
        $shortcut.Save()
    } catch {
        Write-Warning "无法创建桌面快捷方式 $name：$($_.Exception.Message)"
    }
}
New-Shortcut "WeMM Search 启动" (Join-Path $PSScriptRoot "start.bat")
New-Shortcut "WeMM Search 停止" (Join-Path $PSScriptRoot "stop.bat")
New-Shortcut "WeMM Search 状态" (Join-Path $PSScriptRoot "status.bat")

Write-Host ""
Write-Host "安装完成。下一步双击 scripts\start.bat" -ForegroundColor Green
