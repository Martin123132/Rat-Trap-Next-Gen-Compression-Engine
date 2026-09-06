[CmdletBinding()]
param(
    [ValidateSet("Development", "Store")]
    [string]$Channel = "Development",
    [string]$IdentityProfilePath,
    [string]$ExecutablePath,
    [string]$DestinationDir
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($IdentityProfilePath)) {
    $IdentityProfilePath = Join-Path $repoRoot (
        "packaging\publisher-profile.json"
    )
}
if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
    $ExecutablePath = Join-Path $repoRoot "dist\5.7.0\Rat-Trap.exe"
}
$IdentityProfilePath = [IO.Path]::GetFullPath($IdentityProfilePath)
$ExecutablePath = [IO.Path]::GetFullPath($ExecutablePath)

if (-not (Test-Path -LiteralPath $IdentityProfilePath -PathType Leaf)) {
    throw "Publisher profile is missing: $IdentityProfilePath"
}

$profile = Get-Content -LiteralPath $IdentityProfilePath -Raw |
    ConvertFrom-Json
if ($profile.schema -cne "rat-trap-publisher-profile/v1") {
    throw "Unsupported publisher-profile schema."
}
if (
    $profile.product.name -cne "Rat-Trap" -or
    $profile.product.version -cne "5.7.0" -or
    $profile.product.owner -cne "TWO HANDS NETWORK LTD"
) {
    throw "Publisher profile does not describe Rat-Trap 5.7.0 and its owner."
}
if (
    $profile.distribution.primary_channel -cne "Microsoft Store" -or
    $profile.distribution.package_type -cne "MSIX" -or
    -not $profile.distribution.store_signing_selected
) {
    throw "Publisher profile does not select the Microsoft Store MSIX lane."
}

if ($Channel -eq "Development") {
    $identity = $profile.development_identity
    $unsignedMarker = [string]$identity.unsigned_marker
    if (
        $identity.permanent -or
        $identity.public_release -or
        [string]::IsNullOrWhiteSpace($identity.name) -or
        [string]::IsNullOrWhiteSpace($identity.publisher) -or
        [string]::IsNullOrWhiteSpace($identity.publisher_display_name) -or
        -not $identity.publisher.EndsWith(
            $unsignedMarker,
            [StringComparison]::Ordinal
        )
    ) {
        throw "Development identity is not a valid explicit unsigned identity."
    }
    if ([string]::IsNullOrWhiteSpace($DestinationDir)) {
        $DestinationDir = Join-Path $repoRoot (
            "dist\msix\5.7.0\development"
        )
    }
}
else {
    $identity = $profile.store_identity
    if ($identity.status -cne "assigned") {
        throw (
            "Store identity is pending. Verify TWO HANDS NETWORK LTD in " +
            "Partner Center, reserve Rat-Trap, then copy the Product " +
            "identity values into packaging\publisher-profile.json."
        )
    }
    $required = @(
        [string]$identity.reserved_product_name,
        [string]$identity.package_identity_name,
        [string]$identity.package_identity_publisher,
        [string]$identity.package_properties_publisher_display_name
    )
    foreach ($value in $required) {
        if (
            [string]::IsNullOrWhiteSpace($value) -or
            $value.Contains("__") -or
            $value.Contains("REPLACE")
        ) {
            throw "Store identity contains a blank or placeholder value."
        }
    }
    if ([string]::IsNullOrWhiteSpace($DestinationDir)) {
        $DestinationDir = Join-Path $repoRoot (
            "dist\msix\5.7.0\store-upload"
        )
    }
}

if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "Rat-Trap 5.7.0 executable is missing: $ExecutablePath"
}

$DestinationDir = [IO.Path]::GetFullPath($DestinationDir)
$storePath = $null
if ($Channel -eq "Store") {
    $storePath = Join-Path $DestinationDir (
        "Rat-Trap-Windows-5.7.0-x64-store-upload.msix"
    )
    if (Test-Path -LiteralPath $storePath) {
        throw "Refusing to overwrite: $storePath"
    }
}
$baseBuilder = Join-Path $PSScriptRoot "build_msix_5_5_0.ps1"
if (-not (Test-Path -LiteralPath $baseBuilder -PathType Leaf)) {
    throw "Verified MSIX base builder is missing: $baseBuilder"
}

$buildParameters = @{
    ExecutablePath = $ExecutablePath
    DestinationDir = $DestinationDir
    PackageName = if ($Channel -eq "Development") {
        [string]$identity.name
    } else {
        [string]$identity.package_identity_name
    }
    Publisher = if ($Channel -eq "Development") {
        [string]$identity.publisher
    } else {
        [string]$identity.package_identity_publisher
    }
    PublisherDisplayName = if ($Channel -eq "Development") {
        [string]$identity.publisher_display_name
    } else {
        [string]$identity.package_properties_publisher_display_name
    }
    PackageVersion = "5.7.0.0"
}

& $baseBuilder @buildParameters
if (-not $?) {
    throw "The verified MSIX base builder failed."
}

$unsignedPath = Join-Path $DestinationDir (
    "Rat-Trap-Windows-5.7.0-x64-unsigned.msix"
)
if (-not (Test-Path -LiteralPath $unsignedPath -PathType Leaf)) {
    throw "The expected unsigned package was not published."
}

if ($Channel -eq "Store") {
    Move-Item -LiteralPath $unsignedPath -Destination $storePath
    Write-Host "Store upload candidate: $storePath"
}
else {
    Write-Host "Development validation candidate: $unsignedPath"
}
