# Rat-Trap 5.5.0 Windows integration gate

Status: release-candidate requirements for the Windows Integration Beta

## Scope

Rat-Trap 5.5 adds a reproducible x64 MSIX packaging lane, branded Windows
assets, executable icon resources, and safe file activation for `.rtsf` and
`.gmw`. It does not change the registered GMW, encrypted-envelope, repository,
Vault, or Sealed File formats.

The package targets Windows Desktop build 19041 or later and is tested on
Windows 10 build 19045. Its manifest uses `packagedClassicApp`, `mediumIL`, and
the restricted `runFullTrust` capability required by the existing desktop
application.

## File activation

The package registers two separate Open-with associations:

| Extension | Display name | Launch request |
|---|---|---|
| `.rtsf` | Rat-Trap Sealed File | `--open-sealed "%1"` |
| `.gmw` | Rat-Trap GMW Archive | `--open-archive "%1"` |

Activation is selection only:

- `.rtsf` selects **Secure files / Open / restore**;
- `.gmw` selects **Inspect / export**;
- no credential prompt is shown merely because Windows launched the app;
- no file is opened, parsed, verified, decrypted, extracted, replaced, or
  modified until the user chooses an explicit action inside Rat-Trap; and
- invalid extensions and ambiguous or extra arguments are rejected.

Rat-Trap does not attempt to force itself as the Windows default application.
The user remains in control of the default-app choice.

`.rtrk` recovery keys are deliberately not registered. Registering a recovery
key adds little value and risks encouraging users to treat the credential as
an ordinary document. A recovery key is selected explicitly inside the
authenticated operation for its matching archive or Sealed File.

## Package integrity and identity

The MSIX manifest enables:

```xml
<uap10:PackageIntegrity>
  <uap10:Content Enforcement="on" />
</uap10:PackageIntegrity>
```

This allows supported Windows versions to block launch and offer repair if
deployed package content is changed after signing.

The default build identity is intentionally development-only:

```text
Name:      RatTrap.Development
Publisher: CN=Rat-Trap Development
```

It is not a permanent public identity. Before the first public MSIX, Rat-Trap
must freeze:

1. the permanent package name;
2. the legal publisher display name;
3. the exact X.509 publisher subject; and
4. the HTTPS update location, if direct App Installer updates are enabled.

Changing package identity later can break the normal Windows upgrade and
association path.

## Signing

`scripts/build_msix_5_5_0.ps1` has two modes:

- without `CertificateThumbprint`, it creates an explicitly named
  `-unsigned.msix` structure-validation artifact;
- with a Current User `My` code-signing certificate thumbprint, it verifies
  validity, private-key access, Code Signing EKU, and an exact publisher
  subject match, signs the staged executable, packages the app, signs the
  MSIX, and verifies the result with SignTool.

The build script never creates, trusts, exports, or embeds a private signing
key. It never places a certificate password in source or accepts one as an
ordinary command-line parameter.

A public package is blocked until a trusted production publisher certificate
or Microsoft Store signing identity exists. A self-signed certificate is
suitable only for controlled development because every test device must
explicitly trust it.

Production signing should use SHA-256 and a trusted RFC 3161 timestamp. The
manifest `Publisher` must exactly match the signing certificate subject.

## Direct update feed

The optional `.appinstaller` file is generated only when:

- the package is signed;
- both the App Installer and MSIX URIs are supplied;
- both URIs are absolute HTTPS locations; and
- the identity, publisher, architecture, and four-part version match the
  packaged application.

The 2021 App Installer schema checks for updates on launch with a 12-hour
minimum interval and does not block activation while an update is available.
No update feed is claimed until a stable HTTPS host is selected and tested
with the correct MIME types and content-length behaviour.

## Explorer command boundary

This beta does not install a general **Seal with Rat-Trap** context-menu
command for arbitrary files or folders. Current Windows Explorer integration
requires a native x64 COM DLL implementing `IExplorerCommand`, plus
`windows.comServer` and `windows.fileExplorerContextMenus` registrations.
That component runs in the Explorer shell path and therefore requires its own
implementation, signing, performance, crash-isolation, and clean-uninstall
gate. It must only launch Rat-Trap with `--seal-file` or `--seal-folder`; it
must never compress or encrypt inside Explorer.

## Required verification

A 5.5 Windows integration candidate must pass:

1. the complete Python unit suite;
2. Python compilation;
3. launch-parser tests for `.rtsf`, `.gmw`, invalid extensions, ambiguous
   arguments, and no automatic work;
4. frozen `Rat-Trap.exe --self-test`;
5. frozen `Rat-Trap.exe --self-test-folder` on the canonical 464-file corpus;
6. FileVersion and ProductVersion `5.5.0`;
7. executable icon-resource inspection;
8. MakeAppx manifest/schema validation;
9. unpack-and-inventory verification of the completed MSIX;
10. presence of the product notices, upstream licence texts, and available
    component SBOMs in the completed MSIX;
11. explicit unsigned status for a development artifact, or SignTool
    verification for a signed artifact; and
12. clean install, launch, association, upgrade, repair, and uninstall tests
    before any signed package is called a public release.

## Current limitations

- No trusted production signing identity is configured.
- The development MSIX cannot be called a public installer.
- The generic native Explorer context-menu component is not included.
- A permanent package name and update URL have not been frozen.
- Windows may keep an existing default application even after Rat-Trap
  registers as a handler; that is expected user-controlled behaviour.
- MSIX package integrity protects installed application files, not user data,
  `.gmw`, `.rtsf`, passwords, recovery keys, or plaintext temporary files.

## Microsoft platform references

- <https://learn.microsoft.com/windows/msix/desktop/desktop-to-uwp-manual-conversion>
- <https://learn.microsoft.com/windows/msix/package/signing-package-overview>
- <https://learn.microsoft.com/windows/msix/desktop/tamper-protection>
- <https://learn.microsoft.com/windows/apps/desktop/modernize/integrate-packaged-app-with-file-explorer>
- <https://learn.microsoft.com/windows/msix/app-installer/auto-update-and-repair--overview>
