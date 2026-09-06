# Rat-Trap Sealed File profile

Status: normative for Rat-Trap 5.4 Sealed Files Beta

Profile name: `sealed-file`

Windows extension: `.rtsf`

## Scope

A Rat-Trap Sealed File is one authenticated encrypted portable archive that
contains exactly one ordinary file. It is not a new encryption family.

The bytes of an `.rtsf` are:

```text
RAT-TRAP-ENCRYPTED-1, schema 1
  containing one GMW-SOLID-2 archive
    whose profile is "sealed-file"
    and whose payload contains exactly one regular file member
```

The outer envelope is the unchanged schema-1 format specified by
[`SECURE-ARCHIVE-FORMAT.md`](SECURE-ARCHIVE-FORMAT.md). It therefore uses the
same AES-256-GCM-SIV content encryption, Argon2id password slot, independent
recovery slot, authenticated header, sealed metadata, bounded chunks, and
strict exact-length validation introduced in Rat-Trap 5.3.

The `.rtsf` extension is a Windows application association and usability
hint. It is not an authentication mechanism. Readers identify and verify the
outer and inner formats from their bytes, not from the extension.

The words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in
this document describe requirements for the 5.4 Sealed Files Beta profile.

## Format composition

### Authenticated outer envelope

The outer file MUST have:

- magic `b"RAT-TRAP-SECURE-1\x00"`;
- `format` equal to `RAT-TRAP-ENCRYPTED-1`;
- `schema_version` equal to `1`;
- the exact schema-1 cipher, KDF, key-slot, canonical-JSON, chunk, and
  authentication rules in `SECURE-ARCHIVE-FORMAT.md`; and
- one password slot and one independent per-file recovery slot.

A 5.4 writer records its actual writer version in the informational
`writer_version` field. Changing that string does not change the security
suite or reader dispatch. It remains part of the authenticated data context
exactly as specified for schema 1.

The outer plaintext is the complete inner `GMW-SOLID-2` byte sequence. The
schema-1 `plaintext_size` is consequently the inner archive size, not the
original file size.

### Exactly-one-file inner profile

After complete outer authentication and decryption, the plaintext MUST be a
valid `GMW-SOLID-2` archive with these metadata values:

| Field | Required value |
|---|---|
| `format` | `GMW-SOLID-2` |
| `profile` | `sealed-file` |
| `compressor` | `zstd` |
| `compression_level` | `6` |
| `entry_order` | `path` |
| `file_count` | `1` |
| `directory_count` | `0` |
| `whole_file_dedup` | `false` |
| `duplicate_file_count` | `0` |
| `zstd_window_log` | `null` |
| `zstd_long_distance` | `false` |

The compressed PAX tar payload MUST expose exactly one logical member to the
tar reader. That member MUST:

- be a regular file;
- have a one-component Windows-safe basename as its member name;
- have a declared size equal to `GMW-SOLID-2.total_bytes`; and
- contain the exact source bytes selected when the sealed copy was created.

Directories, hard links, symbolic links, junctions, devices, FIFOs, sockets,
and any other special member type are invalid in the `sealed-file` profile.
Whole-file deduplication has no role in a one-file archive and MUST be off.

The existing `GMW-SOLID-2` payload-size and SHA-256 checks remain mandatory.
The authenticated outer envelope additionally binds every byte of the inner
archive, including the compressed payload, its filename and PAX metadata, and
the `GMW-SOLID-2` metadata/footer.

An encrypted archive with zero or multiple members, a Vault inner family, or
a `GMW-SOLID-2` profile other than `sealed-file` MUST NOT be accepted by the
Sealed File workflow, even if it was renamed to end in `.rtsf`. Rat-Trap MAY
offer its separate general archive workflow for a valid non-profile archive.

Rat-Trap 5.4 Beta applies a fixed local resource gate before plaintext work:
the encrypted inner archive may be at most 1 TiB and its authenticated
original-file size may be at most 8 TiB. The one-file decompressor also caps
tar/profile overhead above that authenticated original size. A future release
may make lower limits configurable, but it must not silently remove bounds.

## Windows-safe embedded basename

The stored member name is the original basename only. A writer MUST NOT store
the source drive, parent directories, absolute path, UNC path, or any other
location information in the member name.

For this beta profile, the basename MUST satisfy every rule below:

1. It is non-empty Unicode text that can be encoded as UTF-8.
2. It is already in Unicode NFC form. The writer MUST refuse a non-NFC name
   rather than silently change the user's filename.
3. It contains one path component and contains neither `/` nor `\`.
4. It is not `.` or `..`, is not absolute, and has no drive or UNC prefix.
5. It contains none of `<`, `>`, `:`, `"`, `/`, `\`, `|`, `?`, or `*`.
6. It contains no character from U+0000 through U+001F and no U+007F.
7. It does not end in an ASCII space or full stop.
8. Its device-name component, compared case-insensitively before the first
   full stop, is not `CON`, `PRN`, `AUX`, `NUL`, `CLOCK$`, `COM1` through
   `COM9`, or `LPT1` through `LPT9`. The corresponding `COM` and `LPT` names
   using superscript one, two, or three are also refused.
9. It occupies no more than 255 UTF-16 code units.

The colon prohibition also prevents an embedded name from selecting an NTFS
alternate data stream.

An authenticated name is not automatically a safe name: a file may have
been produced by another implementation or by someone who possesses a valid
credential. Readers MUST apply these rules again after authentication.

When restoring, Rat-Trap combines only the validated basename with a
user-selected destination directory. It MUST verify that the result remains
inside that directory and MUST create the output exclusively. An existing
file, case-insensitive collision, symlink, reparse-point destination, invalid
or overlong resulting path, or unsafe basename causes refusal. Rat-Trap MUST
NOT silently overwrite or automatically choose a numbered replacement name.
The user MAY explicitly choose a different safe basename.

## Opaque outer names

The default private-name output is:

```text
RT-<opaque_id>.rtsf
```

where `<opaque_id>` is a fresh 128-bit random lowercase hexadecimal
identifier generated independently of the source name and content. It MAY be
the authenticated-envelope public `file_id`, but writers are not required to
know that identifier before choosing the output path.

The default name MUST NOT contain or be derived from the original basename,
extension, path, content, or hash. A user MAY explicitly choose a friendly
outer name, but Rat-Trap MUST state that the chosen name and extension are
visible without unlocking the file.

The matching recovery file SHOULD use the same opaque exterior identifier
inside the separately selected recovery directory. This permits unambiguous
pairing without exposing the embedded basename.

## Credentials and recovery

Every `.rtsf` receives:

- a fresh random 32-byte data key;
- a password slot with a fresh salt and the fixed schema-1 Argon2id profile;
  and
- a fresh independent 32-byte recovery secret with its own recovery slot.

The schema-1 password normalization, length policy, and password/recovery
rotation rules apply unchanged. Supplying either active credential grants the
same access to the complete file.

Recovery is per file in 5.4. A recovery file is
`RAT-TRAP-RECOVERY-KEY-1`, schema 1, and its `file_id` MUST match the `.rtsf`
header before key unwrapping. A recovery key for one Sealed File MUST NOT
unlock another.

A batch MAY ask for one password once, but every output still receives
independent data, salt, and recovery material. Rat-Trap MUST NOT store the
password in a command line, environment variable, result document, log,
filename, or recovery file.

The `.rtrk` contains a usable decryption secret and must be treated like a
physical master key for that file. The normal workflow MUST require a
recovery directory outside both the plaintext source directory and the
sealed-output directory. It MUST NOT default to a sibling of the `.rtsf`.
Rat-Trap MUST explain that a copier who obtains both files can unlock the
content without the password and recommend separate offline or separately
controlled storage.

An existing recovery path is never overwritten. Recovery material MUST be
written exclusively and read back before a Sealed File is published. The
completed staged `.rtsf` MUST be verified independently with the password and
with the newly written recovery file before success is reported.

If publication fails after a recovery file was verified, that recovery file
MAY remain as an identified orphan. Retaining uncertain recovery material is
safer than deleting the only key for a possibly published encrypted file.
The workflow MUST never intentionally publish an `.rtsf` before its recovery
material has been published without replacement, read back, and verified.
File and directory durability after sudden power loss remains dependent on
the selected filesystem and Windows storage stack.

This beta profile has no shared workspace master key. Password or recovery
rotation is an independent transaction for each `.rtsf`.

## Copy-only creation transaction

Sealing is non-destructive in Rat-Trap 5.4. The source remains an ordinary
plaintext file.

Before reading content, the writer MUST:

1. require an ordinary local regular file;
2. reject a directory, symbolic link, junction, reparse point, alternate data
   stream, device, or other special input;
3. reject an input with more than one hard-link name;
4. validate the basename under this profile;
5. resolve and compare source, sealed output, and recovery output identities,
   including existing-object file IDs;
6. reject any alias among those paths and reject any existing sealed or
   recovery destination; and
7. preflight that the recovery directory satisfies the separation rule.

The writer MUST then perform this order:

1. Open and identify a stable source.
2. Build the exactly-one-file inner archive in isolated staging.
3. Confirm that the bytes, size, modification state, and opened-file identity
   did not change while the inner archive was produced.
4. Encrypt the complete inner archive to a new same-directory staged output.
5. Flush, sync, reopen, and completely authenticate the staged envelope and
   validate its inner `sealed-file` profile.
6. Create and read back the new recovery file.
7. Verify the staged envelope using the password and matching recovery file.
8. Publish the `.rtsf` exclusively using same-directory atomic publication
   on a supported local filesystem.
9. Report the verified output and explicitly report that the original remains
   plaintext.

The source MUST NOT be deleted, recycled, renamed, truncated, overwritten,
have its timestamps changed, or otherwise be modified by this workflow. A
failure or cancellation at any point leaves the source untouched. An existing
sealed file or recovery file also remains byte-for-byte untouched.

The two output files cannot be published as one filesystem operation. The
required ordering gives these valid interrupted states:

- neither output exists;
- an identified orphan recovery file exists and no `.rtsf` exists; or
- both recovery and a completely verified `.rtsf` exist.

The writer MUST NOT report success for the first two states.

Moving a source to the Recycle Bin would leave readable plaintext. Normal
deletion also cannot guarantee erasure from an SSD, filesystem journal,
backup, synchronizer, antivirus cache, or earlier copy. Original removal and
in-place conversion are therefore outside the 5.4 Sealed Files Beta.

## Bulk creation

Bulk sealing is a sequence of independent copy-only transactions. It is not
an all-or-nothing filesystem transaction and does not create a Private Space.

The 5.4 Beta batch controller:

- requires two new, separate destination trees outside the source tree;
- rejects output and recovery trees that contain one another;
- performs a fail-closed inventory without following reparse points;
- records a stable identity for every candidate and rechecks it before work;
- creates independent opaque output and recovery names before processing;
- distinguishes verified success, failure, unprocessed input, and an orphan
  recovery file;
- keeps every source untouched;
- continues after a per-file error by default, with an explicit stop-on-error
  policy available to command-line callers;
- permits cancellation only between independent file transactions;
- performs a final reconciliation scan and reports files added, changed, or
  removed after preflight as unprocessed; and
- returns exact counts and paths for every observed state. The CLI prints this
  complete JSON result, and the Windows app offers it as an optional
  plaintext JSON report with a filename-privacy warning.

A partial run MUST NOT be presented as "all files protected." A successful
sealed copy also does not mean that the still-present plaintext source,
another hard link, backup, or earlier copy has been encrypted.

This beta does not maintain a durable batch journal and cannot resume an
interrupted batch into the same output directories. Existing verified outputs
remain valid, but a retry must select two new destination trees. Durable
idempotent resume is a later product stage and is not implied by bulk support.

## Locked and unlocked information

### Available while locked

Without a credential, a strict reader can structurally parse only the public
schema-1 envelope and filesystem state. This includes:

- outer format and schema;
- writer version;
- public `file_id` and outer creation time;
- cipher and KDF identifiers and parameters;
- envelope chunk size and count;
- inner-archive byte size and total encrypted size;
- password and recovery slot counts;
- the outer filename, directory, and filesystem timestamps; and
- whether the byte length is structurally consistent.

This state is not a verified Sealed File profile. Until successful
authentication, the reader does not know whether the encrypted plaintext is
a valid one-file inner archive.

Rat-Trap MUST NOT display an original basename, extension, file type,
original byte size, content hash, inner timestamp, preview, or other embedded
metadata while locked.

### Available after complete verification

Rat-Trap may describe an `.rtsf` as a verified Sealed File only after it:

1. unwraps the data key with one active credential;
2. authenticates the complete outer header, sealed metadata, and every
   content chunk;
3. verifies the outer plaintext size and SHA-256;
4. parses and verifies the complete `GMW-SOLID-2` layout and payload checksum;
5. enforces all exact profile values; and
6. validates the one regular member and its safe basename and size.

Only then MAY it show the embedded basename, extension, original byte size,
stored modification time, compression information, or a requested preview.
Embedded metadata is untrusted display text and MUST NOT be interpolated into
a shell command.

## Validation and failure behavior

The Sealed File reader fails closed for:

- an extension-only match without encrypted magic;
- unknown or changed outer family, schema, cipher, KDF, slot, parameter, or
  mandatory field;
- noncanonical, missing, duplicate, extra, wrongly typed, or out-of-range
  outer data;
- a wrong password, wrong recovery code, wrong-file recovery record, or
  revoked credential;
- header, sealed-metadata, nonce, ciphertext, authentication-tag, or inner
  byte changes;
- reordered or duplicated chunks;
- truncation at any point or any trailing data;
- a plaintext-length or SHA-256 mismatch;
- an unsupported, damaged, oversized, or resource-unsafe inner archive;
- a non-solid inner family or wrong solid profile;
- an inner metadata/payload checksum, count, or size mismatch;
- zero, multiple, linked, special, or unsafe members;
- a decompressed member that exceeds its authenticated declared size or a
  configured local resource limit;
- an unsafe restore name or existing output; and
- a source, output, recovery, or staging path collision.

Wrong credentials and damaged input MUST publish no requested plaintext
output. Verification and inspection SHOULD stream or use isolated working
storage and SHOULD avoid materializing plaintext when the requested operation
does not require it.

Authentication proves that bytes were produced by someone holding an active
credential; it does not make a hostile embedded filename, huge file, or
compressed payload safe to use. Resource limits and profile validation remain
mandatory after authentication.

## Plaintext boundary

The source being sealed is already plaintext. Building the inner archive may
also create an unencrypted, losslessly recoverable staged archive. Unlocking,
inspection that needs inner metadata, and restoration may materialize another
plaintext inner archive or the restored file.

Any such working copy MUST use a randomized, isolated directory restricted to
the current user where the operating system permits. Rat-Trap MUST attempt
cleanup on success, cancellation, and failure. Cleanup is best-effort, not
secure erasure.

The selected unseal destination is ordinary plaintext. Rat-Trap MUST obtain
explicit acknowledgement before producing it and MUST state the destination.

Windows, SSD wear levelling, crash dumps, page files, antivirus, indexing,
thumbnailers, recent-document lists, backup tools, synchronization software,
or malware may retain or observe plaintext. Python and Tk strings and keys
cannot be guaranteed to be zeroized.

Rat-Trap 5.4 does not claim secure deletion or absence of recoverable traces.

## Public leakage and threat model

The outer schema protects file content, embedded basename and extension,
inner archive metadata, original byte size, stored modification time, and
inner checksums from someone who lacks both credentials.

It does not conceal:

- the outer `.rtsf` filename or its parent directory;
- the encrypted file size and the declared inner-archive size;
- outer creation and filesystem times;
- envelope chunk count and key-slot count;
- how many `.rtsf` files exist;
- recovery-file existence and its public matching `file_id`;
- access, copy, unlock-attempt, and update patterns; or
- information deliberately placed in a user-selected friendly outer name.

Sizes may permit guesses about the original file or type. The profile does
not add padding.

The threat model and non-claims from `SECURE-ARCHIVE-FORMAT.md` continue to
apply. In particular, Sealed Files do not protect against:

- malware, a keylogger, an administrator, or another process on an unlocked
  computer;
- someone who has the password or recovery file;
- offline guessing of a weak or predictable password;
- deletion, ransomware, or replacement with a complete older valid copy;
- plaintext that existed before sealing or appears after unsealing;
- backups, caches, other hard links, or earlier copies;
- author-identity forgery by another credential holder; or
- lack of digital signing, rollback prevention, or non-repudiation.

## Windows association and accurate product language

The `.rtsf` association may make Rat-Trap the normal Windows double-click
handler. That association is convenience, not access control. A user can
change it, any program can copy or delete ciphertext, and an independent
conforming implementation can decrypt a Sealed File when given a valid
password or matching recovery key.

Rat-Trap MUST NOT claim that proprietary software is the only software capable
of decrypting the format. Accurate language is:

> Rat-Trap Sealed Files are authenticated and encrypted at rest. Without the
> password or matching recovery key, ordinary applications see only
> ciphertext. Rat-Trap provides the supported Windows unlock workflow.

Double-clicking an `.rtsf` in this beta opens Rat-Trap's locked details and
unlock workflow. It does not silently export the file or pass plaintext to
the registered application for the original extension.

## Explicit 5.4 Beta exclusions

The Sealed File profile does not provide:

- deletion, recycling, replacement, or secure erasure of the original;
- automatic opening in Word, Photoshop, or another external application;
- edit monitoring or automatic re-encryption of external-app changes;
- a mounted or projected virtual drive;
- a long-lived unlocked Private Space;
- a shared workspace master key or one recovery key for many files;
- an encrypted cross-file catalogue, search database, or calendar;
- a single encrypted folder container or system-file sealing;
- support for symlinks, junctions, reparse points, alternate data streams,
  special files, or multiple-hard-link inputs;
- atomic batch semantics;
- a durable batch journal or in-place batch resume;
- cloud synchronization, rollback protection, or ransomware protection; or
- independent security certification.

These are separate product stages. They must not be inferred from support for
individual `.rtsf` files.

## Rat-Trap 5.3 interoperability

No 5.3 cryptographic format is replaced or weakened.

A Rat-Trap 5.3 schema-1 reader can recognize, unlock, and authenticate the
outer bytes of an `.rtsf` because they are ordinary
`RAT-TRAP-ENCRYPTED-1`. After decryption it can recognize the
`GMW-SOLID-2` inner archive and restore its one member through the general
archive workflow. This is byte-format interoperability, not a promise that
the 5.3 Windows UI knows the `.rtsf` extension or enforces the 5.4 profile.

A 5.4 Sealed File reader adds the exact profile, one-member, safe-basename,
opaque-name, recovery-placement, and copy-only workflow rules in this
document. It MUST NOT infer Sealed File status merely because a 5.3 encrypted
archive happens to contain one file.

Renaming `.rtsf` to `.gmw`, or the reverse, changes no cryptographic property.
The bytes, authenticated format fields, and verified inner profile decide what
the file is.

The existing `.rtrk` recovery format remains unchanged and a 5.3 reader can
use it with the matching file ID.

Before 5.4 leaves beta, the compatibility suite MUST add:

- a deterministic public-test `.rtsf` and matching `.rtrk`;
- exact outer and inner manifests;
- password and recovery round trips in both 5.4 and the preserved 5.3 reader;
- known embedded filename/content markers absent from locked bytes;
- every validation and corruption rejection class above; and
- a frozen Windows executable test using the real Argon2id and
  AES-256-GCM-SIV implementations.
