$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $ProjectRoot "config\config.json"
$config = Get-Content -Raw $ConfigPath | ConvertFrom-Json
$target = if ($args.Count -gt 0) { $args[0] } elseif ($config.backup.path) { $config.backup.path } else { "" }
if (-not $target) {
    throw "请提供备份目录，例如 .\scripts\backup.ps1 'E:\Backups\wemm-search'"
}

$targetPath = [System.IO.Path]::GetFullPath($target)
New-Item -ItemType Directory -Force -Path $targetPath | Out-Null
foreach ($relative in @("config", "data", "logs")) {
    $source = Join-Path $ProjectRoot $relative
    if (Test-Path $source) {
        Copy-Item -Recurse -Force $source (Join-Path $targetPath $relative)
    }
}
Write-Host "备份完成：$targetPath" -ForegroundColor Green
