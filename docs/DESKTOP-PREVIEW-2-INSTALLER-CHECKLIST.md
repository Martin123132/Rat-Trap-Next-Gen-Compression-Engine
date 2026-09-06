# Desktop Preview 2: hands-on acceptance checks

This record is **unexecuted** until a tester enters results. It complements
automated same-host installer checks; those do not establish a clean-PC or
visual pass. Use non-confidential copies and keep your originals.

## Candidate and machine

Record the setup filename and SHA-256 from the installer release record, the
Windows edition/build, account type, display scaling and test date. Use a clean
Windows 11 x64 machine under a standard user account for the release gate.
Record Windows 10 compatibility separately. This preview is unsigned; record
security warnings or blocks without disabling protection or bypassing policy.

Expected identity: **Rat-Trap Desktop Preview 2**, publisher **TWO HANDS NETWORK
LTD**, setup version **5.7.0.2**, application preview version
**5.7.0-desktop-preview.2**. The main 5.7.0 beta must remain separate.

## Install and launch

1. Run Setup with the optional Desktop and Open-with choices unselected.
2. Check that there is no administrator prompt. Confirm the preview's distinct
   name in the Start menu and Windows Apps settings.
3. Open the preview from its Start menu shortcut. Confirm the Home screen,
   sidebar, preview identity and usable controls at your display scaling.
4. On the clean machine, confirm local-file operations work without Python and
   without a network connection. Do not change security settings to test this.
5. If the old beta is installed, confirm its shortcut and installation remain
   present and unchanged. This is a side-by-side test, not an upgrade test.

## Complete one ordinary archive round trip

1. Create a small test folder containing copies of text, a picture and a nested
   folder. Include spaces and a Unicode character in a filename.
2. Select it for an archive. Save outside the source under a new name.
3. Try pasting a quoted Copy-as-path value into the path field. Check that it
   resolves to the intended file or folder and does not become part of its name.
4. During work, check that the reported stage and elapsed time remain visible.
   No percentage or finish-time prediction is promised. Attempt normal close;
   the active-operation guard must prevent unsafe closure.
5. After success, dismiss the original result dialog. Check that elapsed time
   has stopped and both completion actions remain reachable.
6. Click **Open archive**. It must select the archive inside Rat-Trap without
   extracting, decrypting or launching an associated application.
7. Click **Show in folder**. Explorer must show the output's containing folder.
8. Restore to a new empty folder and compare every restored file's SHA-256 with
   its source. Do not use successful compression alone as a restoration pass.
9. Move only the disposable output to a different folder, then try its old
   completion action. A missing-output warning must replace an attempted open.

## Protection and safe output actions

1. Protect a disposable file, saving its recovery key separately. Confirm that
   the completion dialog still explains where recovery material was saved.
2. Confirm **Open Sealed File** only selects the protected file in Rat-Trap.
   It must not authenticate, decrypt or restore automatically.
3. Restore using the password, then separately using the recovery key; compare
   the restored bytes. A wrong password must not publish plaintext output.
4. Use an inert text fixture with an `.exe` suffix for one round trip. Never
   execute it. Its restored-file completion action must only show its folder,
   not launch the file.
5. Repeat the main result-panel checks at 100%, 150% and 200% display scaling
   where the test machine supports them. Record any clipped or unreachable
   controls and the actual window size. Internal geometry tests do not replace
   this check.

## Explorer and removal

1. Re-run Setup and enable both optional components. Check the distinct
   preview desktop shortcut and `.gmw` / `.rtsf` **Open with** entries.
2. Open disposable files whose paths contain spaces and Unicode through these
   entries. Check the correct screen and selected path. No automatic restore
   should occur. Recovery-key `.rtrk` files must not acquire an association.
3. Confirm existing default applications remain selected. Test a machine with
   pre-existing defaults; absence of a default is not evidence of preservation
   of a populated default. Do not edit UserChoice registry values manually.
4. Re-run Setup with both choices disabled and verify only the preview's
   optional entries disappear. A further re-run should preserve that choice.
5. Close the preview. Remove an installed disposable help-document copy and
   re-run Setup to verify repair. Do not delete the only copy of user data.
6. While the preview is running, try reinstall and uninstall. They must refuse
   safely without terminating it; retry after normal closure.
7. Save disposable archives and recovery fixtures outside the application
   directory, plus an extra test note inside it. Uninstall interactively through
   Windows Apps settings, including the final completion screen.
8. Confirm installed application files and preview registrations are removed,
   but the extra note, saved outputs, recovery keys, local diagnostics and old
   beta are retained. Confirm other applications' Open-with entries remain.

## Record each result

Use `PASS`, `FAIL` or `NOT TESTED` for each numbered check, with expected versus
actual behavior, OS/build, scaling and a minimal reproduction for failures.
Record whether the installer was obtained through its intended download route;
local builds do not test downloaded-file security prompts.

Never include real passwords, recovery keys, confidential archives or personal
paths in reports. Do not mark a blocked security prompt as a successful test.
Signing, public distribution and replacement of the main beta are separate
release decisions.
