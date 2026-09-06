# Rat-Trap 5.6.0 company publisher gate

Status: company identity fixed; Microsoft Store identity pending

## Frozen product identity

Rat-Trap is a product owned and published by **TWO HANDS NETWORK LTD** under
its written agreements with the project's contributors.

The Rat-Trap compressor implementation was designed and built by Glyn Evans,
drawing on Motion-TimeSpace work by Martin Ollett. These credits do not vary
the applicable written agreements.

The selected primary Windows distribution route is:

- product: Rat-Trap;
- owner: TWO HANDS NETWORK LTD;
- public publisher intention: Two Hands Network Ltd;
- package type: x64 MSIX; and
- primary channel: Microsoft Store.

The Store channel is separate from a direct download. Microsoft signs a Store
MSIX after certification. A GitHub, website, enterprise, or `.appinstaller`
download still needs its own trusted production signature.

## Values that must not be invented

The public manifest is not complete until Partner Center assigns:

1. `Package/Identity/Name`;
2. `Package/Identity/Publisher`; and
3. `Package/Properties/PublisherDisplayName`.

The visible reserved name `Rat-Trap` is not necessarily the internal package
identity name. The Publisher value is case-sensitive and certificate-bound.
Do not substitute `TwoHandsNetwork.RatTrap`, `CN=Two Hands Network Ltd`, or
any other guessed value.

The authoritative record is:

`packaging/publisher-profile.json`

Its Store fields remain `null` and its status remains
`pending_partner_center` until copied verbatim from:

Partner Center > Product management > Product identity

## Partner Center company step

An authorised company representative must:

1. start at `https://storedeveloper.microsoft.com`;
2. choose a Company account for TWO HANDS NETWORK LTD;
3. use legal name and address details that exactly match the company record;
4. complete mandatory company and employment verification with a named work
   contact and supporting company or D-U-N-S evidence;
5. create a new MSIX or PWA product;
6. check and reserve `Rat-Trap`, if available; and
7. copy the Product identity values into the publisher profile.

Do not create a duplicate developer account if the company already has one.

## Build behaviour

`scripts/build_msix_5_6_0.ps1` has two fail-closed channels.

### Development

The default Development channel uses a separate, non-permanent package name
and Microsoft's explicit unsigned-package OID marker. It is for structural
validation only and is not the Store identity or a public installer.

### Store

The Store channel refuses to build while the publisher profile status is
pending or any required field is blank or looks like a placeholder:

```powershell
powershell -ExecutionPolicy Bypass -File `
  scripts\build_msix_5_6_0.ps1 -Channel Store
```

Once the exact Partner Center values are present, the script creates an
unsigned `-store-upload.msix`. It is intended only for Partner Center; the
Microsoft Store supplies the public trusted signature after certification.

## Release gates

A Store-labelled package must not be called ready until:

- the company developer account is verified;
- the `Rat-Trap` name reservation is confirmed;
- the three manifest identity values match Partner Center exactly;
- the package passes MakeAppx pack, unpack, identity, inventory and payload
  verification;
- the Store submission validator accepts the package;
- certification completes and the Store-signed result is available; and
- install, file-association, upgrade, repair and uninstall tests pass using
  the Store identity.

The optional direct-download lane remains blocked until TWO HANDS NETWORK LTD
chooses and controls a separate trusted production signing service or
certificate.
