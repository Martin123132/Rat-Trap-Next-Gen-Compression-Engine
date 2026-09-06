# Rat-Trap Desktop Preview 1

6 September 2026 · TWO HANDS NETWORK LTD

This is a separate, runnable Windows interface preview built around the
existing 5.7.0 engine and operation handlers. It does not replace the tested
5.7.0 direct-beta installer or ZIP. No archive format, compression algorithm,
encryption scheme, licence, or repository visibility was changed in this stage.

## What changed

- A Home screen with four starting points: compress a folder, protect a file,
  restore files, and search a Vault.
- Dark sidebar navigation replaces the crowded outer tab row. All eight
  existing workspaces remain available, alongside Home. Nested modes within
  Secure Files, Data Tables and backup results remain intact.
- Teal action buttons, clearer headings, consistent path fields and spacing,
  responsive Home cards, and scroll access for smaller/high-DPI displays.
- An Open Rat-Trap file picker routes `.gmw`, `.rtsf` and `.db` selections to
  the appropriate workspace. Selection does not start work, authenticate,
  decrypt, search, or extract. An arbitrary `.db` is not assumed to be a Vault;
  the existing search operation validates its format.
- A changed source folder updates an automatically suggested archive path.
  A custom destination remains unchanged. Cancelling a picker preserves data.
- Ctrl+O opens the picker; Ctrl+1 returns Home. Navigation and new pickers are
  blocked during work. The existing close-during-work protection is retained.
- About and copied support details identify the preview separately.

The Home screen explicitly distinguishes compression from encryption. No
persistent recent-files list was added. This does not prevent Windows file
dialogs or storage services from keeping their own history.

## Run it

Extract `Rat-Trap-Desktop-Preview-1-Windows-x64-portable.zip` completely into a
new folder, then run `Rat-Trap-Desktop-Preview.exe`. Keep the included Legal
directory and documents. No Python installation is required by the package.
Test copies of files and restore into a new folder; do not use preview output
as your only backup.

The preview is unsigned and has no installer, update service or registered
file associations. It does not modify the existing beta installation.
Windows may warn about or block downloaded executables; do not disable
protection to obtain a test pass.

From source, use the existing project environment:

```powershell
.\.venv\Scripts\python.exe .\windows_desktop_preview.py
```

## Build and verify

```powershell
.\scripts\build_windows_desktop_preview.ps1 -ValidateOnly
.\scripts\build_windows_desktop_preview.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

The builder checks the recorded Python and exact dependency pins without
installing anything. It uses a unique build directory, refuses existing
destinations, verifies ZIP hashes, and gives the preview its own executable
name and prerelease version resource. The frozen EXE and MSIX hashes are
checked before and after the build. The normal 5.7.0 build entrypoint and
packaging scripts remain unchanged.

The packaged `--ui-self-test` path creates a hidden preview window and checks
workspace construction, navigation, launch preselection and busy handling.
The separate `--self-test` path runs the existing packaged engine tests.
Neither test is a visual review or a clean-PC installation test.

## Verification boundary and next gate

Completed: **248 source tests passed**, including 27 desktop-preview tests.
The final run took 114.891 seconds with no failures. Packaged `--ui-self-test`
and `--self-test` both exited successfully. All 14 records in the prior
direct-beta manifest remained unchanged, and all 22 build-input hashes still
matched the packaged source. Download hashes and evidence are recorded in the
[preview release record](../release-manifests/desktop-preview-1.json).

Source tests cover safe file selection, destination preservation, worker
controls, a real generated-fixture compression/restore round trip, and
internal Tk layout measurements. Sidebar reachability is checked at 960×640
and Tk scaling values corresponding approximately to 100%, 150% and 200%.
Home's narrow layout was corrected after an independent review found an
unused equal-width column. These measurements do not replace visual checks
with real Windows DPI settings, keyboard users or assistive technology.

The current host remains Windows 10 Home x64 build 19045. No ready Windows 11
VM or Windows Sandbox was found. Docker/WSL2 is not a clean Windows desktop.
The [clean-PC checklist](DIRECT-BETA-CLEAN-PC-CHECKLIST.md) remains pending.

Windows computer-use capture failed twice with `SetIsBorderRequired failed:
No such interface supported (0x80004002)`. No alternate native UI automation
was used. Visual inspection, real downloaded-file security prompts,
interactive installer screens, and clean Windows 11 testing remain unverified.

Next: try the preview's main tasks with sample files and inspect its layout;
complete the clean-PC/download gate before promoting this UI into a new beta
installer. Calendar/terminal integration is later work. Review the original
repository's accumulated changes and intended public files separately before
any push or visibility change. Nothing was uploaded or published in this stage.
