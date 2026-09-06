[CmdletBinding()]
param(
    [string]$ExecutablePath,
    [string]$DestinationDir,
    [string]$PackageName = "RatTrap.Development",
    [string]$Publisher = "CN=Rat-Trap Development",
    [string]$PublisherDisplayName = "Rat-Trap Development",
    [string]$PackageVersion = "5.5.0.0",
    [string]$CertificateThumbprint,
    [string]$TimestampUrl,
    [string]$AppInstallerUri,
    [string]$PackageUri
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
    $ExecutablePath = Join-Path $repoRoot "dist\5.5.0\Rat-Trap.exe"
}
if ([string]::IsNullOrWhiteSpace($DestinationDir)) {
    $DestinationDir = Join-Path $repoRoot "dist\msix\5.5.0"
}
$ExecutablePath = [IO.Path]::GetFullPath($ExecutablePath)
$DestinationDir = [IO.Path]::GetFullPath($DestinationDir)

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Required executable is missing: $ExecutablePath"
}
if ($PackageVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw "MSIX PackageVersion must contain four numeric parts."
}
if (
    $PackageName -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]{1,48}[A-Za-z0-9]$'
) {
    throw "PackageName must be 3-50 letters, numbers, periods, or dashes."
}
if (
    [string]::IsNullOrWhiteSpace($Publisher) -or
    [string]::IsNullOrWhiteSpace($PublisherDisplayName)
) {
    throw "Publisher and PublisherDisplayName must not be empty."
}
if (
    [string]::IsNullOrWhiteSpace($AppInstallerUri) -xor
    [string]::IsNullOrWhiteSpace($PackageUri)
) {
    throw "AppInstallerUri and PackageUri must be supplied together."
}

function Find-WindowsSdkTool {
    param([Parameter(Mandatory = $true)][string]$Name)

    $sdkRoot = "C:\Program Files (x86)\Windows Kits\10\bin"
    if (-not (Test-Path -LiteralPath $sdkRoot -PathType Container)) {
        throw "Windows SDK tools directory is missing: $sdkRoot"
    }
    $versions = @(
        Get-ChildItem -LiteralPath $sdkRoot -Directory |
            Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } |
            Sort-Object { [version]$_.Name } -Descending
    )
    foreach ($version in $versions) {
        $candidate = Join-Path $version.FullName "x64\$Name"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw "Windows SDK tool '$Name' was not found."
}

function Escape-Xml {
    param([Parameter(Mandatory = $true)][string]$Value)

    return [Security.SecurityElement]::Escape($Value)
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )

    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Invoke-SignTool {
    param(
        [Parameter(Mandatory = $true)][string]$SignTool,
        [Parameter(Mandatory = $true)][string]$Thumbprint,
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$TimeStamp
    )

    $arguments = @(
        "sign",
        "/fd",
        "SHA256",
        "/sha1",
        $Thumbprint,
        "/s",
        "My"
    )
    if (-not [string]::IsNullOrWhiteSpace($TimeStamp)) {
        $arguments += @("/tr", $TimeStamp, "/td", "SHA256")
    }
    $arguments += $Path
    & $SignTool @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool failed for: $Path"
    }
}

$makeAppx = Find-WindowsSdkTool -Name "MakeAppx.exe"
$signTool = Find-WindowsSdkTool -Name "SignTool.exe"
$signed = -not [string]::IsNullOrWhiteSpace($CertificateThumbprint)
$certificate = $null

if ($signed) {
    $thumbprint = ($CertificateThumbprint -replace '\s', '').ToUpperInvariant()
    $certificatePath = "Cert:\CurrentUser\My\$thumbprint"
    $certificate = Get-Item -LiteralPath $certificatePath -ErrorAction Stop
    if (-not $certificate.HasPrivateKey) {
        throw "The selected signing certificate has no accessible private key."
    }
    $now = Get-Date
    if ($certificate.NotBefore -gt $now -or $certificate.NotAfter -le $now) {
        throw "The selected signing certificate is not currently valid."
    }
    $codeSigningOid = "1.3.6.1.5.5.7.3.3"
    $codeSigningEnabled = $false
    foreach ($extension in $certificate.Extensions) {
        if ($extension -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]) {
            foreach ($usage in $extension.EnhancedKeyUsages) {
                if ($usage.Value -eq $codeSigningOid) {
                    $codeSigningEnabled = $true
                }
            }
        }
    }
    if (-not $codeSigningEnabled) {
        throw "The selected certificate is not valid for code signing."
    }
    if ($certificate.Subject -cne $Publisher) {
        throw (
            "The manifest Publisher must exactly match the certificate subject. " +
            "Manifest: '$Publisher'; certificate: '$($certificate.Subject)'."
        )
    }
    if ([string]::IsNullOrWhiteSpace($TimestampUrl)) {
        Write-Warning (
            "The signed package will not be timestamped. A production release " +
            "should use a trusted RFC 3161 timestamp service."
        )
    }
}
elseif (
    -not [string]::IsNullOrWhiteSpace($AppInstallerUri) -or
    -not [string]::IsNullOrWhiteSpace($PackageUri)
) {
    throw "An App Installer update feed must not point to an unsigned package."
}

[IO.Directory]::CreateDirectory($DestinationDir) | Out-Null
$versionLabel = $PackageVersion.Substring(
    0,
    $PackageVersion.LastIndexOf(".")
)
$signatureLabel = if ($signed) { "" } else { "-unsigned" }
$packageFileName = "Rat-Trap-Windows-$versionLabel-x64$signatureLabel.msix"
$packagePath = Join-Path $DestinationDir $packageFileName
if (Test-Path -LiteralPath $packagePath) {
    throw "Refusing to overwrite an existing package: $packagePath"
}
$workingPackagePath = Join-Path $DestinationDir (
    ".rat-trap-msix-package-" + [guid]::NewGuid().ToString("N") + ".msix"
)
$workingAppInstallerPath = $null

$stageRoot = Join-Path $DestinationDir (
    ".rat-trap-msix-stage-" + [guid]::NewGuid().ToString("N")
)
$verifyRoot = Join-Path $DestinationDir (
    ".rat-trap-msix-verify-" + [guid]::NewGuid().ToString("N")
)
$manifestTemplate = Join-Path $repoRoot (
    "packaging\msix\AppxManifest.template.xml"
)
$appInstallerTemplate = Join-Path $repoRoot (
    "packaging\msix\Rat-Trap.appinstaller.template.xml"
)
$assetSource = Join-Path $repoRoot "packaging\msix\Assets"
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "The pinned Python build environment is missing: $venvPython"
}
$pythonBase = (& $venvPython -c "import sys; print(sys.base_prefix)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pythonBase)) {
    throw "Could not resolve the pinned Python base directory."
}
$sitePackages = Join-Path $repoRoot ".venv\Lib\site-packages"
$requiredAssets = @(
    "GMW.png",
    "RTSF.png",
    "Square44x44Logo.png",
    "Square150x150Logo.png",
    "StoreLogo.png"
)
$legalFiles = @(
    "COMMERCIAL-LICENSE.md",
    "LICENSE.md",
    "NOTICE.md",
    "README-WINDOWS.txt",
    "THIRD-PARTY-NOTICES.md"
)
$thirdPartyLicenses = @(
    @{
        Source = Join-Path $pythonBase "LICENSE.txt"
        Name = "PYTHON-3.13.13-LICENSE.txt"
    },
    @{
        Source = Join-Path $pythonBase "tcl\tk8.6\license.terms"
        Name = "TCL-TK-8.6-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "pyinstaller-6.21.0.dist-info\licenses\COPYING.txt"
        Name = "PYINSTALLER-6.21.0-COPYING.txt"
    },
    @{
        Source = Join-Path $sitePackages "pyinstaller_hooks_contrib-2026.6.dist-info\licenses\LICENSE"
        Name = "PYINSTALLER-HOOKS-CONTRIB-2026.6-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "pyfastcdc-0.2.1.dist-info\licenses\LICENSE"
        Name = "PYFASTCDC-0.2.1-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "typing_extensions-4.15.0.dist-info\licenses\LICENSE"
        Name = "TYPING-EXTENSIONS-4.15.0-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "zstandard-0.25.0.dist-info\licenses\LICENSE"
        Name = "PYTHON-ZSTANDARD-0.25.0-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "cryptography-49.0.0.dist-info\licenses\LICENSE"
        Name = "CRYPTOGRAPHY-49.0.0-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "cryptography-49.0.0.dist-info\licenses\LICENSE.APACHE"
        Name = "CRYPTOGRAPHY-49.0.0-LICENSE-APACHE.txt"
    },
    @{
        Source = Join-Path $sitePackages "cryptography-49.0.0.dist-info\licenses\LICENSE.BSD"
        Name = "CRYPTOGRAPHY-49.0.0-LICENSE-BSD.txt"
    },
    @{
        Source = Join-Path $sitePackages "cryptography-49.0.0.dist-info\licenses\LICENSE.APACHE"
        Name = "OPENSSL-4.0.1-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "cffi-2.1.0.dist-info\licenses\LICENSE"
        Name = "CFFI-2.1.0-LICENSE.txt"
    },
    @{
        Source = Join-Path $sitePackages "pycparser-3.0.dist-info\licenses\LICENSE"
        Name = "PYCPARSER-3.0-LICENSE.txt"
    }
)
$sbomFiles = @(
    @{
        Source = Join-Path $sitePackages "cryptography-49.0.0.dist-info\sboms\sbom.json"
        Name = "cryptography-49.0.0-wheel-sbom.json"
    },
    @{
        Source = Join-Path $sitePackages "cryptography-49.0.0.dist-info\sboms\cryptography-rust.cyclonedx.json"
        Name = "cryptography-49.0.0-rust-sbom.json"
    }
)

try {
    [IO.Directory]::CreateDirectory($stageRoot) | Out-Null
    $stageAssets = Join-Path $stageRoot "Assets"
    [IO.Directory]::CreateDirectory($stageAssets) | Out-Null

    Copy-Item -LiteralPath $ExecutablePath -Destination (
        Join-Path $stageRoot "Rat-Trap.exe"
    )
    foreach ($asset in $requiredAssets) {
        $source = Join-Path $assetSource $asset
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required MSIX asset is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination $stageAssets
    }
    $stageLegal = Join-Path $stageRoot "Legal"
    $stageLicenses = Join-Path $stageLegal "THIRD-PARTY-LICENSES"
    $stageSbom = Join-Path $stageLegal "SBOM"
    [IO.Directory]::CreateDirectory($stageLegal) | Out-Null
    [IO.Directory]::CreateDirectory($stageLicenses) | Out-Null
    [IO.Directory]::CreateDirectory($stageSbom) | Out-Null
    foreach ($name in $legalFiles) {
        $source = Join-Path $repoRoot $name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required legal file is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination $stageLegal
    }
    foreach ($license in $thirdPartyLicenses) {
        if (-not (Test-Path -LiteralPath $license.Source -PathType Leaf)) {
            throw "Required third-party licence is missing: $($license.Source)"
        }
        Copy-Item `
            -LiteralPath $license.Source `
            -Destination (Join-Path $stageLicenses $license.Name)
    }
    foreach ($sbom in $sbomFiles) {
        if (-not (Test-Path -LiteralPath $sbom.Source -PathType Leaf)) {
            throw "Required SBOM is missing: $($sbom.Source)"
        }
        Copy-Item `
            -LiteralPath $sbom.Source `
            -Destination (Join-Path $stageSbom $sbom.Name)
    }
    if (-not (Test-Path -LiteralPath $manifestTemplate -PathType Leaf)) {
        throw "MSIX manifest template is missing: $manifestTemplate"
    }

    $manifest = Get-Content -LiteralPath $manifestTemplate -Raw
    $replacements = @{
        "__PACKAGE_NAME__" = Escape-Xml $PackageName
        "__PUBLISHER__" = Escape-Xml $Publisher
        "__PUBLISHER_DISPLAY_NAME__" = Escape-Xml $PublisherDisplayName
        "__PACKAGE_VERSION__" = Escape-Xml $PackageVersion
    }
    foreach ($entry in $replacements.GetEnumerator()) {
        $manifest = $manifest.Replace($entry.Key, $entry.Value)
    }
    if ($manifest -match '__[A-Z_]+__') {
        throw "The generated AppxManifest.xml contains an unresolved token."
    }
    $manifestPath = Join-Path $stageRoot "AppxManifest.xml"
    Write-Utf8NoBom -Path $manifestPath -Text $manifest

    $stageExecutable = Join-Path $stageRoot "Rat-Trap.exe"
    if ($signed) {
        Invoke-SignTool `
            -SignTool $signTool `
            -Thumbprint $thumbprint `
            -Path $stageExecutable `
            -TimeStamp $TimestampUrl
    }

    & $makeAppx pack /d $stageRoot /p $workingPackagePath
    if ($LASTEXITCODE -ne 0) {
        throw "MakeAppx failed to create the package."
    }

    if ($signed) {
        Invoke-SignTool `
            -SignTool $signTool `
            -Thumbprint $thumbprint `
            -Path $workingPackagePath `
            -TimeStamp $TimestampUrl
        & $signTool verify /pa /all $workingPackagePath
        if ($LASTEXITCODE -ne 0) {
            throw "The signed MSIX failed SignTool verification."
        }
    }

    & $makeAppx unpack /p $workingPackagePath /d $verifyRoot
    if ($LASTEXITCODE -ne 0) {
        throw "The completed MSIX could not be unpacked for verification."
    }
    $verifiedManifest = Join-Path $verifyRoot "AppxManifest.xml"
    $verifiedExecutable = Join-Path $verifyRoot "Rat-Trap.exe"
    if (
        -not (Test-Path -LiteralPath $verifiedManifest -PathType Leaf) -or
        -not (Test-Path -LiteralPath $verifiedExecutable -PathType Leaf)
    ) {
        throw "The completed package is missing its manifest or executable."
    }
    [xml]$verifiedManifestXml = Get-Content `
        -LiteralPath $verifiedManifest `
        -Raw
    $verifiedIdentity = $verifiedManifestXml.Package.Identity
    if (
        $verifiedIdentity.Name -cne $PackageName -or
        $verifiedIdentity.Publisher -cne $Publisher -or
        $verifiedIdentity.Version -cne $PackageVersion -or
        $verifiedIdentity.ProcessorArchitecture -cne "x64"
    ) {
        throw (
            "The unpacked package identity does not match the requested " +
            "Name, Publisher, Version, and x64 architecture."
        )
    }

    $appInstallerPath = $null
    if (-not [string]::IsNullOrWhiteSpace($AppInstallerUri)) {
        $appInstallerAbsolute = [uri]$AppInstallerUri
        $packageAbsolute = [uri]$PackageUri
        if (
            -not $appInstallerAbsolute.IsAbsoluteUri -or
            -not $packageAbsolute.IsAbsoluteUri
        ) {
            throw "AppInstallerUri and PackageUri must be absolute URIs."
        }
        if (
            $appInstallerAbsolute.Scheme -ne "https" -or
            $packageAbsolute.Scheme -ne "https"
        ) {
            throw "Public App Installer and package URIs must use HTTPS."
        }
        $appInstaller = Get-Content -LiteralPath $appInstallerTemplate -Raw
        $installerReplacements = @{
            "__APPINSTALLER_URI__" = Escape-Xml $AppInstallerUri
            "__PACKAGE_URI__" = Escape-Xml $PackageUri
            "__PACKAGE_NAME__" = Escape-Xml $PackageName
            "__PUBLISHER__" = Escape-Xml $Publisher
            "__PACKAGE_VERSION__" = Escape-Xml $PackageVersion
        }
        foreach ($entry in $installerReplacements.GetEnumerator()) {
            $appInstaller = $appInstaller.Replace(
                $entry.Key,
                $entry.Value
            )
        }
        if ($appInstaller -match '__[A-Z_]+__') {
            throw "The generated .appinstaller contains an unresolved token."
        }
        $appInstallerPath = Join-Path $DestinationDir (
            "Rat-Trap-$versionLabel.appinstaller"
        )
        if (Test-Path -LiteralPath $appInstallerPath) {
            throw "Refusing to overwrite: $appInstallerPath"
        }
        $workingAppInstallerPath = Join-Path $DestinationDir (
            ".rat-trap-appinstaller-" +
            [guid]::NewGuid().ToString("N") +
            ".appinstaller"
        )
        Write-Utf8NoBom `
            -Path $workingAppInstallerPath `
            -Text $appInstaller
    }

    Move-Item -LiteralPath $workingPackagePath -Destination $packagePath
    if ($null -ne $workingAppInstallerPath) {
        Move-Item `
            -LiteralPath $workingAppInstallerPath `
            -Destination $appInstallerPath
    }
    $packageHash = (
        Get-FileHash -LiteralPath $packagePath -Algorithm SHA256
    ).Hash
    Write-Host "Created: $packagePath"
    Write-Host "Signed: $signed"
    Write-Host "SHA-256: $packageHash"
    if ($null -ne $appInstallerPath) {
        Write-Host "App Installer: $appInstallerPath"
    }
}
finally {
    $destinationPrefix = $DestinationDir.TrimEnd('\') + '\'
    foreach ($temporary in @($stageRoot, $verifyRoot)) {
        $resolved = [IO.Path]::GetFullPath($temporary)
        if (
            $resolved.StartsWith(
                $destinationPrefix,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Test-Path -LiteralPath $resolved)
        ) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
    foreach (
        $temporaryFile in @(
            $workingPackagePath,
            $workingAppInstallerPath
        )
    ) {
        if ([string]::IsNullOrWhiteSpace($temporaryFile)) {
            continue
        }
        $resolvedFile = [IO.Path]::GetFullPath($temporaryFile)
        if (
            $resolvedFile.StartsWith(
                $destinationPrefix,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            (Test-Path -LiteralPath $resolvedFile -PathType Leaf)
        ) {
            Remove-Item -LiteralPath $resolvedFile -Force
        }
    }
}
