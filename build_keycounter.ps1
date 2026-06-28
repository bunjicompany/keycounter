$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$distDir = Join-Path $projectRoot "dist"
$packageRoot = Join-Path $projectRoot ("release-package\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$packageAppDir = Join-Path $packageRoot "KeyCounter"
$zipPath = Join-Path $distDir "KeyCounter.zip"

$python = "python"
if (Test-Path "$projectRoot\.venv\Scripts\python.exe") {
  $python = "$projectRoot\.venv\Scripts\python.exe"
}

& $python -m pip install -r "$projectRoot\requirements.txt"

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null

$buildTime = Get-Date -Format "yyyyMMdd-HHmmss"
$buildInfo = [ordered]@{
  version = $buildTime
  built_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
}
$buildInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot "build_info.json") -Encoding UTF8

& $python -m PyInstaller --clean --noconfirm --distpath $packageRoot "$projectRoot\KeyCounter.spec"

Compress-Archive -LiteralPath $packageAppDir -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Built package: $packageAppDir\KeyCounter.exe"
Write-Host "ZIP:   $zipPath"
