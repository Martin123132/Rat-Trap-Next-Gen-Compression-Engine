$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$buildRequirements = Join-Path $projectRoot "requirements-build-5.1.0.txt"

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
        --hidden-import zstandard `
        --version-file (Join-Path $projectRoot "packaging\windows_version_info.txt") `
        --distpath (Join-Path $projectRoot "dist") `
        --workpath (Join-Path $projectRoot "build\pyinstaller") `
        --specpath (Join-Path $projectRoot "build") `
        (Join-Path $projectRoot "windows_main.py")
}
finally {
    Pop-Location
}

Write-Host "Built: $(Join-Path $projectRoot 'dist\Rat-Trap.exe')"
