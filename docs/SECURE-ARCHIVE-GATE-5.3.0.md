# Rat-Trap 5.3.0 secure-archive release gate

## Delivered boundary

Rat-Trap 5.3.0 adds authenticated encryption to portable `.gmw` archives,
Queryable Vaults, and portable exports from backup history. Existing
4.2–5.2 archive families remain readable and are not silently rewritten.

The canonical `RAT-TRAP-REPOSITORY-1` backup store remains local,
checksum-verified, and unencrypted. Cloud/off-site backends and encrypted
repository schema 2 are separate stages.

## Required behavior

- AES-256-GCM-SIV encrypts the complete inner archive and authenticates every
  bounded chunk before plaintext publication.
- Argon2id uses the fixed RFC 9106 low-memory recommendation: 64 MiB, three
  iterations, four lanes.
- Every archive receives a random data key, one password slot, and one
  independent random recovery slot.
- Recovery `.rtrk` files are never overwritten and are read back and verified
  before archive creation reports success.
- Password and recovery rotations verify the replacement credential before
  revoking the old one, serialize cooperating updates, and reject a stale
  authenticated header before commit.
- Header changes, content changes, truncation, and trailing data fail closed.
- Public and nested numeric fields require their exact schema types, sealed
  metadata has its exact schema-1 length, and authenticated malformed JSON
  remains inside the secure error boundary.
- Wrong credentials and damaged data leave no requested plaintext archive.
- Passwords and recovery secrets are never accepted as raw command-line
  argument values, printed in JSON, placed in environment variables, or
  included in error messages.
- CLI plaintext working-copy/output operations require an explicit
  acknowledgement flag. Structured CSV/TSV/JSON export from an encrypted Vault
  requires the stronger plaintext-output acknowledgement, not only temporary
  working-copy consent.
- The Windows app prompts with masked password fields and shows the
  plaintext-temporary-file limitation. It recommends a recovery-key location
  away from the archive and requires an extra confirmation for the same folder.
- Encrypted backup-history export checks plaintext consent before restoring a
  snapshot and keeps the restored tree in operating-system temporary storage.
- Plaintext creation refuses to replace an encrypted archive unless the API,
  CLI, or Windows caller gives a separate, explicitly named
  remove-encryption acknowledgement.

## Verified source test matrix

The source gate must cover:

- empty, small, multi-chunk, Unicode-password, password, and recovery-key
  round trips;
- known plaintext absent from the envelope;
- wrong password, wrong recovery file, header tamper, chunk tamper,
  truncation, and appended-data rejection;
- output and recovery-file collision refusal, including alternate paths and
  NTFS hard links that identify the same source archive;
- no partial output or temporary-file publication after failure;
- password change and recovery rotation, including old-credential revocation
  and unchanged bulk ciphertext, overlapping-update refusal, stale-header
  rejection, and recovery-file cleanup after a failed rotation;
- hostile KDF settings, non-finite JSON numbers, invalid Unicode, and
  wrong JSON field types in untrusted headers/recovery files fail through the
  secure error boundary;
- encrypted Balanced archive creation, metadata, extraction, and ZIP export;
- encrypted Vault creation, filename/text search, structured table query,
  verification, and selected/full extraction;
- encrypted portable export from a verified repository snapshot;
- Windows stale-result binding and plaintext query-result export consent;
- Windows confirmation before replacing an encrypted archive with a plaintext
  archive;
- API/CLI refusal before a plaintext writer runs on an encrypted output, with
  the original bytes preserved, plus an explicit downgrade success case;
- API, CLI, and Windows refusal before an archive, Vault, ZIP, extraction, or
  query-result output can replace its own encrypted source;
- unchanged golden compatibility fixtures for every older supported family;
- deterministic secure schema-1 fixture and complete interoperability vector
  with password/recovery unlock, exact inner bytes, and corruption rejection.

## Frozen Windows gate

The release build pins:

```text
cryptography==49.0.0
cffi==2.1.0
pycparser==3.0
```

The packaged `--self-test` must execute real Argon2id and AES-GCM-SIV
operations, unlock with both password and recovery key, restore exact bytes,
and reject tampering. Import success alone is not sufficient.

The final release manifest must record the tested Python, cryptography,
OpenSSL, PyInstaller, CFFI, compression and chunker versions; the release
ref/tag and baseline commit; test totals; executable and ZIP hashes;
Authenticode status; and packaged third-party licence inventory. The
containing commit cannot embed its own SHA without becoming self-referential;
the immutable annotated release tag identifies it after commit.

## Explicit non-claims

Rat-Trap 5.3.0 does not claim:

- encrypted live backup repositories;
- secure deletion of plaintext temporary files;
- protection from malware or an already-unlocked Windows account;
- concealment of outer file size, declared inner archive size, timestamp, or
  access patterns;
- rollback prevention, digital signing, cloud synchronization, VSS
  point-in-time snapshots, or independent security certification.

These limits belong in the technical/buyer lane. The front product lane can
accurately say: authenticated encrypted portable archives, tamper detection,
and an independent recovery key.
