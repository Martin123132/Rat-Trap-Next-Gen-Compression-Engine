#Requires -Version 5.1
<#
.SYNOPSIS
Builds a separate, unsigned Rat-Trap Desktop Preview 2 portable application.
.EXAMPLE
.\scripts\build_windows_desktop_preview2.ps1 -ValidateOnly
.EXAMPLE
.\scripts\build_windows_desktop_preview2.ps1
.NOTES
Uses the existing .venv and exact 5.7.0 dependency pins; never installs packages,
downloads tools, signs, installs the app, changes associations, or publishes.
The default final directory is dist\desktop-preview-2 and must not exist.
Build logs/intermediates use a new build\desktop-preview-2-<GUID> directory.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [Alias("DestinationDir")]
    [string]$DestinationDirectory,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-PreviewStreamHash([IO.Stream]$Stream) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Stream))).Replace("-", "") }
    finally { $algorithm.Dispose() }
}

function Get-SourceSnapshot([string[]]$Paths) {
    $result = @{}
    foreach ($path in $Paths) {
        $result.Add($path, (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash)
    }
    return $result
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $repoRoot "requirements-build-5.7.0.txt"
$entrypoint = Join-Path $repoRoot "windows_desktop_preview2.py"
$desktopModule = Join-Path $repoRoot "rat_trap\desktop_preview2.py"
$icon = Join-Path $repoRoot "packaging\branding\rat-trap.ico"
$guide = Join-Path $repoRoot "packaging\direct\README-DESKTOP-PREVIEW-2.txt"
$baselinePackager = Join-Path $PSScriptRoot "package_windows_beta_5_7_0.ps1"
$manifestPath = Join-Path $repoRoot "release-manifests\5.7.0.json"
$requiredPaths = @($python, $requirements, $entrypoint, $desktopModule, $icon,
    $guide, $baselinePackager, $manifestPath)
foreach ($path in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required preview build input is missing: $path. Nothing will be installed automatically."
    }
}
if ([string]::IsNullOrWhiteSpace($DestinationDirectory)) {
    $DestinationDirectory = Join-Path $repoRoot "dist\desktop-preview-2"
}
$finalDirectory = [IO.Path]::GetFullPath(
    $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestinationDirectory)
)
$finalRoot = [IO.Path]::GetPathRoot($finalDirectory)
if ($finalDirectory.Length -gt $finalRoot.Length) {
    $finalDirectory = $finalDirectory.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
}
if (Test-Path -LiteralPath $finalDirectory) {
    throw "Refusing to overwrite the existing preview destination: $finalDirectory"
}
# A custom output path must not nest inside a recorded release or the source.
$protectedDirectories = @(
    (Join-Path $repoRoot "dist\5.7.0"), (Join-Path $repoRoot "dist\msix"),
    (Join-Path $repoRoot "dist\direct"), (Join-Path $repoRoot "rat_trap"),
    (Join-Path $repoRoot ".venv"), (Join-Path $repoRoot "packaging"),
    (Join-Path $repoRoot "release-manifests"),
    (Join-Path $repoRoot "dist\desktop-preview-1")
)
foreach ($protected in $protectedDirectories) {
    if ($finalDirectory.StartsWith($protected + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Preview output cannot be inside a protected source/baseline directory: $protected"
    }
}
$baseline = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($baseline.schema -cne "rat-trap-release-manifest/v1" -or
    $baseline.product -cne "Rat-Trap" -or $baseline.version -cne "5.7.0") {
    throw "Expected the recorded Rat-Trap 5.7.0 baseline manifest."
}
$requirementsRecord = @($baseline.evidence_files | Where-Object { $_.path -ceq "requirements-build-5.7.0.txt" })
if ($requirementsRecord.Count -ne 1 -or
    $requirementsRecord[0].sha256 -cne "CCF125BCFC4E77ED5AFECB059116F836D40D9F4715501F6C90CE67B11D3676E5" -or
    (Get-Item -LiteralPath $requirements).Length -ne [long]$requirementsRecord[0].bytes -or
    (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash -cne $requirementsRecord[0].sha256) {
    throw "The exact recorded 5.7.0 build requirements have changed."
}
$dependencyCheck = @'
import importlib.metadata as metadata
import json, platform, re, struct, sys
from pathlib import Path
requirements = Path(sys.argv[1]).read_text(encoding="utf-8-sig")
expected = {}
for raw in requirements.splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
    if not match:
        raise SystemExit("Build requirements must contain exact name==version pins only")
    name, version = match.groups()
    canonical = re.sub(r"[-_.]+", "-", name).lower()
    if canonical in expected:
        raise SystemExit("Duplicate dependency pin: " + name)
    expected[canonical] = version
    actual = metadata.version(name)
    if actual != version:
        raise SystemExit(f"Pinned dependency mismatch: {name}: expected {version}, installed {actual}")
if len(expected) != 13:
    raise SystemExit("Expected the 13 recorded 5.7.0 dependency pins")
if platform.python_version() != sys.argv[2] or struct.calcsize("P") != 8:
    raise SystemExit("The existing virtual environment must use the recorded 64-bit Python version")
# pip is build infrastructure and rat-trap is this checkout's editable metadata.
# Other extra distributions could introduce unrecorded PyInstaller hooks.
allowed = set(expected) | {"pip", "rat-trap"}
actual_names = {re.sub(r"[-_.]+", "-", d.metadata["Name"]).lower() for d in metadata.distributions()}
if actual_names - allowed:
    raise SystemExit("Unrecorded distributions in build environment: " + ", ".join(sorted(actual_names - allowed)))
print(json.dumps({"python": platform.python_version(), "architecture": "x64", "dependencies": expected}, sort_keys=True))
'@
# stdin avoids Windows PowerShell 5.1's legacy stripping of embedded quotes
# from a native -c argument; the Python code is never written into the checkout.
$environmentJson = $dependencyCheck | & $python -I - $requirements ([string]$baseline.build_environment.python)
if ($LASTEXITCODE -ne 0) { throw "Preview dependency preflight failed; no environment changes were made." }
$buildEnvironment = ($environmentJson -join "`n") | ConvertFrom-Json
foreach ($record in $baseline.artifacts) {
    $path = Join-Path $repoRoot $record.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-Item -LiteralPath $path).Length -ne [long]$record.bytes -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne [string]$record.sha256) {
        throw "Frozen baseline artifact validation failed: $($record.path)"
    }
}
if ($ValidateOnly) {
    [PSCustomObject]@{
        Preflight = "Passed"
        Product = "Rat-Trap Desktop Preview 2"
        Version = "5.7.0-desktop-preview.2"
        DestinationDirectory = $finalDirectory
        Environment = $buildEnvironment
        Built = $false
    }
    return
}

$sourcePaths = @($entrypoint, $requirements, $icon, $guide, $baselinePackager, $manifestPath,
    (Join-Path $repoRoot "PRIVACY.md"), (Join-Path $repoRoot "SUPPORT.md")) +
    @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "rat_trap") -Recurse -File -Filter "*.py" | ForEach-Object { $_.FullName })
$sourceBefore = Get-SourceSnapshot $sourcePaths
$preview1Files = @(
    (Join-Path $repoRoot "windows_desktop_preview.py"),
    (Join-Path $repoRoot "rat_trap\desktop_app.py"),
    (Join-Path $repoRoot "scripts\build_windows_desktop_preview.ps1"),
    (Join-Path $repoRoot "packaging\direct\README-DESKTOP-PREVIEW.txt"),
    (Join-Path $repoRoot "release-manifests\desktop-preview-1.json")
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
$preview1Directory = Join-Path $repoRoot "dist\desktop-preview-1"
if (Test-Path -LiteralPath $preview1Directory -PathType Container) {
    $preview1Files = @($preview1Files) + @(Get-ChildItem -LiteralPath $preview1Directory -Recurse -File |
        ForEach-Object { $_.FullName })
}
$preview1Before = Get-SourceSnapshot @($preview1Files)
$buildName = "desktop-preview-2-" + [Guid]::NewGuid().ToString("N")
$buildDirectory = Join-Path (Join-Path $repoRoot "build") $buildName
if (Test-Path -LiteralPath $buildDirectory) { throw "Unique build path already exists: $buildDirectory" }
[void](New-Item -ItemType Directory -Path $buildDirectory)
$outputParent = [IO.Path]::GetDirectoryName($finalDirectory)
[void][IO.Directory]::CreateDirectory($outputParent)
$stageName = ".desktop-preview-2-" + [Guid]::NewGuid().ToString("N")
$stageDirectory = Join-Path $outputParent $stageName
if (Test-Path -LiteralPath $stageDirectory) { throw "Unique output staging path already exists: $stageDirectory" }
[void](New-Item -ItemType Directory -Path $stageDirectory)
$stageOwned = $true
$previousPyInstallerConfig = [Environment]::GetEnvironmentVariable("PYINSTALLER_CONFIG_DIR", "Process")
try {
    # Reuse the fail-closed baseline verifier/extractor, then select ONLY Legal
    # and the policy documents. Its old executable and ZIP stay in build evidence.
    $frozen = & $baselinePackager -DestinationDirectory (Join-Path $buildDirectory "frozen-package") `
        -PayloadDirectory (Join-Path $buildDirectory "frozen-payload")
    if ($frozen.LegalFileCount -ne 20 -or $frozen.PayloadFileCount -ne 25) {
        throw "The frozen packager returned an unexpected legal/payload inventory."
    }
    $legalPaths = @($baseline.msix_inventory | Where-Object { $_.path -clike "Legal/*" } | ForEach-Object { [string]$_.path })
    if ($legalPaths.Count -ne 20) { throw "Expected exactly 20 frozen legal files." }
    $payloadNames = @($legalPaths) + @("PRIVACY.md", "SUPPORT.md")
    foreach ($relative in $payloadNames) {
        $target = Join-Path $stageDirectory $relative
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        [IO.File]::Copy((Join-Path $frozen.PayloadDirectory $relative), $target, $false)
    }
    [IO.File]::Copy($guide, (Join-Path $stageDirectory "README-FIRST.txt"), $false)
    $payloadNames += "README-FIRST.txt"

    # Generate a separate resource; never change packaging/windows_version_info.txt.
    $versionResource = @'
VSVersionInfo(
  ffi=FixedFileInfo(filevers=(5, 7, 0, 2), prodvers=(5, 7, 0, 2),
    mask=0x3f, flags=0x2, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable(u'040904B0', [
    StringStruct(u'CompanyName', u'TWO HANDS NETWORK LTD'),
    StringStruct(u'FileDescription', u'Rat-Trap Desktop Preview 2'),
    StringStruct(u'FileVersion', u'5.7.0-desktop-preview.2'),
    StringStruct(u'InternalName', u'Rat-Trap-Desktop-Preview-2'),
    StringStruct(u'LegalCopyright', u'Copyright (c) 2026 TWO HANDS NETWORK LTD'),
    StringStruct(u'OriginalFilename', u'Rat-Trap-Desktop-Preview-2.exe'),
    StringStruct(u'ProductName', u'Rat-Trap Desktop Preview 2'),
    StringStruct(u'ProductVersion', u'5.7.0-desktop-preview.2')
  ])]), VarFileInfo([VarStruct(u'Translation', [1033, 1200])])]
)
'@
    $versionPath = Join-Path $buildDirectory "desktop-preview-version-info.txt"
    [IO.File]::WriteAllText($versionPath, $versionResource, (New-Object Text.UTF8Encoding($false)))
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $buildDirectory "pyinstaller-cache"
    $arguments = @("-I", "-m", "PyInstaller", "--clean", "--onefile", "--windowed",
        "--name", "Rat-Trap-Desktop-Preview-2", "--paths", $repoRoot,
        "--collect-all", "pyfastcdc", "--hidden-import", "zstandard",
        "--icon", $icon, "--version-file", $versionPath,
        "--distpath", $stageDirectory, "--workpath", (Join-Path $buildDirectory "work"),
        "--specpath", $buildDirectory, $entrypoint)
    Push-Location $repoRoot
    try {
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed. Inspect retained build evidence: $buildDirectory" }
    }
    finally { Pop-Location }
    $exeName = "Rat-Trap-Desktop-Preview-2.exe"
    $exePath = Join-Path $stageDirectory $exeName
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { throw "Preview executable was not created." }
    $fileInfo = Get-Item -LiteralPath $exePath
    $exeHash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
    if ($fileInfo.Length -le 0 -or $exeHash -ceq "2FDBC470CA51E04E7F38459F0C58089BF487965333C6AE21B6E2886CB14AF273" -or
        $fileInfo.VersionInfo.FileVersion -cne "5.7.0-desktop-preview.2" -or
        $fileInfo.VersionInfo.ProductVersion -cne "5.7.0-desktop-preview.2" -or
        $fileInfo.VersionInfo.ProductName -cne "Rat-Trap Desktop Preview 2") {
        throw "Preview executable is empty, is the frozen baseline, or lacks its separate preview identity."
    }
    $peCheck = @'
import pefile, sys
with pefile.PE(sys.argv[1], fast_load=True) as pe:
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Subsystem != 2:
        raise SystemExit("Expected a Windows x64 GUI executable")
'@
    $peCheck | & $python -I - $exePath
    if ($LASTEXITCODE -ne 0) { throw "Preview executable architecture/subsystem check failed." }
    $signature = Get-AuthenticodeSignature -LiteralPath $exePath
    if ([string]$signature.Status -cne "NotSigned") { throw "Expected an explicitly unsigned preview executable." }
    $payloadNames += $exeName
    $payloadHashes = @{}
    $checksumLines = foreach ($relative in ($payloadNames | Sort-Object)) {
        $hash = (Get-FileHash -LiteralPath (Join-Path $stageDirectory $relative) -Algorithm SHA256).Hash
        $payloadHashes.Add($relative, $hash)
        "{0}  {1}" -f $hash, $relative
    }
    $checksumPath = Join-Path $stageDirectory "SHA256SUMS.txt"
    [IO.File]::WriteAllText($checksumPath, ($checksumLines -join "`n") + "`n", (New-Object Text.UTF8Encoding($false)))
    $payloadHashes.Add("SHA256SUMS.txt", (Get-FileHash -LiteralPath $checksumPath -Algorithm SHA256).Hash)
    $payloadNames += "SHA256SUMS.txt"
    $actualFiles = @(Get-ChildItem -LiteralPath $stageDirectory -Recurse -File)
    if ($payloadNames.Count -ne 25 -or $actualFiles.Count -ne 25 -or
        (Test-Path -LiteralPath (Join-Path $stageDirectory "Rat-Trap.exe"))) {
        throw "Unexpected preview payload inventory; the frozen executable must not be included."
    }
    $zipName = "Rat-Trap-Desktop-Preview-2-Windows-x64-portable.zip"
    $zipPath = Join-Path $stageDirectory $zipName
    $zip = [IO.Compression.ZipFile]::Open($zipPath, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($relative in ($payloadNames | Sort-Object)) {
            [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip,
                (Join-Path $stageDirectory $relative), $relative, [IO.Compression.CompressionLevel]::Optimal)
        }
    }
    finally { $zip.Dispose() }
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        if ($zip.Entries.Count -ne 25) { throw "Portable preview ZIP must contain exactly 25 files." }
        $seen = @{}
        foreach ($entry in $zip.Entries) {
            if (-not $payloadHashes.ContainsKey($entry.FullName) -or $seen.ContainsKey($entry.FullName)) {
                throw "Unexpected/duplicate ZIP entry: $($entry.FullName)"
            }
            $stream = $entry.Open()
            try { $hash = Get-PreviewStreamHash $stream } finally { $stream.Dispose() }
            if ($hash -cne $payloadHashes[$entry.FullName]) { throw "Preview ZIP checksum mismatch: $($entry.FullName)" }
            $seen.Add($entry.FullName, $true)
        }
    }
    finally { $zip.Dispose() }
    foreach ($path in $sourceBefore.Keys) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $sourceBefore[$path]) {
            throw "Build source changed during packaging; refusing publication: $path"
        }
    }
    foreach ($record in $baseline.artifacts) {
        if ((Get-FileHash -LiteralPath (Join-Path $repoRoot $record.path) -Algorithm SHA256).Hash -cne [string]$record.sha256) {
            throw "Frozen baseline artifact changed during the preview build: $($record.path)"
        }
    }
    foreach ($path in $preview1Before.Keys) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $preview1Before[$path]) {
            throw "Preserved Preview 1 file changed during packaging: $path"
        }
    }
    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    $buildInfo = [ordered]@{
        schema = "rat-trap-desktop-preview-build/v1"
        product = "Rat-Trap Desktop Preview 2"
        version = "5.7.0-desktop-preview.2"
        built_at_utc = [DateTime]::UtcNow.ToString("o")
        base_engine_version = "5.7.0"
        previous_preview_preserved = "Rat-Trap Desktop Preview 1"
        preserved_preview1_sha256 = $preview1Before
        environment = $buildEnvironment
        source_sha256 = $sourceBefore
        payload_sha256 = $payloadHashes
        executable_sha256 = $exeHash
        zip_sha256 = $zipHash
        signature = "NotSigned"
        byte_reproducible_build_claimed = $false
        installer_or_associations_created = $false
        published_to_remote = $false
    }
    $buildInfoPath = Join-Path $buildDirectory "build-info.json"
    [IO.File]::WriteAllText($buildInfoPath, ($buildInfo | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $finalDirectory) { throw "Refusing to overwrite: $finalDirectory" }
    [IO.Directory]::Move($stageDirectory, $finalDirectory)
    $stageOwned = $false
    [PSCustomObject]@{
        Product = "Rat-Trap Desktop Preview 2"
        Version = "5.7.0-desktop-preview.2"
        Executable = (Join-Path $finalDirectory $exeName)
        ExecutableSha256 = $exeHash
        PortableZip = (Join-Path $finalDirectory $zipName)
        PortableZipSha256 = $zipHash
        PayloadFileCount = 25
        LegalFileCount = 20
        BuildEvidence = $buildInfoPath
        Authenticode = "NotSigned"
    }
}
finally {
    [Environment]::SetEnvironmentVariable("PYINSTALLER_CONFIG_DIR", $previousPyInstallerConfig, "Process")
    if ($stageOwned -and (Test-Path -LiteralPath $stageDirectory)) {
        $actual = (Resolve-Path -LiteralPath $stageDirectory).ProviderPath
        $expected = [IO.Path]::GetFullPath((Join-Path $outputParent $stageName))
        $prefix = $outputParent.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        if (-not $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase) -or
            -not $actual.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
            $stageName -notmatch '^\.desktop-preview-2-[a-f0-9]{32}$') {
            throw "Refusing cleanup outside the exact owned preview staging directory: $stageDirectory"
        }
        Remove-Item -LiteralPath $actual -Recurse -Force
    }
}
