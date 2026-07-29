[CmdletBinding()]
param(
    [string]$EvidenceDir,
    [string]$ExecutablePath,
    [Parameter(Mandatory = $true)]
    [string]$DestinationDir
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
    $thinRoot = (Get-Item -LiteralPath $repoRoot).Parent.Parent.FullName
    $EvidenceDir = Join-Path $thinRoot "outputs"
}
if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
    $ExecutablePath = Join-Path $repoRoot "dist\5.2.0\Rat-Trap.exe"
}

$version = "5.2.0"
$releaseName = "Rat-Trap-Windows-$version"
$destination = [IO.Path]::GetFullPath($DestinationDir)
$ExecutablePath = [IO.Path]::GetFullPath($ExecutablePath)
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
[IO.Directory]::CreateDirectory($destination) | Out-Null
$zipPath = Join-Path $destination "$releaseName.zip"
if (Test-Path -LiteralPath $zipPath) {
    throw "Refusing to overwrite existing release: $zipPath"
}
if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Required release executable is missing: $ExecutablePath"
}
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "Pinned release environment is missing: $venvPython"
}

$versionInfo = (Get-Item -LiteralPath $ExecutablePath).VersionInfo
if (
    $versionInfo.FileVersion -ne $version -or
    $versionInfo.ProductVersion -ne $version
) {
    throw "Executable version mismatch. Expected $version, got FileVersion '$($versionInfo.FileVersion)' and ProductVersion '$($versionInfo.ProductVersion)'."
}
$pythonVersion = (& $venvPython -c "import platform; print(platform.python_version())").Trim()
if ($pythonVersion -ne "3.13.13") {
    throw "Pinned Python version mismatch. Expected 3.13.13, got '$pythonVersion'."
}
$pythonBase = (& $venvPython -c "import sys; print(sys.base_prefix)").Trim()

$stageRoot = Join-Path $destination (".rat-trap-stage-" + [guid]::NewGuid().ToString("N"))
$releaseFolder = Join-Path $stageRoot $releaseName
[IO.Directory]::CreateDirectory($releaseFolder) | Out-Null

function Copy-RequiredFile {
    param(
        [string]$Source,
        [string]$TargetFolder
    )
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required release input is missing: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $TargetFolder
}

function Copy-RequiredFileAs {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required release input is missing: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Destination
}

try {
    $repositoryFiles = @(
        "BENCHMARK-AUDIT.md",
        "COMMERCIAL-LICENSE.md",
        "LICENSE.md",
        "NOTICE.md",
        "README-WINDOWS.txt",
        "THIRD-PARTY-NOTICES.md",
        "VAULT-README.md"
    )
    foreach ($name in $repositoryFiles) {
        Copy-RequiredFile (Join-Path $repoRoot $name) $releaseFolder
    }
    $technicalFiles = @(
        "COMPATIBILITY-GATE.md",
        "GMW-FORMAT-REGISTRY.md",
        "REPOSITORY-FORMAT.md",
        "REPOSITORY-GATE-5.2.0.md"
    )
    foreach ($name in $technicalFiles) {
        Copy-RequiredFile (Join-Path $repoRoot "docs\$name") $releaseFolder
    }

    $evidenceFiles = @(
        "Rat-Trap-Beta-4.4-final.json",
        "Rat-Trap-Beta-Categories-baseline.json",
        "Rat-Trap-Beta-Categories-hybrid.json",
        "Rat-Trap-Structured-Beta-benchmark.json",
        "Rat-Trap-Vault-Beta-benchmark.json"
    )
    foreach ($name in $evidenceFiles) {
        Copy-RequiredFile (Join-Path $EvidenceDir $name) $releaseFolder
    }

    $thirdPartyFolder = Join-Path $releaseFolder "THIRD-PARTY-LICENSES"
    [IO.Directory]::CreateDirectory($thirdPartyFolder) | Out-Null
    $thirdPartyLicenses = @(
        @{
            Source = Join-Path $pythonBase "LICENSE.txt"
            Name = "PYTHON-3.13.13-LICENSE.txt"
        },
        @{
            Source = Join-Path $pythonBase "tcl\tk8.6\license.terms"
            Name = "TCL-TK-8.6-LICENSE.txt"
        },
        @{
            Source = Join-Path $repoRoot ".venv\Lib\site-packages\pyinstaller-6.21.0.dist-info\licenses\COPYING.txt"
            Name = "PYINSTALLER-6.21.0-COPYING.txt"
        },
        @{
            Source = Join-Path $repoRoot ".venv\Lib\site-packages\pyfastcdc-0.2.1.dist-info\licenses\LICENSE"
            Name = "PYFASTCDC-0.2.1-LICENSE.txt"
        },
        @{
            Source = Join-Path $repoRoot ".venv\Lib\site-packages\typing_extensions-4.15.0.dist-info\licenses\LICENSE"
            Name = "TYPING-EXTENSIONS-4.15.0-LICENSE.txt"
        },
        @{
            Source = Join-Path $repoRoot ".venv\Lib\site-packages\zstandard-0.25.0.dist-info\licenses\LICENSE"
            Name = "PYTHON-ZSTANDARD-0.25.0-LICENSE.txt"
        }
    )
    foreach ($license in $thirdPartyLicenses) {
        Copy-RequiredFileAs `
            $license.Source `
            (Join-Path $thirdPartyFolder $license.Name)
    }

    Copy-RequiredFile $ExecutablePath $releaseFolder
    $exeHash = (Get-FileHash -LiteralPath $ExecutablePath -Algorithm SHA256).Hash
    $checksumLine = "Rat-Trap.exe  SHA-256  $exeHash"
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        (Join-Path $releaseFolder "SHA256.txt"),
        $checksumLine + "`n",
        $utf8NoBom
    )

    Compress-Archive -LiteralPath $releaseFolder -DestinationPath $zipPath -CompressionLevel Optimal

    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    Write-Host "Created: $zipPath"
    Write-Host "SHA-256: $zipHash"
}
finally {
    $resolvedStage = [IO.Path]::GetFullPath($stageRoot)
    $resolvedDestination = [IO.Path]::GetFullPath($destination).TrimEnd('\') + '\'
    if (
        $resolvedStage.StartsWith(
            $resolvedDestination,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        (Test-Path -LiteralPath $resolvedStage)
    ) {
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}
