[CmdletBinding()]
param(
    [string]$DistPath,
    [string]$WorkPath
)

$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$buildRequirements = Join-Path $projectRoot "requirements-build-5.7.0.txt"
if ([string]::IsNullOrWhiteSpace($DistPath)) {
    $DistPath = Join-Path $projectRoot "dist\5.7.0"
}
if ([string]::IsNullOrWhiteSpace($WorkPath)) {
    $WorkPath = Join-Path $projectRoot "build\pyinstaller-5.7.0"
}
$DistPath = [IO.Path]::GetFullPath($DistPath)
$WorkPath = [IO.Path]::GetFullPath($WorkPath)

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $projectRoot ".venv")
}

& $venvPython -m pip install --disable-pip-version-check -r $buildRequirements

Push-Location $projectRoot
try {
    & $venvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name "Rat-Trap" `
        --paths $projectRoot `
        --collect-all pyfastcdc `
        --hidden-import zstandard `
        --icon (Join-Path $projectRoot "packaging\branding\rat-trap.ico") `
        --version-file (Join-Path $projectRoot "packaging\windows_version_info.txt") `
        --distpath $DistPath `
        --workpath $WorkPath `
        --specpath (Join-Path $projectRoot "build") `
        (Join-Path $projectRoot "windows_main.py")
}
finally {
    Pop-Location
}

Write-Host "Built: $(Join-Path $DistPath 'Rat-Trap.exe')"
