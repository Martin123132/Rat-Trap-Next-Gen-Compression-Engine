# Guided tutorials — first walkthrough

This private update adds **Show me how…** to the Desktop Preview 2 header.
Choose **Find a file inside a Vault**, then **Start guided practice**.
The first walkthrough uses the existing Vault search and preview operations,
not simulated search results. Other catalogue entries describe available app
features but are explicitly marked **walkthrough coming later**.

## What to try

1. Open **Search Vault** using the highlighted sidebar button.
2. Click **Load practice Vault**. Rat-Trap creates three fictional documents
   and a tiny unencrypted Vault in a fresh temporary folder.
3. Type **aurora**, then choose **Next**.
4. Click **Search** and wait for the real result.
5. Select **projects/aurora-notes.txt**, then choose **Next**.
6. Click **Preview selected** to read the sample checklist inside Rat-Trap.
7. Choose **Finish tutorial** to return to your previous screen.

Each step explains where you are, what to do, why, and what to expect. A green
outline marks the current control; unrelated actions are disabled. Scrolling
remains available. On smaller displays, the explanation scrolls independently
of the Back, Next and Exit buttons. Escape also exits the walkthrough.

Back revisits an instruction; it does not undo an operation. If a practice
operation is still running, Back or Exit waits for it to finish before changing
the screen or removing its inputs. The tutorial never opens a personal file
picker, restores a folder, exports a result, or launches an external viewer.

## Data and state

The tutorial temporarily uses the real Search Vault workspace. Finishing or
exiting restores its previous selections, search results, preview, navigation
and completion-card state. No password or recovery key is needed.

Cleanup removes only the known practice files if their contents are unchanged,
followed by empty owned directories. Unexpected or modified files are left in
place. Cleanup is not recursive. A force-quit or machine crash can leave the
fictional temporary sample behind; this is not a secure-erasure feature.

For personal files, choose the **Queryable Vault** profile when creating an
archive, then use **Search Vault**. Ordinary archives are not automatically
searchable Vaults. Compression alone is not encryption. This update changes
neither the compression engines nor the archive/encryption formats.

## One version to test

Use `outputs/00 - START HERE/Install Rat-Trap.exe` in the parent workspace.
Close Rat-Trap after any operation finishes before running Setup. The update
retains the existing Desktop Preview 2 installation identity, executable name,
installation folder and Start-menu entry. Historical installers remain outside
the current handoff folder; there is no new public portable ZIP to choose from.

Application support label: `5.7.0-desktop-preview.2-tutorial.1`.
Application/installer numeric version: `5.7.0.3`.
Publisher: **TWO HANDS NETWORK LTD**.

This is still an unsigned private preview, not a Microsoft Store release.
Hands-on visual acceptance and clean-PC/Windows 11 testing remain separate
from local automated checks. Do not disable Windows security protection if
it blocks the installer; report the message instead.

## Development and verification

The new entry point is `windows_guided_preview.py`; the implementation is in
`rat_trap/guided_app.py`, with task definitions and sample ownership in
`rat_trap/tutorials.py`. It extends the previous desktop interface without
editing its frozen engine or interface modules for this update.

Run the source checks from the repository:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe windows_guided_preview.py --tutorial-self-test
```

The new targeted tests are `tests/test_tutorials.py` and
`tests/test_guided_app.py`. They cover the real practice journey, input and
navigation gating, sample replacement checks, state restoration, asynchronous
completion/failure, busy Back/Exit, stale callbacks, monitor recovery and
all-step layout geometry at multiple Tk scaling values. Geometry and direct
widget-callback tests are not a native mouse/keyboard or visual acceptance pass.

Private build and isolated upgrade checks use:

```powershell
.\scripts\build_windows_guided_preview.ps1
.\scripts\build_windows_guided_installer.ps1
.\scripts\test_windows_guided_installer.ps1
```

Builders use the recorded local dependency/toolchain inputs and refuse to
overwrite historical release destinations. The installer harness uses a new
QA-labelled identity for old-to-new upgrade, repair and removal checks; it must
not install into or remove the ordinary user installation. Build receipts and
release evidence distinguish those checks from hands-on acceptance.

Verified on 6 September 2026: all **330 source tests** passed, including
**39 tutorial tests**. All three packaged self-test entry points passed both
before installation and after the isolated QA upgrade. The same-host installer
lifecycle passed **223 checks**, including old-to-new upgrade, option/data
preservation, repair, locked-file refusal and removal, with no cleanup errors.
See [the sanitized QA record](../packaging/direct/qa-results-guided-preview.json).
