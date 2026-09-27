param(
    [string]$Version = "1.1.1"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseName = "DF-Redeem-v$Version-windows-x64"
$ReleaseDirectory = Join-Path $ProjectRoot "dist\$ReleaseName"
$DataDirectory = Join-Path $ReleaseDirectory "data"
$ArchivePath = Join-Path $ProjectRoot "dist\$ReleaseName.zip"
$VirtualEnvironmentPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VirtualEnvironmentPython) {
    $VirtualEnvironmentPython
}
else {
    "py"
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name "DF-Redeem" `
        "main.py"

    if (Test-Path $ReleaseDirectory) {
        Remove-Item $ReleaseDirectory -Recurse -Force
    }
    if (Test-Path $ArchivePath) {
        Remove-Item $ArchivePath -Force
    }

    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    Copy-Item "dist\DF-Redeem.exe" $ReleaseDirectory
    Copy-Item "data\*.example.txt" $DataDirectory
    Copy-Item "README.md" $ReleaseDirectory
    Compress-Archive -Path "$ReleaseDirectory\*" -DestinationPath $ArchivePath

    Write-Host "Đã tạo bản phát hành: $ArchivePath"
}
finally {
    Pop-Location
}
