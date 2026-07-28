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
    $ExecutablePath = Join-Path $repoRoot "dist\5.1.1\Rat-Trap.exe"
}

$version = "5.1.1"
$releaseName = "Rat-Trap-Windows-$version"
$destination = [IO.Path]::GetFullPath($DestinationDir)
$ExecutablePath = [IO.Path]::GetFullPath($ExecutablePath)
[IO.Directory]::CreateDirectory($destination) | Out-Null
$zipPath = Join-Path $destination "$releaseName.zip"
if (Test-Path -LiteralPath $zipPath) {
    throw "Refusing to overwrite existing release: $zipPath"
}
if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Required release executable is missing: $ExecutablePath"
}

$versionInfo = (Get-Item -LiteralPath $ExecutablePath).VersionInfo
if (
    $versionInfo.FileVersion -ne $version -or
    $versionInfo.ProductVersion -ne $version
) {
    throw "Executable version mismatch. Expected $version, got FileVersion '$($versionInfo.FileVersion)' and ProductVersion '$($versionInfo.ProductVersion)'."
}

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

try {
    $repositoryFiles = @(
        "BENCHMARK-AUDIT.md",
        "COMMERCIAL-LICENSE.md",
        "LICENSE.md",
        "NOTICE.md",
        "README-WINDOWS.txt",
        "VAULT-README.md"
    )
    foreach ($name in $repositoryFiles) {
        Copy-RequiredFile (Join-Path $repoRoot $name) $releaseFolder
    }
    Copy-RequiredFile (
        Join-Path $repoRoot "docs\COMPATIBILITY-GATE.md"
    ) $releaseFolder
    Copy-RequiredFile (
        Join-Path $repoRoot "docs\GMW-FORMAT-REGISTRY.md"
    ) $releaseFolder

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
