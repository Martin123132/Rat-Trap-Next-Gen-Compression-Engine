[CmdletBinding()]
param(
    [string]$OutputsDir,
    [string]$FixtureFolder,
    [switch]$SkipFolderSelfTest
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputsDir)) {
    $thinRoot = (Get-Item -LiteralPath $repoRoot).Parent.Parent.FullName
    $OutputsDir = Join-Path $thinRoot "outputs"
}
if ([string]::IsNullOrWhiteSpace($FixtureFolder)) {
    $FixtureFolder = Join-Path (Get-Item -LiteralPath $repoRoot).Parent.FullName "Rat-Trap-Beta-Test-Data"
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Assert-Artifact {
    param(
        [string]$Path,
        [object]$Artifact
    )
    Assert-True (Test-Path -LiteralPath $Path -PathType Leaf) "Missing baseline artifact: $Path"
    $actualSize = (Get-Item -LiteralPath $Path).Length
    Assert-True ($actualSize -eq [long]$Artifact.bytes) "Size mismatch for '$Path'. Expected $($Artifact.bytes), got $actualSize"
    $actualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    Assert-True ($actualHash -eq $Artifact.sha256) "SHA-256 mismatch for '$Path'. Expected $($Artifact.sha256), got $actualHash"
    Write-Host "ARTIFACT PASS  $([IO.Path]::GetFileName($Path))"
}

function Get-TreeEvidence {
    param([string]$Folder)

    $root = (Resolve-Path -LiteralPath $Folder).Path.TrimEnd("\")
    $prefix = $root + "\"
    [string[]]$relativePaths = @(
        Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
            Assert-True ($_.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) "File escaped fixture root: $($_.FullName)"
            $_.FullName.Substring($prefix.Length).Replace("\", "/")
        }
    )
    # pathlib.WindowsPath sorting, used by the benchmark and packaged
    # self-test, compares paths case-insensitively on Windows.
    [Array]::Sort($relativePaths, [StringComparer]::OrdinalIgnoreCase)

    $sha = [Security.Cryptography.SHA256]::Create()
    [long]$totalBytes = 0
    try {
        foreach ($relative in $relativePaths) {
            $relativeBytes = [Text.Encoding]::UTF8.GetBytes($relative)
            $lengthBytes = [BitConverter]::GetBytes([uint32]$relativeBytes.Length)
            if (-not [BitConverter]::IsLittleEndian) {
                [Array]::Reverse($lengthBytes)
            }
            $null = $sha.TransformBlock($lengthBytes, 0, $lengthBytes.Length, $lengthBytes, 0)
            $null = $sha.TransformBlock($relativeBytes, 0, $relativeBytes.Length, $relativeBytes, 0)

            $nativeRelative = $relative.Replace("/", "\")
            $stream = [IO.File]::OpenRead((Join-Path $root $nativeRelative))
            try {
                $buffer = New-Object byte[] (1024 * 1024)
                while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $null = $sha.TransformBlock($buffer, 0, $read, $buffer, 0)
                    $totalBytes += $read
                }
            }
            finally {
                $stream.Dispose()
            }
        }
        $empty = New-Object byte[] 0
        $null = $sha.TransformFinalBlock($empty, 0, 0)
        $digest = [BitConverter]::ToString($sha.Hash).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }

    return [PSCustomObject]@{
        sha256 = $digest
        total_bytes = $totalBytes
        file_count = $relativePaths.Count
    }
}

$manifestPath = Join-Path $repoRoot "release-manifests\5.1.0.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
Assert-True ($manifest.version -eq "5.1.0") "Release manifest version is not 5.1.0"

$pyproject = Get-Content -LiteralPath (Join-Path $repoRoot "pyproject.toml") -Raw
Assert-True ($pyproject -match '(?m)^version = "5\.1\.0"$') "pyproject.toml is not version 5.1.0"

$windowsApp = Get-Content -LiteralPath (Join-Path $repoRoot "rat_trap\windows_app.py") -Raw
Assert-True ($windowsApp -match '(?m)^APP_VERSION = "5\.1\.0"$') "Windows APP_VERSION is not 5.1.0"
Write-Host "VERSION PASS  source declarations"

$requiredArtifacts = @(
    "Rat-Trap.exe",
    "Rat-Trap-Windows-5.1.0.zip",
    "Rat-Trap-Beta-Test-Data.zip",
    "Rat-Trap-Beta-Structured-Vault-5.1.gmw",
    "Rat-Trap-Beta-Categories-baseline.json",
    "Rat-Trap-Beta-Categories-hybrid.json",
    "Rat-Trap-Beta-4.4-final.json",
    "Rat-Trap-Vault-Beta-benchmark.json",
    "Rat-Trap-Structured-Beta-benchmark.json"
)
$manifestNames = @($manifest.artifacts | ForEach-Object { $_.name })
Assert-True (($manifestNames | Select-Object -Unique).Count -eq $manifestNames.Count) "Release manifest contains duplicate artifact names"
Assert-True ((@($manifestNames | Sort-Object) -join "`n") -eq (@($requiredArtifacts | Sort-Object) -join "`n")) "Release manifest artifact set is incomplete or unexpected"

$exePath = Join-Path $repoRoot "dist\Rat-Trap.exe"
$exeArtifact = $manifest.artifacts | Where-Object { $_.name -eq "Rat-Trap.exe" }
$exeHash = $exeArtifact.sha256
foreach ($artifact in $manifest.artifacts) {
    $artifactPath = if ($artifact.name -eq "Rat-Trap.exe") {
        $exePath
    }
    else {
        Join-Path $OutputsDir $artifact.name
    }
    Assert-Artifact $artifactPath $artifact
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$releaseArtifact = $manifest.artifacts | Where-Object { $_.name -eq "Rat-Trap-Windows-5.1.0.zip" }
$releaseZip = Join-Path $OutputsDir $releaseArtifact.name
$zip = [IO.Compression.ZipFile]::OpenRead($releaseZip)
try {
    $entries = @($zip.Entries)
    Assert-True (@($entries | Where-Object { [string]::IsNullOrEmpty($_.Name) }).Count -eq 0) "Release ZIP contains unexpected directory entries"
    $releaseRoot = "Rat-Trap-Windows-$($manifest.version)"
    $actualInventory = @($entries | ForEach-Object { $_.FullName.Replace("\", "/") })
    $expectedInventory = @($manifest.release_zip_inventory | ForEach-Object { "$releaseRoot/$_" })
    Assert-True (($actualInventory | Select-Object -Unique).Count -eq $actualInventory.Count) "Release ZIP contains duplicate full paths"
    Assert-True ((@($actualInventory | Sort-Object) -join "`n") -eq (@($expectedInventory | Sort-Object) -join "`n")) "Release ZIP full-path inventory differs from the manifest"

    $exeEntry = $entries | Where-Object { $_.FullName.Replace("\", "/") -eq "$releaseRoot/Rat-Trap.exe" }
    Assert-True ($null -ne $exeEntry) "Release ZIP does not contain Rat-Trap.exe"
    $entryStream = $exeEntry.Open()
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $entryHashBytes = $sha.ComputeHash($entryStream)
        }
        finally {
            $sha.Dispose()
        }
    }
    finally {
        $entryStream.Dispose()
    }
    $entryHash = [BitConverter]::ToString($entryHashBytes).Replace("-", "")
    Assert-True ($entryHash -eq $exeHash) "Rat-Trap.exe inside the release ZIP has the wrong hash"
    Write-Host "ZIP PASS   13-file inventory and internal executable"
}
finally {
    $zip.Dispose()
}

$signature = Get-AuthenticodeSignature -LiteralPath $exePath
Assert-True ($signature.Status -eq "NotSigned") "Preserved executable signature status changed from NotSigned to $($signature.Status)"
Write-Host "TRUST NOTE Preserved 5.1 executable is not Authenticode-signed"

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
Assert-True (Test-Path -LiteralPath $python -PathType Leaf) "Missing preserved virtual environment Python: $python"
Push-Location $repoRoot
try {
    & $python -m unittest discover -s tests -v
    Assert-True ($LASTEXITCODE -eq 0) "Python unit tests failed with exit code $LASTEXITCODE"
}
finally {
    Pop-Location
}
Write-Host "TEST PASS  Python unit suite"

$selfTest = Start-Process -FilePath $exePath -ArgumentList @("--self-test") -Wait -PassThru -WindowStyle Hidden
Assert-True ($selfTest.ExitCode -eq 0) "Packaged self-test failed with exit code $($selfTest.ExitCode)"
Write-Host "TEST PASS  Packaged self-test"

if (-not $SkipFolderSelfTest) {
    Assert-True (Test-Path -LiteralPath $FixtureFolder -PathType Container) "Missing beta fixture folder: $FixtureFolder"
    $fixtureExpected = $manifest.verification.packaged_folder_test.fixture
    Assert-True ($null -ne $fixtureExpected) "Release manifest does not define packaged-folder fixture evidence"
    $fixtureActual = Get-TreeEvidence $FixtureFolder
    Assert-True ($fixtureActual.file_count -eq [int]$fixtureExpected.file_count) "Beta fixture file count mismatch. Expected $($fixtureExpected.file_count), got $($fixtureActual.file_count)"
    Assert-True ($fixtureActual.total_bytes -eq [long]$fixtureExpected.total_bytes) "Beta fixture byte count mismatch. Expected $($fixtureExpected.total_bytes), got $($fixtureActual.total_bytes)"
    Assert-True ($fixtureActual.sha256 -eq $fixtureExpected.tree_sha256) "Beta fixture tree SHA-256 mismatch. Expected $($fixtureExpected.tree_sha256), got $($fixtureActual.sha256)"
    Write-Host "FIXTURE PASS  Exact 464-file beta corpus"
    $quotedFixture = '"' + $FixtureFolder + '"'
    $folderTest = Start-Process -FilePath $exePath -ArgumentList @("--self-test-folder", $quotedFixture) -Wait -PassThru -WindowStyle Hidden
    Assert-True ($folderTest.ExitCode -eq 0) "Packaged folder self-test failed with exit code $($folderTest.ExitCode)"
    Write-Host "TEST PASS  Packaged folder self-test (fast, balanced, smallest, vault)"
}

Write-Host ""
Write-Host "Rat-Trap 5.1.0 baseline verification PASSED."
