# Rat-Trap Desktop Preview 2

TWO HANDS NETWORK LTD · 6 September 2026

Preview 2 builds on the Home/sidebar design in Preview 1 with three practical
improvements: easier path selection, clearer operation status and useful
actions after work finishes. It is a separate portable build; the earlier
preview and 5.7.0 beta remain intact. No GitHub push, publication, installer
registration, signing purchase or Microsoft Store change is part of this stage.

## Selection

Ordinary compression, archive-restoration and file-protection pickers reuse a
useful existing folder during the current session. They prefer the relevant
field's location, then the last ordinary picker location. Recovery-key dialogs
retain their existing separate-location rules and do not use this memory.

Path fields accept File Explorer's quoted Copy-as-path text: one surrounding
double-quote pair is removed when focus leaves the field, unless an operation
is active, and again before starting the four primary operations. Variables,
wildcards and commands are never expanded or executed.
Source changes update automatic destinations but preserve custom ones.
Cancelling a picker preserves the existing selection.

The result's Open action is also a shortcut to reuse that output without
browsing for it again. No persistent recent-files database was added; Windows
file dialogs can still maintain their own history.

## Progress

The operation area shows the engine's reported status and elapsed time, using
a monotonic clock. Long status text is shortened for display; the underlying
status is unchanged. There is no invented percentage, throughput or estimated
time remaining. An indeterminate bar and advancing clock are not proof that a
worker is healthy.

Elapsed time freezes when worker completion is received, before the user
reads any completion dialog. Each operation has its own presentation token,
so a chained backup refresh or retry cannot be overwritten by an older timer.
Failures stop the activity display without creating a success result. A lost
monitor with a live worker says that work may still be running; the original
close-during-work guard remains in force.

## Completion actions

Successful archive creation, archive restoration, single-file sealing and
single-file restoration leave a compact result panel. The output destination
is captured when work starts or taken from the typed result, not reread from
editable fields at completion. Only the path, result kind and a short summary
are retained; credentials, key contents and whole operation results are not.

- **Open archive / Open Sealed File** preselects the supported output inside
  Rat-Trap. A Vault routes to search. It never automatically authenticates,
  decrypts, extracts, queries, or invokes the file's associated application.
- **Show in folder** opens only the output directory or containing directory
  after an explicit click. A restored executable is never launched by it.
- Outputs are rechecked on click. A missing/moved file produces a warning.
- Starting another operation clears the previous result and disables actions.

Existing completion dialogs are retained because they include recovery-key
locations, verification information and security warnings. Unsupported
operations, exception-valued results and partial bulk work do not receive a
new success card; their existing workspace reports remain authoritative.

The footer reserves space ahead of the scrollable workspace. On completion,
redundant progress rows collapse so the path and result actions remain visible
on compact windows.

## Running and building

Extract the complete `Rat-Trap-Desktop-Preview-2-Windows-x64-portable.zip` into
a new folder, then run `Rat-Trap-Desktop-Preview-2.exe`. Test copies of files
and restore into a new directory. Read the included README and legal notices.

```powershell
.\.venv\Scripts\python.exe .\windows_desktop_preview2.py
.\scripts\build_windows_desktop_preview2.ps1 -ValidateOnly
.\scripts\build_windows_desktop_preview2.ps1
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

The builder uses the existing exact dependency pins, refuses overwrites,
records source/payload hashes and verifies the 25-file ZIP. It uses a separate
5.7.0-desktop-preview.2 version resource, executable name and build directory.
It audits Preview 1's own entrypoint, interface module, packaging files and
payloads before and after building. Compression algorithms, archive formats,
encryption and recovery are unchanged. One shared source-validation guard was
corrected as described below; historical Preview 1 binaries are not rebuilt.

## Windows executable-name compatibility fix

Tests exposed a preexisting single-file protection failure on this Windows
Python runtime: `lstat()` synthesized execute permission bits for `.exe`,
`.com`, `.bat` and `.cmd` names, but `fstat()` on the same open file did not.
The snapshot comparison interpreted that difference as source replacement.
Normal folder compression was unaffected; single-file compression and bulk
sealing inherited the false rejection.

Snapshot comparison now ignores only those synthetic execute bits on Windows.
File type, read/write bits, device/inode, size, modification time, link count
and both content-digest passes remain checked. POSIX mode comparison stays
exact. Original archive metadata serialization is unchanged. Tests use inert
generated data with executable-looking filenames; they never run these files.

## Remaining release gate

Completed on this host: **291 source tests passed** in 105.015 seconds,
including 33 Preview 2 workflow tests and 10 Windows mode-compatibility tests.
The packaged UI and engine self-tests both exited with code 0. The builder
verified all 25 ZIP entries, 23 current build inputs and 31 preserved Preview 1
interface/packaging/payload files. Download hashes and evidence are recorded in
the [Preview 2 release record](../release-manifests/desktop-preview-2.json).

This is unsigned, same-host Windows 10 preview work. The prior screen-capture
failure and lack of a clean Windows 11 environment remain unresolved. Internal
Tk geometry tests and mocked folder-opening tests are not a visual sign-off,
actual Explorer integration test or clean-PC installation pass. The
[clean-PC checklist](DIRECT-BETA-CLEAN-PC-CHECKLIST.md) remains required before
promotion into a broader release.
