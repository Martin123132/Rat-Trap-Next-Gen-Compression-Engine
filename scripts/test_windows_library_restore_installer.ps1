[CmdletBinding()]
param(
    [string]$PayloadDirectory,
    [string]$OldPayloadDirectory,
    [string]$BuildManifestPath,
    [string]$CompilerPath,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$QaIdentity = ([guid]::NewGuid().ToString('N'))
)

# Adapted from the frozen guided tutorial lifecycle harness; the old harness is unchanged.
# Installs old 5.7.0.9, then upgrades the SAME fresh QA identity to 5.7.0.10.
# The normal Desktop Preview 2 identity is observed only, never installed or removed.
# Destructive lifecycle checks run only against a freshly generated QA identity.
# This is a same-host test, not evidence of a clean Windows VM or SmartScreen UX.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($PayloadDirectory)) { $PayloadDirectory = Join-Path $PSScriptRoot '..\dist\library' }
if ([string]::IsNullOrWhiteSpace($OldPayloadDirectory)) { $OldPayloadDirectory = Join-Path $PSScriptRoot '..\dist\library-search-1a15bb1d817' }
if ([string]::IsNullOrWhiteSpace($BuildManifestPath)) { $BuildManifestPath = Join-Path $PayloadDirectory 'BUILD-MANIFEST.json' }
if ([string]::IsNullOrWhiteSpace($CompilerPath)) { $CompilerPath = Join-Path $PSScriptRoot '..\build\tools\portable\nsis-3.12\makensis.exe' }
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$qaRoot = Join-Path $repoRoot "build\library-qa\$QaIdentity"
$appKey = "TwoHandsNetwork.RatTrap.DesktopPreview2.QA.$QaIdentity"
$displayName = "Rat-Trap Desktop Preview 2 QA $QaIdentity"
$installRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "Programs\Two Hands Network Ltd\$displayName"
$menuRoot = Join-Path ([Environment]::GetFolderPath('Programs')) $displayName
$desktopLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) "$displayName.lnk"
$arpPath = "Software\Microsoft\Windows\CurrentVersion\Uninstall\$appKey"
$currentUser = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
$localMachine = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$checks = New-Object 'Collections.Generic.List[object]'
$cleanupErrors = New-Object 'Collections.Generic.List[string]'
$retainedFiles = @{}
$sentinelNames = @{ '.gmw' = "RatTrapDesktopPreview2InstallerQA.Other.$QaIdentity.GMW"; '.rtsf' = "RatTrapDesktopPreview2InstallerQA.Other.$QaIdentity.RTSF" }
$createdRegistryParents = New-Object 'Collections.Generic.List[string]'
$payloadFiles = @()
$observedProgIds = @()
$testedSourceHashes = @()
$buildResult = $null
$oldBuildResult = $null
$failure = $null
$testStarted = [DateTime]::UtcNow
$reportPath = Join-Path $qaRoot 'lifecycle-report.json'
$allowCleanup = $false
$oldReleasePath = Join-Path $repoRoot 'release-manifests\library-search.json'
$oldRelease = Get-Content -LiteralPath $oldReleasePath -Raw | ConvertFrom-Json
$oldReceiptPath = Join-Path $OldPayloadDirectory 'BUILD-MANIFEST.json'
$previewManifest = Get-Content -LiteralPath $oldReceiptPath -Raw | ConvertFrom-Json
$expectedExeRecords = @($oldRelease.artifacts | Where-Object { $_.path -ceq 'dist/library-search-1a15bb1d817/Rat-Trap-Desktop-Preview-2.exe' })
if ($expectedExeRecords.Count -ne 1 -or
    $oldRelease.schema -cne 'rat-trap-library-search-release/v1' -or
    $oldRelease.application_version -cne '5.7.0-desktop-preview.2-library.3' -or
    $oldRelease.installer_version -cne '5.7.0.9') {
    throw 'Expected the frozen Library preview release and its one pinned executable.'
}
$expectedExe = $expectedExeRecords[0]
if ($previewManifest.schema -cne 'rat-trap-library-build/v1' -or
    $previewManifest.version -cne '5.7.0-desktop-preview.2-library.3' -or
    $previewManifest.installer_version -cne '5.7.0.9' -or
    $previewManifest.executable_sha256 -cne $expectedExe.sha256 -or
    [long]$previewManifest.executable_bytes -ne [long]$expectedExe.bytes) {
    throw 'The old private receipt does not match the recorded Library preview executable.'
}
$oldManifest = $previewManifest
$oldExpectedExe = $expectedExe
$guidedManifest = Get-Content -LiteralPath $BuildManifestPath -Raw | ConvertFrom-Json
if ($guidedManifest.schema -cne 'rat-trap-library-build/v1' -or
    $guidedManifest.product -cne 'Rat-Trap Desktop Preview 2' -or
    $guidedManifest.version -cne '5.7.0-desktop-preview.2-library.4' -or
    $guidedManifest.installer_version -cne '5.7.0.10' -or
    $guidedManifest.app_key -cne 'TwoHandsNetwork.RatTrap.DesktopPreview2' -or
    $guidedManifest.executable -cne 'Rat-Trap-Desktop-Preview-2.exe') {
    throw 'The supplied build receipt does not identify the same-product Library update.'
}
$guidedExpectedExe = [pscustomobject]@{ path = $guidedManifest.executable; bytes = $guidedManifest.executable_bytes; sha256 = $guidedManifest.executable_sha256 }
if ($guidedExpectedExe.sha256 -ceq $oldExpectedExe.sha256) { throw 'The Library update must not contain the old executable.' }
$currentInstallerGuide = 'packaging\direct\README-LIBRARY-SEARCH-INSTALLER.txt'
$protectedFiles = @(
    'scripts\build_windows_desktop_preview2.ps1',
    'scripts\build_windows_desktop_preview2_installer.ps1',
    'scripts\test_windows_desktop_preview2_installer.ps1',
    'packaging\direct\rat-trap-desktop-preview2.nsi',
    'packaging\direct\README-DESKTOP-PREVIEW-2.txt',
    'packaging\direct\README-DESKTOP-PREVIEW-2-INSTALLER.txt',
    'dist\desktop-preview-2\Rat-Trap-Desktop-Preview-2.exe',
    'dist\desktop-preview-2\Rat-Trap-Desktop-Preview-2-Windows-x64-portable.zip',
    'dist\desktop-preview-2-installer\Rat-Trap-Desktop-Preview-2-Windows-x64-setup.exe',
    'scripts\test_windows_beta_installer_5_7_0.ps1',
    'scripts\build_windows_beta_installer_5_7_0.ps1',
    'packaging\direct\rat-trap-beta.nsi',
    'release-manifests\5.7.0.json',
    'release-manifests\5.7.0-direct-beta.json',
    'release-manifests\desktop-preview-1.json',
    'release-manifests\desktop-preview-2.json',
    'release-manifests\guided-preview.json',
    'scripts\build_windows_guided_preview.ps1',
    'scripts\build_windows_guided_installer.ps1',
    'scripts\test_windows_guided_installer.ps1',
    'packaging\direct\rat-trap-guided-preview.nsi',
    'packaging\direct\README-GUIDED-PREVIEW.txt',
    'packaging\direct\README-GUIDED-INSTALLER.txt',
    'packaging\direct\qa-results-guided-preview.json',
    'dist\guided-preview\Rat-Trap-Desktop-Preview-2.exe',
    'dist\guided-preview\BUILD-MANIFEST.json',
    'dist\guided-preview-installer\Rat-Trap-Guided-Preview-Windows-x64-setup.exe',
    'release-manifests\guided-lessons.json',
    'scripts\build_windows_guided_lessons.ps1',
    'scripts\build_windows_guided_lessons_installer.ps1',
    'scripts\test_windows_guided_lessons_installer.ps1',
    'packaging\direct\rat-trap-guided-lessons.nsi',
    'packaging\direct\README-GUIDED-LESSONS.txt',
    'packaging\direct\README-GUIDED-LESSONS-INSTALLER.txt',
    'packaging\direct\qa-results-guided-lessons.json',
    'dist\guided-lessons\Rat-Trap-Desktop-Preview-2.exe',
    'dist\guided-lessons\BUILD-MANIFEST.json',
    'dist\guided-lessons-installer\Rat-Trap-Guided-Lessons-Windows-x64-setup.exe',
    'release-manifests\guided-history.json',
    'scripts\build_windows_guided_history.ps1',
    'scripts\build_windows_guided_history_installer.ps1',
    'scripts\test_windows_guided_history_installer.ps1',
    'packaging\direct\rat-trap-guided-history.nsi',
    'packaging\direct\README-GUIDED-HISTORY.txt',
    'packaging\direct\README-GUIDED-HISTORY-INSTALLER.txt',
    'packaging\direct\qa-results-guided-history.json',
    'dist\guided-history\Rat-Trap-Desktop-Preview-2.exe',
    'dist\guided-history\BUILD-MANIFEST.json',
    'dist\guided-history-installer\Rat-Trap-Guided-History-Windows-x64-setup.exe'
)
$protectedSnapshot = @()

function Assert-Check([bool]$Condition, [string]$Name, [string]$Detail = '') {
    $checks.Add([pscustomobject]@{ Name = $Name; Passed = $Condition; Detail = $Detail })
    Write-Host (('{0}: {1}' -f $(if ($Condition) { 'PASS' } else { 'FAIL' }), $Name))
    if (-not $Condition) { throw "$Name failed. $Detail" }
}

function Get-RegValue([Microsoft.Win32.RegistryKey]$Hive, [string]$Path, [string]$Name) {
    $key = $Hive.OpenSubKey($Path)
    if ($null -eq $key) { return $null }
    try { return $key.GetValue($Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) }
    finally { $key.Dispose() }
}

function Test-RegKey([Microsoft.Win32.RegistryKey]$Hive, [string]$Path) {
    $key = $Hive.OpenSubKey($Path)
    if ($null -eq $key) { return $false }
    $key.Dispose()
    return $true
}

function Get-RegTree([Microsoft.Win32.RegistryKey]$Hive, [string]$Path, [string[]]$IgnoreNames = @()) {
    $key = $Hive.OpenSubKey($Path)
    if ($null -eq $key) { return }
    try {
        [pscustomobject][ordered]@{ Path = $Path; KeyExists = $true } | ConvertTo-Json -Compress
        foreach ($name in $key.GetValueNames() | Sort-Object) {
            if ($name -in $IgnoreNames) { continue }
            $value = $key.GetValue($name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            $kind = $key.GetValueKind($name).ToString()
            if ($value -is [byte[]]) { $value = [Convert]::ToBase64String($value) }
            [pscustomobject][ordered]@{ Path = $Path; Name = $name; Kind = $kind; Value = $value } | ConvertTo-Json -Compress -Depth 8
        }
        foreach ($child in $key.GetSubKeyNames() | Sort-Object) { Get-RegTree $Hive "$Path\$child" $IgnoreNames }
    }
    finally { $key.Dispose() }
}

function Get-SharedAssociations {
    # Compare every value, including defaults and UserChoice, but never write them.
    # Ignore only this QA app's two optional OpenWithProgids values.
    $ignore = @("$appKey.GMW", "$appKey.RTSF")
    foreach ($ext in @('.gmw', '.rtsf', '.rtrk')) {
        Get-RegTree $currentUser "Software\Classes\$ext" $ignore | ForEach-Object { "HKCU|$_" }
        Get-RegTree $currentUser "Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\$ext" | ForEach-Object { "HKCU|$_" }
        Get-RegTree $localMachine "Software\Classes\$ext" | ForEach-Object { "HKLM|$_" }
    }
    foreach ($name in $sentinelNames.Values | Sort-Object) {
        Get-RegTree $currentUser "Software\Classes\$name" | ForEach-Object { "HKCU|$_" }
    }
    foreach ($name in $script:observedProgIds) {
        Get-RegTree $currentUser "Software\Classes\$name" | ForEach-Object { "HKCU|$_" }
        Get-RegTree $localMachine "Software\Classes\$name" | ForEach-Object { "HKLM|$_" }
    }
}

function Get-ProtectedState {
    # Also catch a mistakenly introduced third installed Rat-Trap product.
    foreach ($hive in @($currentUser, $localMachine)) {
        $uninstall = $hive.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall')
        if ($null -eq $uninstall) { continue }
        try {
            foreach ($name in $uninstall.GetSubKeyNames() | Sort-Object) {
                if ($name -like 'TwoHandsNetwork.RatTrap*' -and $name -cne $appKey) {
                    "APP-KEY|$($hive.Name)|$name"
                }
            }
        }
        finally { $uninstall.Dispose() }
    }
    # Observe only application-owned names in real installs; never scan user
    # archives or remove anything from these non-QA locations.
    foreach ($identity in @(
        @('TwoHandsNetwork.RatTrap.DesktopPreview2', 'Rat-Trap Desktop Preview 2', 'Rat-Trap-Desktop-Preview-2.exe', 'Rat-Trap Desktop Preview 2.lnk'),
        @('TwoHandsNetwork.RatTrap.Beta', 'Rat-Trap Beta', 'Rat-Trap.exe', 'Rat-Trap.lnk')
    )) {
        $keyPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + $identity[0]
        "HKCU-KEY|$keyPath|$(Test-RegKey $currentUser $keyPath)"
        "HKLM-KEY|$keyPath|$(Test-RegKey $localMachine $keyPath)"
        Get-RegTree $currentUser $keyPath | ForEach-Object { "HKCU|$_" }
        Get-RegTree $localMachine $keyPath | ForEach-Object { "HKLM|$_" }
        foreach ($suffix in @('GMW', 'RTSF')) {
            $progIdPath = "Software\Classes\$($identity[0]).$suffix"
            "HKCU-KEY|$progIdPath|$(Test-RegKey $currentUser $progIdPath)"
            Get-RegTree $currentUser $progIdPath | ForEach-Object { "HKCU|$_" }
        }
        $realDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "Programs\Two Hands Network Ltd\$($identity[1])"
        $realMenu = Join-Path ([Environment]::GetFolderPath('Programs')) $identity[1]
        $realPaths = @(
            (Join-Path $realDirectory $identity[2]),
            (Join-Path $realDirectory 'Uninstall.exe'),
            (Join-Path $realDirectory 'README-FIRST.txt'),
            (Join-Path $realMenu $identity[3]),
            (Join-Path $realMenu 'Read me first.lnk'),
            (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) ($identity[1] + '.lnk'))
        )
        foreach ($path in $realPaths) {
            if (Test-Path -LiteralPath $path -PathType Leaf) { "FILE|$path|$((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash)" }
            else { "ABSENT|$path" }
        }
    }
    foreach ($relative in $script:protectedFiles) {
        $path = Join-Path $repoRoot $relative
        "FROZEN|$relative|$((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash)"
    }
}

function Assert-ProtectedState([string]$Phase) {
    Assert-Check ((@(Get-ProtectedState | Sort-Object) -join "`n") -ceq ($script:protectedSnapshot -join "`n")) "$Phase leaves real installations and frozen beta/preview records unchanged"
}

function Assert-SharedAssociations([string]$Phase) {
    $actual = @(Get-SharedAssociations | Sort-Object)
    Assert-Check (($actual -join "`n") -ceq ($script:sharedSnapshot -join "`n")) "$Phase preserves defaults, UserChoice, other OpenWith values and .rtrk"
}

function Invoke-TestProcess([string]$Executable, [string]$Arguments, [string]$Label, [int]$ExpectedExit, [int]$TimeoutSeconds = 180) {
    $outPath = Join-Path $qaRoot "$Label.stdout.log"
    $errPath = Join-Path $qaRoot "$Label.stderr.log"
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $qaRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath
    try {
        # Retain the native handle before a short-lived process can exit; Windows
        # PowerShell 5.1 otherwise occasionally reports a null ExitCode.
        [void]$process.Handle
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            # This PID is a test process created immediately above, never an existing app.
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "$Label exceeded $TimeoutSeconds seconds; its QA process was stopped."
        }
        $process.WaitForExit()
        Assert-Check ($process.ExitCode -eq $ExpectedExit) "$Label exit code" "Expected $ExpectedExit; observed $($process.ExitCode)."
    }
    finally { $process.Dispose() }
}

function Get-InstalledHashes {
    foreach ($relative in $script:payloadFiles | Sort-Object) {
        $path = Join-Path $installRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { "$relative=MISSING"; continue }
        "$relative=$((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash)"
    }
}

function Assert-Payload([string]$Phase) {
    $exe = Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe'
    Assert-Check ((Get-Item -LiteralPath $exe).Length -eq $script:expectedExe.bytes -and (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ceq $script:expectedExe.sha256) "$Phase exact manifest-pinned Desktop Preview 2 executable"
    $seen = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $installRoot 'SHA256SUMS.txt')) {
        if ($line -notmatch '^([A-Fa-f0-9]{64})  ([a-zA-Z0-9_./-]+)$') { throw "Invalid installed checksum: $line" }
        $hash = $Matches[1]; $relative = $Matches[2]
        if ($relative -match '(^|/)\.\.(/|$)' -or $relative.StartsWith('/') -or $seen.ContainsKey($relative)) { throw 'Unsafe or repeated installed checksum path.' }
        $seen[$relative] = $hash
        if ((Get-FileHash -LiteralPath (Join-Path $installRoot $relative) -Algorithm SHA256).Hash -ne $hash) { throw "Installed checksum mismatch: $relative" }
    }
    $script:payloadFiles = @($seen.Keys) + @('SHA256SUMS.txt')
    $expected = @($script:previewManifest.payload_sha256.PSObject.Properties.Name) + @('README-PORTABLE.txt', 'Legal/NSIS-3.12-COPYING.txt')
    Assert-Check (@(Compare-Object ($expected | Sort-Object) ($script:payloadFiles | Sort-Object)).Count -eq 0) "$Phase complete installed checksum inventory"
    foreach ($property in $script:previewManifest.payload_sha256.PSObject.Properties) {
        if ($property.Name -eq 'SHA256SUMS.txt') { continue }
        $installedName = if ($property.Name -eq 'README-FIRST.txt') { 'README-PORTABLE.txt' } else { $property.Name }
        if ((Get-FileHash -LiteralPath (Join-Path $installRoot $installedName) -Algorithm SHA256).Hash -cne $property.Value) {
            throw "Installed frozen portable payload differs from its release record: $installedName"
        }
    }
    Assert-Check $true "$Phase preserves every frozen portable payload file and original guide"
    $guide = Join-Path $repoRoot $script:currentInstallerGuide
    Assert-Check ((Get-FileHash -LiteralPath (Join-Path $installRoot 'README-FIRST.txt') -Algorithm SHA256).Hash -ceq (Get-FileHash -LiteralPath $guide -Algorithm SHA256).Hash) "$Phase installs the current installer-specific first-run guide"
    $licence = Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $CompilerPath).Path) 'COPYING'
    Assert-Check ((Get-FileHash -LiteralPath (Join-Path $installRoot 'Legal/NSIS-3.12-COPYING.txt') -Algorithm SHA256).Hash -ceq (Get-FileHash -LiteralPath $licence -Algorithm SHA256).Hash) "$Phase preserves the NSIS compiler licence"
    Assert-Check (Test-Path -LiteralPath (Join-Path $installRoot 'Uninstall.exe') -PathType Leaf) "$Phase has uninstaller"
    Assert-Check (-not (Test-Path -LiteralPath (Join-Path $installRoot 'BUILD-MANIFEST.json')) -and @(Get-ChildItem -LiteralPath $installRoot -File -Filter '*.zip').Count -eq 0) "$Phase does not embed build receipts or portable ZIPs"
    $expectedOnDisk = @($script:payloadFiles) + @('Uninstall.exe') + @($script:retainedFiles.Keys | Where-Object { Test-Path -LiteralPath (Join-Path $installRoot $_) })
    $expectedOnDisk = @($expectedOnDisk | ForEach-Object { $_.Replace('\', '/') } | Sort-Object)
    $actualOnDisk = @(Get-ChildItem -LiteralPath $installRoot -File -Force -Recurse | ForEach-Object { $_.FullName.Substring($installRoot.Length + 1).Replace('\', '/') } | Sort-Object)
    Assert-Check (@(Compare-Object $expectedOnDisk $actualOnDisk).Count -eq 0) "$Phase exact on-disk payload plus uninstaller and generated retained fixtures"
}

function Assert-Shortcut([string]$Path, [string]$Target, [string]$Label) {
    Assert-Check (Test-Path -LiteralPath $Path -PathType Leaf) "$Label exists"
    $shell = New-Object -ComObject WScript.Shell
    try {
        $link = $shell.CreateShortcut($Path)
        Assert-Check ($link.TargetPath -ieq $Target -and $link.Arguments -eq '') "$Label target"
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($link)
    }
    finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) }
}

function Assert-Choices([bool]$Enabled, [string]$Phase) {
    foreach ($type in @(@('.gmw', 'GMW', '--open-archive'), @('.rtsf', 'RTSF', '--open-sealed'))) {
        $progId = "$appKey.$($type[1])"
        $key = $currentUser.OpenSubKey("Software\Classes\$($type[0])\OpenWithProgids")
        try { $present = $null -ne $key -and $progId -in $key.GetValueNames() }
        finally { if ($null -ne $key) { $key.Dispose() } }
        Assert-Check ($present -eq $Enabled) "$Phase $($type[0]) OpenWith value"
        if ($Enabled) {
            $command = Get-RegValue $currentUser "Software\Classes\$progId\shell\open\command" ''
            Assert-Check ($command -ceq ('"' + (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') + '" ' + $type[2] + ' "%1"')) "$Phase $($type[0]) quoted non-extracting command"
        }
        else { Assert-Check (-not (Test-RegKey $currentUser "Software\Classes\$progId")) "$Phase $($type[0]) ProgID absent" }
    }
    Assert-Check ((Test-Path -LiteralPath $desktopLink) -eq $Enabled) "$Phase desktop choice"
    if ($Enabled) { Assert-Shortcut $desktopLink (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') "$Phase desktop shortcut" }
    Assert-Check ((Get-RegValue $currentUser $arpPath 'OpenWithEnabled') -eq [int]$Enabled -and (Get-RegValue $currentUser $arpPath 'DesktopEnabled') -eq [int]$Enabled) "$Phase persisted option flags"
    Assert-SharedAssociations $Phase
}

function Remove-EmptyDirectory([string]$Path) {
    if ((Test-Path -LiteralPath $Path -PathType Container) -and @(Get-ChildItem -LiteralPath $Path -Force).Count -eq 0) { Remove-Item -LiteralPath $Path -Force }
}

try {
    foreach ($path in @($qaRoot, $installRoot, $menuRoot, $desktopLink)) {
        if (Test-Path -LiteralPath $path) { throw "QA target already exists; refusing to reuse it: $path" }
    }
    if ((Test-RegKey $currentUser $arpPath) -or (Test-RegKey $localMachine $arpPath)) { throw 'QA application registration already exists.' }
    foreach ($name in @("$appKey.GMW", "$appKey.RTSF") + @($sentinelNames.Values)) {
        if (Test-RegKey $currentUser "Software\Classes\$name") { throw "QA ProgID already exists: $name" }
    }
    foreach ($ext in @('.gmw', '.rtsf')) {
        $key = $currentUser.OpenSubKey("Software\Classes\$ext\OpenWithProgids")
        if ($null -ne $key) {
            try {
                foreach ($name in @($sentinelNames[$ext], "$appKey.GMW", "$appKey.RTSF")) {
                    if ($name -in $key.GetValueNames()) { throw "QA OpenWith value already exists; refusing to overwrite: $name" }
                }
            }
            finally { $key.Dispose() }
        }
    }
    $script:protectedSnapshot = @(Get-ProtectedState | Sort-Object)
    [IO.Directory]::CreateDirectory($qaRoot) | Out-Null
    $allowCleanup = $true
    $ids = New-Object 'Collections.Generic.List[string]'
    foreach ($hive in @($currentUser, $localMachine)) {
        foreach ($ext in @('.gmw', '.rtsf', '.rtrk')) {
            $default = Get-RegValue $hive "Software\Classes\$ext" ''
            if ($default -is [string] -and $default.Length -gt 0) { $ids.Add($default) }
            $key = $hive.OpenSubKey("Software\Classes\$ext\OpenWithProgids")
            if ($null -ne $key) {
                try { foreach ($name in $key.GetValueNames()) { if ($name.Length -gt 0) { $ids.Add($name) } } }
                finally { $key.Dispose() }
            }
        }
    }
    $script:observedProgIds = @($ids | Sort-Object -Unique)
    $initialSharedSnapshot = @(Get-SharedAssociations | Sort-Object)
    foreach ($ext in @('.gmw', '.rtsf')) {
        foreach ($path in @("Software\Classes\$ext", "Software\Classes\$ext\OpenWithProgids")) {
            if (-not (Test-RegKey $currentUser $path)) { $createdRegistryParents.Add($path) }
        }
        # A uniquely named fake other-app value makes preservation observable even
        # on hosts with no existing GMW/RTSF associations. No defaults are written.
        $key = $currentUser.CreateSubKey("Software\Classes\$ext\OpenWithProgids")
        try { $key.SetValue($sentinelNames[$ext], [byte[]]@(31, 41, 59), [Microsoft.Win32.RegistryValueKind]::Binary) }
        finally { $key.Dispose() }
        $key = $currentUser.CreateSubKey("Software\Classes\$($sentinelNames[$ext])")
        try { $key.SetValue('InstallerQASentinel', $QaIdentity, [Microsoft.Win32.RegistryValueKind]::String) }
        finally { $key.Dispose() }
    }
    $script:sharedSnapshot = @(Get-SharedAssociations | Sort-Object)
    $testedSourceHashes = @(
        'packaging\direct\rat-trap-desktop-preview2.nsi',
        'scripts\build_windows_desktop_preview2_installer.ps1',
        'scripts\test_windows_desktop_preview2_installer.ps1',
        'packaging\direct\README-DESKTOP-PREVIEW-2-INSTALLER.txt',
        'release-manifests\desktop-preview-2.json',
        'packaging\direct\rat-trap-library-restore.nsi',
        'scripts\build_windows_guided_preview.ps1',
        'scripts\build_windows_guided_installer.ps1',
        'scripts\build_windows_guided_lessons.ps1',
        'scripts\build_windows_guided_lessons_installer.ps1',
        'scripts\build_windows_library_restore.ps1',
        'scripts\build_windows_library_restore_installer.ps1',
        'scripts\test_windows_library_restore_installer.ps1',
        'packaging\direct\README-GUIDED-PREVIEW.txt',
        'packaging\direct\README-GUIDED-INSTALLER.txt',
        'packaging\direct\README-GUIDED-LESSONS.txt',
        'packaging\direct\README-GUIDED-LESSONS-INSTALLER.txt',
        'packaging\direct\rat-trap-guided-lessons.nsi',
        'packaging\direct\README-LIBRARY-RESTORE.txt',
        'release-manifests\guided-preview.json',
        'release-manifests\guided-lessons.json',
        'packaging\direct\README-LIBRARY-RESTORE-INSTALLER.txt',
        'scripts\build_windows_guided_history.ps1',
        'scripts\build_windows_guided_history_installer.ps1',
        'packaging\direct\rat-trap-guided-history.nsi',
        'packaging\direct\README-GUIDED-HISTORY.txt',
        'packaging\direct\README-GUIDED-HISTORY-INSTALLER.txt',
        'release-manifests\guided-history.json'
    ) | ForEach-Object { [pscustomobject]@{ Path = $_; Sha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot $_) -Algorithm SHA256).Hash } }
    $testedSourceHashes += [pscustomobject]@{ Path = (Resolve-Path -LiteralPath $BuildManifestPath).Path; Sha256 = (Get-FileHash -LiteralPath $BuildManifestPath -Algorithm SHA256).Hash }
    $oldBuildOutput = @(& (Join-Path $PSScriptRoot 'build_windows_library_search_installer.ps1') -PayloadDirectory $OldPayloadDirectory -BuildManifestPath $oldReceiptPath -CompilerPath $CompilerPath -DestinationDirectory $qaRoot -QaIdentity $QaIdentity)
    [IO.File]::WriteAllLines((Join-Path $qaRoot 'old-build.log'), [string[]]$oldBuildOutput)
    $oldBuildResult = $oldBuildOutput[-1] | ConvertFrom-Json
    Assert-Check ($oldBuildResult.AppKey -ceq $appKey -and $oldBuildResult.QaIdentity -ceq $QaIdentity -and $oldBuildResult.InstallFolder -ceq $displayName -and $oldBuildResult.Version -ceq '5.7.0.9') 'Old installer uses isolated QA identity and version'
    $buildOutput = @(& (Join-Path $PSScriptRoot 'build_windows_library_restore_installer.ps1') -PayloadDirectory $PayloadDirectory -BuildManifestPath $BuildManifestPath -CompilerPath $CompilerPath -DestinationDirectory $qaRoot -QaIdentity $QaIdentity)
    [IO.File]::WriteAllLines((Join-Path $qaRoot 'guided-build.log'), [string[]]$buildOutput)
    $buildResult = $buildOutput[-1] | ConvertFrom-Json
    Assert-Check ($buildResult.AppKey -ceq $oldBuildResult.AppKey -and $buildResult.QaIdentity -ceq $QaIdentity -and $buildResult.InstallFolder -ceq $oldBuildResult.InstallFolder -and $buildResult.DisplayName -ceq $oldBuildResult.DisplayName -and $buildResult.Version -ceq '5.7.0.10') 'Guided installer updates exactly the same QA product identity'
    Assert-Check ($buildResult.Installer -cne $oldBuildResult.Installer -and $buildResult.ExecutableSha256 -ceq $guidedExpectedExe.sha256) 'Guided setup remains a separate private artifact with pinned new application'
    $installer = $oldBuildResult.Installer

    [IO.Directory]::CreateDirectory($installRoot) | Out-Null
    $occupied = Join-Path $installRoot "qa-occupied-$QaIdentity.txt"
    [IO.File]::WriteAllText($occupied, 'Unregistered test directory: do not overwrite.')
    $occupiedHash = (Get-FileHash -LiteralPath $occupied -Algorithm SHA256).Hash
    Invoke-TestProcess $installer '/S' 'occupied-directory-install' 3
    Assert-Check ((Get-FileHash -LiteralPath $occupied -Algorithm SHA256).Hash -ceq $occupiedHash -and @(Get-ChildItem -LiteralPath $installRoot -Force).Count -eq 1 -and -not (Test-RegKey $currentUser $arpPath)) 'Occupied unregistered directory remains unchanged'
    Remove-Item -LiteralPath $occupied
    Remove-EmptyDirectory $installRoot

    Invoke-TestProcess $installer '/S' 'default-install' 0
    Assert-Payload 'Default install'
    Assert-Check ((Get-RegValue $currentUser $arpPath 'DisplayName') -ceq $displayName -and (Get-RegValue $currentUser $arpPath 'DisplayVersion') -ceq '5.7.0.9' -and (Get-RegValue $currentUser $arpPath 'InstallOwner') -ceq 'RatTrapDesktopPreview2/v1' -and (Get-RegValue $currentUser $arpPath 'InstallLocation') -ieq $installRoot) 'Per-user Apps and Features registration'
    Assert-Check (-not (Test-RegKey $localMachine $arpPath)) 'No machine-wide Apps and Features registration'
    Assert-Check ((Get-RegValue $currentUser $arpPath 'UninstallString') -ceq ('"' + (Join-Path $installRoot 'Uninstall.exe') + '"') -and (Get-RegValue $currentUser $arpPath 'QuietUninstallString') -ceq ('"' + (Join-Path $installRoot 'Uninstall.exe') + '" /S')) 'Quoted Apps and Features uninstall commands'
    Assert-Shortcut (Join-Path $menuRoot 'Rat-Trap Desktop Preview 2.lnk') (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') 'Start menu application shortcut'
    Assert-Shortcut (Join-Path $menuRoot 'Read me first.lnk') (Join-Path $installRoot 'README-FIRST.txt') 'Start menu readme shortcut'
    Assert-Choices $false 'Default install'
    Assert-ProtectedState 'Default install'
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--self-test' 'installed-old-application-self-test' 0 300
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--ui-self-test' 'installed-old-preview2-ui-self-test' 0 120
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--tutorial-self-test' 'installed-old-guided-tutorial-self-test' 0 300

    foreach ($relative in @('qa-preserved.gmw', 'qa-user-files\nested\qa-recovery.rtrk', 'qa-user-files\nested\qa-archive.gmw', 'Legal\qa-user-note.txt')) {
        $path = Join-Path $installRoot $relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
        [IO.File]::WriteAllText($path, "Generated installer QA fixture $QaIdentity : $relative")
        $retainedFiles[$relative] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    }
    Invoke-TestProcess $installer '/S /OPENWITH=1 /DESKTOP=1' 'enable-options-reinstall' 0
    Assert-Payload 'Options reinstall'
    Assert-Choices $true 'Options enabled'
    # A blocked upgrade must leave the old application and registration intact.
    $beforeHashes = @(Get-InstalledHashes)
    $beforeRegistration = @(Get-RegTree $currentUser $arpPath)
    $lock = [IO.File]::Open((Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
    try { Invoke-TestProcess $buildResult.Installer '/S' 'locked-old-exe-upgrade' 4 }
    finally { $lock.Dispose() }
    Assert-Check ((@(Get-InstalledHashes) -join "`n") -ceq ($beforeHashes -join "`n")) 'Blocked upgrade preserves every old payload file'
    Assert-Check ((@(Get-RegTree $currentUser $arpPath) -join "`n") -ceq ($beforeRegistration -join "`n")) 'Blocked upgrade preserves old Apps and Features registration'
    Assert-Choices $true 'Blocked upgrade'
    Assert-ProtectedState 'Blocked upgrade'

    # Switch only our freshly created QA installation to the guided version.
    $installer = $buildResult.Installer
    Invoke-TestProcess $installer '/S' 'upgrade-library-to-store-folder' 0
    $script:previewManifest = $guidedManifest
    $script:expectedExe = $guidedExpectedExe
    $script:currentInstallerGuide = 'packaging\direct\README-LIBRARY-RESTORE-INSTALLER.txt'
    Assert-Payload 'Guided upgrade'
    Assert-Check ((Get-RegValue $currentUser $arpPath 'DisplayVersion') -ceq '5.7.0.10' -and (Get-RegValue $currentUser $arpPath 'DisplayName') -ceq $displayName -and (Get-RegValue $currentUser $arpPath 'InstallOwner') -ceq 'RatTrapDesktopPreview2/v1' -and (Get-RegValue $currentUser $arpPath 'InstallLocation') -ieq $installRoot -and (Get-RegValue $currentUser $arpPath 'InstallState') -ceq 'complete') 'Upgrade changes version in the same complete per-user registration'
    Assert-Check ((Get-Item -LiteralPath (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe')).VersionInfo.FileVersion -ceq '5.7.0.10' -and (Get-Item -LiteralPath (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe')).VersionInfo.ProductVersion -ceq '5.7.0-desktop-preview.2-library.4') 'Installed guided application has the new numeric and support versions'
    Assert-Check (-not (Test-RegKey $localMachine $arpPath)) 'Upgrade does not create machine-wide registration'
    Assert-Shortcut (Join-Path $menuRoot 'Rat-Trap Desktop Preview 2.lnk') (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') 'Upgraded Start menu application shortcut'
    Assert-Shortcut (Join-Path $menuRoot 'Read me first.lnk') (Join-Path $installRoot 'README-FIRST.txt') 'Upgraded Start menu guide shortcut'
    Assert-Choices $true 'Upgrade preserves prior optional choices'
    foreach ($relative in $retainedFiles.Keys) {
        Assert-Check ((Get-FileHash -LiteralPath (Join-Path $installRoot $relative) -Algorithm SHA256).Hash -ceq $retainedFiles[$relative]) "Upgrade preserves generated user file $relative"
    }
    Assert-ProtectedState 'Guided upgrade'
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--self-test' 'installed-guided-application-self-test' 0 300
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--ui-self-test' 'installed-guided-ui-self-test' 0 180
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--tutorial-self-test' 'installed-guided-tutorial-self-test' 0 300
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--library-self-test' 'installed-library-self-test' 0 300
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--store-folder-self-test' 'installed-store-folder-self-test' 0 300
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--library-search-self-test' 'installed-library-search-self-test' 0 300
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap-Desktop-Preview-2.exe') '--library-restore-self-test' 'installed-library-restore-self-test' 0 300

    Invoke-TestProcess $installer '/S' 'preserve-options-reinstall' 0
    Assert-Choices $true 'Options preserved on reinstall'
    Remove-Item -LiteralPath (Join-Path $installRoot 'README-FIRST.txt')
    $key = $currentUser.OpenSubKey($arpPath, $true)
    try { $key.SetValue('InstallState', 'incomplete', [Microsoft.Win32.RegistryValueKind]::String) }
    finally { $key.Dispose() }
    Invoke-TestProcess $installer '/S' 'repair-incomplete-install' 0
    Assert-Payload 'Repaired incomplete installation'
    Assert-Check ((Get-RegValue $currentUser $arpPath 'InstallState') -ceq 'complete') 'Repair completes pending registration and restores missing readme'
    Assert-Choices $true 'Repair preserves choices'

    $uninstallerCopy = Join-Path $qaRoot 'Uninstall-QA.exe'
    Copy-Item -LiteralPath (Join-Path $installRoot 'Uninstall.exe') -Destination $uninstallerCopy
    foreach ($relative in @('Rat-Trap-Desktop-Preview-2.exe', 'README-FIRST.txt')) {
        $beforeHashes = @(Get-InstalledHashes)
        $beforeRegistration = @(Get-RegTree $currentUser $arpPath)
        $label = if ($relative -eq 'Rat-Trap-Desktop-Preview-2.exe') { 'exe' } else { 'readme' }
        $lock = [IO.File]::Open((Join-Path $installRoot $relative), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
        try {
            Invoke-TestProcess $installer '/S /OPENWITH=0 /DESKTOP=0' "locked-$label-reinstall" 4
            # NSIS _?= must be the final, unquoted suffix. A copied uninstaller
            # allows the installed Uninstall.exe to be removed synchronously.
            Invoke-TestProcess $uninstallerCopy "/S _?=$installRoot" "locked-$label-uninstall" 4
        }
        finally { $lock.Dispose() }
        Assert-Check ((@(Get-InstalledHashes) -join "`n") -ceq ($beforeHashes -join "`n")) "Locked $label leaves every payload file unchanged"
        Assert-Check ((@(Get-RegTree $currentUser $arpPath) -join "`n") -ceq ($beforeRegistration -join "`n")) "Locked $label leaves repair registration unchanged"
        Assert-Choices $true "Locked $label"
    }

    Invoke-TestProcess $installer '/S /OPENWITH=0 /DESKTOP=0' 'disable-options-reinstall' 0
    Assert-Choices $false 'Options disabled'
    Invoke-TestProcess $installer '/S /OPENWITH=1 /DESKTOP=1' 'reenable-options-reinstall' 0
    Assert-Choices $true 'Options reenabled'
    foreach ($relative in $retainedFiles.Keys) {
        Assert-Check ((Get-FileHash -LiteralPath (Join-Path $installRoot $relative) -Algorithm SHA256).Hash -ceq $retainedFiles[$relative]) "Reinstall preserves generated user file $relative"
    }
    Copy-Item -LiteralPath (Join-Path $installRoot 'Uninstall.exe') -Destination $uninstallerCopy -Force
    Invoke-TestProcess $uninstallerCopy "/S _?=$installRoot" 'uninstall' 0
    Assert-Check (-not (Test-RegKey $currentUser $arpPath) -and -not (Test-RegKey $localMachine $arpPath)) 'Uninstall removes only QA Apps and Features registration'
    Assert-Check (-not (Test-Path -LiteralPath $menuRoot) -and -not (Test-Path -LiteralPath $desktopLink)) 'Uninstall removes QA shortcuts'
    foreach ($progId in @("$appKey.GMW", "$appKey.RTSF")) { Assert-Check (-not (Test-RegKey $currentUser "Software\Classes\$progId")) "Uninstall removes own ProgID $progId" }
    foreach ($ext in @('.gmw', '.rtsf')) {
        $key = $currentUser.OpenSubKey("Software\Classes\$ext\OpenWithProgids")
        try { $remainingOwnValue = $null -ne $key -and @($key.GetValueNames() | Where-Object { $_ -eq "$appKey.GMW" -or $_ -eq "$appKey.RTSF" }).Count -ne 0 }
        finally { if ($null -ne $key) { $key.Dispose() } }
        Assert-Check (-not $remainingOwnValue) "Uninstall removes own $ext OpenWith value"
    }
    $remaining = @(Get-ChildItem -LiteralPath $installRoot -File -Force -Recurse | ForEach-Object { $_.FullName.Substring($installRoot.Length + 1) })
    Assert-Check (@(Compare-Object ($remaining | Sort-Object) ($retainedFiles.Keys | Sort-Object)).Count -eq 0) 'Uninstall leaves only generated user-owned fixtures, no application payload'
    foreach ($relative in $retainedFiles.Keys) { Assert-Check ((Get-FileHash -LiteralPath (Join-Path $installRoot $relative) -Algorithm SHA256).Hash -ceq $retainedFiles[$relative]) "Uninstall preserves generated user file $relative" }
    Assert-SharedAssociations 'Uninstall'
    Assert-ProtectedState 'Uninstall'
    Invoke-TestProcess $uninstallerCopy "/S _?=$installRoot" 'unregistered-repeat-uninstall' 3
    Assert-SharedAssociations 'Rejected repeat uninstall'

    # Exercise the ordinary end-user uninstaller, including NSIS's temporary
    # child-process handoff, independently of the deterministic copied _?= path.
    foreach ($relative in $retainedFiles.Keys) { Remove-Item -LiteralPath (Join-Path $installRoot $relative) }
    foreach ($relative in @('qa-user-files\nested', 'qa-user-files', 'Legal')) { Remove-EmptyDirectory (Join-Path $installRoot $relative) }
    Remove-EmptyDirectory $installRoot
    Invoke-TestProcess $installer '/S /OPENWITH=1 /DESKTOP=1' 'normal-uninstall-fresh-install' 0
    Assert-Payload 'Fresh install for ordinary uninstall'
    Assert-Choices $true 'Fresh install for ordinary uninstall'
    foreach ($relative in $retainedFiles.Keys) {
        $path = Join-Path $installRoot $relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
        [IO.File]::WriteAllText($path, "Generated installer QA fixture $QaIdentity : $relative")
    }
    Invoke-TestProcess (Join-Path $installRoot 'Uninstall.exe') '/S' 'normal-installed-uninstaller-bootstrap' 0
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline -and ((Test-RegKey $currentUser $arpPath) -or (Test-Path -LiteralPath (Join-Path $installRoot 'Uninstall.exe')))) {
        Start-Sleep -Milliseconds 200
    }
    Assert-Check (-not (Test-RegKey $currentUser $arpPath) -and -not (Test-Path -LiteralPath (Join-Path $installRoot 'Uninstall.exe'))) 'Ordinary uninstall handoff completes and removes its installed executable'
    Assert-Check (-not (Test-Path -LiteralPath $menuRoot) -and -not (Test-Path -LiteralPath $desktopLink)) 'Ordinary uninstall removes QA shortcuts'
    foreach ($progId in @("$appKey.GMW", "$appKey.RTSF")) { Assert-Check (-not (Test-RegKey $currentUser "Software\Classes\$progId")) "Ordinary uninstall removes own ProgID $progId" }
    foreach ($ext in @('.gmw', '.rtsf')) {
        $key = $currentUser.OpenSubKey("Software\Classes\$ext\OpenWithProgids")
        try { $remainingOwnValue = $null -ne $key -and @($key.GetValueNames() | Where-Object { $_ -eq "$appKey.GMW" -or $_ -eq "$appKey.RTSF" }).Count -ne 0 }
        finally { if ($null -ne $key) { $key.Dispose() } }
        Assert-Check (-not $remainingOwnValue) "Ordinary uninstall removes own $ext OpenWith value"
    }
    $remaining = @(Get-ChildItem -LiteralPath $installRoot -File -Force -Recurse | ForEach-Object { $_.FullName.Substring($installRoot.Length + 1) })
    Assert-Check (@(Compare-Object ($remaining | Sort-Object) ($retainedFiles.Keys | Sort-Object)).Count -eq 0) 'Ordinary uninstall leaves only generated user-owned fixtures'
    foreach ($relative in $retainedFiles.Keys) { Assert-Check ((Get-FileHash -LiteralPath (Join-Path $installRoot $relative) -Algorithm SHA256).Hash -ceq $retainedFiles[$relative]) "Ordinary uninstall preserves generated user file $relative" }
    Assert-SharedAssociations 'Ordinary uninstall'
    Assert-ProtectedState 'Ordinary uninstall'
}
catch { $failure = $_.Exception.Message; Write-Warning $failure }
finally {
    if ($allowCleanup) {
        try {
            if ((Test-RegKey $currentUser $arpPath) -and (Test-Path -LiteralPath (Join-Path $installRoot 'Uninstall.exe'))) {
                $cleanupUninstaller = Join-Path $qaRoot 'Uninstall-cleanup-QA.exe'
                Copy-Item -LiteralPath (Join-Path $installRoot 'Uninstall.exe') -Destination $cleanupUninstaller -Force
                Invoke-TestProcess $cleanupUninstaller "/S _?=$installRoot" 'failure-cleanup-uninstall' 0
            }
        }
        catch { $cleanupErrors.Add($_.Exception.Message) }
        try {
            # Only generated fixtures are removed manually. Never recursively delete
            # an installation directory, even one bearing this test's identity.
            foreach ($relative in @($retainedFiles.Keys) + @("qa-occupied-$QaIdentity.txt")) {
                $path = [IO.Path]::GetFullPath((Join-Path $installRoot $relative))
                if (-not $path.StartsWith($installRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe QA cleanup file path.' }
                if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
            }
            foreach ($relative in @('qa-user-files\nested', 'qa-user-files', 'Legal')) { Remove-EmptyDirectory (Join-Path $installRoot $relative) }
            Remove-EmptyDirectory $installRoot
            foreach ($ext in @('.gmw', '.rtsf')) {
                $key = $currentUser.OpenSubKey("Software\Classes\$ext\OpenWithProgids", $true)
                if ($null -ne $key) {
                    try { $key.DeleteValue($sentinelNames[$ext], $false) }
                    finally { $key.Dispose() }
                }
                $currentUser.DeleteSubKeyTree("Software\Classes\$($sentinelNames[$ext])", $false)
            }
            foreach ($path in $createdRegistryParents | Sort-Object Length -Descending) {
                $key = $currentUser.OpenSubKey($path)
                if ($null -eq $key) { continue }
                try { $empty = $key.SubKeyCount -eq 0 -and $key.ValueCount -eq 0 }
                finally { $key.Dispose() }
                if ($empty) { $currentUser.DeleteSubKey($path, $false) }
            }
            Assert-Check ((@(Get-SharedAssociations | Sort-Object) -join "`n") -ceq ($initialSharedSnapshot -join "`n")) 'Cleanup restores original shared association values'
            Assert-Check (-not (Test-Path -LiteralPath $installRoot) -and -not (Test-RegKey $currentUser $arpPath)) 'QA installed files and registration cleaned up'
            Assert-ProtectedState 'Final cleanup'
        }
        catch { $cleanupErrors.Add($_.Exception.Message) }
        $report = [pscustomobject][ordered]@{
            TestKind = 'Same-host Windows Library 5.7.0.9 to Library-restore 5.7.0.10 lifecycle; not a clean-VM test'
            CleanVm = $false
            QaIdentity = $QaIdentity
            StartedUtc = $testStarted.ToString('o')
            CompletedUtc = [DateTime]::UtcNow.ToString('o')
            WindowsVersion = [Environment]::OSVersion.VersionString
            Is64BitOperatingSystem = [Environment]::Is64BitOperatingSystem
            PowerShellVersion = $PSVersionTable.PSVersion.ToString()
            OldInstaller = $oldBuildResult
            Installer = $buildResult
            OldExpectedExecutable = $oldExpectedExe
            ExpectedExecutable = $expectedExe
            UpgradeFromVersion = '5.7.0.9'
            ExpectedInstallVersion = '5.7.0.10'
            ExpectedSupportVersion = '5.7.0-desktop-preview.2-library.4'
            ProtectedNonQaState = @($protectedSnapshot)
            TestedSourceHashes = @($testedSourceHashes)
            ExistingReferencedProgIds = @($observedProgIds)
            Passed = $null -eq $failure -and $cleanupErrors.Count -eq 0
            Failure = $failure
            CleanupErrors = @($cleanupErrors.ToArray())
            Checks = @($checks.ToArray())
            Limitations = @('No clean Windows VM, SmartScreen UI, or interactive wizard test.', 'Tests the specific 5.7.0.9 to 5.7.0.10 upgrade under one isolated QA identity; not arbitrary future upgrades.', 'Generated archive/recovery fixtures test preservation, not user originals.')
        }
        [IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
        Write-Host "Lifecycle report: $reportPath"
    }
    $currentUser.Dispose()
    $localMachine.Dispose()
}
if ($null -ne $failure -or $cleanupErrors.Count -ne 0) { throw "Installer lifecycle QA failed: $failure $($cleanupErrors -join '; '). Report: $reportPath" }
Get-Content -LiteralPath $reportPath -Raw
