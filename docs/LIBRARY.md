# Rat-Trap Library and project timeline

The original Library preview below is followed by the **5.7.0.8 Store a folder
update**; see [the new workflow](LIBRARY-STORE.md). Existing registration and
timeline behaviour remains available.

The Library preview adds an organiser to the existing Windows application.
It does not replace your archive formats, change compression settings, or
move your stored files. Engine version: **5.7.0**. Application version:
**5.7.0.7**, support label **5.7.0-desktop-preview.2-library.1**.

## Start with one project

1. Open **Library & timeline** from the sidebar or **Open your Library** on Home.
2. Choose **New project**, enter a name, and leave that project selected.
3. Choose **Add archive / protected file** for an existing `.gmw`, `.db`
   Vault or `.rtsf` Sealed File. For existing snapshot storage, use
   **Add backup repository** and select its repository folder.
4. Select the item to see its saved location and last check. **Open workspace**
   takes you to the existing archive, Vault, protection or backup tools.
   It does not decrypt, execute or restore a file automatically.
5. Write a dated note about what you did. The target label says whether the
   note belongs to the selected item or project. **Note for project** clears
   the item selection. Choose **Project timeline** to see your history.

Registration may take time for large files: Rat-Trap reads the outer file
bytes to record a SHA-256 identity. Protected files stay locked and their
contents are not indexed. Registration is not a full integrity check or
restore test. Keep using the existing Verify and restore tools.

## Projects and timeline

An item belongs to at most one project. Select it and use **Assign** to change
that grouping. Project names can be changed without changing their stable
IDs. Removing a project unassigns its items; it does not delete files. Its
notes remain in the overall timeline.

Timeline dates have distinct meanings, shown in the event details:

- **Library registration:** when you added the reference, not when its files
  were created or backed up.
- **Repository manifest:** a snapshot's recorded time. Each event retains its
  exact snapshot ID. An ordinary archive is not inferred to contain versions.
- **User-entered date:** the date you assigned to your note, not a verified
  record of work or a scheduled calendar event.

Open a snapshot event to select that exact version in **Backups & history**.
Restore is still a separate, explicit action. If that snapshot has gone,
Rat-Trap refuses to silently substitute the latest version. The Library's
backup view reads manifest metadata without recovering jobs, rebuilding the
repository catalogue, or calculating payload totals. Existing backup actions
such as Refresh, Verify, Pin and Restore keep their normal engine behaviour.

The project filter applies to the stored items and timeline. Find searches
catalogue labels and locations, not file contents. Use **Search Vault** for
indexed text and **Data Tables** for the existing queryable-data features.
The timeline is limited to the newest 500 matching events in this preview.

## Missing or moved storage

Startup and filtering use saved catalogue metadata only: no source scanning
or automatic refresh. **Refresh selected** checks the current source and adds
new repository snapshot events without duplicating known ones. Status is a
last-check result, not a live availability or full integrity guarantee.

If you move a file, use **Locate moved item**. Rat-Trap accepts only the same
outer file bytes or the same repository identity. A modified archive should
be added as a separate item at a separate location. Missing records and their
notes remain until you explicitly remove them.

**Remove from Library** removes the reference and that item's Library notes
and timeline records only. The actual archive or repository is untouched.
This catalogue is not a backup, synchronisation service, or automatic recorder.

## Privacy, limits and backup

The catalogue is **unencrypted local metadata**, including file locations,
labels, project names, notes, snapshot labels and timestamps. Encrypting an
archive does not encrypt its Library entry. Never enter passwords, recovery
keys or other secrets in notes. `.rtrk` recovery keys cannot be registered.
Protected inner filenames and contents are not stored in the catalogue.

The default location is:

```text
%LOCALAPPDATA%\Two Hands Network Ltd\Rat-Trap\Library\library.sqlite3
```

The catalogue is created only on the first intentional change. Uninstall
preserves it. To keep a catalogue backup, close Rat-Trap and copy the whole
Library directory to trusted storage. This saves the organiser metadata,
not the referenced files: back up those separately. Do not send a personal
catalogue in a support request.

This preview accepts ordinary local-drive paths, not network-share paths,
symbolic links, junctions or other reparse points. A writer's SQLite
sidecars cause registration to refuse until the writer is closed. Repository
inspection is bounded to 10,000 snapshots, 32 MiB per manifest and 128 MiB of
total inspected metadata. Repository disk usage is not calculated. Nothing
is uploaded by this feature; a selected local cloud-sync directory still
follows that service's own behaviour.

Calendar integration, an external integration API, scheduling and automatic
capture are not implemented in this stage. The five existing guided lessons
remain available; a dedicated Library lesson is a possible later addition.
Use copies for preview testing and retain originals and an independent backup.
