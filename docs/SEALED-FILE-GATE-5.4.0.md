# Rat-Trap 5.4.0 Sealed File release gate

## Delivered boundary

Rat-Trap 5.4.0 Beta adds a copy-only Sealed File workflow for ordinary files.
Each source file becomes one independently compressed, authenticated and
encrypted `.rtsf`, with one independently generated `.rtrk` recovery key.

The outer bytes remain `RAT-TRAP-ENCRYPTED-1`, schema 1. The authenticated
plaintext is an exact one-member `GMW-SOLID-2` archive using the
`sealed-file` profile. Rat-Trap does not infer this profile from the `.rtsf`
extension.

The original file is always retained. This release does not delete, recycle,
replace, rename, truncate, or securely erase it.

## Required single-file behavior

- A default exterior filename is `RT-<128-bit-random-lowercase-hex>.rtsf` and
  is not derived from the original name, extension, path, content, or hash.
- The authenticated inner archive stores only the original basename, never its
  source directory, drive, UNC path, or other location information.
- The inner archive contains exactly one regular file and has every fixed
  `sealed-file` profile value described in `SEALED-FILE-FORMAT.md`.
- The password uses the schema-1 Argon2id policy, while AES-256-GCM-SIV
  authenticates the outer header, sealed metadata, and every bounded chunk.
- Each file receives independent random data-key, password-salt, nonce, and
  recovery material. A recovery key for one file cannot unlock another.
- Passwords are entered through masked prompts and are not accepted as raw
  command-line values, environment defaults, output filenames, or result
  fields.
- The recovery path is new and is separate from both the plaintext source
  tree and sealed-output tree. The single-file workflow may allow a recovery
  key beside its sealed file only after an explicitly named override; it may
  never allow recovery material inside the plaintext source tree.
- Existing sealed, recovery, and restored-plaintext paths are never
  overwritten, including aliases that identify an input through an NTFS hard
  link.
- Recovery material is staged, published without replacement, read back, and
  verified before the sealed output is published. Sudden-power-loss
  durability remains dependent on the selected filesystem and storage stack.
- The completed staged envelope is independently unlocked and its exact inner
  profile is verified with both the password and newly written recovery key
  before success is reported.
- The source identity, hard-link state, alternate-data-stream state, size,
  modification time, and complete SHA-256 digest are rechecked before
  publication. A change fails closed and leaves the source untouched.
- A publication failure may leave a clearly reported orphan recovery file,
  but must not publish an unverified `.rtsf` or report success.
- Wrong credentials, truncation, trailing bytes, malformed authenticated
  metadata, ciphertext tampering, or an invalid inner profile publish no
  plaintext.
- Unsealing restores the authenticated basename into a new directory and
  refuses replacement. The restored size and SHA-256 digest must match the
  authenticated inner metadata.
- Before decrypting an existing Sealed File, Rat-Trap enforces a maximum
  1 TiB inner-archive size. Creation refuses to publish a larger inner
  archive. Before decompression it enforces a maximum 8 TiB authenticated
  original-file size plus a bounded profile-overhead allowance.

## Required bulk behavior

Bulk sealing is a sequence of independent single-file transactions, not an
all-or-nothing encrypted folder container.

- The source inventory fails closed on read errors and does not follow
  reparse points.
- Both destination trees must be new, mutually separate, outside the source
  tree, and neither may contain the other.
- Every candidate receives its opaque output and recovery names before
  processing, and its filesystem identity is checked again before work.
- The result distinguishes verified sealed files, failures, unprocessed
  inputs, and recovery-only incidents.
- The CLI prints the complete JSON result and exits non-zero for every partial
  batch. The Windows app offers the complete mapping as an optional plaintext
  JSON report and warns that it reveals original filenames and paths.
- The default policy continues after an independent file failure. A
  `--stop-on-error` policy may instead leave the remaining planned inputs
  explicitly unprocessed.
- A final reconciliation reports new, removed, renamed, or changed source
  entries observed after the initial inventory. It does not silently treat an
  incomplete view as a complete batch.
- Every plaintext source remains untouched regardless of success, failure, or
  cancellation.

Rat-Trap 5.4 Beta has no durable batch journal. An interrupted batch cannot
resume into the same destination trees. Existing verified outputs remain
valid, but a retry must select two new destination trees. The Windows app and
documentation must state this limitation.

## Locked and authenticated information

Before authentication, the application may display only validated public
outer-envelope information. It must not claim that the ciphertext has the
Sealed File profile or reveal an original basename, extension, content size,
content hash, timestamp, preview, or inferred file type.

The original metadata may be displayed only after one valid credential has
authenticated the complete outer envelope and Rat-Trap has validated the
complete exact one-file inner profile.

## Windows and command-line gate

- **Secure files** is the first Windows tab and exposes Protect one file,
  Verify / restore, and Protect a folder.
- Warning text states that the original remains plaintext and that temporary
  plaintext cleanup is best-effort with no secure-deletion guarantee.
- A custom visible exterior name receives a privacy warning; the generated
  opaque name is the default.
- Double-click or launch handling for `.rtsf` preselects the locked
  verify/restore workflow. It must never authenticate, decrypt, export, or
  launch another application without an explicit user action.
- CLI creation and verification operations that use plaintext inner staging
  require `--allow-plaintext-temp`.
- CLI restoration requires both `--allow-plaintext-temp` and
  `--allow-plaintext-output`.
- CLI credentials use a masked prompt or `--recovery-key-file`; there is no
  password argument.

The Windows association is a usability feature, not access control. Without a
valid credential, ordinary applications see ciphertext. Any independent
conforming implementation can decrypt the documented format when supplied
with the password or matching recovery key.

## Required source test matrix

The source gate must cover:

- password and recovery-key single-file round trips with exact basename,
  bytes, size, and SHA-256 restoration plus authenticated stored modification
  time;
- fresh opaque names and independent recovery material across multiple files;
- known original name, extension, and content absent from locked outer bytes;
- public locked inspection versus authenticated private inspection;
- wrong password, wrong recovery key, header tamper, ciphertext tamper,
  truncation, trailing data, malformed inner metadata, and profile mismatch;
- no plaintext output or partial final output after every failure class;
- output, recovery, source, and destination collision refusal through direct
  paths, aliases, and hard links;
- source mutation, new hard link, alternate data stream, and reparse-point
  rejection before publication;
- password-policy rejection before source reads, directory creation, or
  plaintext staging;
- atomic recovery publication and safe reporting of an orphan recovery file;
- resource-gate enforcement before large plaintext work;
- bulk success, continue-on-error, stop-on-error, cancellation, unprocessed
  state, recovery-only state, final source reconciliation, and unreadable
  inventory failure;
- Windows controls, warnings, launch parsing, stale-result binding, and a real
  Sealed File self-test;
- CLI masked-credential paths, acknowledgement gates, JSON status, and
  non-zero failure behavior;
- unchanged compatibility coverage for all previously supported `.gmw`,
  encrypted archive, Vault, and repository families; and
- a deterministic public compatibility vector that unlocks by both password
  and recovery key and rejects corruption.

## Frozen Windows gate

The release build pins:

```text
Python 3.13.13
cryptography 49.0.0
OpenSSL 4.0.1
cffi 2.1.0
pycparser 3.0
PyInstaller 6.21.0
zstandard 0.25.0
pyfastcdc 0.2.1
```

The packaged `Rat-Trap.exe --self-test` must execute real Argon2id and
AES-256-GCM-SIV operations, seal and restore exact bytes with both password
and recovery credentials, and reject tampering. Import success alone is not
sufficient.

The final release record must include the source ref and baseline commit,
complete test totals, pinned runtime versions, executable and ZIP SHA-256
hashes, executable version-resource values, Authenticode status, ZIP
inventory, and bundled third-party licences and SBOMs. This gate document
defines acceptance criteria; it is not, by itself, evidence that a particular
artifact passed them.

## Explicit non-claims

Rat-Trap 5.4.0 Beta does not claim:

- deletion, recycling, replacement, or secure erasure of originals or
  temporary plaintext;
- protection from malware, an already-unlocked Windows account, credential
  theft, or someone holding the matching `.rtrk`;
- concealment of exterior filename, encrypted size, declared inner size,
  outer timestamps, file count, or access patterns;
- that only the Rat-Trap executable can implement the documented format;
- automatic opening, external-application editing, or automatic
  re-encryption;
- a mounted drive, projected filesystem, shared workspace key, or encrypted
  live backup repository;
- system-file, link, sparse-file, NTFS-compressed-file, EFS, or alternate-data
  stream support;
- atomic folder transactions, a durable batch journal, or same-directory
  batch resume;
- rollback prevention, ransomware protection, cloud synchronization, VSS
  point-in-time capture, digital signing, or independent security
  certification.
