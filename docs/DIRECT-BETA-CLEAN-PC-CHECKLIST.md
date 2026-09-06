# Rat-Trap direct beta: clean-PC test record

Use a clean Windows 11 x64 VM or separate test PC under a standard user
account, and a Windows 10 compatibility test machine if available. Record OS
version/build, installation route, artifact SHA-256 and each result. This
checklist is unexecuted until those results are entered.

## Download and installation

1. Download the candidate through its intended HTTPS route. Record any Windows
   security prompt or block. Do not switch off protection to obtain a pass.
2. Verify the candidate hash against the release record.
3. Install with both optional components unselected. Confirm no administrator
   prompt, correct company/app names and Start menu/Apps settings entries.
4. Launch with no Python installation and with the network disconnected.
5. Confirm the About tab shows 5.7.0 and the expected support information.
6. Repeat using the ZIP: Extract All, then run the app from the extracted folder.

## Files and recovery

1. Use copies of representative text, photos, already-compressed files and a
   nested folder. Include spaces and Unicode in names.
2. Compress and restore into a new directory. Compare every restored file hash.
3. Protect an archive with a password and a separately stored recovery key.
4. Verify password and recovery-key restoration. Confirm a wrong password
   fails without creating usable plaintext output.
5. Create and restore a Sealed File. Test the Vault search and table views on
   non-confidential sample data.
6. Attempt normal window close during work. Confirm the operation is protected
   and close works after completion.

## Installer lifecycle

1. Re-run Setup with optional desktop and Open-with registration enabled.
2. Confirm `.gmw` and `.rtsf` appear under Open with and both paths containing
   spaces and Unicode open the intended screen. Neither action should decrypt
   or extract automatically. Confirm `.rtrk` has no Rat-Trap association.
3. Confirm previously selected default apps remain unchanged.
4. Re-run Setup with optional components disabled; verify their removal.
5. Remove an installed help document and re-run Setup; confirm repair.
6. With Rat-Trap running, attempt reinstall/uninstall. Confirm it asks you to
   close the app and does not terminate an active operation.
7. Save generated test archives/recovery keys outside the application directory
   and an extra test file inside it. Uninstall through Windows Apps settings.
8. Confirm shortcuts and app registration are removed while those test files
   and local diagnostics remain. Confirm other applications' associations
   still work.
9. On a clean installation, run the actual uninstaller interactively to verify
   its normal temporary-process handoff and completion screen.

## Report

For every failure, record expected/actual behaviour, app version, OS build,
error reference and the smallest reproduction using non-confidential files.
Never include real passwords, recovery keys or private archives. A signing or
security-policy block is a recorded result, not a reason to disable Windows
protection. Keep future-version upgrade tests separate from same-version repair.
