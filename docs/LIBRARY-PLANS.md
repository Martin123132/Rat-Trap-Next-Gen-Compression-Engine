# Saved backup plans — manual runs

Application/installer **5.7.0.12**, support
`5.7.0-desktop-preview.2-library.6`; storage engines/formats remain 5.7.0.

## Workflow

1. Create a Library project if needed.
2. Open **Library & timeline > Backup plans**, then **New plan**.
3. Enter a name, source folder, backup folder and project. The destination
   may be new, empty or an existing versioned-backup repository.
4. Choose **Save plan** and confirm the settings/privacy notice. This saves
   metadata only: no repository or snapshot is created.
5. Select the saved plan and choose **Back up now**. Check the saved paths
   and project in its confirmation, then wait for the result.

The **Store a folder** form also offers **Save as backup plan…** in Versioned
backup mode. It copies the visible settings into the plan editor; saving and
running still require separate actions. Unsaved editor changes never affect a
run of the selected saved plan.

All plans are listed independently of the Library's project filter. Each plan
retains its explicitly chosen project. A missing/deleted project is shown and
blocks a run until the user edits the plan to choose a valid project.
If the repository is already registered to another project (or is unassigned),
use **Assign** in Stored items first; a plan never silently reassigns it.

## Results and history

Last attempt result and last successful backup are separate. A failed attempt
does not erase the last successful timestamp/snapshot. Success means that the
backup engine returned a completed snapshot, not that Library Health Check or
a restore drill has been performed.

A project timeline **Backup plan run** note records the source/destination,
result and exact completed snapshot ID when one was confirmed. Opening that
note displays text; it does not restore anything or silently select the latest
snapshot. Normal repository snapshot events are also registered.

A published backup is retained even if Library registration or result/receipt
storage fails. The UI shows its location and exact snapshot when available.
Do not run again merely to fix a catalogue entry. Use the existing Library
registration/refresh tools and inspect Backups & history first.

**Edit selected** loads a saved plan. Saving changed source/destination folder
identities or project resets the plan's displayed run history, while old
timeline receipts remain. A name-only change preserves run history.
**Remove plan…** forgets settings only: source files, repositories, Library
entries and receipts are retained. It is not secure erasure of old metadata.

## Identity and interruption safeguards

Plans pin local source-directory identity, destination-parent identity and
either the selected empty directory or an existing repository identity and
directory identity. Ordinary file edits inside the source are expected.
A missing/replaced source, changed drive/parent, substituted backup folder or
different repository is refused. A previously pinned repository is never
silently recreated. New destinations that become occupied require review.

An explicit first run may initialize the selected new/empty destination.
Initialization refuses a competing existing repository; the new repository
identity is recorded before any snapshot is written. Failure may leave an
empty repository or incomplete work, which is retained for investigation.

An OS-released lock beside the Library catalogue serializes saved-plan runs,
edits and removal across app instances. A run-start marker is recorded before
storage work. A crash or failed final result write can leave **Running / review
required**. It is not a success claim or proof that a worker is still active.
Use **Review interrupted run…** only after inspecting Backups & history.
Acknowledgement clears the metadata marker, not the stored work; an actually
active run still blocks it.

Each run performs another identity/project/pending-work check under the
repository lifecycle lock, before cache updates or recovery. Pending jobs
are refused, never resumed automatically by this workflow. Existing dedicated
Backups & history recovery tools remain explicit user choices. The normal
backup engine may update its cache during a successful new run.

These are safety checks, not a filesystem snapshot or protection against a
hostile same-account process/administrator. Close other writers. Previously
saved bytes can be lost if the storage itself fails: keep independent backups.

## Metadata, privacy and scope

Plans are bounded JSON records under namespaced `library_meta` keys in the
existing schema-v1 Library catalogue. No schema migration or archive-format
change occurs. Old application versions leave these settings alone but cannot
show/run them; old-version changes to projects/storage may require plan review.

The local catalogue, plan names, source/destination paths, identities, results
and diagnostic notes are **plaintext**. No password or recovery key is saved.
Source/repository contents are inspected only after explicit save/run actions,
not on startup, selection or refresh of the plans list. Health navigation
opens its screen without starting a check.

Versioned backup repositories are **not encrypted**. There is no scheduler,
startup task, filesystem watcher, background service, automatic retention,
source deletion, cloud sync or Codex dependency. Supported paths are ordinary
local drive paths, not network/device paths, links or reparse points.
Limits include 1,000 plans and 24,000 UTF-8 bytes per plan record, plus existing
Library inspection and storage-engine limits. Malformed records block plan
operations rather than being guessed or silently discarded.

## Build and test

Use the pinned toolchain in `LIBRARY-BUILD.md` and new output directories:

```powershell
.\scripts\build_windows_library_plans.ps1 -DestinationDirectory .\dist\library-plans-local-1
.\scripts\build_windows_library_plans_installer.ps1 -PayloadDirectory .\dist\library-plans-local-1 -DestinationDirectory .\dist\library-plans-installer-local-1
.\scripts\test_windows_library_plans_installer.ps1 -PayloadDirectory .\dist\library-plans-local-1
```

The new `--backup-plans-self-test` saves settings through the Tk worker, makes
two explicit runs, restores the older snapshot and checks receipts using only
generated disposable data. It joins the eight existing packaged self-tests.
The isolated lifecycle harness upgrades the frozen 5.7.0.11 payload to 5.7.0.12,
without updating the normal installed app. See `LIBRARY-PLANS-VALIDATION.md`
and the plans release manifest for measured results, not assumed passes.
