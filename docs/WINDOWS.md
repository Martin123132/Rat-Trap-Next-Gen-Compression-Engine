# Install and start Rat-Trap on Windows

## One download

[Download the Windows x64 installer](https://github.com/Martin123132/Rat-Trap-Next-Gen-Compression-Engine/releases/download/v5.7.0-preview.12/Rat-Trap-Windows-x64-setup.exe).

Use this executable, not GitHub's source-code ZIP or an older portable/MSIX
package. It is the current guided application with all five tutorials.
Python, Codex and a Rat-Trap account are not required.

This public preview targets Windows 10 or later, 64-bit. The recorded
qualification was on Windows 10; clean Windows 11 acceptance is still
outstanding. See the [release notes](releases/5.7.0-preview.12.md) for exact
versions, checksums and test scope.

## Before installing

The app and installer are **unsigned**. Microsoft Store approval and code
signing are not part of this download. Windows or your organisation may block
it or warn about an unknown publisher. Verify where you downloaded it and
the checksum; do not disable antivirus, SmartScreen or organisation policies.
If installation is blocked, stop and consult your administrator or
[support](../SUPPORT.md).

In PowerShell, from the folder containing the download:

```powershell
Get-FileHash -LiteralPath .\Rat-Trap-Windows-x64-setup.exe -Algorithm SHA256
```

The result must match:

```text
DA03D4BB04EE3389D23D0D5DA58AE8EFD5352915925F12039E41A8607E8256A4
```

A matching checksum checks the file against this release record; it is not
a code-signing certificate or independent security certification.

## Install and learn

1. Close an already running Rat-Trap window, then run the downloaded installer.
2. Follow Setup. Installation is for your Windows user and does not need
   administrator privileges.
3. Optional desktop shortcut and Open-with entries are initially off. They
   do not replace your default applications.
4. Open **Rat-Trap Desktop Preview 2** from Start.
5. Select **Show me how…** and choose a lesson.

The installed name stays the same so an existing Preview 2 installation is
updated in place instead of adding another app. The support label is
`5.7.0-desktop-preview.2-library.6`; the Windows numeric version is
`5.7.0.12`. The application is the previously qualified build; the installer
was rebuilt for public release with an additional shortcut-uninstall safeguard.
Its embedded guide describes the original local-preview qualification.

The five guided practices cover Vault search, folder compression, restoring
an archive, protecting and recovering a file, and browsing backup history.
They use fictional sample files and the real storage engines. Only the
controls needed for the current step are available; Back and Exit remain
available. You can then use the normal workspaces on your own files.

## Use your own files safely

Start with copies of a small folder. Save an archive outside its source
folder, restore it into a separate new folder, and check the restored files.
Keep originals and an independent backup while using the preview.

- **GMW archives:** compact portable folders, with optional encryption.
- **Queryable Vaults:** stored filenames, supported text and structured tables
  can be searched without extracting the entire collection.
- **Backups & history:** manually create snapshots and restore an earlier
  version into a new folder. Live repositories are not encrypted.
- **Library & timeline:** organise stored items by project, search filenames,
  restore supported individual files, and run a manual health check.
  Save a backup plan and choose **Back up now** when you want another version.
  Plans do not run automatically.
- **Sealed Files:** protect a copy of an individual file, with password access
  and an independent recovery key.

Keep recovery keys separately from their protected files. Anyone with the
matching key can unlock the file; losing both password and recovery key
makes recovery impossible. Unlocking can create temporary plaintext files;
cleanup is best-effort, not secure erasure. See the
[technical boundaries](TECHNICAL.md#exact-feature-boundaries).

## Updates, removal and help

There is no automatic updater. Future downloads will be identified on the
[project front page](../README.md). Do not delete your old archives, Vaults,
repositories or keys as part of an application update.

Remove the application through Windows Settings → Apps, selecting
**Rat-Trap Desktop Preview 2**. Your separately saved data remains yours to
manage; uninstalling the app is not a data-erasure operation.

For problems, follow [support guidance](../SUPPORT.md). A
[public issue](https://github.com/Martin123132/Rat-Trap-Next-Gen-Compression-Engine/issues)
must contain only non-confidential examples. Use the private contact route
for [security reports](../SECURITY.md).
