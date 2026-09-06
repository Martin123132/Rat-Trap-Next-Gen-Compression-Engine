#Requires -Version 5.1
<#
.SYNOPSIS
Packages the recorded, unsigned Rat-Trap 5.7.0 beta without rebuilding it.
.EXAMPLE
.\scripts\package_windows_beta_5_7_0.ps1 -DestinationDirectory C:\Releases\Beta `
    -PayloadDirectory C:\Releases\Beta\installer-payload
.NOTES
No Python, SDK, benchmark fixtures, network access, signing, or Store identity
is required. Existing final outputs are never replaced. Each completed output
is published by a same-volume atomic move; two outputs are not one transaction.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [Alias("DestinationDir")]
    [string]$DestinationDirectory,

    [ValidateNotNullOrEmpty()]
    [string]$PayloadDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-AbsolutePath([string]$Path) {
    return [IO.Path]::GetFullPath(
        $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    )
}

function Get-StreamSha256([IO.Stream]$Stream) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($Stream))).Replace("-", "")
    }
    finally { $algorithm.Dispose() }
}

function Assert-Artifact([IO.FileStream]$Stream, $Record, [long]$Bytes, [string]$Sha256) {
    if ([long]$Record.bytes -ne $Bytes -or [string]$Record.sha256 -cne $Sha256) {
        throw "The release manifest no longer records the fixed 5.7.0 baseline: $($Record.path)"
    }
    if ($Stream.Length -ne [long]$Record.bytes) {
        throw "Artifact size does not match the release manifest: $($Record.path)"
    }
    $Stream.Position = 0
    if ((Get-StreamSha256 $Stream) -cne [string]$Record.sha256) {
        throw "Artifact SHA256 does not match the release manifest: $($Record.path)"
    }
    $Stream.Position = 0
}

function Assert-LegalPath([string]$Path) {
    # Use one canonical, relative ZIP spelling. No traversal, ADS, aliases,
    # trailing dots/spaces, drive prefixes, or Windows device-name segments.
    if (-not $Path.StartsWith("Legal/", [StringComparison]::Ordinal) -or
        $Path.Contains("\") -or $Path.Contains(":")) {
        throw "Unsafe or non-canonical legal inventory path: $Path"
    }
    foreach ($segment in $Path.Split("/")) {
        if ([string]::IsNullOrWhiteSpace($segment) -or $segment -eq "." -or
            $segment -eq ".." -or $segment.EndsWith(".") -or
            $segment.EndsWith(" ") -or $segment.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or
            $segment -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            throw "Unsafe legal inventory path segment: $Path"
        }
    }
}

function Remove-OwnedStage([string]$Path, [string]$Parent, [string]$Name) {
    if ([string]::IsNullOrEmpty($Path) -or -not (Test-Path -LiteralPath $Path)) { return }
    $expected = [IO.Path]::GetFullPath((Join-Path $Parent $Name))
    $actual = (Resolve-Path -LiteralPath $Path).ProviderPath
    $prefix = $Parent.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase) -or
        -not $actual.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        $Name -notmatch '^\.rat-trap-beta-[a-f0-9]{32}$') {
        throw "Refusing cleanup outside this invocation's exact staging directory: $Path"
    }
    Remove-Item -LiteralPath $actual -Recurse -Force
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$manifestPath = Join-Path $repoRoot "release-manifests\5.7.0.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -cne "rat-trap-release-manifest/v1" -or
    $manifest.product -cne "Rat-Trap" -or $manifest.version -cne "5.7.0") {
    throw "Expected the Rat-Trap 5.7.0 release manifest."
}
$exeRelative = "dist/5.7.0/Rat-Trap.exe"
$msixRelative = "dist/msix/5.7.0/development/Rat-Trap-Windows-5.7.0-x64-unsigned.msix"
$exeRecords = @($manifest.artifacts | Where-Object { $_.path -ceq $exeRelative })
$msixRecords = @($manifest.artifacts | Where-Object { $_.path -ceq $msixRelative })
if ($exeRecords.Count -ne 1 -or $msixRecords.Count -ne 1) {
    throw "The manifest must contain each fixed input artifact exactly once."
}
$exePath = Join-Path $repoRoot $exeRelative
$msixPath = Join-Path $repoRoot $msixRelative
$destination = Get-AbsolutePath $DestinationDirectory
$zipPath = Join-Path $destination "Rat-Trap-Windows-5.7.0-beta-portable.zip"
$payloadFinal = $null
if ($PSBoundParameters.ContainsKey("PayloadDirectory")) {
    $payloadFinal = Get-AbsolutePath $PayloadDirectory
    $payloadRoot = [IO.Path]::GetPathRoot($payloadFinal)
    if ($payloadFinal.Length -gt $payloadRoot.Length) {
        $payloadFinal = $payloadFinal.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    }
    $payloadPrefix = $payloadFinal.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if ($zipPath.StartsWith($payloadPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        $zipPath.Equals($payloadFinal, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PayloadDirectory cannot contain the final ZIP or be its filename."
    }
    if (Test-Path -LiteralPath $payloadFinal) {
        throw "Refusing to overwrite the existing payload path: $payloadFinal"
    }
}
if (Test-Path -LiteralPath $zipPath) { throw "Refusing to overwrite: $zipPath" }
if ((Test-Path -LiteralPath $destination) -and
    -not (Test-Path -LiteralPath $destination -PathType Container)) {
    throw "DestinationDirectory is not a directory: $destination"
}

$copyFiles = [ordered]@{
    "PRIVACY.md" = (Join-Path $repoRoot "PRIVACY.md")
    "SUPPORT.md" = (Join-Path $repoRoot "SUPPORT.md")
    "README-FIRST.txt" = (Join-Path $repoRoot "packaging\direct\README-BETA.txt")
}
foreach ($sourcePath in $copyFiles.Values) {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required payload document is missing: $sourcePath"
    }
}

$exeStream = $null
$msixStream = $null
$msixArchive = $null
$stage = $null
$stageCreated = $false
$payloadStage = $null
$payloadStageCreated = $false
$payloadStageParent = $null
$payloadStageName = $null
$stageName = ".rat-trap-beta-" + [Guid]::NewGuid().ToString("N")
try {
    # Retain read-only handles denying concurrent writes/deletes from the
    # baseline validation through copying/extraction (no check/use race).
    $exeStream = [IO.File]::Open($exePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $msixStream = [IO.File]::Open($msixPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    Assert-Artifact $exeStream $exeRecords[0] 18038953 "2FDBC470CA51E04E7F38459F0C58089BF487965333C6AE21B6E2886CB14AF273"
    Assert-Artifact $msixStream $msixRecords[0] 17909407 "A246E1A41D1E0ACEDDA734EDA825DFBDFC4FF1B50E3AA950757F723162C1CF4B"

    # Only after BOTH artifacts pass their recorded SHA256 and size checks may
    # the MSIX be interpreted or any payload files be copied.
    $legalRecords = @($manifest.msix_inventory | Where-Object {
        ([string]$_.path).StartsWith("Legal/", [StringComparison]::Ordinal)
    })
    if ($legalRecords.Count -ne 20 -or
        [int]$manifest.verification.development_msix.legal_payload_file_count -ne 20) {
        throw "Expected exactly 20 recorded Legal payload files."
    }
    $expectedLegal = @{}
    foreach ($record in $legalRecords) {
        $relative = [string]$record.path
        Assert-LegalPath $relative
        if ($expectedLegal.ContainsKey($relative) -or [long]$record.bytes -le 0) {
            throw "Duplicate or invalid legal inventory entry: $relative"
        }
        $expectedLegal.Add($relative, $record)
    }
    $msixArchive = New-Object IO.Compression.ZipArchive($msixStream, [IO.Compression.ZipArchiveMode]::Read, $true)
    $actualLegal = @{}
    foreach ($entry in $msixArchive.Entries) {
        if ($entry.FullName -imatch '^Legal[/\\]') {
            Assert-LegalPath $entry.FullName
            if (-not $expectedLegal.ContainsKey($entry.FullName) -or
                $actualLegal.ContainsKey($entry.FullName)) {
                throw "Unexpected or duplicate legal archive entry: $($entry.FullName)"
            }
            $record = $expectedLegal[$entry.FullName]
            if ($entry.FullName -cne [string]$record.path -or $entry.Length -ne [long]$record.bytes) {
                throw "Legal archive entry does not match its recorded spelling/size: $($entry.FullName)"
            }
            $actualLegal.Add($entry.FullName, $entry)
        }
    }
    if ($actualLegal.Count -ne $expectedLegal.Count) { throw "Legal archive inventory is incomplete." }

    [void][IO.Directory]::CreateDirectory($destination)
    $stage = Join-Path $destination $stageName
    if (Test-Path -LiteralPath $stage) { throw "Staging collision: $stage" }
    [void](New-Item -ItemType Directory -Path $stage)
    $stageCreated = $true
    if ($null -ne $payloadFinal) {
        $payloadStageParent = [IO.Path]::GetDirectoryName($payloadFinal)
        [void][IO.Directory]::CreateDirectory($payloadStageParent)
        $payloadStageName = ".rat-trap-beta-" + [Guid]::NewGuid().ToString("N")
        $payloadStage = Join-Path $payloadStageParent $payloadStageName
        if (Test-Path -LiteralPath $payloadStage) { throw "Staging collision: $payloadStage" }
        [void](New-Item -ItemType Directory -Path $payloadStage)
        $payloadStageCreated = $true
    }
    else {
        $payloadStage = Join-Path $stage "payload"
        [void][IO.Directory]::CreateDirectory($payloadStage)
    }

    $exeOutput = Join-Path $payloadStage "Rat-Trap.exe"
    $outputStream = [IO.File]::Open($exeOutput, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $exeStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
    foreach ($relative in ($expectedLegal.Keys | Sort-Object)) {
        $outputPath = [IO.Path]::GetFullPath((Join-Path $payloadStage $relative))
        $legalPrefix = (Join-Path $payloadStage "Legal") + [IO.Path]::DirectorySeparatorChar
        if (-not $outputPath.StartsWith($legalPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Legal extraction escaped its destination: $relative"
        }
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($outputPath))
        $inputStream = $actualLegal[$relative].Open()
        try {
            $outputStream = [IO.File]::Open($outputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
        }
        finally { $inputStream.Dispose() }
        if ((Get-Item -LiteralPath $outputPath).Length -ne [long]$expectedLegal[$relative].bytes) {
            throw "Extracted legal file has an unexpected size: $relative"
        }
    }
    foreach ($name in $copyFiles.Keys) {
        [IO.File]::Copy($copyFiles[$name], (Join-Path $payloadStage $name), $false)
    }
    if ((Get-FileHash -LiteralPath $exeOutput -Algorithm SHA256).Hash -cne [string]$exeRecords[0].sha256) {
        throw "Copied executable does not match the fixed baseline."
    }
    $payloadNames = @("Rat-Trap.exe") + @($expectedLegal.Keys) + @($copyFiles.Keys)
    $payloadNames = @($payloadNames | Sort-Object)
    $payloadHashes = @{}
    $checksumLines = foreach ($relative in $payloadNames) {
        $hash = (Get-FileHash -LiteralPath (Join-Path $payloadStage $relative) -Algorithm SHA256).Hash
        $payloadHashes.Add($relative, $hash)
        "{0}  {1}" -f $hash, $relative
    }
    # SHA256SUMS lists every other payload file; it cannot hash itself.
    $checksumPath = Join-Path $payloadStage "SHA256SUMS.txt"
    [IO.File]::WriteAllText($checksumPath, ($checksumLines -join "`n") + "`n", (New-Object Text.UTF8Encoding($false)))
    $payloadHashes.Add("SHA256SUMS.txt", (Get-FileHash -LiteralPath $checksumPath -Algorithm SHA256).Hash)
    $payloadNames += "SHA256SUMS.txt"

    $stagedZip = Join-Path $stage ([IO.Path]::GetFileName($zipPath))
    $zipStream = [IO.File]::Open($stagedZip, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $zip = New-Object IO.Compression.ZipArchive($zipStream, [IO.Compression.ZipArchiveMode]::Create, $true)
        try {
            foreach ($relative in ($payloadNames | Sort-Object)) {
                [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $zip, (Join-Path $payloadStage $relative), $relative, [IO.Compression.CompressionLevel]::Optimal
                )
            }
        }
        finally { $zip.Dispose() }
    }
    finally { $zipStream.Dispose() }

    # Reopen the completed ZIP and verify every entry's bytes before publication.
    $zip = [IO.Compression.ZipFile]::OpenRead($stagedZip)
    try {
        if ($zip.Entries.Count -ne $payloadNames.Count) { throw "Portable ZIP file count mismatch." }
        $verifiedNames = @{}
        foreach ($entry in $zip.Entries) {
            if (-not $payloadHashes.ContainsKey($entry.FullName) -or $verifiedNames.ContainsKey($entry.FullName)) {
                throw "Unexpected or duplicate portable ZIP entry: $($entry.FullName)"
            }
            $entryStream = $entry.Open()
            try { $hash = Get-StreamSha256 $entryStream } finally { $entryStream.Dispose() }
            if ($hash -cne $payloadHashes[$entry.FullName]) { throw "Portable ZIP hash mismatch: $($entry.FullName)" }
            $verifiedNames.Add($entry.FullName, $true)
        }
    }
    finally { $zip.Dispose() }
    if (Test-Path -LiteralPath $zipPath) { throw "Refusing to overwrite: $zipPath" }
    if ($null -ne $payloadFinal -and (Test-Path -LiteralPath $payloadFinal)) {
        throw "Refusing to overwrite: $payloadFinal"
    }
    # These .NET move overloads fail if the destination already exists.
    [IO.File]::Move($stagedZip, $zipPath)
    Write-Host "Portable beta ZIP: $zipPath"
    if ($null -ne $payloadFinal) {
        [IO.Directory]::Move($payloadStage, $payloadFinal)
        $payloadStage = $null
        Write-Host "Verified installer payload: $payloadFinal"
    }
    [PSCustomObject]@{
        Version = "5.7.0"
        PortableZip = $zipPath
        Sha256 = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
        Bytes = (Get-Item -LiteralPath $zipPath).Length
        PayloadDirectory = $payloadFinal
        LegalFileCount = $expectedLegal.Count
        PayloadFileCount = $payloadNames.Count
        Authenticode = "NotSigned"
    }
}
finally {
    if ($null -ne $msixArchive) { $msixArchive.Dispose() }
    if ($null -ne $msixStream) { $msixStream.Dispose() }
    if ($null -ne $exeStream) { $exeStream.Dispose() }
    if ($payloadStageCreated -and $null -ne $payloadStage) {
        Remove-OwnedStage $payloadStage $payloadStageParent $payloadStageName
    }
    if ($stageCreated) { Remove-OwnedStage $stage $destination $stageName }
}
