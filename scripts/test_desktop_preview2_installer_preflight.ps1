[CmdletBinding()]
param()

# Build-input tests only: no installation, registry writes, or app launching.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$payload = (Resolve-Path -LiteralPath (Join-Path $repoRoot '../../outputs/Rat-Trap-Desktop-Preview-2')).Path
$compiler = Join-Path $repoRoot 'build/tools/portable/nsis-3.12/makensis.exe'
$builder = Join-Path $PSScriptRoot 'build_windows_desktop_preview2_installer.ps1'
$preview = Get-Content -LiteralPath (Join-Path $repoRoot 'release-manifests/desktop-preview-2.json') -Raw | ConvertFrom-Json
$qaId = [guid]::NewGuid().ToString('N')
$qaRoot = Join-Path $repoRoot "build/preview2-installer-preflight/$qaId"
$checks = New-Object 'Collections.Generic.List[object]'
$failure = $null
$started = [DateTime]::UtcNow
[IO.Directory]::CreateDirectory($qaRoot) | Out-Null

function Assert-Result([bool]$Condition, [string]$Name) {
    $checks.Add([pscustomobject]@{ Name = $Name; Passed = $Condition })
    Write-Host ("{0}: {1}" -f $(if ($Condition) { 'PASS' } else { 'FAIL' }), $Name)
    if (-not $Condition) { throw $Name }
}

function New-Case([string]$Name) {
    $caseRoot = Join-Path $qaRoot $Name
    $casePayload = Join-Path $caseRoot 'payload'
    [IO.Directory]::CreateDirectory($caseRoot) | Out-Null
    Copy-Item -LiteralPath $payload -Destination $casePayload -Recurse
    return [pscustomobject]@{ Root = $caseRoot; Payload = $casePayload; Destination = (Join-Path $caseRoot 'result') }
}

function Invoke-Case($Case, [bool]$ShouldPass, [bool]$ValidateOnly = $true, [string]$CompilerOverride = '') {
    $chosenCompiler = if ($CompilerOverride) { $CompilerOverride } else { $compiler }
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $builder + '"'),
        '-PayloadDirectory', ('"' + $Case.Payload + '"'), '-CompilerPath', ('"' + $chosenCompiler + '"'),
        '-DestinationDirectory', ('"' + $Case.Destination + '"'))
    if ($ValidateOnly) { $arguments += '-ValidateOnly' }
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Case.Root 'stdout.log') -RedirectStandardError (Join-Path $Case.Root 'stderr.log')
    try {
        # Windows PowerShell 5.1 can lose ExitCode for a fast child unless its
        # native handle is retained before waiting.
        [void]$process.Handle
        if (-not $process.WaitForExit(60000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw 'Builder preflight exceeded 60 seconds; only its newly created test process was stopped.'
        }
        $process.WaitForExit()
        Assert-Result ($null -ne $process.ExitCode -and (($process.ExitCode -eq 0) -eq $ShouldPass)) ((Split-Path -Leaf $Case.Root) + ' expected exit')
    }
    finally { $process.Dispose() }
}

try {
    $case = New-Case 'valid-payload'
    Invoke-Case $case $true
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'ValidateOnly creates no destination'

    $case = New-Case 'valid-payload-with-frozen-zip'
    Copy-Item -LiteralPath (Join-Path $repoRoot 'dist/desktop-preview-2/Rat-Trap-Desktop-Preview-2-Windows-x64-portable.zip') -Destination $case.Payload
    Invoke-Case $case $true
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'Frozen sibling ZIP validation creates no destination'

    $case = New-Case 'tampered-executable'
    [IO.File]::WriteAllText((Join-Path $case.Payload 'Rat-Trap-Desktop-Preview-2.exe'), 'Inert deliberately invalid test executable; never run.')
    Invoke-Case $case $false
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'Tampered executable rejected before output'

    $case = New-Case 'tampered-document-with-updated-checksum'
    [IO.File]::AppendAllText((Join-Path $case.Payload 'README-FIRST.txt'), "`r`nDeliberately changed test instructions.")
    $lines = @(Get-Content -LiteralPath (Join-Path $case.Payload 'SHA256SUMS.txt') | ForEach-Object {
        if ($_ -match '  README-FIRST\.txt$') { (Get-FileHash -LiteralPath (Join-Path $case.Payload 'README-FIRST.txt') -Algorithm SHA256).Hash + '  README-FIRST.txt' }
        else { $_ }
    })
    [IO.File]::WriteAllLines((Join-Path $case.Payload 'SHA256SUMS.txt'), $lines, (New-Object Text.UTF8Encoding($false)))
    Invoke-Case $case $false
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'Self-rewritten checksums cannot replace frozen release hashes'

    $case = New-Case 'unexpected-file'
    [IO.File]::WriteAllText((Join-Path $case.Payload 'extra.txt'), 'Generated unexpected input.')
    Invoke-Case $case $false
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'Unexpected payload file rejected before output'

    $case = New-Case 'missing-file'
    Remove-Item -LiteralPath (Join-Path $case.Payload 'SUPPORT.md')
    Invoke-Case $case $false
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'Missing payload file rejected before output'

    $case = New-Case 'tampered-sibling-zip'
    [IO.File]::WriteAllText((Join-Path $case.Payload 'Rat-Trap-Desktop-Preview-2-Windows-x64-portable.zip'), 'Generated invalid ZIP; do not accept by name alone.')
    Invoke-Case $case $false
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'Invalid sibling ZIP rejected before output'

    $case = New-Case 'mismatched-compiler'
    $fakeCompiler = Join-Path $case.Root 'not-a-compiler.exe'
    [IO.File]::WriteAllText($fakeCompiler, 'Inert test bytes. Hash check must reject without execution.')
    Invoke-Case $case $false $true $fakeCompiler
    Assert-Result (-not (Test-Path -LiteralPath $case.Destination)) 'Mismatched compiler rejected before output'

    $case = New-Case 'existing-destination'
    [IO.Directory]::CreateDirectory($case.Destination) | Out-Null
    $sentinel = Join-Path $case.Destination 'Rat-Trap-Desktop-Preview-2-Windows-x64-setup.exe'
    [IO.File]::WriteAllText($sentinel, 'Generated existing-output fixture; never overwrite.')
    $sentinelHash = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
    Invoke-Case $case $false $false
    Assert-Result ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ceq $sentinelHash) 'Existing destination remains byte-identical'
    Assert-Result (@(Get-ChildItem -LiteralPath $case.Destination -Force).Count -eq 1) 'No partial output left beside existing destination'

    foreach ($entry in $preview.payload_sha256.PSObject.Properties) {
        Assert-Result ((Get-FileHash -LiteralPath (Join-Path $payload $entry.Name) -Algorithm SHA256).Hash -ceq $entry.Value) ('Original input unchanged: ' + $entry.Name)
    }
}
catch { $failure = $_.Exception.Message; Write-Warning $failure }
finally {
    $reportPath = Join-Path $qaRoot 'preflight-report.json'
    $record = [ordered]@{
        Kind = 'Desktop Preview 2 installer build-input negative tests; no installation'
        StartedUtc = $started.ToString('o'); CompletedUtc = [DateTime]::UtcNow.ToString('o')
        Passed = $null -eq $failure; Failure = $failure; Checks = @($checks.ToArray())
        BuilderSha256 = (Get-FileHash -LiteralPath $builder -Algorithm SHA256).Hash
        TestScriptSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
        GeneratedFixturesRetained = $true; RegistryChanged = $false; InstallerExecuted = $false
    }
    [IO.File]::WriteAllText($reportPath, ($record | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    Write-Host "Preflight report: $reportPath"
}
if ($failure) { throw "Preflight tests failed: $failure" }
Get-Content -LiteralPath $reportPath -Raw
