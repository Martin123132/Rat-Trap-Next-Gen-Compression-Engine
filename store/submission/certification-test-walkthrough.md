# Rat-Trap certification test walkthrough

This detailed walkthrough supports the concise text pasted into Partner
Center's Notes for certification field.

Use ordinary non-confidential certification files or the synthetic files under
`store/demo-data`.

Public test password:

`Rat-Trap-Certification-2026!`

This is a test password only and is not a product secret.

## Primary test steps

1. Launch Rat-Trap. Confirm that seven functional tabs appear and that the app
   remains usable without a network connection.
2. Create archive:
   - choose a small test folder;
   - choose an output path outside that folder;
   - select Balanced; and
   - create the `.gmw` archive.
3. Extract archive:
   - select the new `.gmw`;
   - restore to a new empty folder; and
   - compare the restored files with the source.
4. Backups and history:
   - initialise a new empty repository outside the source folder;
   - create a labelled snapshot of the test folder;
   - search for a known test filename;
   - run Quick verify; and
   - restore the selected snapshot to a new folder.
5. Inspect and export:
   - load the `.gmw`;
   - inspect its file count and archive metadata; and
   - optionally export it to ZIP.
6. Sealed File:
   - choose a small test file;
   - protect it with the public test password;
   - save the `.rtrk` recovery key separately;
   - verify the `.rtsf`;
   - restore a plaintext copy using the password; and
   - repeat verification using the recovery key if desired.
7. Queryable Vault:
   - create a Vault from a folder containing a text file and a CSV;
   - search for a known word;
   - browse the imported CSV table; and
   - run a read-only `SELECT` query.
8. File activation:
   - use Open with Rat-Trap on a `.gmw` and confirm that Inspect/export is
     preselected;
   - use Open with Rat-Trap on a `.rtsf` and confirm that Open/restore is
     preselected; and
   - confirm that neither action starts restoration or decryption by itself.

## Security and storage boundaries

Passwords and recovery-key contents are processed locally and are not sent to
Two Hands Network. Some protection, export, and restoration operations may
require temporary plaintext on local storage; Rat-Trap displays a warning
before the relevant operation.

A live repository is not encrypted merely because Rat-Trap created it.
Uninstalling Rat-Trap does not delete archives, repositories, recovery keys,
reports, exports, or restored files created by the user. No diagnostic
information is uploaded automatically.

