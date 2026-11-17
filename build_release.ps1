# Build the Windows release zip (PyInstaller onedir).
# Usage: powershell -ExecutionPolicy Bypass -File build_release.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

$m = Select-String -Path (Join-Path $Root 'eye_protect.py') `
                   -Pattern '^__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $m) { throw 'Cannot read __version__ from eye_protect.py' }
$Version = $m.Matches[0].Groups[1].Value
Write-Host "Building EyeProtect $Version"

foreach ($d in @('build', 'dist')) {
    if (Test-Path $d) { Remove-Item $d -Recurse -Force }
}

$pyArgs = @('--noconfirm', '--clean', '--onedir', '--console', '--name', 'EyeProtect')
foreach ($h in @('install_service', 'uninstall_service', 'restart_service', 'procutil',
                 'updater', 'win32com.client')) {
    $pyArgs += @('--hidden-import', $h)
}
$pyArgs += 'eye_protect.py'

& pyinstaller @pyArgs
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed with exit code $LASTEXITCODE" }

$AppDir = Join-Path $Root 'dist\EyeProtect'
foreach ($f in @('config.example.json', 'LICENSE', 'NOTICE', 'README.md')) {
    Copy-Item (Join-Path $Root $f) $AppDir -Force
}
Get-ChildItem (Join-Path $Root 'dist_scripts') -Filter '*.bat' |
    Copy-Item -Destination $AppDir -Force

$Zip = Join-Path $Root "dist\eye-protect_${Version}_windows_amd64.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path $AppDir -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "Output: $Zip"
