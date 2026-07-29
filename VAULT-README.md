# Rat-Trap Queryable Vault

Rat-Trap uses `GMW-VAULT-1`, a searchable SQLite format intended for data
collections where discovery and selective extraction matter more than the
smallest possible container.

## What is queryable

- Every stored path, file size, media type, timestamp, mode and SHA-256 digest.
- Every filename through the FTS5 search index, including binary files.
- Text content detected in files up to 16 MiB. Detection is content-based, so
  extensionless text and dataset names such as `adult.data` are included.
- Optional extension filtering in the application and API.
- Typed rows and columns from CSV, TSV, JSON, JSONL, NDJSON, `.data`, and
  `.test` sources up to 64 MiB.
- UCI `.names` sidecars, when present, provide meaningful column names.
- Point-and-click row filtering and sorting, plus advanced read-only SQL.
- CSV, TSV, and JSON result export with original-file provenance in the
  structured catalog.

Structured tables are an additional representation. Original source files are
still stored byte-for-byte in the compressed object layer and restored exactly.
Types are conservatively inferred as `INTEGER`, `REAL`, or `TEXT`; empty values
become SQL `NULL`.

## Storage model

- `files`: path, size, timestamp, permissions, media type, full-file SHA-256,
  index state and chunk count.
- `directories`: empty-directory and directory metadata preservation.
- `objects`: unique 4 MiB content-addressed blocks compressed with Zstandard.
- `file_chunks`: ordered mapping from each file to its objects.
- `file_search`: contentless SQLite FTS5 index for paths and detected text.
- `structured_sources`: source path, safe table name, format, row count and
  column count.
- `structured_columns`: original and SQL-safe column names plus inferred type.
- `rt_data_<file-id>`: one real relational table for each imported source.
- `vault_metadata`: version, totals, compressor settings and deduplication
  statistics.

Every object and reconstructed file is SHA-256 checked during verification or
extraction. Paths are validated before writing and symbolic links are rejected.

## Windows workflow

1. Choose `Queryable Vault - searchable SQLite` on the Create tab.
2. Select the Vault on the Search Vault tab.
3. Enter ordinary words; terms are combined with AND semantics.
4. Preview one result or export multiple selected results.
5. Use Extract archive for a complete restoration or Inspect / export for ZIP.

For structured data, open **Data Tables**, select the same Vault, then choose a
source. The Browse / filter view requires no SQL. The SQL query view accepts
one read-only `SELECT` or `WITH` statement. The interface displays each safe
table name and can export the current result set.

## Command line

```powershell
rat-trap vault-create C:\Data C:\Archives\Data.vault.gmw
rat-trap vault-search C:\Archives\Data.vault.gmw "search terms"
rat-trap vault-search C:\Archives\Data.vault.gmw "report" --extension pdf
rat-trap vault-extract C:\Archives\Data.vault.gmw C:\Restored
rat-trap vault-extract C:\Archives\Data.vault.gmw C:\Selected "docs/readme.txt"
rat-trap vault-verify C:\Archives\Data.vault.gmw
rat-trap vault-tables C:\Archives\Data.vault.gmw
rat-trap vault-query C:\Archives\Data.vault.gmw 1 --find Private --column workclass
rat-trap vault-sql C:\Archives\Data.vault.gmw "SELECT age, workclass FROM rt_data_5 WHERE age >= 50"
rat-trap vault-query C:\Archives\Data.vault.gmw 1 --output results.csv
```

Python callers can additionally use `list_structured_sources`,
`list_structured_columns`, `query_structured_source`, `execute_structured_sql`,
and `export_structured_result`.

## Encrypted Vaults in 5.3

The Create tab and `vault-create --encrypt` can wrap the complete Vault with
the authenticated `RAT-TRAP-ENCRYPTED-1` envelope. Filenames, indexed text,
table schemas, rows, checksums and stored content are encrypted at rest. A
password and independently generated `.rtrk` recovery file can each unlock it.

Search and SQLite queryability require an unlocked database. Rat-Trap 5.3
therefore decrypts an encrypted Vault into an isolated plaintext temporary
working copy for each operation, removes it on a best-effort basis, and makes
no secure-deletion claim. Windows, SSDs, backup tools, crash dumps, antivirus,
or malware may retain traces. CLI users must pass
`--allow-plaintext-temp`; operations that restore/export plaintext use
`--allow-plaintext-output`.

For very large collections that must remain instantly queryable, use an
unencrypted local Vault on a device protected by Windows drive encryption and
create a separate encrypted portable copy for storage or transport.

## Current limits

- Search indexes text, not OCR within images or speech recognition within WAV.
- Text files larger than 16 MiB are stored but not content-indexed by default.
- Structured files larger than 64 MiB are stored but not materialised as
  relational tables. Each source is currently limited to 250,000 rows and 256
  columns; larger sources remain fully restorable as ordinary files.
- JSON import targets objects, arrays of objects, or an object containing an
  array of objects. Deep nested values remain lossless JSON text in one cell.
- Fixed-size object deduplication finds aligned repeated blocks; it is not
  content-defined chunking for shifted duplicate regions.
- FTS results are file-level and do not currently include highlighted snippets.
- HTTP serving remains available only for the legacy v4 SQLite block format.
- Encrypted Vault queries currently authenticate and materialize the complete
  Vault before SQLite opens it; random-access encrypted pages are a later
  storage-format project.
