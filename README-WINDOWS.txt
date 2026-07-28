RAT-TRAP 5.1.0 FOR WINDOWS
==========================

Quick start
-----------
1. Extract the ZIP file to a folder.
2. Double-click Rat-Trap.exe. No Python installation is required.
3. Use Create, Search Vault, Data Tables, Extract archive, or Inspect / export.

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
- Version 5.1 reads 5.0 searchable Vaults, 4.4 hybrid archives, earlier solid
  archives, and existing v4.2 SQLite block archives.
- Inspect / export can convert a normal archive or Vault to a conventional ZIP.
- The executable is not digitally signed. Windows may show an
  unknown-publisher warning. Verify the supplied SHA-256 value before running.
- See BENCHMARK-AUDIT.md and VAULT-README.md for evidence and technical limits.

License
-------
Rat-Trap is source-available for personal and non-commercial use. Commercial
use requires a separate written license from TWO HANDS NETWORK LTD. See
LICENSE.md and NOTICE.md for the full terms.

Required Notice: Copyright (c) 2026 TWO HANDS NETWORK LTD.
Based on the Motion-TimeSpace Framework by Martin Ollett.

This software is provided as-is, without warranty.
