RAT-TRAP 5.2.0 FOR WINDOWS
==========================

Quick start
-----------
1. Extract the ZIP file to a folder.
2. Double-click Rat-Trap.exe. No Python installation is required.
3. Use Backups & history for recurring snapshots, or the other tabs for
   portable archives and Queryable Vaults.

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
7. Cleanup always previews first. Version 5.2 moves eligible data to
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
- Version 5.2.0 reads 5.0 searchable Vaults, 4.4 hybrid archives, earlier solid
  archives, and existing v4.2 SQLite block archives.
- Version 5.2.0 validates the archive family and required database schema
  before reading. Unknown, incomplete, or ambiguous SQLite files are rejected.
- Repository schema 1 rejects symbolic links, junctions, alternate data
  streams, sparse files, hard links, NTFS-compressed items and EFS-encrypted
  items instead of silently changing their meaning or copying decrypted
  plaintext. ACL preservation and VSS handling for open files are not
  implemented yet.
- Backups read a live folder file by file, then atomically publish the complete
  capture. Without VSS they are not a filesystem-wide point-in-time view while
  applications are actively changing multiple files.
- Repository snapshots are checksum-verified but are not encrypted.
- Inspect / export can convert a normal archive or Vault to a conventional ZIP.
- The executable is not digitally signed. Windows may show an
  unknown-publisher warning. Verify the supplied SHA-256 value before running.
- See REPOSITORY-FORMAT.md, BENCHMARK-AUDIT.md and VAULT-README.md for evidence,
  formats and technical limits.

License
-------
Rat-Trap is source-available for personal and non-commercial use. Commercial
use requires a separate written license from TWO HANDS NETWORK LTD. See
LICENSE.md and NOTICE.md for the full terms.

Required Notice: Copyright (c) 2026 TWO HANDS NETWORK LTD.
Based on the Motion-TimeSpace Framework by Martin Ollett.

This software is provided as-is, without warranty.
