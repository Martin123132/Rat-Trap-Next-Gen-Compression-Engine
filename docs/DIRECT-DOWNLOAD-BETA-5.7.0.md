# Rat-Trap 5.7.0 direct-download beta

Packaging stage: 5 September 2026. Publisher: TWO HANDS NETWORK LTD.

This stage wraps the existing, tested 5.7.0 Windows application in a portable
ZIP and a conventional installer. The compression engine and archived 5.7.0
EXE/MSIX are unchanged. No Partner Center account is needed to build or test
these packages. They are unsigned beta candidates; no public release or
repository visibility change has been performed.

## For beta testers

- `Rat-Trap-Windows-5.7.0-beta-setup.exe`: install for your Windows account,
  then open Rat-Trap Beta from the Start menu.
- `Rat-Trap-Windows-5.7.0-beta-portable.zip`: choose Extract All, open the
  extracted folder and run `Rat-Trap.exe`.

Both include the same app, legal notices, privacy/support documents and a
first-run guide. No separate Python installation or Rat-Trap account is
required. The ZIP contains 25 files; the installed payload adds the NSIS
licence for 26 files, plus the generated uninstaller. Each payload includes a
SHA256SUMS.txt listing every other payload file. There is no automatic updater.

Windows may warn about or block unsigned downloads. These packages have not
been granted a trusted publisher signature. Download checksums detect changed
bytes; they do not establish publisher identity on their own. Signing and
testing the downloaded experience remain requirements before a broad release.

## Installer behaviour

- Runs as the current user without an administrator prompt.
- Uses a fixed app directory:
  `%LOCALAPPDATA%\Programs\Two Hands Network Ltd\Rat-Trap Beta`.
- Creates a Start menu folder and an entry in Windows Apps settings.
- Offers optional desktop and Open-with choices, both initially unselected.
- Open-with adds `.gmw` and `.rtsf` entries without changing the current default
  applications or Windows UserChoice. `.rtrk` recovery keys are not associated.
- Quotes the executable and input path. Activation only selects the relevant
  app screen; no automatic decryption or extraction takes place.
- Reinstalling the same beta preserves optional choices unless explicitly
  changed, and restores missing installed files. It records an incomplete
  installation before writing app files so an interrupted installation can
  be repaired by rerunning Setup.
- Refuses to update/remove a locked payload file. It does not terminate a
  running Rat-Trap process. Linked installation directories and linked payload
  files are rejected.
- Uninstall removes an explicit list of installed files and empty directories.
  Files you add, including archives and recovery keys, are retained. Saved
  outputs and local diagnostics outside the app directory are retained too.
- If a payload deletion fails, the registered uninstaller remains available
  for retry. A completed uninstall that leaves user-added files in the app
  directory requires those files to be moved before a fresh install there.

The installer has its own beta identity, separate from the future Store app.
This is not an automatic migration from a Store installation. A future app
version needs an explicitly tested upgrade before its installer is released.

## Build from the frozen baseline

Run Windows PowerShell 5.1 or PowerShell 7 in the repository:

```powershell
.\scripts\package_windows_beta_5_7_0.ps1 `
  -DestinationDirectory .\dist\direct\5.7.0\release `
  -PayloadDirectory .\dist\direct\5.7.0\installer-payload

.\scripts\build_windows_beta_installer_5_7_0.ps1 `
  -PayloadDirectory .\dist\direct\5.7.0\installer-payload `
  -CompilerPath <path-to-official-NSIS-3.12>\makensis.exe `
  -DestinationDirectory .\dist\direct\5.7.0\release
```

Existing output files are refused. The ZIP packager checks both frozen
artifacts against the original release manifest and pinned baseline hashes,
then reads only the 20 recorded legal entries from the MSIX. It verifies all
ZIP entries before publishing the output. It needs no Python environment, SDK,
benchmarks, credentials or network access.

The installer builder checks the payload inventory and checksums, frozen EXE,
and recorded NSIS compiler. It generates explicit install/uninstall file lists,
includes the compiler licence, compiles with warnings treated as errors and
publishes only a completed installer. It never downloads a compiler itself.

Compiler: [official NSIS 3.12 portable ZIP](https://sourceforge.net/projects/nsis/files/NSIS%203/3.12/nsis-3.12.zip/download).
Archive SHA-256 observed for this build:
`56581F90DB321581C5381193D796FFFCF2D24B2F8FED2160A6C6A3BAA67F2C4F`.
The observed checksum records this download, not an independent publisher
signature. [NSIS licence](https://nsis.sourceforge.io/License).

## Verification boundary

The earlier app release passed 221 tests and the packaged 464-file corpus
round trip; see [the original reliability gate](WINDOWS-RELIABILITY-GATE-5.7.0.md).
Those are app results from July, not new clean-PC installation results.

This packaging stage adds executable installer lifecycle tests using a unique
test identity. The test build uses the same installer source and app payload,
but separate registry keys, shortcuts and installation folder. Its report
records the source hashes tested and each result. Tests cover default install,
checksum verification, repair/reinstall, optional choice changes, file locks,
uninstall, and retention of user-created test files. Shared file associations
are compared before and after testing.

The current machine is Windows 10 Home, build 19045. No ready Windows Sandbox
or clean Windows VM was found. Local lifecycle evidence must not be presented
as a clean-PC pass. The separate [clean-PC checklist](DIRECT-BETA-CLEAN-PC-CHECKLIST.md)
is still required, particularly for Windows 11 and the downloaded-file trust
experience. Current hashes and completed checks are recorded in the separate
[direct-beta release manifest](../release-manifests/5.7.0-direct-beta.json);
the original 5.7.0 manifest remains frozen.

Completed result: **150 of 150 installer checks passed**, with zero cleanup
errors, using the final installer source. This includes both a copied
uninstaller with an explicit installation path and the normal installed
uninstaller's temporary-process handoff. The host had no existing default
ProgIDs for these extensions; unchanged default/UserChoice state and two
generated other-app Open-with entries were verified. See the durable
[QA result summary](../packaging/direct/qa-results-5.7.0.json).

Final portable ZIP: 17,863,808 bytes; SHA-256
`E3540156601A823C0BD2CCE399270752716B09E909E6E19DA48770BA0B7F67E1`.
Final setup EXE: 17,872,557 bytes; SHA-256
`E0F2C9ED275B2A5A4BFD94A3606BF8930A29AF84F1E077B0FAA149D01B682209`.
The setup EXE declares `asInvoker`, has no Authenticode signature, and wraps
the x64 app in NSIS's standard x86 installer launcher.

## Next stages

1. Complete clean-PC testing and choose trusted signing for broader downloads.
2. Improve the home screen and everyday file selection, with user testing.
3. Package the terminal companion, then connect it to the calendar workflow.
4. Review all accumulated local changes and the intended public files before
   updating the original GitHub repository and changing its visibility.

No credentials, signing subscription, website deployment, GitHub publication
or repository visibility changes are part of this packaging stage.
