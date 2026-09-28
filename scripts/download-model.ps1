$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "未找到虚拟环境，请先运行 .\scripts\setup.ps1"
}
$env:HF_HOME = Join-Path $ProjectRoot "models\huggingface"
$env:HF_HUB_CACHE = Join-Path $ProjectRoot "models\huggingface\hub"
New-Item -ItemType Directory -Force -Path $env:HF_HUB_CACHE | Out-Null
& $Python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='tencent/WeMM-Embedding-2B', cache_dir=r'$env:HF_HUB_CACHE', local_dir=r'$ProjectRoot\models\WeMM-Embedding-2B')"
if ($LASTEXITCODE -ne 0) { throw "模型下载失败。" }
$configPath = Join-Path $ProjectRoot "config\config.json"
$config = Get-Content -Raw $configPath | ConvertFrom-Json
$config.model.path = Join-Path $ProjectRoot "models\WeMM-Embedding-2B"
$config.model.enabled = $true
$config | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $configPath
Write-Host "WeMM-Embedding-2B 已下载并启用。" -ForegroundColor Green

