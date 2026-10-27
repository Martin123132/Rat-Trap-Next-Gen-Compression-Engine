#Requires -Version 5.1
<#
.SYNOPSIS
Build the unsigned Library preview from this checkout and pinned local tools.
.NOTES
No old private payload/MSIX is needed. No downloads, dependency installation,
normal app installation, association changes, signing or publication occurs.
Output must be a new child of dist. Failed staging is retained for diagnosis.
#>
[CmdletBinding()]
param([string]$PythonPath, [Alias('DestinationDir')][string]$DestinationDirectory, [switch]$ValidateOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
if ([string]::IsNullOrWhiteSpace($PythonPath)) { $PythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe' }
$python = (Resolve-Path -LiteralPath $PythonPath).ProviderPath
$requirements = Join-Path $repoRoot 'requirements-build-5.7.0.txt'
$entrypoint = Join-Path $repoRoot 'windows_library_preview.py'
$icon = Join-Path $repoRoot 'packaging\branding\rat-trap.ico'
$guide = Join-Path $repoRoot 'packaging\direct\README-LIBRARY-HEALTH.txt'
$distRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'dist')).TrimEnd('\')
if ([string]::IsNullOrWhiteSpace($DestinationDirectory)) { $DestinationDirectory = Join-Path $distRoot ('library-' + [guid]::NewGuid().ToString('N')) }
$destination = [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestinationDirectory)).TrimEnd('\')
if ([IO.Path]::GetDirectoryName($destination) -ine $distRoot) { throw 'Destination must be a new immediate child of this checkout''s dist directory.' }
if (Test-Path -LiteralPath $destination) { throw "Refusing to overwrite: $destination" }
$documentNames = @('LICENSE.md','COMMERCIAL-LICENSE.md','NOTICE.md','THIRD-PARTY-NOTICES.md','README-WINDOWS.txt','PRIVACY.md','SUPPORT.md')
$sourcePaths = @($PSCommandPath, $requirements, $entrypoint, $icon, $guide) + @($documentNames | ForEach-Object { Join-Path $repoRoot $_ }) +
    @(Get-ChildItem -LiteralPath (Join-Path $repoRoot 'rat_trap') -Recurse -File -Filter '*.py' | ForEach-Object {$_.FullName})
foreach ($path in $sourcePaths + @((Join-Path $repoRoot 'rat_trap\library.py'), (Join-Path $repoRoot 'rat_trap\library_app.py'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required checkout input missing: $path" }
}
if ((Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash -cne 'CCF125BCFC4E77ED5AFECB059116F836D40D9F4715501F6C90CE67B11D3676E5') { throw 'Exact dependency pins changed.' }
# Read-only resolver. Absolute paths stay in local build evidence, not installed
# COMPONENTS.json. Licence texts and SBOMs come from this installed environment.
$probe = @'
import hashlib, importlib.metadata as md, json, platform, re, sqlite3, ssl, struct, sys
from pathlib import Path
from cryptography.hazmat.backends.openssl.backend import backend
expected = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
    line = line.strip()
    if not line or line.startswith("#"): continue
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
    if not match: raise SystemExit("Exact pins required")
    name, version = match.groups()
    canonical = re.sub(r"[-_.]+", "-", name).lower()
    if canonical in expected or md.version(name) != version: raise SystemExit("Dependency mismatch: " + name)
    expected[canonical] = version
if len(expected) != 13 or platform.python_version() != "3.13.13" or struct.calcsize("P") != 8:
    raise SystemExit("Expected 13 pins and Python 3.13.13 x64")
installed = {re.sub(r"[-_.]+", "-", d.metadata["Name"]).lower() for d in md.distributions()}
if installed - set(expected) - {"pip", "rat-trap"}: raise SystemExit("Unexpected build distributions")
if not backend.openssl_version_text().startswith("OpenSSL 4.0.1 "): raise SystemExit("Unexpected cryptography OpenSSL")
copies = []
def add(source, target):
    source = Path(source)
    if source.is_symlink() or not source.is_file(): raise SystemExit("Missing/linked licence input")
    source = source.resolve(strict=True)
    copies.append({"source": str(source), "target": target,
                   "sha256": hashlib.sha256(source.read_bytes()).hexdigest().upper()})
def distfile(name, suffix):
    d = md.distribution(name)
    matches = [p for p in d.files or [] if str(p).replace("\\", "/").endswith(suffix)]
    if len(matches) != 1: raise SystemExit("Missing/ambiguous licence: " + name + suffix)
    return d.locate_file(matches[0])
legal = "Legal/THIRD-PARTY-LICENSES/"
base = Path(sys.base_prefix)
add(base / "LICENSE.txt", legal + "PYTHON-3.13.13-LICENSE.txt")
add(base / "tcl/tk8.6/license.terms", legal + "TCL-TK-8.6-LICENSE.txt")
primary = [
("pyinstaller","/licenses/COPYING.txt","PYINSTALLER-6.21.0-COPYING.txt"),
("pyinstaller-hooks-contrib","/licenses/LICENSE","PYINSTALLER-HOOKS-CONTRIB-2026.6-LICENSE.txt"),
("pyfastcdc","/licenses/LICENSE","PYFASTCDC-0.2.1-LICENSE.txt"),
("typing_extensions","/licenses/LICENSE","TYPING-EXTENSIONS-4.15.0-LICENSE.txt"),
("zstandard","/licenses/LICENSE","PYTHON-ZSTANDARD-0.25.0-LICENSE.txt"),
("cryptography","/licenses/LICENSE","CRYPTOGRAPHY-49.0.0-LICENSE.txt"),
("cryptography","/licenses/LICENSE.APACHE","CRYPTOGRAPHY-49.0.0-LICENSE-APACHE.txt"),
("cryptography","/licenses/LICENSE.BSD","CRYPTOGRAPHY-49.0.0-LICENSE-BSD.txt"),
("cryptography","/licenses/LICENSE.APACHE","OPENSSL-4.0.1-LICENSE.txt"),
("cffi","/licenses/LICENSE","CFFI-2.1.0-LICENSE.txt"),
("pycparser","/licenses/LICENSE","PYCPARSER-3.0-LICENSE.txt")]
for name, suffix, target in primary: add(distfile(name, suffix), legal + target)
for suffix, target in [("/sboms/sbom.json","cryptography-49.0.0-wheel-sbom.json"),("/sboms/cryptography-rust.cyclonedx.json","cryptography-49.0.0-rust-sbom.json")]:
    add(distfile("cryptography", suffix), "Legal/SBOM/" + target)
# Include build-only and vendored tool licences conservatively, without claiming
# every build dependency is present at runtime.
for name in sorted(expected):
    d = md.distribution(name)
    files = [p for p in d.files or [] if re.match(r"(?i)^(license|licence|copying)([.-].*)?$", Path(str(p)).name)]
    if not files: raise SystemExit("No licence for " + name)
    for index, item in enumerate(files, 1):
        relative = str(item).replace("\\", "/")
        if ".." in Path(relative).parts or relative.startswith("/"): raise SystemExit("Unsafe metadata path")
        target = "Legal/BUILD-DEPENDENCY-LICENSES/" + name + "/" + str(index) + "-" + Path(relative).name + ".txt"
        add(d.locate_file(item), target)
        copies[-1].update(source_distribution=name, source_record=relative)
if len(copies) != len({c["target"] for c in copies}): raise SystemExit("Duplicate legal output")
print(json.dumps({"python":platform.python_version(),"architecture":"x64","dependencies":expected,
 "python_openssl":ssl.OPENSSL_VERSION,"cryptography_openssl":backend.openssl_version_text(),
 "sqlite":sqlite3.sqlite_version,"licence_copies":copies}, sort_keys=True))
'@
$probeOutput = $probe | & $python -I - $requirements
if ($LASTEXITCODE -ne 0) { throw 'Read-only environment/licence preflight failed.' }
$environment = ($probeOutput -join [char]10) | ConvertFrom-Json
if ($ValidateOnly) {
    [pscustomobject]@{Preflight='Passed'; Built=$false; Version='5.7.0-desktop-preview.2-library.5'; Python=$environment.python
        DependencyCount=@($environment.dependencies.PSObject.Properties).Count; LicenceInputCount=@($environment.licence_copies).Count; DestinationDirectory=$destination}
    return
}
$sourceHashes = @{}
foreach ($path in $sourcePaths) { $sourceHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
foreach ($item in $environment.licence_copies) { $sourceHashes[$item.source] = $item.sha256 }
$buildDirectory = Join-Path $repoRoot ('build\library-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($buildDirectory)
[void][IO.Directory]::CreateDirectory($distRoot)
$stage = Join-Path $distRoot ('.library-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($stage)
$previousConfig = [Environment]::GetEnvironmentVariable('PYINSTALLER_CONFIG_DIR','Process')
$utf8 = New-Object Text.UTF8Encoding($false)
try {
    foreach ($item in $environment.licence_copies) {
        $target = Join-Path $stage $item.target
        if (-not [IO.Path]::GetFullPath($target).StartsWith($stage + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Licence output escaped staging.' }
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        [IO.File]::Copy($item.source,$target,$false)
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -cne $item.sha256) { throw 'Licence copy changed.' }
    }
    foreach ($name in $documentNames) {
        $target = if ($name -in @('PRIVACY.md','SUPPORT.md')) {Join-Path $stage $name} else {Join-Path $stage "Legal\$name"}
        [IO.File]::Copy((Join-Path $repoRoot $name),$target,$false)
    }
    [IO.File]::Copy($guide,(Join-Path $stage 'README-FIRST.txt'),$false)
    $sqliteNotice = @"
SQLite $($environment.sqlite) is distributed with Python's sqlite3 module.
SQLite deliverable code is dedicated to the public domain by its authors.
Official copyright/dedication information: https://sqlite.org/copyright.html
This explanatory notice is not a replacement licence or warranty.
"@
    [IO.File]::WriteAllText((Join-Path $stage 'Legal\THIRD-PARTY-LICENSES\SQLITE-PUBLIC-DOMAIN.txt'),$sqliteNotice,$utf8)
    $components = [ordered]@{schema='rat-trap-library-build-components/v1'; python=$environment.python
        python_openssl=$environment.python_openssl; cryptography_openssl=$environment.cryptography_openssl; sqlite=$environment.sqlite
        build_dependencies=$environment.dependencies
        note='Build dependencies include tools not necessarily bundled at runtime. Python LICENSE includes Windows runtime notices. Cryptography SBOMs identify compiled dependencies.'
        licence_files=@($environment.licence_copies | ForEach-Object {
            $record = [ordered]@{path=$_.target;sha256=$_.sha256}
            if ($_.PSObject.Properties.Name -contains 'source_record') {
                $record.Add('source_distribution', $_.source_distribution)
                $record.Add('source_record', $_.source_record)
            }
            $record
        })}
    [IO.File]::WriteAllText((Join-Path $stage 'Legal\COMPONENTS.json'),($components | ConvertTo-Json -Depth 8),$utf8)
    $version = @'
VSVersionInfo(
 ffi=FixedFileInfo(filevers=(5,7,0,11),prodvers=(5,7,0,11),mask=0x3f,flags=0x2,OS=0x40004,fileType=0x1,subtype=0,date=(0,0)),
 kids=[StringFileInfo([StringTable(u'040904B0',[
 StringStruct(u'CompanyName',u'TWO HANDS NETWORK LTD'),
 StringStruct(u'FileDescription',u'Rat-Trap Library and project timeline preview'),
 StringStruct(u'FileVersion',u'5.7.0.11'),
 StringStruct(u'InternalName',u'Rat-Trap-Desktop-Preview-2'),
 StringStruct(u'LegalCopyright',u'Copyright (c) 2026 TWO HANDS NETWORK LTD'),
 StringStruct(u'OriginalFilename',u'Rat-Trap-Desktop-Preview-2.exe'),
 StringStruct(u'ProductName',u'Rat-Trap Desktop Preview 2'),
 StringStruct(u'ProductVersion',u'5.7.0-desktop-preview.2-library.5')
 ])]),VarFileInfo([VarStruct(u'Translation',[1033,1200])])])
'@
    $versionPath = Join-Path $buildDirectory 'version-info.txt'
    [IO.File]::WriteAllText($versionPath,$version,$utf8)
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $buildDirectory 'pyinstaller-cache'
    $arguments = @('-I','-m','PyInstaller','--clean','--onefile','--windowed','--name','Rat-Trap-Desktop-Preview-2',
        '--paths',$repoRoot,'--collect-all','pyfastcdc','--hidden-import','zstandard','--icon',$icon,'--version-file',$versionPath,
        '--distpath',$stage,'--workpath',(Join-Path $buildDirectory 'work'),'--specpath',$buildDirectory,$entrypoint)
    Push-Location $repoRoot
    try { & $python @arguments; if ($LASTEXITCODE -ne 0) {throw 'PyInstaller failed; evidence retained.'} }
    finally {Pop-Location}
    $exeName = 'Rat-Trap-Desktop-Preview-2.exe'
    $exePath = Join-Path $stage $exeName
    $exe = Get-Item -LiteralPath $exePath
    if ($exe.Length -le 0 -or $exe.VersionInfo.FileVersion -cne '5.7.0.11' -or
        $exe.VersionInfo.ProductVersion -cne '5.7.0-desktop-preview.2-library.5' -or
        [string](Get-AuthenticodeSignature -LiteralPath $exePath).Status -cne 'NotSigned') {throw 'Unexpected executable identity or signature.'}
    $peCheck = @'
import pefile, sys
with pefile.PE(sys.argv[1], fast_load=True) as pe:
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Subsystem != 2:
        raise SystemExit("Expected Windows x64 GUI")
'@
    $peCheck | & $python -I - $exePath
    if ($LASTEXITCODE -ne 0) {throw 'Architecture/subsystem check failed.'}
    $selfTests = @('--self-test','--ui-self-test','--tutorial-self-test','--library-self-test','--store-folder-self-test','--library-search-self-test','--library-restore-self-test','--library-health-self-test')
    foreach ($mode in $selfTests) {
        $label = $mode.TrimStart('-')
        $process = Start-Process -FilePath $exePath -ArgumentList $mode -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $buildDirectory "$label.stdout.log") -RedirectStandardError (Join-Path $buildDirectory "$label.stderr.log")
        try {
            [void]$process.Handle
            if (-not $process.WaitForExit(300000)) {Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue; throw "Packaged $mode timed out."}
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) {throw "Packaged $mode failed: $($process.ExitCode)"}
        } finally {$process.Dispose()}
    }
    $payloadHashes = @{}
    $checksumLines = @(Get-ChildItem -LiteralPath $stage -Recurse -File | Sort-Object FullName | ForEach-Object {
        $relative=$_.FullName.Substring($stage.Length+1).Replace('\','/')
        $hash=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        $payloadHashes.Add($relative,$hash)
        "$hash  $relative"
    })
    [IO.File]::WriteAllLines((Join-Path $stage 'SHA256SUMS.txt'),$checksumLines,$utf8)
    $payloadHashes.Add('SHA256SUMS.txt',(Get-FileHash -LiteralPath (Join-Path $stage 'SHA256SUMS.txt') -Algorithm SHA256).Hash)
    foreach ($path in $sourceHashes.Keys) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne $sourceHashes[$path]) {throw "Input changed during build: $path"}
    }
    $publicSources=@{}
    foreach ($path in $sourcePaths) {$publicSources.Add($path.Substring($repoRoot.Length+1).Replace('\','/'),$sourceHashes[$path])}
    $receipt=[ordered]@{schema='rat-trap-library-build/v1';product='Rat-Trap Desktop Preview 2';version='5.7.0-desktop-preview.2-library.5'
        installer_version='5.7.0.11';base_engine_version='5.7.0';built_at_utc=[DateTime]::UtcNow.ToString('o')
        app_key='TwoHandsNetwork.RatTrap.DesktopPreview2';signature='NotSigned';executable=$exeName;executable_bytes=$exe.Length
        executable_sha256=$payloadHashes[$exeName];payload_files=$payloadHashes.Count
        legal_files=@($payloadHashes.Keys | Where-Object {$_.StartsWith('Legal/')}).Count;payload_sha256=$payloadHashes
        source_sha256=$publicSources;environment=$components;packaged_self_tests=$selfTests
        byte_reproducible_build_claimed=$false;installer_or_associations_created=$false;published_to_remote=$false}
    [IO.File]::WriteAllText((Join-Path $stage 'BUILD-MANIFEST.json'),($receipt | ConvertTo-Json -Depth 10),$utf8)
    [IO.File]::WriteAllText((Join-Path $buildDirectory 'input-provenance.json'),($sourceHashes | ConvertTo-Json -Depth 4),$utf8)
    if (Test-Path -LiteralPath $destination) {throw 'Destination appeared during build.'}
    [IO.Directory]::Move($stage,$destination)
    [pscustomobject]@{Product=$receipt.product;Version=$receipt.version;InstallerVersion=$receipt.installer_version
        Executable=(Join-Path $destination $exeName);ExecutableSha256=$receipt.executable_sha256
        BuildManifest=(Join-Path $destination 'BUILD-MANIFEST.json');BuildEvidence=$buildDirectory
        PayloadFileCount=$receipt.payload_files;LegalFileCount=$receipt.legal_files;Authenticode='NotSigned'}
}
finally {
    [Environment]::SetEnvironmentVariable('PYINSTALLER_CONFIG_DIR',$previousConfig,'Process')
    if (Test-Path -LiteralPath $stage) {Write-Warning "Incomplete staging retained: $stage"}
}
