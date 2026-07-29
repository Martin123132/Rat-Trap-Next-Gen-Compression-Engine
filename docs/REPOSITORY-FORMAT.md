# Rat-Trap snapshot repository format

Status: normative for the Rat-Trap 5.3 repository writer and reader.

## Purpose

The repository format stores many versioned folder captures without
putting every generation into a new monolithic archive. It is a separate
product lane from portable `.gmw` files:

- a repository is the local, deduplicated history used for recurring backups;
- a `.gmw` file is a portable archive used for sharing, moving or long-term
  standalone storage;
- any verified repository snapshot can be exported as a Balanced `.gmw`.
- an exported `.gmw` can be wrapped with the separate authenticated format
  documented in
  [`SECURE-ARCHIVE-FORMAT.md`](SECURE-ARCHIVE-FORMAT.md).

The first repository schema is local-storage focused. It is not encrypted and
is not yet a cloud synchronization protocol.

## Canonical layout

```text
repository/
  repository.json
  manifests/
    <manifest-sha256>.rtsnap.json
  packs/
    <first-two-pack-id-characters>/
      <pack-id>.rtpack
  refs/
    pins/
      <snapshot-id>.json
  locks/
    repository.lock
  staging/
    jobs/
  trash/
  catalog.sqlite3
```

Only `repository.json`, sealed packs, checksum-named manifests and pin
references define active repository state. `catalog.sqlite3` is a disposable
index. Rat-Trap validates and rebuilds it from the canonical files when it is
missing, damaged or stale.

A malformed historical manifest or pack is recorded as a catalog issue and
omitted from the disposable index. This keeps unrelated healthy snapshots
browsable and restorable. Repository information reports the issue count,
verification still fails loudly on the damaged artifact, and retention is
blocked until the damage is resolved so degraded history cannot be cleaned up
silently.

## Objects and packs

Files are divided with deterministic `fastcdc-2020-hybrid-1` content-defined
chunking. Rat-Trap 5.3 pins PyFastCDC 0.2.1, normalized chunking 1 and seed 0:

| Setting | 5.2 default |
|---|---:|
| Minimum object | 256 KiB |
| Target average | 1 MiB |
| Maximum object | 4 MiB |
| Object identity | SHA-256 of original bytes |
| Compression | Zstandard level 6, or raw when compression is not smaller |

Content-defined boundaries allow most later chunks to keep their identities
when bytes are inserted near the start of a large file. An object already
present anywhere in the repository is referenced instead of written again.
When the FastCDC gear hash reaches a maximum-size chunk whose sample contains
no more than eight distinct byte values, deterministic content markers
subdivide that exceptional low-entropy block. This avoids repeated
position-only 4 MiB boundaries on common constant or phased data. CDC improves
shift reuse; it is not a promise that every constructed byte pattern will
deduplicate at a particular percentage.

Each `.rtpack` is a sealed SQLite database with:

- one `pack_info` row containing repository identity, counts, byte totals and
  an inventory checksum;
- one `objects` row per unique new object;
- original size, codec, compressed-payload size and payload SHA-256;
- the compressed or raw payload.

Readers verify pack structure, inventory, payload checksum, decompression
length and original object SHA-256. Multiple physical copies of an object are
allowed; restore tries another valid copy if one location fails.

### Storage accounting

Rat-Trap keeps distinct figures instead of presenting compressed BLOB payload
as disk use:

- **logical bytes** are the original file content represented by a snapshot;
- **object payload bytes** are compressed/raw BLOB bytes, excluding SQLite
  and filesystem overhead;
- **pack file bytes** are the actual lengths of active `.rtpack` files;
- **repository file bytes** include packs, manifests, the rebuildable catalog,
  configuration, staging and recoverable trash;
- **trash file bytes** are the recoverable-trash portion of that repository
  total.

Snapshot completion reports both new object payload and the new pack-file
length. Retention reports physically movable whole-pack bytes separately from
logical dead object bytes trapped inside a mixed live/dead pack.

## Snapshot manifests

A snapshot manifest is canonical UTF-8 JSON. Its filename is the SHA-256 of
its canonical bytes. It records:

- a random snapshot id and creation time;
- source identity, original path and optional label;
- an advisory parent snapshot id;
- root and entry metadata;
- every file's SHA-256 and ordered object sequence;
- file, directory, logical-byte and change counts;
- new-object and reused-byte statistics.

Stored paths are relative and Windows-portable. Absolute paths, traversal,
reserved device names, trailing spaces/dots, control characters, alternate
data stream separators and Windows-invalid characters are rejected.
Symbolic links, junctions, alternate data streams, sparse files, hard links,
NTFS-compressed items and EFS-encrypted items are rejected in schema 1 rather
than followed, expanded, decrypted or otherwise changed silently.

## Atomic snapshot commit and recovery

Snapshot work is committed per file to a private staging database. After all
planned source entries have been read:

1. Rat-Trap enumerates the source again and checks the original plan.
2. New objects are streamed into a fully verified sealed pack.
3. The pack is moved into its final immutable path.
4. Every manifest object reference is resolved against the rebuildable
   catalog.
5. The checksum-named manifest is published last.

The manifest is the commit marker. A published pack without a manifest is
uncommitted data and can be recovered by the unfinished job. A published
manifest is a complete, atomically published capture. Operating-system
byte-range locking serializes repository lifecycle operations, and SQLite
transactions preserve per-file job progress.

On resume, Rat-Trap re-enumerates the source and re-hashes completed files. If
the source changed, the user must explicitly restart; the incompatible
unfinished job is moved to repository trash.

Interrupted jobs can also be listed and explicitly moved to recoverable trash
by job id even when the original source drive is no longer available. This
prevents an unreachable source from permanently blocking retention.

The source is read file by file from a live folder. Plan/stat checks catch
ordinary changes before publication, but schema 1 has no VSS integration and
does not promise a filesystem-wide point-in-time state when an application
changes multiple files while a capture is running. The atomic guarantee is
about publishing repository history, not freezing the source filesystem.

The automated gate terminates a separate process at all three durable
boundaries—after a file commit, after pack publication and after manifest
publication—and requires recovery to one fully verified snapshot.

## Restore and verification

Restore never merges into an existing directory. It writes and verifies the
whole snapshot in a sibling temporary directory, restores supported metadata,
then renames the complete directory into place.

Quick verification checks:

- repository configuration and feature compatibility;
- canonical pack and manifest structure;
- pack and manifest inventory checksums;
- catalog rebuildability;
- every snapshot-to-object reference;
- pin references.

Full verification additionally reads, checksums and decompresses every stored
object, reconstructs each file hash from its ordered objects, and detects
unreferenced objects and orphan packs.

SHA-256 checks detect accidental or deliberate modification. They are not an
authentication or encryption scheme.

## Retention

Retention supports newest, daily, weekly and monthly rules independently per
source. The newest snapshot for every source and every pinned snapshot are
always protected.

Cleanup has two explicit steps:

1. preview a deterministic plan against the current repository and receive a
   plan id;
2. apply that exact plan while holding the repository lock.

If repository or pin state changes, the plan id is rejected and a new preview
is required. Applied cleanup moves manifests and packs that are entirely
unreachable into timestamped recoverable trash. Mixed packs are retained and
reported honestly. Moving data to repository trash does not free disk space;
permanent trash expiry/compaction is intentionally a later, separately
confirmed stage.

## Current limitations

Repository schema 1 does not yet provide:

- authenticated encryption or recovery keys;
- VSS snapshots for files that another program has open;
- ACL/security-descriptor preservation;
- alternate-data-stream, sparse-file, hard-link, symbolic-link,
  NTFS-compression or EFS preservation; schema 1 rejects these inputs before
  reading file payloads;
- scheduling;
- remote/S3/SFTP/rclone storage;
- pack compaction or permanent trash expiry;
- bounded multi-pack sealing: one capture currently stages its new payloads
  and derives one pack, so peak free-space demand can approach twice the new
  payload plus SQLite/catalog overhead;
- cross-snapshot full-content indexing;
- authentication against a malicious local repository writer.

These are product stages, not hidden claims of the 5.2 format.

## CLI

```text
rat-trap repo-init REPOSITORY
rat-trap repo-info REPOSITORY
rat-trap repo-issues REPOSITORY
rat-trap repo-jobs REPOSITORY
rat-trap repo-abandon-job REPOSITORY JOB_ID --confirm-job-id JOB_ID
rat-trap repo-snapshot REPOSITORY SOURCE [--label TEXT] [--restart]
rat-trap repo-list REPOSITORY
rat-trap repo-search REPOSITORY QUERY [--limit N]
rat-trap repo-restore REPOSITORY SNAPSHOT_ID NEW_DESTINATION
rat-trap repo-verify REPOSITORY [--quick]
rat-trap repo-pin REPOSITORY SNAPSHOT_ID
rat-trap repo-unpin REPOSITORY SNAPSHOT_ID
rat-trap repo-prune REPOSITORY [retention options]
rat-trap repo-prune REPOSITORY [retention options] --apply --plan-id PLAN_ID
rat-trap repo-export REPOSITORY SNAPSHOT_ID OUTPUT.gmw
```
