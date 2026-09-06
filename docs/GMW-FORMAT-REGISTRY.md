# GMW format registry and compatibility policy

Status: normative for Rat-Trap 5.4.0 and later readers

## Registry

| Family or profile | Identification | First supported | Current writer | 5.4 reader | Status |
|---|---|---:|---:|---:|---|
| `RAT-TRAP-ENCRYPTED-1`, schema 1 | `RAT-TRAP-SECURE-1\0` file magic | 5.3 | Yes | Yes | Authenticated outer envelope |
| Sealed File profile 1 | Outer encrypted magic; profile only after authenticated inner validation | 5.4 | Yes | Yes | Independent `.rtsf` per-file protection |
| `GMW-SQLITE-1` | SQLite plus `metadata.format` | 4.2 | Optional legacy profile | Yes | Legacy read/export |
| `GMW-SOLID-2` | `RATGMW2\n` file magic | 4.3 | Yes | Yes | Current portable archive |
| `GMW-VAULT-1`, schema 1 | SQLite plus Vault metadata | 5.0 | No | Yes | Supported legacy Vault |
| `GMW-VAULT-1`, schema 2 | SQLite plus Vault metadata | 5.1 | Yes | Yes | Current queryable Vault |

Earlier raw compressed-tar experiments, JSON-footer tar drafts, and
`GMW-DEDUP-1` are historical prototypes, not supported release formats.
`MBT2` is a separate spatial-record format and is not a folder archive.

## `RAT-TRAP-ENCRYPTED-1`

The secure family wraps one complete supported inner `.gmw` and therefore
does not modify any existing inner family. Its AES-256-GCM-SIV envelope,
Argon2id password slot, independent HKDF-SHA256 recovery slot, strict parser,
metadata leakage, and plaintext-working-copy limit are normative in
[`SECURE-ARCHIVE-FORMAT.md`](SECURE-ARCHIVE-FORMAT.md).

The live schema-1 backup repository is not this family and remains
unencrypted.

## Sealed File profile 1

A Rat-Trap Sealed File is not a new encryption family. Its `.rtsf` exterior
uses the unchanged `RAT-TRAP-ENCRYPTED-1` schema-1 envelope and contains one
exact `GMW-SOLID-2` archive with:

- profile `sealed-file`;
- Zstandard level 6;
- exactly one regular file and no directory or link members;
- path entry order, with whole-file deduplication and long-distance mode off.

The original basename, content hash, byte size, modification time, and mode
exist only inside the authenticated ciphertext. Before unlock, a reader may
report public outer-envelope fields but must not claim that the file has the
Sealed File profile. Each `.rtsf` has its own independent `.rtrk` recovery key;
normal writers give the encrypted file an opaque `RT-<128-bit hex>.rtsf`
exterior name. The profile and its resource and path-safety requirements are
normative in [`SEALED-FILE-FORMAT.md`](SEALED-FILE-FORMAT.md).

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

Readers identify formats in this order:

1. `RAT-TRAP-SECURE-1\0` means the strict authenticated outer envelope. It
   must be unlocked and completely authenticated before inner dispatch.
2. An `.rtsf` operation additionally requires the authenticated inner archive
   to match every Sealed File profile-1 constraint before original metadata is
   reported or plaintext is published.
3. `RATGMW2\n` means `GMW-SOLID-2`.
4. A SQLite header is opened read-only and its format metadata is validated.
5. A recognized `GMW-VAULT-1` schema is handled by the Vault reader.
6. A recognized `GMW-SQLITE-1` database is handled by the legacy reader.
7. Anything else fails as unsupported.

Rat-Trap 5.4.0 enforces this policy before inspect, extraction, ZIP export, or
legacy HTTP serving. The legacy detector requires SQLite magic, the exact
`GMW-SQLITE-1` marker, and the required metadata/chunk/file columns. The Vault
detector requires the exact family and supported schema version, typed
metadata, all required tables/columns, and an FTS5 search table. A database
that presents both legacy and Vault family structures is rejected as
ambiguous.

Encrypted HTTP serving is refused because it would require a long-lived
plaintext working copy.

The preserved 5.1.0 reader did not fully meet steps 4 and 5: after solid and
Vault detection it unconditionally tried the legacy reader. That historical
limitation remains documented in the frozen
[`BASELINE-5.1.0.md`](BASELINE-5.1.0.md); it is fixed in 5.1.1.

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

## Committed compatibility fixture set

The reader gate includes:

```text
tests/fixtures/formats/
  README.md
  generate_fixtures.py
  manifest.json
  gmw-sqlite-1-4.2.gmw
  gmw-solid-2-4.3.gmw
  gmw-solid-2-4.4-dedup.gmw
  gmw-vault-1-schema-1.gmw
  gmw-vault-1-schema-2.gmw
  rat-trap-encrypted-1-5.3.gmw
  rat-trap-encrypted-1-5.3.rtrk
  rat-trap-encrypted-1-5.3-vector.json
  rat-trap-sealed-file-1-5.4.rtsf
  rat-trap-sealed-file-1-5.4.rtrk
  rat-trap-sealed-file-1-5.4-inner.gmw
```

Every test run checks each fixture's byte size and SHA-256, metadata, family
detection, exact extracted tree, and ZIP export. Vault fixtures also pass the
Vault verifier. The secure fixture unlocks independently with its public test
password and recovery file, verifies its exact inner bytes, rejects wrong
credentials and corruption, and is regenerated twice byte-for-byte.
The Sealed File fixture also verifies that locked inspection discloses no
inner-profile or original-file fields, authenticates the exact profile with
both credentials, restores the original Unicode basename and bytes, and
publishes no plaintext after a wrong password or ciphertext corruption.

These small files are deterministic compatibility reconstructions made from
the maintained implementations with old metadata/schema shapes. They are not
original release outputs and are not benchmark evidence. Their manifest says
so explicitly and records the hashes of the preserved original executables
for provenance. The workspace's authentic 16–22 MB schema-1 and schema-2 beta
Vaults remain separate empirical evidence and are referenced by hash rather
than duplicated in Git.

The schema-1 secure vector is different: it is a deterministic 5.3 writer
output intended for interoperability, not historical provenance or benchmark
evidence. It publishes test-only keys and credentials by design. Never use
them for private archives.

The Sealed File fixture is likewise a deterministic 5.4 writer output for
profile compatibility, not historical provenance or benchmark evidence. Its
test password, recovery key, decrypted inner archive, and original plaintext
description are public by design and must never be reused for private files.
