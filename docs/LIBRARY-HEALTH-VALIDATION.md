# Library Health Check validation

Local Windows preview, 21 October 2026. Engine 5.7.0; application/installer
5.7.0.11; support `5.7.0-desktop-preview.2-library.5`.

## Automated checks

- Focused backend and Library interface suite: **78 tests passed**, 99.679
  seconds (24 health-check backend tests and 54 Library UI tests).
- Full regression discovery: **668 tests run, 667 passed and one skipped**,
  623.522 seconds, with resource warnings treated as errors. No failures.
  The native symbolic-link test reported Windows symbolic-link creation
  permission unavailable; non-native path/reparse guard tests still ran.
- Source `--library-health-self-test` passed using generated disposable data.
- Eight packaged self-tests passed: engine, UI, tutorials, Library, Store a
  folder, Library search, Library restore and Library health. All eight also
  passed after installation under the isolated QA identity.
- Build receipt verified **38 source hashes**, 58 payload files and 53 Legal
  files, with pinned Python 3.13.13 x64 and the existing 13 dependencies.
- **229 installer lifecycle checks passed**, zero failed checks and zero
  cleanup errors. Actual 5.7.0.10 to 5.7.0.11 upgrade, repair, optional
  integration, locked-file refusal and ordinary uninstall were exercised.
  Settings and generated user-file sentinels were preserved; normal app
  state was unchanged. Only the generated QA installation was removed.

## Health-specific coverage

Generated Vaults and multi-version repositories are checked without changing
their stored bytes or modification times. Checks cover every completed backup
version, file checksums, sealed-pack data and database integrity. A missing
repository cache remains missing: a RAM-only object index is used instead.

Failure fixtures cover corrupted Vault payloads, wrong file checksums despite
valid chunks, corrupt/missing packs, missing previously registered snapshots,
active sidecars, orphan pins, changed storage identities, busy repository
locks, pending recovery work, sources changing mid-check and preview limits.
Pending jobs and damaged sources are retained, not repaired or deleted.

Protected items are never inspected/decrypted; ordinary archives are not given
a payload verification result. Cancellation is tested inside both Vault and
backup verification, and before a run. An unfinished item is not marked
Verified. A mixed Library run can report healthy and failed items independently.

Receipts persist as ordinary schema-v1 timeline notes without migration.
Tests cover metadata-only cached reads, malformed receipt rejection, context
changes, receipt-write failure, and a newer failed availability check overriding
an older Verified display. UI coverage includes explicit confirmation,
selected-item scope, cancellation while busy, clearing stale green results,
receipt display and navigation to search for a deliberate restore.

The first backend run exposed test-fixture mistakes (SQLite handles left open
by a context manager, and a mutated manifest with an out-of-date inventory
hash). Those fixtures were corrected before the passing focused/full runs
above; no failures are omitted from the final qualification results.

## Evidence and limits

The sanitized lifecycle report is
[qa-results-library-health.json](../packaging/direct/qa-results-library-health.json).
Raw local evidence is retained in ignored `build/` directories, including
`health-1a15eedbe87-regression.log` and
`library-qa/ca38858cfb234cd7b91f55b09c450c90/lifecycle-report.json`.
These raw records contain local paths and are not publication-ready.
Artifact and stage-source hashes are recorded in the separate health release
manifest; previous release records remain unchanged.

The executable is an unsigned Windows x64 GUI build. This was same-host
Windows 10 build 19045 / PowerShell 7.6.5, not a clean Windows VM/Windows 11
qualification, interactive installer/SmartScreen assessment, independent
security audit, signing or Microsoft Store approval. The normal app has not
been installed/updated automatically and no remote release was published.

Results are historical observations, not continuous monitoring, a live-source
filesystem snapshot or a guarantee against same-account/administrator changes.
Repository cache, trash and original source folders are not verified. Protected
contents remain locked; ordinary archive contents are outside this stage.
A successful check is not an independent backup or a restore drill.

Only local plaintext health receipts are written; diagnostics can contain
filenames. No file contents, passwords or recovery keys are put in receipts.
No automatic repair, recovery, pruning, restore, decryption or deletion is
performed. See [LIBRARY-HEALTH.md](LIBRARY-HEALTH.md) for the exact scope,
cancellation behaviour and preview resource limits.
