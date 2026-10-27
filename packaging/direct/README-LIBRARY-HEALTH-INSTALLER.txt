RAT-TRAP LIBRARY HEALTH CHECK UPDATE
Application version: 5.7.0.11
Support label: 5.7.0-desktop-preview.2-library.5
Publisher: TWO HANDS NETWORK LTD

1. Close Rat-Trap when its current operation has finished.
2. Run the supplied setup executable for your Windows account.
3. Open Rat-Trap Desktop Preview 2 from Start.
4. Open Library & timeline > Library health.
5. Choose Check Library (all projects), or select an item and Check selected.

This updates the same installed application; it does not create a second app.
Your Library and stored files are retained. Setup does not set default file
associations. Its optional Open with integration and desktop shortcut remain
your choices. Recovery keys are not registered as openable archives.

One-off archives can be encrypted with a password and independent recovery
key. Versioned backup repositories are NOT encrypted. Original files are kept.
Read README-PORTABLE.txt for the workflow, privacy, failure recovery and limits.

Use copies for your first test. Save outside the source, restore into a new
folder, compare the files and retain an independent backup. A Library entry
is not a second backup; the catalogue itself is unencrypted local metadata.
Never enter passwords or recovery keys in notes.

This is an unsigned local preview, not a Microsoft Store release. No Python,
Codex or Rat-Trap account is needed. If Windows, antivirus or company policy
blocks it, do not disable security protections; ask your administrator/support.
No automatic updater, telemetry service or cloud upload is added.
Nothing in this release claims a clean-machine test, security audit, signing
or Microsoft approval. The installer is per-user and uses the existing app
identity. Uninstall preserves your catalogue and independently stored work.

For support: ollett123123@outlook.com. Quote the support label above.
See SUPPORT.md, PRIVACY.md, Legal/LICENSE.md and Legal/COMMERCIAL-LICENSE.md.
Do not submit passwords, keys, private archives or a personal catalogue.

LIBRARY-WIDE SEARCH
Open Library & timeline > Search entire Library. Type part of a filename,
project name or note, then click Search. The search covers all projects,
regardless of the project filter. Open result selects its containing archive,
exact backup snapshot or the matching Vault filename. Nothing is automatically
extracted, restored, decrypted or run. Notes open as text; projects open their
stored-item list. Clear results forgets the in-memory results.

Protected archives and sealed files are searched only by their existing
Library labels, locations and user-entered notes, never inner filenames.
Uncheck Include filenames for a quick catalogue-only search. Full text inside
files remains a separate Search Vault feature. No filename index is saved.
Solid archives require a streaming read and can take time; Cancel search stops
after the current identity/metadata read. Any skipped/missing/changed items,
cancellation or preview limits are reported as incomplete coverage. Limits:
500 displayed matches, 1,000 registered items considered for filenames,
250,000 filename entries / 32 MiB of names per stored item, and 2 GiB expanded
solid-archive stream. Search is discovery, not a full payload integrity check.

RESTORE A FILE DIRECTLY FROM LIBRARY
Search for a filename with Include filenames enabled. Select a File result
from an unencrypted Vault or a versioned backup and choose Restore this file.
Check the full snapshot ID (for backups). Choose an existing parent folder;
Rat-Trap proposes a NEW restore folder which you may rename. Confirm Restore
file. The selected file retains its relative path inside that new folder.

The exact source and selected bytes are checked before publication. Only the
selected file is restored; existing folders/files are never merged/replaced.
After success, Show restored file opens its containing folder, not the file.
A local plaintext File restored timeline receipt records the filename,
destination, SHA-256 and exact snapshot ID. This receipt is a historical
record, not ongoing verification of the output. Ordinary/locked archives
still use Open result and their existing workspace tools.

If the file was restored but its receipt could not be saved, keep the file;
do not repeat the restore merely to repair its timeline entry. No original
is removed. Restored files are plaintext, not automatically encrypted.
Close writers before restoring. Private temporary folders are not encrypted
or securely erased and a crash may leave staging data. Backup restore uses
the existing repository lock/recovery mechanism and may update its cache.
This Windows-only stage does not provide batch restore, automatic cleanup,
restoring into existing folders, or unlocked search of protected files.

LIBRARY HEALTH CHECK
Open Library & timeline > Library health. Choose Check Library to check ALL
projects, or select an item and choose Check selected. Confirm the read-only
check. Cancel check stops cooperatively; the current metadata/database read
may need to finish first. Unfinished items are never marked Verified.

Availability and integrity are separate. Located does not mean verified.
Vault file data and completed backup versions/sealed packs can be Verified.
Missing, changed, busy, damaged, pending-recovery or over-limit items need
attention. Locked contents remain Locked; ordinary archives are Not checked.
No automatic restore, repair, recovery, pruning, decryption or deletion occurs.
Repository cache/trash and original source folders are not verified. The
read-only check builds its object lookup in RAM, not the repository cache.

Check dates and details are retained as unencrypted timeline notes. These
are historical observations, NEVER a live guarantee. Nothing scans on startup.
Recheck after changes and retain an independent backup. A newer failed
availability check supersedes an earlier Verified result in the health view.
Receipt-save failures are shown separately; the current result remains visible.

Use Locate moved item for the SAME storage identity, Open workspace to
investigate, or Find a file to restore to enter Library search. These actions
never automatically repair, overwrite or execute your files. A missing old
snapshot is flagged, even if it was intentionally pruned: review history.

Preview limits: 1,000 items per run; 50,000 relevant repository paths, depth 8;
250,000 object locations; 2 GiB per pack; existing Library metadata limits
also apply. Exceeding a limit is NOT a pass. Close other writers first.
This is not a filesystem snapshot or protection from a hostile administrator.
