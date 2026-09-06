RAT-TRAP 5.7.0 FOR WINDOWS
==========================

Quick start
-----------
1. Use a trusted signed MSIX installer when supplied. For the portable build,
   extract the ZIP file to a folder.
2. Start Rat-Trap from Windows, or double-click Rat-Trap.exe in the portable
   build. No Python installation is required.
3. Use Secure files to protect, verify, or restore individual files; use
   Backups & history for recurring snapshots.

Windows integration (5.5 Beta)
------------------------------
- The MSIX package makes Rat-Trap available in Windows Open with for .rtsf
  Sealed Files and .gmw archives. Windows keeps control of the user's default
  application choice.
- Opening either type from Explorer only selects it in the correct Rat-Trap
  screen. It never decrypts, verifies, extracts, or modifies the selected file
  automatically.
- .rtrk recovery keys are deliberately not registered. Choose a matching
  recovery key explicitly inside Rat-Trap when authenticating an operation.
- The installer declares Windows package-integrity enforcement. A public MSIX
  must still be signed by a trusted publisher whose certificate subject
  exactly matches the package identity.
- The unsigned development MSIX is a validation artifact, not an installable
  public release. Rat-Trap does not ask users to bypass Windows trust warnings.

Company publisher and reliability (5.7 Beta)
----------------------------
- Rat-Trap is a product owned and published by TWO HANDS NETWORK LTD under
  its written agreements with the project's contributors.
- The compressor implementation was designed and built by Glyn Evans, drawing
  on Motion-TimeSpace work by Martin Ollett.
- Microsoft Store MSIX is the selected primary distribution route.
- Partner Center must assign the exact package Name, Publisher and publisher
  display name after company verification and Rat-Trap name reservation.
  Those values are copied verbatim; they are never guessed from the company
  name.
- Microsoft signs a Store MSIX after certification. Direct downloads remain
  a separate signing lane and require their own trusted signature.

Sealed Files (5.4 Beta)
-----------------------
1. Open Secure files and choose Protect one file.
2. Select the existing file, a new opaque .rtsf path, and a new .rtrk
   recovery-key path in a separate location.
3. Enter and confirm a password or passphrase of at least 15 characters.
4. Rat-Trap compresses, encrypts, authenticates, and verifies a copy. It never
   deletes, replaces, recycles, or securely erases the original.
5. To check or restore it, choose Verify / restore, enter the password or
   select the matching recovery key, and restore into a new folder.

The original basename, extension, contents, stored modification time, and
content checksum remain inside authenticated ciphertext. The recommended
outside name is RT-<random>.rtsf. A custom outside name remains visible.
Ordinary applications see ciphertext without a valid credential; the .rtsf
association is convenience, not access control, and an independent conforming
reader could decrypt the documented format with a valid credential.

Protect a folder creates one independent .rtsf and .rtrk per regular file.
The sealed and recovery destination folders must both be new, separate, and
outside the plaintext source tree. Bulk sealing is not an all-or-nothing
transaction. The 5.4 Beta has no durable batch journal and cannot resume an
interrupted batch into the same folders. Already verified outputs remain
valid; retry with two new destination folders. Rat-Trap offers a complete
plaintext JSON batch report that maps original relative paths to the opaque
sealed and recovery filenames. Store that report separately if filenames are
sensitive.

Encrypted portable archives
---------------------------
1. On Create, turn on authenticated encryption.
2. Enter and confirm a password or passphrase of at least 15 characters.
3. Choose a new .rtrk recovery-key file. Rat-Trap will not overwrite one.
4. Keep the recovery file somewhere separate from the archive and computer it
   protects. Either the password or recovery file can unlock the archive.
5. Losing both credentials makes the archive unrecoverable.

Encryption covers the complete inner archive, including filenames, Vault
indexes and structured tables. Rat-Trap detects tampering, truncation and
trailing data before it publishes decrypted output.

Backups & history
-----------------
1. Choose a new empty folder for the repository and select Initialize.
2. Choose the folder you want to protect, add an optional label, and select
   Back up now.
3. Later backups reuse matching content already in the repository.
4. Select any snapshot to restore it into a new verified folder, pin it
   against retention, or export it as a portable .gmw archive.
5. Search finds stored filenames, paths and snapshot labels across history.
6. Quick verify checks repository structure and references. Full verify reads
   every object and reconstructs every file checksum.
7. Cleanup always previews first. Version 5.4 moves eligible data to
   recoverable repository trash; it does not yet free that disk space.

Available formats
-----------------
- Balanced (recommended archive): streaming solid Zstandard level 6 plus
  exact whole-file deduplication. Choose this for compact backups and sharing.
- Fast: streaming solid Zstandard level 3 without the duplicate hash pass.
- Smallest: hybrid Zstandard level 19. It can be much slower for a small gain.
- Queryable Vault: a versioned SQLite database with content-addressed,
  Zstandard-compressed objects. Every filename is searchable. Supported text
  contents up to 16 MiB are indexed with SQLite FTS5. CSV, TSV, JSON, JSONL,
  NDJSON, and UCI .data/.test files up to 64 MiB become relational tables.

Using a Vault
-------------
1. On Create, choose "Queryable Vault - searchable files and data tables".
2. Open Search Vault and select the new .vault.gmw file.
3. Search by words or filename. An optional extension filter is available.
4. Double-click or select one result to preview it.
5. Select one or more results and choose Export selected files.

Using Data Tables
-----------------
1. Open Data Tables and choose a Vault made by Rat-Trap 5.1.
2. Pick an imported source such as a CSV or JSON file.
3. Use Find, In, and Sort, then choose Show rows. No SQL is required.
4. For advanced queries, open SQL query and run a SELECT or WITH statement.
5. Export the current results as CSV, TSV, or JSON.

Types are inferred as INTEGER, REAL, or TEXT. Original files are still stored
unchanged and are checksum-verified when restored. UCI .names sidecars are
used when available so datasets such as adult.data receive meaningful columns.

Vaults are intentionally larger than Balanced archives because SQLite and the
search index consume space. Use Balanced when queryability is not needed.

Notes
-----
- Save every new .gmw file outside the folder being ingested.
- Keep a backup repository outside the folder it protects.
- Version 5.7.0 reads 5.4 Sealed Files, encrypted 5.3 archives, 5.0
  searchable Vaults, 4.4 hybrid archives, earlier solid archives, and
  existing v4.2 SQLite block archives.
- Version 5.7.0 validates the encrypted outer family, inner archive family and
  required database schema before reading. Unknown, incomplete, or ambiguous
  SQLite files are rejected.
- Repository schema 1 rejects symbolic links, junctions, alternate data
  streams, sparse files, hard links, NTFS-compressed items and EFS-encrypted
  items instead of silently changing their meaning or copying decrypted
  plaintext. ACL preservation and VSS handling for open files are not
  implemented yet.
- Backups read a live folder file by file, then atomically publish the complete
  capture. Without VSS they are not a filesystem-wide point-in-time view while
  applications are actively changing multiple files.
- Portable .gmw archives and Vaults can be encrypted. The live backup
  repository remains checksum-verified but unencrypted.
- Encrypted creation, Sealed File creation/verification/restoration,
  inspection and Vault queries can use an isolated plaintext temporary inner
  archive. It is removed best-effort, but Windows, SSDs, backup tools or
  malware may retain traces. Secure deletion is not claimed.
- Anyone holding the .rtrk recovery file can read its matching archive. Store
  it separately and do not email or upload it beside the archive.
- Replacing an encrypted output with a plaintext archive requires a separate
  warning and explicit confirmation; the shared API and command line also
  refuse that downgrade by default.
- Inspect / export can convert a normal archive or Vault to a conventional ZIP.
- The development executable and unsigned MSIX are not a trusted public
  installer. A production MSIX must be signed and timestamped with the
  publisher identity recorded in its release manifest.
- See SEALED-FILE-FORMAT.md, SEALED-FILE-GATE-5.4.0.md,
  WINDOWS-INTEGRATION-GATE-5.5.0.md,
  COMPANY-PUBLISHER-GATE-5.6.0.md,
  WINDOWS-RELIABILITY-GATE-5.7.0.md,
  SECURE-ARCHIVE-FORMAT.md, SECURE-ARCHIVE-GATE-5.3.0.md,
  REPOSITORY-FORMAT.md, BENCHMARK-AUDIT.md and VAULT-README.md for evidence,
  formats and technical limits.

License
-------
Rat-Trap is source-available for personal and non-commercial use. Commercial
use requires a separate written license from TWO HANDS NETWORK LTD. See
LICENSE.md and NOTICE.md for the full terms.

Required Notice: Copyright (c) 2026 TWO HANDS NETWORK LTD.
Based on the Motion-TimeSpace Framework by Martin Ollett.

This software is provided as-is, without warranty.
