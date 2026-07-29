# Rat-Trap authenticated portable archive format

Status: normative for `RAT-TRAP-ENCRYPTED-1`, schema 1
Writer: Rat-Trap 5.3.0

## Scope

The encrypted family is a strict outer envelope around one complete supported
`.gmw` archive. The inner Solid, Vault, and legacy archive families are not
changed. Encrypting the whole inner file hides its filenames, paths, search
index, structured tables, file metadata, content, and checksums.

This format is for portable archives and encrypted exports from backup
history. `RAT-TRAP-REPOSITORY-1` is still checksum-protected but unencrypted.
Encrypting the canonical repository safely requires a new repository schema;
Rat-Trap does not describe the current repository as encrypted.

## Fixed security suite

Schema 1 has one supported suite. Readers reject substitutions and unsafe
parameter changes.

| Purpose | Primitive and parameters |
|---|---|
| Content and key wrapping | AES-256-GCM-SIV, 32-byte key, 12-byte random nonce, 16-byte tag |
| Password derivation | Argon2id v1.3, 64 MiB, 3 iterations, 4 lanes, 16-byte random salt, 32-byte output |
| Recovery-key derivation | HKDF-SHA256, 32-byte random salt and fixed Rat-Trap domain string |
| Plaintext identity | SHA-256, stored only inside sealed metadata |
| Random material | operating-system CSPRNG |

New passwords and passphrases must contain at least 15 Unicode characters.
Rat-Trap normalizes them to NFC, encodes them as UTF-8, does not trim or
case-fold them, and accepts spaces and pasted text. The encoded maximum is
4,096 bytes.

## File layout

```text
18 bytes  b"RAT-TRAP-SECURE-1\x00"
4 bytes   unsigned little-endian canonical-header length
N bytes   canonical UTF-8 JSON security header
repeated chunks:
  12 bytes  random nonce
  P bytes   ciphertext, where P is this chunk's plaintext length
  16 bytes  authentication tag
```

The normal plaintext chunk size is 4 MiB. Readers accept only 64 KiB through
16 MiB and calculate the required chunk count from the declared plaintext
size. A zero-byte input has zero content chunks; its exact size, empty SHA-256
and complete header remain authenticated.

The public header has exactly these fields:

```text
format, schema_version, writer_version, file_id, created_at_ns,
cipher, chunk_size, chunk_count, plaintext_size,
sealed_metadata, key_slots, header_auth
```

It is canonical JSON: keys are sorted, whitespace is absent, NaN is forbidden,
and UTF-8 is used. The maximum header is 256 KiB. Unknown, duplicate, missing,
noncanonical, or out-of-range values fail closed before password derivation or
large allocation.

### Canonical encodings

This document uses `CJ(value)` for the exact UTF-8 bytes produced by:

```python
json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

Schema-1 protocol keys and generated values are ASCII, so an independent
implementation does not need locale-sensitive sorting. JSON booleans are not
integers. Duplicate keys, non-finite numbers, malformed Unicode, extra keys,
and any byte representation that differs from `CJ(parsed_value)` are invalid.

`B64(value)` is canonical RFC 4648 standard Base64 with the normal `=`
padding, no whitespace, and no alternate alphabet. Binary fields in the JSON
header use `B64`. Hexadecimal identifiers and digests use lowercase ASCII
without a prefix.

AES-256-GCM-SIV notation below follows the AEAD interface:

```text
ciphertext_and_tag = Encrypt(key, nonce, plaintext, associated_data)
plaintext          = Decrypt(key, nonce, ciphertext_and_tag, associated_data)
```

The returned 16-byte tag is appended to the ciphertext. Nonces are stored
separately. Every schema-1 nonce is 12 fresh CSPRNG bytes.

### Exact public-header shape and types

The conceptual shape below is shown in logical order; the bytes on disk use
`CJ`, which sorts every object's keys:

```json
{
  "format": "RAT-TRAP-ENCRYPTED-1",
  "schema_version": 1,
  "writer_version": "5.3.0",
  "file_id": "32 lowercase hexadecimal characters",
  "created_at_ns": 1,
  "cipher": "AES-256-GCM-SIV",
  "chunk_size": 4194304,
  "chunk_count": 0,
  "plaintext_size": 0,
  "sealed_metadata": {
    "cipher": "AES-256-GCM-SIV",
    "nonce": "B64(12 bytes)",
    "ciphertext": "B64(ciphertext || 16-byte tag)"
  },
  "key_slots": [
    {
      "slot_id": "32 lowercase hexadecimal characters",
      "type": "password",
      "kdf": {
        "name": "argon2id-rfc9106-low-memory",
        "salt": "B64(16 bytes)",
        "length": 32,
        "memory_kib": 65536,
        "iterations": 3,
        "lanes": 4
      },
      "wrap": {
        "cipher": "AES-256-GCM-SIV",
        "nonce": "B64(12 bytes)",
        "ciphertext": "B64(32-byte data key ciphertext || 16-byte tag)"
      }
    },
    {
      "slot_id": "32 lowercase hexadecimal characters",
      "type": "recovery",
      "kdf": {
        "name": "hkdf-sha256",
        "salt": "B64(32 bytes)",
        "length": 32,
        "info": "rat-trap-recovery-slot-v1"
      },
      "wrap": {
        "cipher": "AES-256-GCM-SIV",
        "nonce": "B64(12 bytes)",
        "ciphertext": "B64(32-byte data key ciphertext || 16-byte tag)"
      }
    }
  ],
  "header_auth": {
    "cipher": "AES-256-GCM-SIV",
    "nonce": "B64(12 bytes)",
    "ciphertext": "B64(16-byte tag for an empty plaintext)"
  }
}
```

Objects at every level have exactly the displayed keys. `key_slots` has
exactly two objects: one `password` and one `recovery`, in either order, with
different `slot_id` values. The writer generates `file_id` and both slot IDs
as random UUID-v4 values with hyphens removed. Readers depend only on the
32-character lowercase-hex rule.

`schema_version`, `created_at_ns`, `chunk_size`, `chunk_count`, and
`plaintext_size` are JSON integers, not booleans or floating-point values.
`schema_version` is exactly 1; `created_at_ns` is 1 through 2^63 - 1;
`chunk_size` is 64 KiB through 16 MiB inclusive; `plaintext_size` is 0 through
2^63 - 1; and `chunk_count` is 0 through 2^32 - 1 and exactly:

```text
0                                      when plaintext_size == 0
ceil(plaintext_size / chunk_size)      otherwise
```

`writer_version` is a JSON string and is informational for format dispatch.
Schema-1 writers use `5.3.0`; readers do not use it to select cryptography,
but they must use the exact parsed string when calculating the cryptographic
data context below. The decoded `sealed_metadata.ciphertext` is exactly 141
bytes: 125 bytes of canonical sealed plaintext plus the 16-byte tag.

### Domain strings and data context

All strings in this table are exact ASCII bytes. `\x00` is one zero byte.
There is no implicit separator or terminating zero beyond the one shown.

| Name | Exact bytes |
|---|---|
| `DATA_CONTEXT_PREFIX` | `b"Rat-Trap secure data context v1\x00"` |
| `METADATA_AAD_PREFIX` | `b"Rat-Trap sealed metadata v1\x00"` |
| `SLOT_AAD_PREFIX` | `b"Rat-Trap key slot v1\x00"` |
| `HEADER_AAD_PREFIX` | `b"Rat-Trap secure header v1\x00"` |
| `CHUNK_AAD_PREFIX` | `b"Rat-Trap secure chunk v1\x00"` |
| `PASSWORD_AD_PREFIX` | `b"Rat-Trap password KDF v1\x00"` |
| `RECOVERY_CHECKSUM_PREFIX` | `b"Rat-Trap recovery key v1\x00"` |
| `RECOVERY_HKDF_INFO` | `b"rat-trap-recovery-slot-v1"` |

The base descriptor is an object with exactly these fields copied from the
header:

```json
{
  "format": "RAT-TRAP-ENCRYPTED-1",
  "schema_version": 1,
  "writer_version": "5.3.0",
  "file_id": "32 lowercase hexadecimal characters",
  "created_at_ns": 1,
  "cipher": "AES-256-GCM-SIV",
  "chunk_size": 4194304,
  "chunk_count": 0,
  "plaintext_size": 0
}
```

The 32-byte data context is:

```text
DC = SHA256(DATA_CONTEXT_PREFIX || CJ(base_descriptor))
```

This context binds every slot, sealed-metadata record, and data chunk to the
archive's public identity and declared sizes.

### Password key slot

Normalize the supplied password to Unicode NFC and encode it as UTF-8 without
trimming or case folding. For new archives it must have at least 15 Python
Unicode code points after NFC normalization (not 15 grapheme clusters or
UTF-16 code units). Invalid Unicode scalar text is refused. Readers accept an
existing non-empty password up to 4,096 UTF-8 bytes so a future policy change
cannot make an old archive unreadable.

Derive the 32-byte password key-encryption key with Argon2id version 1.3:

```text
password     = normalized UTF-8 bytes
salt         = decoded 16-byte kdf.salt
length       = 32 bytes
iterations   = 3
lanes        = 4
memory_cost  = 65536 KiB
associated_data =
    PASSWORD_AD_PREFIX || HEX_DECODE(header.file_id)
secret       = absent
```

The associated data is the 16 raw bytes represented by `file_id`, not its
32 ASCII hex bytes.

### Recovery key slot

Creation generates an independent random 32-byte recovery secret. Derive its
32-byte key-encryption key with HKDF-SHA256:

```text
input_key_material = recovery secret
salt               = decoded 32-byte kdf.salt
info               = RECOVERY_HKDF_INFO
output_length      = 32 bytes
```

For either slot, form the slot descriptor using exactly:

```json
{"slot_id": "...", "type": "...", "kdf": {"...": "..."}}
```

The `kdf` value is the complete exact password or recovery object shown in the
header shape. The `wrap` object is not part of the descriptor. Then:

```text
slot_AAD = SLOT_AAD_PREFIX || DC || CJ(slot_descriptor)
wrapped_data_key =
    Encrypt(key_encryption_key, wrap_nonce, 32-byte data_key, slot_AAD)
```

`wrap.ciphertext` is therefore exactly 48 decoded bytes.

### Sealed metadata and header authentication

The sealed plaintext is exactly:

```json
{
  "format": "RAT-TRAP-SEALED-METADATA-1",
  "plaintext_sha256": "64 lowercase hexadecimal characters"
}
```

`plaintext_sha256` is SHA-256 over the complete inner `.gmw` bytes.

```text
sealed_metadata.ciphertext =
    Encrypt(
        data_key,
        sealed_metadata.nonce,
        CJ(sealed_plaintext),
        METADATA_AAD_PREFIX || DC
    )
```

Let `header_without_auth` be the complete exact header object, including
`sealed_metadata` and `key_slots`, with only `header_auth` omitted:

```text
header_auth.ciphertext =
    Encrypt(
        data_key,
        header_auth.nonce,
        empty byte string,
        HEADER_AAD_PREFIX || CJ(header_without_auth)
    )
```

The decoded header-authentication ciphertext is exactly the 16-byte tag.

### Content chunks and complete verification

Chunk indices start at zero. The expected plaintext length is `chunk_size`
except for the final chunk, which is the remaining declared length. For each
chunk:

```text
chunk_AAD =
    CHUNK_AAD_PREFIX ||
    DC ||
    UINT64_LE(chunk_index) ||
    UINT64_LE(chunk_plaintext_length)

chunk_ciphertext_and_tag =
    Encrypt(data_key, chunk_nonce, chunk_plaintext, chunk_AAD)
```

The on-disk chunk is the 12-byte nonce followed by the ciphertext and its
16-byte tag. No per-chunk length field is stored; lengths are derived from the
public header. The reader calculates the exact expected outer length:

```text
18 + 4 + header_length +
plaintext_size + chunk_count * (12 + 16)
```

and rejects both truncation and trailing bytes. It authenticates a chunk
before writing that chunk's plaintext, then requires the complete plaintext
length and SHA-256 from sealed metadata to match before publishing any
requested decrypted file.

## Password and recovery slots

Creation generates one random 32-byte data key. Exactly two independently
usable slots wrap it:

- A password slot derives its wrapping key with the fixed Argon2id profile.
- A recovery slot derives its wrapping key from a separate random 32-byte
  recovery secret with HKDF-SHA256.

The recovery secret is not calculated from the password. Either credential can
unlock the same archive. Anyone with either credential can read it.

The human-readable recovery code is derived exactly as follows:

```text
checksum = SHA256(RECOVERY_CHECKSUM_PREFIX || 32-byte recovery_secret)[0:4]
payload  = recovery_secret || checksum
encoded  = RFC4648_BASE32(payload), uppercase, with all "=" padding removed
code     = "RTRK1-" || encoded split left-to-right into 4-character
           hyphen-separated groups (the final group may be shorter)
```

A reader uppercases the supplied text, removes only hyphens, ASCII space, tab,
carriage return, and line feed, requires the compact value to begin `RTRK1`,
reconstructs Base32 padding, and requires a decoded length of 36 bytes and the
four-byte checksum above. The checksum detects transcription mistakes; it is
not an authentication substitute. Successful slot decryption is the
cryptographic validity check.

That lenient normalization applies to a recovery code entered by a person.
The canonical code emitted by the writer is uppercase, unpadded, and grouped
exactly as described above. Inside a `.rtrk` file the code must be in that
canonical writer form; a reader decodes it and requires re-encoding to produce
the exact stored string.

The `.rtrk` recovery file is at most 16 KiB and contains this exact object:

```json
{
  "format": "RAT-TRAP-RECOVERY-KEY-1",
  "schema_version": 1,
  "file_id": "32 lowercase hexadecimal characters",
  "created_at_ns": 1,
  "recovery_key": "RTRK1-..."
}
```

It has exactly those keys. `schema_version` and `created_at_ns` are JSON
integers, not booleans or floats; the former is exactly 1 and the latter is
1 through 2^63 - 1. The content is `CJ(object)` with either no suffix or one
final LF byte. The 5.3 writer emits one final LF. When used for an archive,
`file_id` must exactly match the archive header before slot decryption.

Recovery files are created exclusively and verified by reading them back.
Rat-Trap never overwrites an existing `.rtrk` file. Keep recovery files
separate from the archive and from the computer or storage account the archive
protects.

Password and recovery rotation authenticate the old archive, create and
authenticate a replacement slot, verify the staged replacement with the new
credential, then write and verify a complete staged archive whose bulk
ciphertext tail is copied byte-for-byte. Only then does Rat-Trap atomically
replace the archive file; the bulk ciphertext is not re-encrypted. Credential
updates hold an operating-system lock for the archive transaction and compare
the current authenticated header immediately before replacement. A
simultaneous update is refused instead of silently
undoing a completed password or recovery change.

## Deterministic interoperability vector

The source tree includes a deterministic public-test-credential schema-1
archive and complete vector:

```text
tests/fixtures/formats/rat-trap-encrypted-1-5.3.gmw
tests/fixtures/formats/rat-trap-encrypted-1-5.3.rtrk
tests/fixtures/formats/rat-trap-encrypted-1-5.3-vector.json
```

The vector records the inner bytes and hash, decomposed and NFC password
forms, recovery code, data/recovery keys, file and slot IDs, timestamp, salts,
every nonce, derived KEKs, every canonical JSON value, data context, every AAD
value, stored ciphertext, final sizes, and SHA-256 values. The generator
produced the three files twice with identical bytes.

All credentials in that fixture are public and are only for implementation
tests. They provide no secrecy and must never be copied into a private
archive.

## Dispatch and publication

Readers check the encrypted magic before any inner archive detector. They
authenticate and decrypt the entire outer file into a private working path
before passing it to the existing strict inner-family dispatcher. Wrong
credentials, tampering, truncation, or an unknown suite must not publish a
plaintext `.gmw`, ZIP, or extracted destination.

Creation and decryption use same-directory staging plus flush/fsync and atomic
publication where the operating system supports it. A recovery file may
remain as an intentional orphan if archive publication fails after that key
was safely written; deleting uncertain recovery material would be worse.

## Threat model and disclosed leakage

The format protects confidentiality and authenticity against someone who can
copy, read, modify, reorder, append to, or truncate stored archive bytes. The
memory-hard password KDF raises the cost of offline guessing, but it cannot
make a weak password strong.

It does not protect against:

- malware, a keylogger, an administrator, or another process on an unlocked
  computer;
- someone who has the password or recovery file;
- archive deletion or replacement with a complete older valid copy;
- information exposed before encryption or after extraction;
- the outer filename, encrypted file size, declared plaintext archive size,
  chunk count, creation time, access pattern, or key-slot count;
- author identity, signing, or non-repudiation.

Python and Tk strings cannot be guaranteed to be zeroized in process memory.

## Plaintext working-copy boundary

Rat-Trap 5.3 first creates the normal inner `.gmw`, then encrypts it. Unlocking
for inner inspection, Vault search/query, extraction, or ZIP conversion
materializes an isolated plaintext temporary inner archive. It is removed on
a best-effort basis when the operation finishes.

Encrypted portable exports from backup history restore their source tree in
operating-system temporary storage only after explicit acknowledgement. The
destination directory may contain a temporary portable-archive filename, but
that staged file is already encrypted.

Windows, SSD wear levelling, crash dumps, antivirus, indexing, backup
software, or malware may retain traces. Rat-Trap 5.3 does not claim secure
deletion. Command-line automation must explicitly acknowledge this boundary;
the Windows app presents it before the relevant operation.

## Cryptographic references

- RFC 8452, AES-GCM-SIV: <https://www.rfc-editor.org/rfc/rfc8452.html>
- RFC 9106, Argon2id: <https://www.rfc-editor.org/rfc/rfc9106.html>
- pyca/cryptography AEAD API:
  <https://cryptography.io/en/stable/hazmat/primitives/aead/>
- pyca/cryptography Argon2id API:
  <https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/>
