# Restore a file directly from Library

Windows preview **5.7.0.10**, support label
`5.7.0-desktop-preview.2-library.4`. The existing Desktop Preview 2 app identity
and schema-v1 Library catalogue remain unchanged.

## User workflow

1. Open **Library & timeline > Search entire Library**. Leave **Include filenames** on.
2. Search for the filename, then select a **File** result from an unencrypted
   Vault or a versioned backup. Choose **Restore this file…**.
3. Check the filename, source, project, size and full backup snapshot ID.
4. Choose an existing parent directory. Rat-Trap proposes a new restore-folder
   name; you can edit it. The restore folder must not already exist.
5. Choose **Restore file…** and confirm the exact file/version and destination.
6. After success, use **Show restored file** to reveal its containing folder.
   Rat-Trap does not execute or automatically open the restored file.

The selected file keeps its relative path. For example, restoring
`design/notes.txt` to a new `Recovered notes` folder creates
`Recovered notes/design/notes.txt`, not the rest of the archive.

Ordinary archives and protected archives/sealed files still use **Open result**
and their existing workspace tools. This stage does not unlock protected
filename search, restore entire folders or multiple search results, or merge
into an existing destination. Existing whole-backup restore remains available.

## Safety and recovery

The worker rechecks the registered storage identity and captured project.
Backup results are pinned to both the snapshot ID and manifest SHA-256; a
missing/changed version fails instead of falling back to the latest version.
Only the selected backup file's chunks are read. Vault extraction also selects
the exact file rather than extracting the archive wholesale.

The engines verify their data, then Library independently checks the staged
file count, size and SHA-256 against the selected source metadata. It rechecks
the source/version and destination before publishing. The temporary working
folder is on the destination's filesystem. Windows rename provides no-replace
publication: even a destination appearing at the last moment is preserved.
No merge, overwrite or deletion of the original is attempted.

Destinations inside the Library catalogue or any registered backup repository
are refused. Only ordinary local paths are supported; links, reparse points,
network/device paths, traversal and alternate-stream member paths are refused.
These checks are not a defence against an administrator or another hostile
process with the same account privileges racing filesystem changes.

A restored file is plaintext. Working folders are not encrypted or securely
erased; an interruption can leave staging data. Keep originals and independent
backups. Close writers before restoring: this is not an operating-system
snapshot of a live source. Vault reads refuse active SQLite sidecars and use
immutable read-only access with before/after identity checks. Backup restore
uses the existing repository lock/recovery mechanism, which may recover pending
work or rebuild its catalogue cache. It is not advertised as a read-only source
operation.

## Timeline receipts

After publication, a **File restored** note records the filename, destination,
verified SHA-256 and exact backup snapshot ID (or Vault source description).
It is a plaintext local receipt, not proof that the output still exists or is
unchanged later. Existing catalogue privacy guidance still applies; never
record passwords or recovery keys. Receipts are ordinary schema-v1 notes and
do not reuse the unique snapshot-event key, so repeated restores are supported.
Opening a receipt shows its text, not the latest backup version.

If receipt creation fails, the app reports that the verified output is safe,
shows its path and keeps **Show restored file** available. Do not repeat the
restore merely to repair the timeline. An application/process interruption
between publication and receipt creation can leave a valid output without a
receipt; inspect that new destination before trying again.

## Build and qualification

Use the pinned local toolchain described in `LIBRARY-BUILD.md`, with the new
recipes (fresh output directories are required):

```powershell
.\scripts\build_windows_library_restore.ps1 -DestinationDirectory .\dist\library-restore-local-1
.\scripts\build_windows_library_restore_installer.ps1 -PayloadDirectory .\dist\library-restore-local-1 -DestinationDirectory .\dist\library-restore-installer-local-1
.\scripts\test_windows_library_restore_installer.ps1 -PayloadDirectory .\dist\library-restore-local-1
```

The lifecycle test uses the frozen 5.7.0.9 search payload to test an actual
upgrade under a fresh isolated QA identity. It never installs/removes the
normal app. Seven packaged self-test modes include the new
`--library-restore-self-test`, which restores a generated Vault file and an
exact older backup, checks their bytes/receipts, and refuses repeat publication
into the existing output folder. See `LIBRARY-RESTORE-VALIDATION.md` for measured
results and limitations. This remains an unsigned local preview, not a Store
release, independent security audit or clean-machine qualification.
