# Library Health Check

Windows preview **5.7.0.11**, support
`5.7.0-desktop-preview.2-library.5`. Same Desktop Preview 2 installation identity;
no archive-format change or Library catalogue migration.

## Check stored work

1. Open **Library & timeline > Library health**.
2. Choose **Check Library…** to check all registered projects, regardless of the
   project filter. Or select a row and choose **Check selected…**.
3. Confirm the read-only data check and local plaintext receipt storage.
4. Read the separate availability and integrity columns. Select a row for details.

**Located** means the path was found, not that its contents were verified.

| Integrity result | Meaning |
| --- | --- |
| Verified | The supported stored-data checks completed successfully at the shown time. |
| Needs attention | A missing/changed item, verification error, busy repository, pending work, missing previously listed version, or preview limit prevented a pass. This does not always mean corruption. |
| Locked | The protected storage path was located. Its contents were not opened, decrypted or verified. |
| Not checked | No result yet, unsupported ordinary archive contents, or an unfinished/cancelled check. |

Dates/results are **historical observations**, never a live health guarantee.
Nothing scans on startup or when viewing the table. Recheck after changes.
The latest receipt for each item persists across restarts; older receipts remain
timeline notes. A changed location/project invalidates the cached receipt's
context. A newer unsuccessful availability refresh overrides an older Verified
result in the health view. A receipt says nothing about an independent backup.

**Cancel check** is cooperative between reads/chunks. Identity hashing and a
SQLite integrity query may need to finish before cancellation takes effect.
Only completed verifications can pass. The current run clears previous results
from its display; unfinished/unvisited items are not represented as current passes.
An older dated receipt may still appear after restarting/view refresh.

## Scope and safety

Vault checks validate database integrity, stored file bytes/chunk checksums,
file inventories and the existing structured-data catalogue checks. They do
not assert that full-text indexes or user-entered notes are semantically correct.
Before/after registered identity checks reject changed sources and active
SQLite sidecars. Immutable read-only database access avoids creating sidecars.

Backup checks hold a shared read lock on the **existing** lifecycle lock file,
validate the completed manifests, all sealed packs and referenced file checksums
across every completed snapshot. An in-memory SQLite object lookup replaces any
need to consult or rebuild the on-disk cache. File counts and logical bytes count
each snapshot's files, not unique deduplicated objects. Duplicate stored objects
are still checked in each pack. A missing previously registered snapshot is
flagged even after intentional pruning: review the history instead of assuming
corruption or silently dropping the historical expectation.

No recovery, repair, restore, pruning, decryption, source-file scan, or deletion
is performed. Pending recovery jobs and busy repositories need attention;
the health check does not complete those jobs. The repository cache and trash
are outside the verified scope. Thus verified stored data does not promise the
cache is intact or prove the interactive restore workflow has been exercised.
Use a separate restore test and independent backup before relying on stored work.

Only explicit Library receipt writes occur. Stored files' bytes/modification
times are covered by read-only regression tests. Relevant repository inventory
signatures are compared before/after verification. These measures do not provide
an operating-system snapshot or defend against a hostile same-account process
or administrator changing data while it is being checked. Close other writers.

## Results and next actions

Check dates, status, storage identity/location, counts and diagnostic text are
saved as bounded JSON in ordinary **Library health check** timeline notes.
The catalogue remains schema v1 and is unencrypted. Diagnostics can contain
filenames; no file contents, passwords or recovery keys are added. Opening a
receipt displays its result, never opens the latest backup version implicitly.
If receipt saving fails, the current result remains available with a warning;
it is not claimed to have been persisted.

- **Locate moved item…** requires the same registered storage identity.
- **Open workspace** opens the existing tools for deliberate investigation.
- **Find a file to restore** enters Library search. Selecting a version and
  confirming its new destination remain separate actions.

These buttons never silently repair, overwrite, execute or delete stored files.
Keep the whole Library directory and referenced storage backed up separately;
a catalogue reference or health receipt is not another copy of your data.

## Preview limits

At most 1,000 items per run, 50,000 relevant repository paths at depth 8,
250,000 pack object locations in total, and 2 GiB per pack. Existing Library
limits apply: 10,000 snapshots, 32 MiB per manifest and 128 MiB inspected metadata.
Pack objects are bounded by the engine's 16 MiB maximum; a Vault object exceeding
its configured chunk size plus 1 MiB compressed overhead is refused before
materialisation. Over-limit data is not marked Verified. Narrow the item scope
or use the existing dedicated verification workflow with appropriate resources.

## Build and qualification

Use the pinned local toolchain in `LIBRARY-BUILD.md` and fresh output directories:

```powershell
.\scripts\build_windows_library_health.ps1 -DestinationDirectory .\dist\library-health-local-1
.\scripts\build_windows_library_health_installer.ps1 -PayloadDirectory .\dist\library-health-local-1 -DestinationDirectory .\dist\library-health-installer-local-1
.\scripts\test_windows_library_health_installer.ps1 -PayloadDirectory .\dist\library-health-local-1
```

Eight packaged self-tests include `--library-health-self-test`, which uses
generated storage through the Tk worker, verifies read-only operation/receipts,
and checks that a damaged pack is not marked Verified. Lifecycle qualification
upgrades the frozen 5.7.0.10 payload to 5.7.0.11 under an isolated QA identity;
it does not update the normal installed app. See `LIBRARY-HEALTH-VALIDATION.md`
and the health release manifest for results. This is an unsigned local preview,
not a Store release, clean-machine certification or independent security audit.
