# GMW format registry and compatibility policy

Status: normative for Rat-Trap 5.1.0 and later readers

## Registry

| Family | Identification | First supported | 5.1 writer | 5.1 reader | Status |
|---|---|---:|---:|---:|---|
| `GMW-SQLITE-1` | SQLite plus `metadata.format` | 4.2 | Optional legacy profile | Yes | Legacy read/export |
| `GMW-SOLID-2` | `RATGMW2\n` file magic | 4.3 | Yes | Yes | Current portable archive |
| `GMW-VAULT-1`, schema 1 | SQLite plus Vault metadata | 5.0 | No | Yes | Supported legacy Vault |
| `GMW-VAULT-1`, schema 2 | SQLite plus Vault metadata | 5.1 | Yes | Yes | Current queryable Vault |

Earlier raw compressed-tar experiments, JSON-footer tar drafts, and
`GMW-DEDUP-1` are historical prototypes, not supported release formats.
`MBT2` is a separate spatial-record format and is not a folder archive.

## `GMW-SOLID-2`

On-disk layout:

```text
[RATGMW2\n]
[compressed PAX tar payload]
[UTF-8 JSON metadata]
[metadata length: unsigned 64-bit little-endian]
[GMWMETA2]
```

Supported payload compressors are Zstandard and XZ. The metadata records the
compressor, level, file/directory counts, original and payload sizes, profile,
creation timing, entry order, and deduplication settings.

When exact whole-file deduplication is enabled, files of at least 4 KiB are
hashed. A duplicate is represented as a safe tar hard-link to the first
matching member, and the original size is retained in a PAX header. This is
lossless whole-file reuse, not general content-defined chunking.

The stored SHA-256 covers only the compressed payload. Metadata length,
metadata JSON, and footer magic are structurally checked but are not
cryptographically authenticated. Extraction code must continue to reject
absolute paths, traversal, unsafe link targets, and output paths escaping the
selected destination.

## `GMW-VAULT-1`

The Vault is a SQLite database. Both schemas contain:

- `vault_metadata`;
- `directories`;
- `objects`;
- `files`;
- `file_chunks`;
- contentless FTS5 `file_search`.

File data is split into fixed-size blocks, 4 MiB by default. The raw block
SHA-256 is its object ID; each unique object is compressed independently with
Zstandard. Files store their own SHA-256 and ordered object references.

Schema 2 adds:

- `structured_sources`;
- `structured_columns`;
- a typed `rt_data_<source id>` table for each recognized CSV, TSV, JSON,
  JSONL, NDJSON, or supported UCI source.

The compressed original files are canonical. FTS and relational tables are
derived indexes and must be considered rebuildable. Read-only SQL is restricted
to the Vault query surface; archive mutation is not part of that interface.

The verifier checks SQLite integrity, metadata totals, object hashes and
decompression, ordered file reconstruction, and file hashes. It does not make
the database tamper-authenticated, and every derived index cell is not
individually bound to the original bytes.

## `GMW-SQLITE-1`

This legacy SQLite family stores:

- key/value `metadata`;
- compressed `chunks`;
- `files` with ordered JSON lists of chunk IDs and sizes.

The normal chunk size is 512 KiB. Chunk IDs are BLAKE2b-128 digests of raw
blocks; blocks use Zstandard or the zlib fallback. Exact aligned blocks can be
reused across files.

This family lacks the current Vault's per-file SHA-256 and full validation
model. It remains supported for reading and export so existing 4.2 archives
are not stranded. New general-purpose archives should use a current profile.

## Reader dispatch

The required dispatch behavior for future readers is:

Readers identify formats in this order:

1. `RATGMW2\n` means `GMW-SOLID-2`.
2. A SQLite header is opened read-only and its format metadata is validated.
3. A recognized `GMW-VAULT-1` schema is handled by the Vault reader.
4. A recognized `GMW-SQLITE-1` database is handled by the legacy reader.
5. Anything else fails as unsupported.

The preserved 5.1 implementation does not fully meet steps 4 and 5. After
solid and Vault detection, it falls back to the legacy SQLite reader, whose
metadata loader does not explicitly assert `format == "GMW-SQLITE-1"`. An
unknown SQLite database with a sufficiently compatible `metadata` table could
therefore reach legacy processing. This is a known 5.1 dispatch limitation,
not the intended compatibility policy.

The next reader change must validate the legacy family marker and required
schema before extraction or export. It also needs a regression test proving
that unrelated and unknown-family SQLite databases fail closed.

## Compatibility rules

1. **Readers are long-lived.** Every future official reader must read every
   officially released 4.2+ archive unless a documented security reason makes
   that impossible.
2. **Writers move forward.** Normal writers emit only the latest suitable
   format. A legacy writer may exist only as an explicitly labelled
   compatibility option.
3. **Fail closed.** An unknown family, mandatory feature, or schema newer than
   the reader supports is an error.
4. **Additive derived data uses a schema bump.** New optional/rebuildable Vault
   indexes can use a new schema version when older canonical content remains
   meaningful.
5. **Incompatible semantics use a new family or major marker.** Changing
   canonical chunk identity, encryption, authentication, or payload layout is
   not a silent schema tweak.
6. **No in-place migration of the only copy.** Migration writes a new archive,
   fully verifies it, then leaves replacement/deletion to the user.
7. **Encryption gets an authenticated envelope.** Paths, metadata, indexes and
   data must be authenticated. A dependency named `crypto` does not make an
   existing archive encrypted.
8. **Samples make support real.** Each supported family/schema needs a small
   immutable golden archive, expected manifest, corruption cases, and tests
   before the reader is changed.

## Planned compatibility fixture set

Later work should add:

```text
tests/fixtures/formats/
  gmw-sqlite-1/
  gmw-solid-2-4.3/
  gmw-solid-2-4.4-dedup/
  gmw-vault-1-schema-1/
  gmw-vault-1-schema-2/
```

Each directory should contain a tiny archive, source-tree manifest, SHA-256,
expected metadata, and a licence-safe provenance note. Fixtures should be
generated by the original release writer where possible, not reconstructed
from a later implementation.
