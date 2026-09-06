# Browse backup history

All five **Show me how…** walkthroughs are now available. This final lesson
teaches saving two versions and restoring an older snapshot without replacing
the current source. It uses the existing Backups & history workspace and the
real repository engine, not a simulated backup list.

## Try it

Let any Rat-Trap operation finish and close the app. Run the installer in the
parent workspace's `outputs/00 - START HERE` folder, then open the existing
**Rat-Trap Desktop Preview 2** Start-menu entry. Choose **Show me how…**,
**Browse backup history**, then **Start guided practice**.

The twelve steps cover the workspace, fictional source, separate repository,
first backup, sample change, second backup, reading history, choosing the older
snapshot, separate restore destination, restoration, comparison and finishing.
Only the current action is enabled; Back, Exit and harmless scrolling remain
available. The compact snapshot table shows labels and file counts during the
lesson, then returns to its original columns afterward.

Two fictional documents are created in a fresh temporary folder. The Aurora
note initially says the meeting is on Monday. The sample-change button edits
only that owned note so the current version says Thursday. The checklist is
unchanged. The first and second snapshots are both saved and verified through
the normal repository engine. The history button reads their real identifiers
and labels. Only selecting the first backup enables the older-version restore.

Restoring creates a separate, previously absent folder. A final independent
SHA-256 comparison checks four file states: the two recovered original files
and the two current source files. Thus a matching restore alone is not enough:
the current note must still be the newer Thursday version. Missing, changed,
unexpected or unsafe data prevents a successful comparison. The result explains
the difference between the recovered Monday note and the current Thursday note.

## What this does and does not mean

A snapshot is a saved point-in-time state, not an automatic backup of subsequent
changes. This lesson does not enable scheduling. The temporary repository is
unencrypted and is not a durable, independent backup. A repository is different
from a portable `.gmw` archive. This small sample demonstrates the workflow and
data reuse; it is not a compression benchmark or a prediction of savings.

For real work, restore into a separate folder first and keep independent backups
on appropriate storage. Two versions on one drive do not protect against losing
that drive. Repository history, compression and encryption are distinct features.
No archive format, encryption primitive or production backup engine was changed
for this stage.

## Preserving work and safe replay

No personal source, repository or restore destination is accepted by practice.
Ordinary file pickers, retention cleanup, pinning, exports and unrelated direct
callbacks are blocked. On exit, previous repository paths, labels, search,
retention fields, both result tables, selections, metadata mappings, nested tab,
column settings and the previous app workspace are restored.

Back revisits instructions; completed backup, sample-change and restore actions
become integrity-checked reviews instead of overwriting output or adding extra
snapshots. Load a fresh sample to repeat the actual operations. Back and Exit
wait for an active worker. Stale completion cannot advance another lesson.

The practice wrapper tracks file identities and hashes. Repository writes are
staged and published only into owned practice locations; a failed publication
does not overwrite a newly appearing unowned destination. Cleanup removes only
unchanged recorded files and empty owned directories, not whole directory trees.
Modified, replaced, linked or unexpected entries are preserved or refused.
These are conservative safety checks, not protection against a hostile process
continuously racing files under the same Windows account. A crash can leave
fictional temporary files. Ordinary cleanup is not secure erasure.

## Private release

Support label: `5.7.0-desktop-preview.2-tutorial.4`.
Numeric application/installer version: `5.7.0.6`.
Publisher: **TWO HANDS NETWORK LTD**.

The app keeps the same installation identity, filename, folder and Start-menu
entry. It remains an unsigned private preview, not a Store release or automatic
updater. No extra public portable ZIP is introduced. If Windows blocks Setup,
do not disable security protection; report the message instead.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe windows_guided_preview.py --tutorial-self-test

# Run packaging in Windows PowerShell 5.1, using fresh private destinations.
$historyBuildId = [guid]::NewGuid().ToString('N')
$historyPayload = "dist\guided-history-rebuild-$historyBuildId"
$historySetup = "dist\guided-history-installer-rebuild-$historyBuildId"
.\scripts\build_windows_guided_history.ps1 -DestinationDirectory $historyPayload
.\scripts\build_windows_guided_history_installer.ps1 -PayloadDirectory $historyPayload -DestinationDirectory $historySetup
.\scripts\test_windows_guided_history_installer.ps1 -PayloadDirectory $historyPayload
```

The installer harness checks `5.7.0.5` to `5.7.0.6` using one new isolated QA
identity, never the normal installation. Historical artifacts and source
snapshots are retained. Internal Tk geometry and workflow tests are not native
visual acceptance or clean Windows 11 certification. Actual test results and
artifact hashes are recorded separately after verification.

An initial private history build was superseded during high-DPI regression
testing and is retained only as development evidence. The final artifact paths
and hashes are in `release-manifests/guided-history.json`; users should continue
to use only the installer in `outputs/00 - START HERE`. Rebuild commands use
fresh destinations so they cannot overwrite earlier evidence.

## Verified result — 6 September 2026

All **488 discovered source tests passed**, with no failures or skips. The
final run used two concurrent, disjoint partitions: 27 history-interface tests
and the remaining 461 tests. Their recorded test identifiers cover the full
inventory exactly once. The new history coverage totals 66 tests: 27 interface
and 39 backend tests. An additional independent run confirmed all six exact
Exit/Finish restoration journeys at Tk scaling 1.333, 2.0 and 2.667.

Regression testing corrected both an unsettled test fixture and a real
high-DPI issue where a longer practice action label left hidden tables with a
wider allocation. The final app settles both restored tables before allowing
columns to stretch again. Original rows, columns, selected tabs and scroll
positions are checked, not merely the restored file contents.

All three frozen-application self-tests passed and were repeated successfully
on the isolated installed application. The final installer passed **224/224
lifecycle checks**, with no cleanup errors. All 30 recorded build inputs match
the final receipt. Seventeen prior engine/interface modules remain unchanged.
See `packaging/direct/qa-results-guided-history.json` for sanitized results and
`release-manifests/guided-history.json` for the final artifact hashes. Neither
the normal installer nor an automatic update was run on the user's app.
