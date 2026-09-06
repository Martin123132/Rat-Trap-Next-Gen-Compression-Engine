[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PayloadDirectory,
    [Parameter(Mandatory = $true)][string]$CompilerPath,
    [Parameter(Mandatory = $true)][string]$DestinationDirectory,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$QaIdentity
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$payload = (Resolve-Path -LiteralPath $PayloadDirectory).Path
$compiler = (Resolve-Path -LiteralPath $CompilerPath).Path
$destination = [IO.Path]::GetFullPath($DestinationDirectory)
$baseline = Get-Content -LiteralPath (Join-Path $repoRoot 'release-manifests\5.7.0.json') -Raw | ConvertFrom-Json
$exeRecord = @($baseline.artifacts | Where-Object { $_.name -eq 'Rat-Trap.exe' })[0]
$executable = Join-Path $payload 'Rat-Trap.exe'
if ((Get-Item -LiteralPath $executable).Length -ne $exeRecord.bytes -or
    (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash -cne $exeRecord.sha256) {
    throw 'Installer payload does not contain the frozen 5.7.0 executable.'
}
$expectedFiles = @('Rat-Trap.exe', 'PRIVACY.md', 'SUPPORT.md', 'README-FIRST.txt', 'SHA256SUMS.txt') +
    @($baseline.msix_inventory | Where-Object { $_.path.StartsWith('Legal/') } | ForEach-Object { $_.path })
$allItems = @(Get-ChildItem -LiteralPath $payload -Recurse -Force)
if (@($allItems | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0 -or
    ((Get-Item -LiteralPath $payload).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Linked payload files and directories are not supported.'
}
$actualFiles = @($allItems | Where-Object { -not $_.PSIsContainer } | ForEach-Object {
    $_.FullName.Substring($payload.Length + 1).Replace('\', '/')
})
if (@(Compare-Object ($expectedFiles | Sort-Object) ($actualFiles | Sort-Object)).Count -ne 0) {
    throw 'Payload file inventory differs from the portable beta contract.'
}
$checksums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $payload 'SHA256SUMS.txt')) {
    if ($line -notmatch '^([A-Fa-f0-9]{64})  (.+)$') { throw 'Malformed payload checksum line.' }
    $relative = $Matches[2]
    if ($relative -notin $expectedFiles -or $checksums.ContainsKey($relative)) { throw 'Unexpected or duplicate checksum path.' }
    $checksums[$relative] = $Matches[1]
}
foreach ($relative in $actualFiles | Where-Object { $_ -ne 'SHA256SUMS.txt' }) {
    if (-not $checksums.ContainsKey($relative) -or
        (Get-FileHash -LiteralPath (Join-Path $payload $relative) -Algorithm SHA256).Hash -ne $checksums[$relative]) {
        throw "Payload checksum mismatch: $relative"
    }
}
if ($checksums.Count -ne $actualFiles.Count - 1) { throw 'Incomplete checksum inventory.' }
$compilerVersion = (& $compiler /VERSION | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $compilerVersion -ne 'v3.12') { throw 'NSIS 3.12 is required.' }
if ((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash -ne 'B043E554AFEFBFC56315669D0B4779793AEAE67F0F2A7A790E2EA91F05298EFF') {
    throw 'The compiler differs from the recorded official NSIS 3.12 portable compiler.'
}
$compilerLicence = Join-Path (Split-Path -Parent $compiler) 'COPYING'
if (-not (Test-Path -LiteralPath $compilerLicence -PathType Leaf)) { throw 'NSIS licence is missing.' }

$appKey = 'TwoHandsNetwork.RatTrap.Beta'
$displayName = 'Rat-Trap Beta'
$installFolder = 'Rat-Trap Beta'
$name = 'Rat-Trap-Windows-5.7.0-beta-setup.exe'
if ($QaIdentity) {
    $appKey += ".QA.$QaIdentity"
    $displayName += " QA $QaIdentity"
    $installFolder += " QA $QaIdentity"
    $name = "Rat-Trap-Windows-5.7.0-beta-setup-QA-$QaIdentity.exe"
}
[IO.Directory]::CreateDirectory($destination) | Out-Null
$finalPath = Join-Path $destination $name
if (Test-Path -LiteralPath $finalPath) { throw "Refusing to overwrite existing installer: $finalPath" }
$stageParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$stage = Join-Path $stageParent ('.rat-trap-setup-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($stage) | Out-Null
$pendingOutput = Join-Path $destination ('.rat-trap-publish-' + [guid]::NewGuid().ToString('N') + '.exe')
$stagePayload = Join-Path $stage 'payload'
$utf8 = New-Object Text.UTF8Encoding($false)
try {
    Copy-Item -LiteralPath $payload -Destination $stagePayload -Recurse
    Copy-Item -LiteralPath $compilerLicence -Destination (Join-Path $stagePayload 'Legal\NSIS-3.12-COPYING.txt')
    $files = @(Get-ChildItem -LiteralPath $stagePayload -Recurse -File | Sort-Object FullName)
    $checksumLines = @($files | Where-Object { $_.Name -ne 'SHA256SUMS.txt' } | ForEach-Object {
        '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($stagePayload.Length + 1).Replace('\', '/')
    })
    [IO.File]::WriteAllLines((Join-Path $stagePayload 'SHA256SUMS.txt'), $checksumLines, $utf8)
    $files = @(Get-ChildItem -LiteralPath $stagePayload -Recurse -File | Sort-Object FullName)
    $installLines = New-Object 'Collections.Generic.List[string]'
    $uninstallLines = New-Object 'Collections.Generic.List[string]'
    $checkLines = New-Object 'Collections.Generic.List[string]'
    $checkFileLines = New-Object 'Collections.Generic.List[string]'
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($stagePayload.Length + 1)
        if ($relative -notmatch '^[a-zA-Z0-9_.\\/-]+$' -or $relative -match '(^|\\)\.\.(\\|$)') { throw "Unsafe installer payload name: $relative" }
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
    $directories = @(Get-ChildItem -LiteralPath $stagePayload -Recurse -Directory | ForEach-Object { $_.FullName.Substring($stagePayload.Length + 1) })
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
        "/DINSTALL_FILES_INCLUDE=$installInclude", "/DUNINSTALL_FILES_INCLUDE=$uninstallInclude", "/DCHECK_DIRS_INCLUDE=$checkInclude",
        "/DCHECK_FILES_INCLUDE=$checkFilesInclude",
        ('/DAPP_ICON=' + (Join-Path $repoRoot 'packaging\branding\rat-trap.ico')),
        (Join-Path $repoRoot 'packaging\direct\rat-trap-beta.nsi'))
    & $compiler @arguments
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $stageInstaller -PathType Leaf)) { throw 'Installer compilation failed.' }
    # Compile under a short temporary path for NSIS's legacy path limit, then
    # publish by a completed same-directory move at the requested destination.
    [IO.File]::Copy($stageInstaller, $pendingOutput, $false)
    [IO.File]::Move($pendingOutput, $finalPath)
    [pscustomobject]@{
        Installer = $finalPath; Bytes = (Get-Item -LiteralPath $finalPath).Length
        Sha256 = (Get-FileHash -LiteralPath $finalPath -Algorithm SHA256).Hash
        Signed = $false; AppKey = $appKey; InstallFolder = $installFolder
        PayloadFiles = $files.Count; Compiler = $compilerVersion; QaIdentity = $QaIdentity
    } | ConvertTo-Json
}
finally {
    $resolvedStage = [IO.Path]::GetFullPath($stage)
    if ($resolvedStage.StartsWith($stageParent + '\.rat-trap-setup-', [StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedStage)) {
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
    if (Test-Path -LiteralPath $pendingOutput) {
        Remove-Item -LiteralPath $pendingOutput -Force
    }
}
