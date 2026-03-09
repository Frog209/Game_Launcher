$ErrorActionPreference = "Stop"

Write-Host "Installing dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "Building portable launcher..."
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
python -m PyInstaller GameLauncher.spec --noconfirm

Write-Host "Creating zip archive..."
if (!(Test-Path "release")) { New-Item -ItemType Directory -Path "release" | Out-Null }
$zipPath = "release/GameLauncher-portable-windows.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path "dist/GameLauncher/*" -DestinationPath $zipPath

Write-Host "Done: $zipPath"
