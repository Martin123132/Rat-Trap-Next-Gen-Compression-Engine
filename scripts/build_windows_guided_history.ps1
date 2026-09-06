#Requires -Version 5.1
<#
.SYNOPSIS
Builds the private guided backup-history lesson for the existing Desktop Preview 2 app.
.EXAMPLE
.\scripts\build_windows_guided_history.ps1 -ValidateOnly
.EXAMPLE
.\scripts\build_windows_guided_history.ps1
.NOTES
Uses the existing .venv and exact 5.7.0 dependency pins; never installs packages,
downloads tools, signs, installs the app, changes associations, or publishes.
The default final directory is dist\guided-history and must not exist.
Build logs/intermediates use a new build\guided-history-<GUID> directory.
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
$entrypoint = Join-Path $repoRoot "windows_guided_preview.py"
$desktopModule = Join-Path $repoRoot "rat_trap\guided_app.py"
$tutorialModule = Join-Path $repoRoot "rat_trap\tutorials.py"
$archiveTutorialModule = Join-Path $repoRoot "rat_trap\archive_tutorials.py"
$protectionTutorialModule = Join-Path $repoRoot "rat_trap\protection_tutorials.py"
$historyTutorialModule = Join-Path $repoRoot "rat_trap\history_tutorials.py"
$guidedBaselinePath = Join-Path $repoRoot "release-manifests\guided-protection.json"
$icon = Join-Path $repoRoot "packaging\branding\rat-trap.ico"
$guide = Join-Path $repoRoot "packaging\direct\README-GUIDED-HISTORY.txt"
$baselinePackager = Join-Path $PSScriptRoot "package_windows_beta_5_7_0.ps1"
$manifestPath = Join-Path $repoRoot "release-manifests\5.7.0.json"
$requiredPaths = @($python, $requirements, $entrypoint, $desktopModule, $tutorialModule, $icon,
    $guide, $baselinePackager, $manifestPath, $archiveTutorialModule, $protectionTutorialModule, $historyTutorialModule, $guidedBaselinePath)
foreach ($path in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required preview build input is missing: $path. Nothing will be installed automatically."
    }
}
if ([string]::IsNullOrWhiteSpace($DestinationDirectory)) {
    $DestinationDirectory = Join-Path $repoRoot "dist\guided-history"
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
    (Join-Path $repoRoot "dist\desktop-preview-1"),
    (Join-Path $repoRoot "dist\desktop-preview-2"),
    (Join-Path $repoRoot "dist\desktop-preview-2-installer"),
    (Join-Path $repoRoot "dist\guided-preview"),
    (Join-Path $repoRoot "dist\guided-preview-installer"),
    (Join-Path $repoRoot "dist\guided-lessons"),
    (Join-Path $repoRoot "dist\guided-lessons-installer"),
    (Join-Path $repoRoot "dist\guided-protection"),
    (Join-Path $repoRoot "dist\guided-protection-installer")
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
# Validate the preceding tutorial's frozen artifacts and packaging before work.
# Its live UI source may now implement new lessons; preserved source is separate.
$guidedBaseline = Get-Content -LiteralPath $guidedBaselinePath -Raw | ConvertFrom-Json
if ($guidedBaseline.schema -cne "rat-trap-guided-protection-release/v1" -or
    $guidedBaseline.application_version -cne "5.7.0-desktop-preview.2-tutorial.3" -or
    $guidedBaseline.installer_version -cne "5.7.0.5") {
    throw "Expected the recorded protection and recovery tutorial release."
}
$frozenGuidedRecords = @($guidedBaseline.artifacts | Where-Object { $_.path.StartsWith("dist/", [StringComparison]::Ordinal) }) +
    @($guidedBaseline.evidence_files | Where-Object {
        $_.path.StartsWith("scripts/", [StringComparison]::Ordinal) -or
        $_.path.StartsWith("packaging/direct/", [StringComparison]::Ordinal)
    })
foreach ($record in $frozenGuidedRecords) {
    $path = Join-Path $repoRoot $record.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-Item -LiteralPath $path).Length -ne [long]$record.bytes -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne [string]$record.sha256) {
        throw "Frozen protection and recovery artifact/packaging changed: $($record.path)"
    }
}
if ($ValidateOnly) {
    [PSCustomObject]@{
        Preflight = "Passed"
        Product = "Rat-Trap Desktop Preview 2"
        Version = "5.7.0-desktop-preview.2-tutorial.4"
        DestinationDirectory = $finalDirectory
        Environment = $buildEnvironment
        Built = $false
    }
    return
}

$sourcePaths = @($PSCommandPath, $entrypoint, $requirements, $icon, $guide, $baselinePackager, $manifestPath, $guidedBaselinePath,
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
foreach ($priorDirectory in @("dist\desktop-preview-2", "dist\desktop-preview-2-installer", "dist\guided-preview", "dist\guided-preview-installer", "dist\guided-lessons", "dist\guided-lessons-installer", "dist\guided-protection", "dist\guided-protection-installer")) {
    $priorPath = Join-Path $repoRoot $priorDirectory
    if (Test-Path -LiteralPath $priorPath -PathType Container) {
        $preview1Files = @($preview1Files) + @(Get-ChildItem -LiteralPath $priorPath -Recurse -File |
            ForEach-Object { $_.FullName })
    }
}
foreach ($priorFile in @("windows_desktop_preview2.py", "scripts\build_windows_desktop_preview2.ps1",
    "scripts\build_windows_desktop_preview2_installer.ps1", "packaging\direct\rat-trap-desktop-preview2.nsi",
    "packaging\direct\README-DESKTOP-PREVIEW-2.txt", "packaging\direct\README-DESKTOP-PREVIEW-2-INSTALLER.txt",
    "release-manifests\desktop-preview-2.json")) {
    $priorPath = Join-Path $repoRoot $priorFile
    if (Test-Path -LiteralPath $priorPath -PathType Leaf) { $preview1Files = @($preview1Files) + @($priorPath) }
}
$preview1Files = @($preview1Files) + @($frozenGuidedRecords | ForEach-Object { Join-Path $repoRoot $_.path }) + @($guidedBaselinePath)
$preview1Before = Get-SourceSnapshot @($preview1Files | Select-Object -Unique)
$buildName = "guided-history-" + [Guid]::NewGuid().ToString("N")
$buildDirectory = Join-Path (Join-Path $repoRoot "build") $buildName
if (Test-Path -LiteralPath $buildDirectory) { throw "Unique build path already exists: $buildDirectory" }
[void](New-Item -ItemType Directory -Path $buildDirectory)
$outputParent = [IO.Path]::GetDirectoryName($finalDirectory)
[void][IO.Directory]::CreateDirectory($outputParent)
$stageName = ".guided-history-" + [Guid]::NewGuid().ToString("N")
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
  ffi=FixedFileInfo(filevers=(5, 7, 0, 6), prodvers=(5, 7, 0, 6),
    mask=0x3f, flags=0x2, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable(u'040904B0', [
    StringStruct(u'CompanyName', u'TWO HANDS NETWORK LTD'),
    StringStruct(u'FileDescription', u'Rat-Trap Desktop Preview 2 guided backup-history lesson'),
    StringStruct(u'FileVersion', u'5.7.0.6'),
    StringStruct(u'InternalName', u'Rat-Trap-Desktop-Preview-2'),
    StringStruct(u'LegalCopyright', u'Copyright (c) 2026 TWO HANDS NETWORK LTD'),
    StringStruct(u'OriginalFilename', u'Rat-Trap-Desktop-Preview-2.exe'),
    StringStruct(u'ProductName', u'Rat-Trap Desktop Preview 2'),
    StringStruct(u'ProductVersion', u'5.7.0-desktop-preview.2-tutorial.4')
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
        $fileInfo.VersionInfo.FileVersion -cne "5.7.0.6" -or
        $fileInfo.VersionInfo.ProductVersion -cne "5.7.0-desktop-preview.2-tutorial.4" -or
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
    # Exercise the actual frozen executable before handing it to the installer.
    # Each process is ours, hidden, bounded, and writes only generated test data.
    foreach ($mode in @("--self-test", "--ui-self-test", "--tutorial-self-test")) {
        $label = $mode.TrimStart("-")
        $process = Start-Process -FilePath $exePath -ArgumentList $mode -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $buildDirectory "$label.stdout.log") `
            -RedirectStandardError (Join-Path $buildDirectory "$label.stderr.log")
        try {
            [void]$process.Handle
            if (-not $process.WaitForExit(300000)) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                throw "Packaged $mode exceeded its test timeout."
            }
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) { throw "Packaged $mode failed with exit $($process.ExitCode)." }
        }
        finally { $process.Dispose() }
    }
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
    # No extra portable ZIP: this private payload exists to build the installer.
    foreach ($relative in $payloadNames) {
        if ((Get-FileHash -LiteralPath (Join-Path $stageDirectory $relative) -Algorithm SHA256).Hash -cne $payloadHashes[$relative]) {
            throw "Private guided payload checksum mismatch: $relative"
        }
    }
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
    $buildInfo = [ordered]@{
        schema = "rat-trap-guided-history-build/v1"
        product = "Rat-Trap Desktop Preview 2"
        version = "5.7.0-desktop-preview.2-tutorial.4"
        built_at_utc = [DateTime]::UtcNow.ToString("o")
        base_engine_version = "5.7.0"
        previous_preview_preserved = "Frozen Desktop Preview 1, 2, and all preceding guided tutorial artifacts"
        preserved_preview1_sha256 = $preview1Before
        environment = $buildEnvironment
        source_sha256 = $sourceBefore
        payload_sha256 = $payloadHashes
        executable_sha256 = $exeHash
        executable = $exeName
        executable_bytes = $fileInfo.Length
        packaged_self_tests = @("--self-test", "--ui-self-test", "--tutorial-self-test")
        installer_version = "5.7.0.6"
        app_key = "TwoHandsNetwork.RatTrap.DesktopPreview2"
        payload_files = 25
        legal_files = 20
        signature = "NotSigned"
        byte_reproducible_build_claimed = $false
        installer_or_associations_created = $false
        published_to_remote = $false
    }
    $buildInfoPath = Join-Path $buildDirectory "build-info.json"
    [IO.File]::WriteAllText($buildInfoPath, ($buildInfo | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    [IO.File]::Copy($buildInfoPath, (Join-Path $stageDirectory "BUILD-MANIFEST.json"), $false)
    if (Test-Path -LiteralPath $finalDirectory) { throw "Refusing to overwrite: $finalDirectory" }
    [IO.Directory]::Move($stageDirectory, $finalDirectory)
    $stageOwned = $false
    [PSCustomObject]@{
        Product = "Rat-Trap Desktop Preview 2"
        Version = "5.7.0-desktop-preview.2-tutorial.4"
        Executable = (Join-Path $finalDirectory $exeName)
        ExecutableSha256 = $exeHash
        BuildManifest = (Join-Path $finalDirectory "BUILD-MANIFEST.json")
        InstallerVersion = "5.7.0.6"
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
            $stageName -notmatch '^\.guided-history-[a-f0-9]{32}$') {
            throw "Refusing cleanup outside the exact owned preview staging directory: $stageDirectory"
        }
        Remove-Item -LiteralPath $actual -Recurse -Force
    }
}
