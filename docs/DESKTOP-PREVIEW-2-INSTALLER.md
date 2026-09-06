# Rat-Trap Desktop Preview 2 installer

This is a separate **unsigned preview installer**, not a promotion of the main
beta or a Microsoft Store release. It packages the byte-identical, previously
tested Desktop Preview 2 executable. No compression algorithm, archive format,
encryption, recovery or application UI code is changed by this packaging stage.

## What the installer adds

Run `Rat-Trap-Desktop-Preview-2-Windows-x64-setup.exe` to install for the current
Windows account. Start-menu shortcuts are included. Desktop and `.gmw` / `.rtsf`
Open-with registration are optional and initially unselected. Opening a file
through these entries only selects a screen; it does not restore or decrypt it.
Setup does not change default applications or associate `.rtrk` recovery keys.

The preview installs under
`%LOCALAPPDATA%\Programs\Two Hands Network Ltd\Rat-Trap Desktop Preview 2`.
Its registration is `TwoHandsNetwork.RatTrap.DesktopPreview2`, separate from
`TwoHandsNetwork.RatTrap.Beta`. This stage does not migrate or replace an old
beta installation. It uses setup version `5.7.0.2` and preserves application
version `5.7.0-desktop-preview.2`.

Re-running this setup repairs its own files and remembers the optional choices.
Close the preview before reinstalling or removing it; Setup refuses locked
files and does not terminate an active compression operation. There is no
automatic updater and no future-version migration is claimed here.

Use Windows Apps settings to uninstall this preview. Removal uses an explicit
application-file list, not recursive deletion of the installation directory.
User-added files, saved archives, recovery keys and local diagnostics are not
installer payload and are retained. Keep important data outside app folders
and maintain independent backups regardless.

## Packaging and verification

The new builder checks all 25 input payload files against the frozen portable
release record. The installer adds its own `README-FIRST.txt`, retaining the
original instructions as `README-PORTABLE.txt`, and includes the NSIS licence.
The installed payload therefore has 27 files, plus its generated uninstaller.
The installed checksum list is regenerated for that payload.

The portable EXE, ZIP, original guides and previous release records remain
unchanged. The local pinned NSIS 3.12 compiler is used without installing it
globally. Setup requests current-user execution. Neither executable is signed;
matching hashes detect changes, but are not independent publisher verification.

```powershell
.\scripts\build_windows_desktop_preview2_installer.ps1 -ValidateOnly
.\scripts\build_windows_desktop_preview2_installer.ps1
.\scripts\test_desktop_preview2_installer_preflight.ps1
.\scripts\test_windows_desktop_preview2_installer.ps1
```

The builder refuses an existing destination setup file. The test harness uses
a newly generated, separate QA identity for temporary installations and tests
only generated fixture data. It must not be pointed at a user's normal app
identity. Retained test evidence lives under `build`, separately from downloads.

Completed on this host: **167/167 isolated installer lifecycle checks** and
**44/44 build-input checks**, with no lifecycle cleanup errors. Both self-tests
passed from the installed QA copy. All **291 application tests** also passed
again in 158.400 seconds. The QA installer differs from the handoff installer
only in its explicit QA identity and resulting metadata; the application
payload and installer sources are the same. The handoff setup was inspected
without executing it: expected version/publisher, x86 NSIS launcher wrapping
the x64 app, `asInvoker`, `uiAccess=false`, and `NotSigned`.

The [installer release record](../release-manifests/desktop-preview-2-installer.json)
records hashes, scope and limits. The
[sanitized QA record](../packaging/direct/qa-results-desktop-preview-2-installer.json)
keeps the automated check results without local profile paths. No existing
default ProgIDs were present on this host; two generated other-app Open-with
sentinels were preserved. Populated-default testing remains outstanding.

## Remaining release checks

Follow the [hands-on acceptance checklist](DESKTOP-PREVIEW-2-INSTALLER-CHECKLIST.md)
on a clean Windows 11 x64 machine. Actual Explorer behavior, interactive wizard
screens, populated existing defaults, display-scaling appearance and the
intended downloaded-file security experience must be recorded there.

The development host is Windows 10 Home 22H2, build 19045.6456. A bounded check
found no usable local clean Windows 11 runner. Native desktop capture also
failed with `SetIsBorderRequired failed: No such interface supported
(0x80004002)`. Those checks remain unverified, not passed by automated tests.

This stage does not push to GitHub, make the repository public, publish a
download, purchase signing or change the pending Store registration. The
commercial product page and full technical evidence remain separate lanes;
packaging improvements are not claims of improved compression ratios.
