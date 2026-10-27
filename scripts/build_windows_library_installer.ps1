#Requires -Version 5.1
<#
.SYNOPSIS
Builds an unsigned Library and project timeline update for Desktop Preview 2.
.NOTES
No application rebuilding, downloads, installation, signing, or remote publication is performed.
Supply the fresh Library payload directory with its BUILD-MANIFEST.json.
No ZIP or build manifest is embedded. -ValidateOnly creates no output or staging.
The default compiler is build\tools\portable\nsis-3.12\makensis.exe and the
default output directory is dist\library-installer.
#>
[CmdletBinding()]
param(
    [string]$PayloadDirectory,
    [string]$BuildManifestPath,
    [ValidateNotNullOrEmpty()][string]$CompilerPath,
    [ValidateNotNullOrEmpty()][string]$DestinationDirectory,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$QaIdentity,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
if ([string]::IsNullOrWhiteSpace($PayloadDirectory)) {
    $PayloadDirectory = Join-Path $repoRoot 'dist\library'
}
if ([string]::IsNullOrWhiteSpace($CompilerPath)) {
    $CompilerPath = Join-Path $repoRoot 'build\tools\portable\nsis-3.12\makensis.exe'
}
if ([string]::IsNullOrWhiteSpace($DestinationDirectory)) {
    $DestinationDirectory = Join-Path $repoRoot 'dist\library-installer'
}
$payload = (Resolve-Path -LiteralPath $PayloadDirectory).ProviderPath.TrimEnd('\')
$compiler = (Resolve-Path -LiteralPath $CompilerPath).ProviderPath
$destination = [IO.Path]::GetFullPath(
    $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestinationDirectory)
)
$destinationRoot = [IO.Path]::GetPathRoot($destination)
if ($destination.Length -gt $destinationRoot.Length) { $destination = $destination.TrimEnd('\', '/') }
if ($QaIdentity) {
    $qaDestination = [IO.Path]::GetFullPath((Join-Path $repoRoot "build\library-qa\$QaIdentity"))
    if (-not $destination.Equals($qaDestination, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'QA installers may only be emitted into their matching isolated library-qa directory.'
    }
}
else {
    $distRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'dist')).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($destination) -ine $distRoot -or (Test-Path -LiteralPath $destination)) {
        throw 'Normal installer output must be a new immediate child of this checkout''s dist directory.'
    }
}
if (-not (Test-Path -LiteralPath $payload -PathType Container)) { throw 'PayloadDirectory must be a directory.' }
if ((Test-Path -LiteralPath $destination) -and -not (Test-Path -LiteralPath $destination -PathType Container)) {
    throw 'DestinationDirectory must be a directory.'
}
$appKey = 'TwoHandsNetwork.RatTrap.DesktopPreview2'
$displayName = 'Rat-Trap Desktop Preview 2'
$installFolder = 'Rat-Trap Desktop Preview 2'
$name = 'Rat-Trap-Library-Windows-x64-setup.exe'
if ($QaIdentity) {
    $appKey += ".QA.$QaIdentity"
    $displayName += " QA $QaIdentity"
    $installFolder += " QA $QaIdentity"
    $name = "Rat-Trap-Library-Windows-x64-setup-QA-$QaIdentity.exe"
}
$finalPath = Join-Path $destination $name
if (Test-Path -LiteralPath $finalPath) { throw "Refusing to overwrite existing installer: $finalPath" }
$protected = @($payload,
    (Join-Path $repoRoot 'dist\5.7.0'), (Join-Path $repoRoot 'dist\msix'),
    (Join-Path $repoRoot 'dist\direct\5.7.0'),
    (Join-Path $repoRoot 'dist\desktop-preview-1'),
    (Join-Path $repoRoot 'dist\desktop-preview-2'),
    (Join-Path $repoRoot 'dist\desktop-preview-2-installer'),
    (Join-Path $repoRoot 'dist\guided-preview'),
    (Join-Path $repoRoot 'dist\guided-preview-installer'),
    (Join-Path $repoRoot 'dist\guided-lessons'),
    (Join-Path $repoRoot 'dist\guided-lessons-installer'),
    (Join-Path $repoRoot 'dist\guided-protection'),
    (Join-Path $repoRoot 'dist\guided-protection-installer'),
    (Join-Path $repoRoot 'rat_trap'), (Join-Path $repoRoot 'packaging'),
    (Join-Path $repoRoot 'release-manifests'))
foreach ($directory in $protected) {
    $directory = [IO.Path]::GetFullPath($directory).TrimEnd('\')
    if ($destination.Equals($directory, [StringComparison]::OrdinalIgnoreCase) -or
        $destination.StartsWith($directory + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Installer output cannot modify a frozen payload or source directory: $directory"
    }
}
if ([string]::IsNullOrWhiteSpace($BuildManifestPath)) {
    $BuildManifestPath = Join-Path $payload 'BUILD-MANIFEST.json'
}
$manifestPath = (Resolve-Path -LiteralPath $BuildManifestPath).ProviderPath
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -cne 'rat-trap-library-build/v1' -or
    $manifest.product -cne 'Rat-Trap Desktop Preview 2' -or
    $manifest.version -cne '5.7.0-desktop-preview.2-library.1' -or
    $manifest.installer_version -cne '5.7.0.7' -or
    $manifest.app_key -cne 'TwoHandsNetwork.RatTrap.DesktopPreview2' -or
    $manifest.signature -cne 'NotSigned' -or $manifest.payload_files -lt 25 -or $manifest.legal_files -lt 20) {
    throw 'Expected a complete clean-source Library build receipt.'
}
$exeName = 'Rat-Trap-Desktop-Preview-2.exe'
if ($manifest.executable -cne $exeName -or [long]$manifest.executable_bytes -le 0 -or
    $manifest.executable_sha256 -cnotmatch '^[A-F0-9]{64}$' -or
    $manifest.executable_sha256 -cin @(
        '977A6012ED9C126009582D2AAA1C696901938E5D60B0D85E7D2EEA47E2EEB023',
        '98E935A747C8853E71195ACFCA96A6354FDA44C4468CAC85E4DDAFC0FCE35C7D',
        'F64290DA170C91A7417BF35CD06EDEFB580464D8586C071BD0C8A355C251C6AC',
        'C2F26CAA509D6F5ED887E0E839DDEA6095341A6DD0A0C1D29097BFEF42A3324F',
        '2FDBC470CA51E04E7F38459F0C58089BF487965333C6AE21B6E2886CB14AF273')) {
    throw 'The Library receipt must describe a new tutorial executable, not a historical binary.'
}
$exeRecord = [pscustomobject]@{
    bytes = [long]$manifest.executable_bytes
    sha256 = [string]$manifest.executable_sha256
}
$expectedFiles = @($manifest.payload_sha256.PSObject.Properties.Name)
$requiredFiles = @($exeName, 'PRIVACY.md', 'SUPPORT.md', 'README-FIRST.txt', 'SHA256SUMS.txt',
    'Legal/LICENSE.md', 'Legal/COMMERCIAL-LICENSE.md', 'Legal/NOTICE.md',
    'Legal/COMPONENTS.json', 'Legal/THIRD-PARTY-NOTICES.md')
foreach ($relative in $requiredFiles) {
    if ($relative -cnotin $expectedFiles) { throw "Required payload input missing: $relative" }
}
if (@($expectedFiles | Where-Object { $_ -cnotin $requiredFiles -and -not $_.StartsWith('Legal/', [StringComparison]::Ordinal) }).Count -gt 0) {
    throw 'Only application/policy/checksum files and Legal documents may be installed.'
}
$manifestHashes = @{}
foreach ($property in $manifest.payload_sha256.PSObject.Properties) {
    if ($property.Name -notmatch '^[a-zA-Z0-9_./-]+$' -or
        $property.Name -match '(^|/)\.\.?(/|$)' -or $property.Name.StartsWith('/') -or
        $property.Value -cnotmatch '^[A-F0-9]{64}$' -or $manifestHashes.ContainsKey($property.Name)) {
        throw 'Unsafe or duplicate preview manifest payload record.'
    }
    $manifestHashes.Add($property.Name, [string]$property.Value)
}
if ($manifestHashes.Count -ne [int]$manifest.payload_files -or
    @($manifestHashes.Keys | Where-Object {$_.StartsWith('Legal/', [StringComparison]::Ordinal)}).Count -ne [int]$manifest.legal_files) {
    throw 'Library receipt inventory count mismatch.'
}
$allItems = @(Get-ChildItem -LiteralPath $payload -Recurse -Force)
if (((Get-Item -LiteralPath $payload).Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    @($allItems | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0) {
    throw 'Linked payload files and directories are not supported.'
}
$actualFiles = @($allItems | Where-Object { -not $_.PSIsContainer } | ForEach-Object {
    $_.FullName.Substring($payload.Length + 1).Replace('\', '/')
})
$sourceHashes = @{}
foreach ($relative in $expectedFiles) {
    $path = Join-Path $payload $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $manifestHashes[$relative]) {
        throw "Frozen preview payload checksum mismatch: $relative"
    }
    $sourceHashes.Add($path, $manifestHashes[$relative])
}
if ((Get-Item -LiteralPath (Join-Path $payload $exeName)).Length -ne $exeRecord.bytes -or
    $manifestHashes[$exeName] -cne $exeRecord.sha256) {
    throw 'Installer payload does not contain the byte-identical Preview 2 executable.'
}
$allowedFiles = @($expectedFiles)
if ('BUILD-MANIFEST.json' -cin $actualFiles) {
    $localReceipt = Join-Path $payload 'BUILD-MANIFEST.json'
    if ((Get-FileHash -LiteralPath $localReceipt -Algorithm SHA256).Hash -cne
        (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash) {
        throw 'The payload build manifest differs from the selected Library receipt.'
    }
    $allowedFiles += 'BUILD-MANIFEST.json'
}
if (@(Compare-Object -CaseSensitive ($allowedFiles | Sort-Object) ($actualFiles | Sort-Object)).Count -ne 0) {
    throw 'Unexpected file in Library payload; only its build receipt is excluded from installation.'
}
$appVersion = (Get-Item -LiteralPath (Join-Path $payload $exeName)).VersionInfo
if ($appVersion.FileVersion -cne '5.7.0.7' -or
    $appVersion.ProductVersion -cne '5.7.0-desktop-preview.2-library.1' -or
    $appVersion.ProductName -cne 'Rat-Trap Desktop Preview 2' -or
    $appVersion.CompanyName -cne 'TWO HANDS NETWORK LTD' -or
    [string](Get-AuthenticodeSignature -LiteralPath (Join-Path $payload $exeName)).Status -cne 'NotSigned') {
    throw 'Guided application metadata does not match the expected unsigned tutorial update.'
}
$checksums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $payload 'SHA256SUMS.txt')) {
    if ($line -cnotmatch '^([A-F0-9]{64})  (.+)$') { throw 'Malformed frozen payload checksum line.' }
    $relative = $Matches[2]
    if ($relative -cnotin $expectedFiles -or $relative -ceq 'SHA256SUMS.txt' -or $checksums.ContainsKey($relative)) {
        throw 'Unexpected or duplicate frozen checksum path.'
    }
    $checksums.Add($relative, $Matches[1])
}
foreach ($relative in $expectedFiles | Where-Object { $_ -cne 'SHA256SUMS.txt' }) {
    if (-not $checksums.ContainsKey($relative) -or $checksums[$relative] -cne $manifestHashes[$relative]) {
        throw "Frozen checksum inventory disagrees with the release manifest: $relative"
    }
}
if ($checksums.Count -ne ($expectedFiles.Count - 1)) { throw 'Incomplete frozen checksum inventory.' }

# Check the pinned local compiler before executing even its version query.
if ((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash -cne
    'B043E554AFEFBFC56315669D0B4779793AEAE67F0F2A7A790E2EA91F05298EFF') {
    throw 'The compiler differs from the recorded NSIS 3.12 portable compiler.'
}
$compilerVersion = (& $compiler /VERSION | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $compilerVersion -cne 'v3.12') { throw 'NSIS 3.12 is required.' }
$compilerLicence = Join-Path (Split-Path -Parent $compiler) 'COPYING'
$guide = Join-Path $repoRoot 'packaging\direct\README-LIBRARY-INSTALLER.txt'
$nsi = Join-Path $repoRoot 'packaging\direct\rat-trap-library.nsi'
$icon = Join-Path $repoRoot 'packaging\branding\rat-trap.ico'
foreach ($path in @($compiler, $compilerLicence, $guide, $nsi, $icon, $manifestPath, $PSCommandPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required installer input is missing: $path" }
    $sourceHashes.Add($path, (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash)
}
if ($sourceHashes[$compilerLicence] -cne '388357C1215FF403C5EBDE3A5ECD273E68F8B79A579996775245D1EE65442ABA') {
    throw 'The NSIS COPYING file differs from the recorded local NSIS 3.12 licence.'
}
if ($ValidateOnly) {
    [pscustomobject]@{
        Preflight = 'Passed'; Built = $false; Installer = $finalPath
        AppKey = $appKey; InstallFolder = $installFolder; DisplayName = $displayName
        Version = '5.7.0.7'; Executable = $exeName; ExecutableSha256 = $exeRecord.sha256
        FrozenPayloadFiles = $expectedFiles.Count; PayloadFiles = ($expectedFiles.Count + 2); Compiler = $compilerVersion
        Signed = $false; QaIdentity = $QaIdentity
    } | ConvertTo-Json
    return
}

[void][IO.Directory]::CreateDirectory($destination)
$stageParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$stageName = '.rt-library-setup-' + [guid]::NewGuid().ToString('N')
$stage = Join-Path $stageParent $stageName
if (Test-Path -LiteralPath $stage) { throw "Staging collision: $stage" }
[void](New-Item -ItemType Directory -Path $stage)
$pendingOutput = Join-Path $destination ('.rt-library-publish-' + [guid]::NewGuid().ToString('N') + '.exe')
$pendingOwned = $false
$stagePayload = Join-Path $stage 'payload'
$utf8 = New-Object Text.UTF8Encoding($false)
try {
    [void][IO.Directory]::CreateDirectory($stagePayload)
    # Copy explicit verified files only, never the portable ZIP or other input.
    foreach ($relative in $expectedFiles) {
        $target = Join-Path $stagePayload $relative
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        [IO.File]::Copy((Join-Path $payload $relative), $target, $false)
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -cne $manifestHashes[$relative]) {
            throw "Staged preview file differs from the frozen manifest: $relative"
        }
    }
    [IO.File]::Move((Join-Path $stagePayload 'README-FIRST.txt'), (Join-Path $stagePayload 'README-PORTABLE.txt'))
    [IO.File]::Copy($guide, (Join-Path $stagePayload 'README-FIRST.txt'), $false)
    [IO.File]::Copy($compilerLicence, (Join-Path $stagePayload 'Legal\NSIS-3.12-COPYING.txt'), $false)
    $files = @(Get-ChildItem -LiteralPath $stagePayload -Recurse -File | Sort-Object FullName)
    if ($files.Count -ne ($expectedFiles.Count + 2)) { throw 'Unexpected installer payload inventory.' }
    $checksumLines = @($files | Where-Object { $_.FullName -cne (Join-Path $stagePayload 'SHA256SUMS.txt') } |
        ForEach-Object {
            '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash,
                $_.FullName.Substring($stagePayload.Length + 1).Replace('\', '/')
        })
    [IO.File]::WriteAllLines((Join-Path $stagePayload 'SHA256SUMS.txt'), $checksumLines, $utf8)
    $files = @(Get-ChildItem -LiteralPath $stagePayload -Recurse -File | Sort-Object FullName)
    $stageHashes = @{}
    $installLines = New-Object 'Collections.Generic.List[string]'
    $uninstallLines = New-Object 'Collections.Generic.List[string]'
    $checkLines = New-Object 'Collections.Generic.List[string]'
    $checkFileLines = New-Object 'Collections.Generic.List[string]'
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($stagePayload.Length + 1)
        if ($relative -notmatch '^[a-zA-Z0-9_.\\/-]+$' -or $relative -match '(^|\\)\.\.(\\|$)') {
            throw "Unsafe installer payload name: $relative"
        }
        $stageHashes.Add($file.FullName, (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash)
        $parent = Split-Path -Parent $relative
        $suffix = if ($parent) { '\' + $parent } else { '' }
        $installLines.Add('SetOutPath "$INSTDIR' + $suffix + '"')
        $installLines.Add('!insertmacro CheckWrite')
        $installLines.Add('File "${PAYLOAD_DIR}\' + $relative + '"')
        $installLines.Add('!insertmacro CheckWrite')
        $uninstallLines.Add('ClearErrors')
        $uninstallLines.Add('Delete "$INSTDIR\' + $relative + '"')
        $uninstallLines.Add('IfErrors uninstall_failed')
        $checkFileLines.Add('!insertmacro CheckFileUnlocked "$INSTDIR\' + $relative + '"')
    }
    $directories = @(Get-ChildItem -LiteralPath $stagePayload -Recurse -Directory |
        ForEach-Object { $_.FullName.Substring($stagePayload.Length + 1) })
    foreach ($directory in $directories | Sort-Object Length -Descending) {
        $uninstallLines.Add('RMDir "$INSTDIR\' + $directory + '"')
        $checkLines.Add('!insertmacro CheckDirectory "$INSTDIR\' + $directory + '"')
    }
    $installInclude = Join-Path $stage 'install.nsh'
    $uninstallInclude = Join-Path $stage 'uninstall.nsh'
    $checkInclude = Join-Path $stage 'directories.nsh'
    $checkFilesInclude = Join-Path $stage 'check-files.nsh'
    [IO.File]::WriteAllLines($installInclude, $installLines, $utf8)
    [IO.File]::WriteAllLines($uninstallInclude, $uninstallLines, $utf8)
    [IO.File]::WriteAllLines($checkInclude, $checkLines, $utf8)
    [IO.File]::WriteAllLines($checkFilesInclude, $checkFileLines, $utf8)
    $stageInstaller = Join-Path $stage $name
    $installedKib = [int][Math]::Ceiling(($files | Measure-Object -Property Length -Sum).Sum / 1024.0) + 128
    $arguments = @('/NOCONFIG', '/V3', '/WX',
        "/DAPP_KEY=$appKey", "/DDISPLAY_NAME=$displayName", "/DINSTALL_FOLDER=$installFolder",
        "/DPAYLOAD_DIR=$stagePayload", "/DOUTPUT_FILE=$stageInstaller", "/DINSTALLED_KIB=$installedKib",
        "/DINSTALL_FILES_INCLUDE=$installInclude", "/DUNINSTALL_FILES_INCLUDE=$uninstallInclude",
        "/DCHECK_DIRS_INCLUDE=$checkInclude", "/DCHECK_FILES_INCLUDE=$checkFilesInclude",
        "/DAPP_ICON=$icon", $nsi)
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $stageInstaller -PathType Leaf)) {
        throw 'Guided installer compilation failed.'
    }
    $installerInfo = Get-Item -LiteralPath $stageInstaller
    if ($installerInfo.Length -le 0 -or $installerInfo.VersionInfo.FileVersion -cne '5.7.0.7' -or
        $installerInfo.VersionInfo.ProductVersion -cne '5.7.0.7' -or
        $installerInfo.VersionInfo.ProductName -cne "$displayName Setup" -or
        [string](Get-AuthenticodeSignature -LiteralPath $stageInstaller).Status -cne 'NotSigned') {
        throw 'The compiled installer lacks the expected unsigned Preview 2 identity.'
    }
    foreach ($path in $sourceHashes.Keys) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $sourceHashes[$path]) {
            throw "A frozen payload or packaging input changed during compilation: $path"
        }
    }
    foreach ($path in $stageHashes.Keys) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $stageHashes[$path]) {
            throw "A staged payload file changed during compilation: $path"
        }
    }
    # Short compiler path, then a completed same-directory no-overwrite move.
    $installerHash = (Get-FileHash -LiteralPath $stageInstaller -Algorithm SHA256).Hash
    [IO.File]::Copy($stageInstaller, $pendingOutput, $false)
    $pendingOwned = $true
    if ((Get-FileHash -LiteralPath $pendingOutput -Algorithm SHA256).Hash -cne $installerHash) {
        throw 'Installer changed while being copied for publication.'
    }
    [IO.File]::Move($pendingOutput, $finalPath)
    $pendingOwned = $false
    [pscustomobject]@{
        Installer = $finalPath; Bytes = (Get-Item -LiteralPath $finalPath).Length
        Sha256 = $installerHash; Signed = $false; AppKey = $appKey
        InstallFolder = $installFolder; DisplayName = $displayName; Version = '5.7.0.7'
        PayloadFiles = $files.Count; Compiler = $compilerVersion; QaIdentity = $QaIdentity
        ExecutableSha256 = $exeRecord.sha256
    } | ConvertTo-Json
}
finally {
    if (Test-Path -LiteralPath $stage) {
        $resolvedStage = (Resolve-Path -LiteralPath $stage).ProviderPath
        $expectedStage = [IO.Path]::GetFullPath((Join-Path $stageParent $stageName))
        if (-not $resolvedStage.Equals($expectedStage, [StringComparison]::OrdinalIgnoreCase) -or
            -not $resolvedStage.StartsWith($stageParent + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $stageName -notmatch '^\.rt-library-setup-[a-f0-9]{32}$') {
            throw "Refusing cleanup outside this build's exact staging directory: $stage"
        }
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
    if ($pendingOwned -and (Test-Path -LiteralPath $pendingOutput)) {
        Remove-Item -LiteralPath $pendingOutput -Force
    }
}


