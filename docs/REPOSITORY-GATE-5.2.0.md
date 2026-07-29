# Rat-Trap 5.2.0 repository gate

## Release purpose

Rat-Trap 5.2.0 adds the first recurring-backup foundation without replacing
the existing portable archive and Queryable Vault formats.

The new lane consists of:

- immutable sealed object packs;
- SHA-256-named atomic snapshot manifests;
- repository-wide content-defined deduplication;
- resumable per-file snapshot jobs;
- snapshot and path history;
- transactional verified restore;
- quick and full integrity checks;
- pinned snapshots;
- previewed newest/daily/weekly/monthly retention;
- recoverable cleanup trash;
- portable `.gmw` export from any verified snapshot;
- a Windows “Backups & history” workflow and equivalent CLI.

## Compatibility boundary

Version 5.2.0 does not change any supported `.gmw` family or schema. The
existing golden fixtures remain the compatibility gate for:

- `GMW-SQLITE-1`;
- `GMW-SOLID-2`;
- `GMW-VAULT-1` schema 1;
- `GMW-VAULT-1` schema 2.

Snapshot repositories use their own `RAT-TRAP-REPOSITORY-1`,
`RAT-TRAP-PACK-1` and `RAT-TRAP-SNAPSHOT-1` families. They must not be
dispatched through the `.gmw` archive reader.

## Required automated checks

The release candidate must pass:

1. every preserved archive compatibility and corruption test;
2. repository initialization and idempotence;
3. exact historical restore across changed, added and deleted files;
4. duplicate-file, shifted-data and adversarial low-entropy deduplication;
5. quick and full verification;
6. disposable catalog rebuild;
7. payload-corruption detection before restore;
8. malformed or missing historical-artifact isolation without hiding damage;
9. integrity-issue inspection and retention refusal while damage is unresolved;
10. safe-path and existing-destination refusal;
11. symbolic-link, junction, alternate-data-stream, sparse-file, hard-link,
    NTFS-compression and EFS refusal before payload capture;
12. pin-aware retention preview with separate logical and physical accounting;
13. stale-plan refusal and recoverable prune;
14. interrupted-job inspection and exact-id recoverable abandonment;
15. portable `.gmw` export and round trip;
16. concurrent initialization without repository-identity replacement;
17. real child-process termination and recovery after:
    - a committed file;
    - a published pack;
    - a published manifest;
18. CLI JSON workflows, exact-id confirmation and dry-run cleanup default;
19. packaged GUI self-test with six tabs;
20. packaged PyFastCDC 0.2.1 Cython accelerator check;
21. packaged repository snapshot, full verification and restore;
22. packaged full-folder round trips for every portable profile and the
    repository engine.

## Integrity interpretation

“Verified” in the 5.2 interface means Rat-Trap checked the checksums and
structural rules described in
[`REPOSITORY-FORMAT.md`](REPOSITORY-FORMAT.md). It does not mean:

- encrypted;
- authenticated to a particular owner;
- protected from an attacker who can replace both data and checksums;
- backed up off-site;
- restorable while applications continue mutating open files.

Those boundaries remain visible in the application and technical material.

## Retention interpretation

Retention preview reports:

- logical history selected for removal;
- whole packs eligible to move into recoverable trash;
- dead objects that remain inside mixed live packs.

The 5.2 apply action moves eligible files to repository trash. It does not
claim disk space has been freed. Permanent trash expiry and mixed-pack
compaction require a later explicit design and safety gate.

## Release evidence to record

The final release manifest must record:

- source commit and tag;
- Python, PyInstaller and dependency versions;
- test count and pass result;
- packaged self-test result;
- beta-folder digest round-trip result;
- executable and ZIP byte sizes and SHA-256 values;
- Authenticode status;
- known limitations above.
