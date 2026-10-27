# Store a folder in Library

Application **5.7.0.8**, support **5.7.0-desktop-preview.2-library.2**.
The 5.7.0 compression, encryption and backup formats remain unchanged.

## Workflow

1. Open **Library & timeline** and create or select a project.
2. Choose **Store a folder**, then **One-off archive** or **Versioned backup**.
3. Choose a source folder and a destination outside that folder.
4. For an archive, choose Fast/Balanced/Smallest and optionally encryption.
   For backups, choose a new/empty directory or an existing repository, and
   optionally label the new version. Existing repository settings are retained.
5. Click **Store folder**. A completed output is added to the captured project,
   even if the user changes the visible project filter while the worker runs.
6. Open the item or an exact timeline snapshot using the established tools.
   Restoring remains a separate explicit operation.

**Save another version** on a project-owned repository preselects its location
but deliberately asks for the source again: repositories can hold more than
one source. Repeated saves within the form retain the user's chosen paths.
No background scheduling, automatic retention, calendar bridge or Codex
dependency is introduced. Ordinary archive creation elsewhere in the app
still does not implicitly add items to Library.

## Safety and privacy

- Originals are retained. Archive destinations must be new `.gmw` files;
  same-volume publication refuses to replace a file even if it appears during
  compression. Existing Library items and projects are never silently reassigned.
- Backup/source trees may not overlap. The catalogue must be outside the source
  and backup trees. Outputs and recovery keys cannot be placed inside its folder.
- Shared engine source checks reject unsupported links, reparse points, alternate
  data streams and Windows-name collisions before creating a destination.
- Archives use a private staging directory. Source filesystem metadata is checked
  before/after compression; detected changes refuse publication. This is **not**
  a live filesystem snapshot or proof against concurrent edits that evade metadata
  checks. Close editing applications and verify restored contents.
- Archive encryption reuses the existing password/recovery-key consent flow,
  including its plaintext-temporary warning. Passwords and keys are not recorded
  in the catalogue. Library labels, paths, notes and timestamps remain plaintext.
- Live backup repositories are **not encrypted**. The form disables archive
  encryption controls in backup mode and makes this limitation visible.
- A successful save is not a claim that a full restore test has run. Library
  registration checks identity and manifests; use the existing integrity/restore
  tools. Keep independent backups during this unsigned preview.

## Separate save and catalogue outcomes

Storage publication and the Library database cannot be a single transaction.
Only a completed storage result reaches catalogue registration. The expected
file/repository identity and exact snapshot ID are checked again before the
catalogue transaction commits. Existing snapshot events remain idempotent.

If publication succeeds but catalogue registration fails, the output is kept
and the UI reports **Files saved, but Library could not be updated**, including
the path and exact snapshot ID. Add the existing output, or refresh its existing
Library entry; do not repeat the save just to repair the listing.

If a backup fails, its engine-managed incomplete work is kept for the existing
Backups & history recovery tools. No automatic restart, prune or source deletion
occurs. An encrypted attempt can leave a recovery-key file even when its final
archive was not published; check the result before deciding whether to keep it.
When a backup resumes, the success message says it may reflect the earlier
job's source state. Check that version and save again for any later edits;
recovery is not presented as a newly captured current version.

## Build

Use the same pinned toolchain described in `LIBRARY-BUILD.md`, with the new
`scripts/build_windows_library_store.ps1` and
`scripts/build_windows_library_store_installer.ps1`. They produce application
5.7.0.8 and retain the existing installation identity. Old recipes/artifacts and
their release evidence are retained. Use fresh immediate children of `dist`.

`scripts/test_windows_library_store_installer.ps1` tests the actual recorded
5.7.0.7 Library payload upgrading to 5.7.0.8 under an isolated QA identity;
it must not install/uninstall the normal application. The packaged
`--store-folder-self-test` adds generated archive and two-snapshot restore tests.
See the separate Store-folder validation report for executed checks, not promises.
