[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PayloadDirectory,
    [Parameter(Mandatory = $true)][string]$CompilerPath,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$QaIdentity = ([guid]::NewGuid().ToString('N'))
)

# Destructive lifecycle checks run only against a freshly generated QA identity.
# This is a same-host test, not evidence of a clean Windows VM or SmartScreen UX.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$qaRoot = Join-Path $repoRoot "build\installer-qa\$QaIdentity"
$appKey = "TwoHandsNetwork.RatTrap.Beta.QA.$QaIdentity"
$displayName = "Rat-Trap Beta QA $QaIdentity"
$installRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) "Programs\Two Hands Network Ltd\$displayName"
$menuRoot = Join-Path ([Environment]::GetFolderPath('Programs')) $displayName
$desktopLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) "$displayName.lnk"
$arpPath = "Software\Microsoft\Windows\CurrentVersion\Uninstall\$appKey"
$currentUser = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
$localMachine = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
$checks = New-Object 'Collections.Generic.List[object]'
$cleanupErrors = New-Object 'Collections.Generic.List[string]'
$retainedFiles = @{}
$sentinelNames = @{ '.gmw' = "RatTrapInstallerQA.Other.$QaIdentity.GMW"; '.rtsf' = "RatTrapInstallerQA.Other.$QaIdentity.RTSF" }
$createdRegistryParents = New-Object 'Collections.Generic.List[string]'
$payloadFiles = @()
$observedProgIds = @()
$testedSourceHashes = @()
$buildResult = $null
$failure = $null
$testStarted = [DateTime]::UtcNow
$reportPath = Join-Path $qaRoot 'lifecycle-report.json'
$allowCleanup = $false

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

function Assert-SharedAssociations([string]$Phase) {
    $actual = @(Get-SharedAssociations | Sort-Object)
    Assert-Check (($actual -join "`n") -ceq ($script:sharedSnapshot -join "`n")) "$Phase preserves defaults, UserChoice, other OpenWith values and .rtrk"
}

function Invoke-TestProcess([string]$Executable, [string]$Arguments, [string]$Label, [int]$ExpectedExit, [int]$TimeoutSeconds = 180) {
    $outPath = Join-Path $qaRoot "$Label.stdout.log"
    $errPath = Join-Path $qaRoot "$Label.stderr.log"
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $qaRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath
    try {
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
    $baseline = Get-Content -LiteralPath (Join-Path $repoRoot 'release-manifests\5.7.0.json') -Raw | ConvertFrom-Json
    $expectedExe = @($baseline.artifacts | Where-Object { $_.name -eq 'Rat-Trap.exe' })[0]
    $exe = Join-Path $installRoot 'Rat-Trap.exe'
    Assert-Check ((Get-Item -LiteralPath $exe).Length -eq $expectedExe.bytes -and (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ceq $expectedExe.sha256) "$Phase frozen 5.7.0 executable"
    $seen = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $installRoot 'SHA256SUMS.txt')) {
        if ($line -notmatch '^([A-Fa-f0-9]{64})  ([a-zA-Z0-9_./-]+)$') { throw "Invalid installed checksum: $line" }
        $hash = $Matches[1]; $relative = $Matches[2]
        if ($relative -match '(^|/)\.\.(/|$)' -or $relative.StartsWith('/') -or $seen.ContainsKey($relative)) { throw 'Unsafe or repeated installed checksum path.' }
        $seen[$relative] = $hash
        if ((Get-FileHash -LiteralPath (Join-Path $installRoot $relative) -Algorithm SHA256).Hash -ne $hash) { throw "Installed checksum mismatch: $relative" }
    }
    $script:payloadFiles = @($seen.Keys) + @('SHA256SUMS.txt')
    $expected = @(Get-ChildItem -LiteralPath $PayloadDirectory -File -Recurse | ForEach-Object { $_.FullName.Substring((Resolve-Path -LiteralPath $PayloadDirectory).Path.Length + 1).Replace('\', '/') }) + @('Legal/NSIS-3.12-COPYING.txt')
    Assert-Check (@(Compare-Object ($expected | Sort-Object) ($script:payloadFiles | Sort-Object)).Count -eq 0) "$Phase complete installed checksum inventory"
    Assert-Check (Test-Path -LiteralPath (Join-Path $installRoot 'Uninstall.exe') -PathType Leaf) "$Phase has uninstaller"
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
            Assert-Check ($command -ceq ('"' + (Join-Path $installRoot 'Rat-Trap.exe') + '" ' + $type[2] + ' "%1"')) "$Phase $($type[0]) quoted non-extracting command"
        }
        else { Assert-Check (-not (Test-RegKey $currentUser "Software\Classes\$progId")) "$Phase $($type[0]) ProgID absent" }
    }
    Assert-Check ((Test-Path -LiteralPath $desktopLink) -eq $Enabled) "$Phase desktop choice"
    if ($Enabled) { Assert-Shortcut $desktopLink (Join-Path $installRoot 'Rat-Trap.exe') "$Phase desktop shortcut" }
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
        'packaging\direct\rat-trap-beta.nsi',
        'scripts\build_windows_beta_installer_5_7_0.ps1',
        'scripts\test_windows_beta_installer_5_7_0.ps1'
    ) | ForEach-Object { [pscustomobject]@{ Path = $_; Sha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot $_) -Algorithm SHA256).Hash } }
    $buildOutput = @(& (Join-Path $PSScriptRoot 'build_windows_beta_installer_5_7_0.ps1') -PayloadDirectory $PayloadDirectory -CompilerPath $CompilerPath -DestinationDirectory $qaRoot -QaIdentity $QaIdentity)
    [IO.File]::WriteAllLines((Join-Path $qaRoot 'build.log'), [string[]]$buildOutput)
    $buildResult = $buildOutput[-1] | ConvertFrom-Json
    Assert-Check ($buildResult.AppKey -ceq $appKey -and $buildResult.QaIdentity -ceq $QaIdentity) 'Isolated QA installer identity'
    $installer = $buildResult.Installer

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
    Assert-Check ((Get-RegValue $currentUser $arpPath 'DisplayName') -ceq $displayName -and (Get-RegValue $currentUser $arpPath 'DisplayVersion') -ceq '5.7.0' -and (Get-RegValue $currentUser $arpPath 'InstallOwner') -ceq 'RatTrapDirectBeta/v1' -and (Get-RegValue $currentUser $arpPath 'InstallLocation') -ieq $installRoot) 'Per-user Apps and Features registration'
    Assert-Check (-not (Test-RegKey $localMachine $arpPath)) 'No machine-wide Apps and Features registration'
    Assert-Check ((Get-RegValue $currentUser $arpPath 'UninstallString') -ceq ('"' + (Join-Path $installRoot 'Uninstall.exe') + '"') -and (Get-RegValue $currentUser $arpPath 'QuietUninstallString') -ceq ('"' + (Join-Path $installRoot 'Uninstall.exe') + '" /S')) 'Quoted Apps and Features uninstall commands'
    Assert-Shortcut (Join-Path $menuRoot 'Rat-Trap.lnk') (Join-Path $installRoot 'Rat-Trap.exe') 'Start menu application shortcut'
    Assert-Shortcut (Join-Path $menuRoot 'Read me first.lnk') (Join-Path $installRoot 'README-FIRST.txt') 'Start menu readme shortcut'
    Assert-Choices $false 'Default install'
    Invoke-TestProcess (Join-Path $installRoot 'Rat-Trap.exe') '--self-test' 'installed-application-self-test' 0 300

    foreach ($relative in @('qa-preserved.gmw', 'qa-user-files\nested\qa-recovery.rtrk', 'qa-user-files\nested\qa-archive.gmw', 'Legal\qa-user-note.txt')) {
        $path = Join-Path $installRoot $relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $path)) | Out-Null
        [IO.File]::WriteAllText($path, "Generated installer QA fixture $QaIdentity : $relative")
        $retainedFiles[$relative] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    }
    Invoke-TestProcess $installer '/S /OPENWITH=1 /DESKTOP=1' 'enable-options-reinstall' 0
    Assert-Payload 'Options reinstall'
    Assert-Choices $true 'Options enabled'
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
    foreach ($relative in @('Rat-Trap.exe', 'README-FIRST.txt')) {
        $beforeHashes = @(Get-InstalledHashes)
        $beforeRegistration = @(Get-RegTree $currentUser $arpPath)
        $label = if ($relative -eq 'Rat-Trap.exe') { 'exe' } else { 'readme' }
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
        }
        catch { $cleanupErrors.Add($_.Exception.Message) }
        $report = [pscustomobject][ordered]@{
            TestKind = 'Same-host Windows installer lifecycle; not a clean-VM test'
            CleanVm = $false
            QaIdentity = $QaIdentity
            StartedUtc = $testStarted.ToString('o')
            CompletedUtc = [DateTime]::UtcNow.ToString('o')
            WindowsVersion = [Environment]::OSVersion.VersionString
            Is64BitOperatingSystem = [Environment]::Is64BitOperatingSystem
            PowerShellVersion = $PSVersionTable.PSVersion.ToString()
            Installer = $buildResult
            TestedSourceHashes = @($testedSourceHashes)
            ExistingReferencedProgIds = @($observedProgIds)
            Passed = $null -eq $failure -and $cleanupErrors.Count -eq 0
            Failure = $failure
            CleanupErrors = @($cleanupErrors.ToArray())
            Checks = @($checks.ToArray())
            Limitations = @('No clean Windows VM, SmartScreen UI, or interactive wizard test.', 'A compatible same-version reinstall was tested; no future-version upgrade was claimed.', 'Generated archive/recovery fixtures test preservation, not user originals.')
        }
        [IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
        Write-Host "Lifecycle report: $reportPath"
    }
    $currentUser.Dispose()
    $localMachine.Dispose()
}
if ($null -ne $failure -or $cleanupErrors.Count -ne 0) { throw "Installer lifecycle QA failed: $failure $($cleanupErrors -join '; '). Report: $reportPath" }
Get-Content -LiteralPath $reportPath -Raw
