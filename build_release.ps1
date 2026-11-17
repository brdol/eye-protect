# Build the Windows release zip using the official embeddable Python.
# No custom exe is produced: users run the signed pythonw.exe from python.org.
# Usage: powershell -ExecutionPolicy Bypass -File build_release.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

$m = Select-String -Path (Join-Path $Root 'eye_protect.py') `
                   -Pattern '^__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $m) { throw 'Cannot read __version__ from eye_protect.py' }
$Version = $m.Matches[0].Groups[1].Value

$PyVersion = '3.12.10'
Write-Host "Building EyeProtect $Version with embedded Python $PyVersion"

function Invoke-Download([string]$Uri, [string]$OutFile, [int]$Tries = 5) {
    for ($i = 1; $i -le $Tries; $i++) {
        try {
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -TimeoutSec 180
            return
        } catch {
            if ($i -eq $Tries) { throw }
            Write-Warning "Download failed (attempt $i/$Tries): $($_.Exception.Message)"
            Start-Sleep -Seconds 3
        }
    }
}

foreach ($d in @('build', 'dist')) {
    if (Test-Path $d) { Remove-Item $d -Recurse -Force }
}

$AppDir = Join-Path $Root 'dist\EyeProtect'
$PyDir = Join-Path $AppDir 'python'
New-Item -ItemType Directory -Force -Path $PyDir | Out-Null

# 1. Official embeddable Python (signed by the Python Software Foundation)
$EmbedUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
$EmbedZip = Join-Path $Root 'python-embed.zip'
Write-Host "Downloading $EmbedUrl"
Invoke-Download $EmbedUrl $EmbedZip
Expand-Archive -Path $EmbedZip -DestinationPath $PyDir -Force
Remove-Item $EmbedZip -Force

$PyExe = Join-Path $PyDir 'python.exe'

# 2. Enable site-packages in the embeddable runtime
$pth = Get-ChildItem $PyDir -Filter 'python*._pth' | Select-Object -First 1
if ($pth) {
    $text = Get-Content $pth.FullName -Raw
    if ($text -notmatch 'Lib\\site-packages') { Add-Content $pth.FullName 'Lib\site-packages' }
    if ($text -notmatch '(?m)^import site') { Add-Content $pth.FullName 'import site' }
}
New-Item -ItemType Directory -Force -Path (Join-Path $PyDir 'Lib\site-packages') | Out-Null

# 3. Install pywin32 into the bundled runtime
$GetPip = Join-Path $Root 'get-pip.py'
Invoke-Download 'https://bootstrap.pypa.io/get-pip.py' $GetPip
& $PyExe $GetPip
if ($LASTEXITCODE -ne 0) { throw "get-pip failed: $LASTEXITCODE" }
& $PyExe -m pip install --no-warn-script-location --retries 5 --timeout 120 pywin32
if ($LASTEXITCODE -ne 0) { throw "pip install pywin32 failed: $LASTEXITCODE" }
Remove-Item $GetPip -Force

# 4. Make the pywin32 DLLs discoverable next to python.exe
$SitePackages = Join-Path $PyDir 'Lib\site-packages'
$Sys32 = Join-Path $SitePackages 'pywin32_system32'
if (Test-Path $Sys32) {
    Copy-Item (Join-Path $Sys32 '*.dll') $PyDir -Force
}

# 5. Slim the package: pip and unused pywin32 components are not needed at runtime
try { & $PyExe -m pip uninstall -y pip | Out-Null } catch { }
foreach ($p in @('pythonwin', 'PyWin32.chm', 'adodbapi', 'isapi')) {
    $target = Join-Path $SitePackages $p
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
}

# 6. Application files (source is shipped as-is; the project is Apache-2.0)
foreach ($f in @('eye_protect.py', 'install_service.py', 'uninstall_service.py',
                 'restart_service.py', 'procutil.py', 'updater.py',
                 'config.example.json', 'LICENSE', 'NOTICE', 'README.md')) {
    Copy-Item (Join-Path $Root $f) $AppDir -Force
}
Get-ChildItem (Join-Path $Root 'dist_scripts') -Filter '*.bat' |
    Copy-Item -Destination $AppDir -Force

# 7. Sanity checks with the bundled interpreter
& $PyExe -c "import win32api, win32gui, win32ts, win32com.client; print('pywin32 ok')"
if ($LASTEXITCODE -ne 0) { throw 'pywin32 import check failed' }

Push-Location $AppDir
try {
    # embeddable Python 是隔离模式，PYTHONPATH 不生效，需在代码里插入路径
    & $PyExe -c "import sys; sys.path.insert(0, r'$AppDir'); import install_service, uninstall_service, restart_service, procutil, updater; print('app modules ok')"
    if ($LASTEXITCODE -ne 0) { throw 'app module import check failed' }
    & $PyExe 'eye_protect.py' --version
    if ($LASTEXITCODE -ne 0) { throw 'app --version check failed' }
} finally {
    Pop-Location
}

$Zip = Join-Path $Root "dist\eye-protect_${Version}_windows_amd64.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path $AppDir -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "Output: $Zip"
