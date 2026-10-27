# Saved backup plans validation

Local Windows preview, 21 October 2026. Engine 5.7.0; application/installer
5.7.0.12; support `5.7.0-desktop-preview.2-library.6`.

## Automated checks

- Focused manual-plan backend and interface suite: **36 tests passed** in
  33.602 seconds (29 backend and seven Library UI tests).
- Full regression discovery: **704 tests run, 703 passed and one skipped**
  in 622.165 seconds, with resource warnings treated as errors. No failures.
  The native symbolic-link test reported Windows symbolic-link creation
  permission unavailable; non-native path/reparse guards still ran.
- Source `--backup-plans-self-test` passed on generated disposable data.
- **Nine packaged self-test modes passed**: engine, UI, tutorials, Library,
  Store a folder, Library search, Library restore, Library health and saved
  backup plans. All nine also passed after isolated QA installation.
- Build receipt verified **39 source hashes**, 58 payload files and 53 Legal
  files, using pinned Python 3.13.13 x64 and the existing 13 dependencies.
- **230 installer lifecycle checks passed**, zero failed checks and zero
  cleanup errors. The harness exercised an actual 5.7.0.11-to-5.7.0.12 upgrade,
  repair, optional integration, locked-file refusal and ordinary uninstall.
  Generated user-file sentinels/settings were preserved; normal app state
  was unchanged. Only the generated QA installation was removed.

## Plan-specific coverage

Generated source folders and repositories cover saving settings without
creating storage, reopening metadata without inspecting source files, explicit
first initialization, existing repository settings, two manual runs and
byte-for-byte restoration of the older version without changing current files.

Failure tests cover missing/replaced sources, missing/substituted repositories,
changed destination parent identity, an occupied planned destination, replaced
empty destinations, changed/deleted projects, stale edits, duplicates, malformed
records, plan limits, initial identity-record failure and detached progress
listeners. Missing pinned repositories are never silently recreated.

Pending jobs are preserved, not recovered. The engine preflight runs inside the
repository lifecycle lock before cache/recovery actions; tests inject pending
work or project reassignment at that boundary and confirm no version is created.
OS locking blocks concurrent plan operations. Interrupted markers require
explicit acknowledgement; acknowledgement alone never creates a version.
Removing a plan retains its source, backups, Library entries and receipts.

Successful publication followed by catalogue/receipt failure remains visibly
different from an unconfirmed backup. The saved snapshot is returned; failed
final metadata storage leaves a review-required marker, not a fabricated
success. Failed later attempts preserve the previous successful snapshot/date.

UI tests cover confirmation cancellation, saved settings taking precedence
over unsaved editor fields, explicit edit/removal, result/receipt errors,
interruption acknowledgement, metadata-only listing, health navigation and
busy/tutorial guards. The initial 61-test interface run found one oversized
button at Tk scaling 2.667. Its label was shortened; the dedicated high-DPI
rerun passed (6.806 seconds), and the final full regression includes the fixed
test passing at all three tested scaling values.

## Evidence and limits

Sanitized installer evidence:
[qa-results-library-plans.json](../packaging/direct/qa-results-library-plans.json).
Raw local evidence remains in ignored `build/` directories:
`plans-1a15fe5adce-regression.log`, `plans-1a15fe5adce-focused.log` and
`library-qa/e04ab376227240aead6413d2e6d17024/lifecycle-report.json`.
Raw records contain local paths and are not publication-ready. The plans
release manifest records relative stage-source and artifact hashes; previous
release records/payloads remain unchanged.

This is an unsigned Windows x64 local preview, qualified on the same Windows
10 build 19045 host with PowerShell 7.6.5. It is not a clean-VM/Windows 11 test,
interactive installer/SmartScreen assessment, independent security audit,
signing or Microsoft Store approval. The normal app was not automatically
installed/updated and no remote release was published.

No scheduler, watcher, startup task, automatic retention/deletion, saved
credentials, cloud sync or encryption of live backup repositories was added.
Plans/results are plaintext local metadata. A successful backup is not a full
Library health check, restore drill or independent copy on another device.
Close other writers; no live-filesystem snapshot, secure metadata erasure or
hostile same-account/administrator guarantee is claimed.
See [LIBRARY-PLANS.md](LIBRARY-PLANS.md) for workflow and exact safety boundaries.
