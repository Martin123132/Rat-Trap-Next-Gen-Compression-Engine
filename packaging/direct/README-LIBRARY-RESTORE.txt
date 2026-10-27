RAT-TRAP: RESTORE DIRECTLY FROM YOUR LIBRARY
Application version: 5.7.0.10
Support label: 5.7.0-desktop-preview.2-library.4
TWO HANDS NETWORK LTD

Open Library & timeline. Create or select a project, then choose Store a
folder. Pick your source folder and a separate save location.

ONE-OFF ARCHIVE
Choose a new .gmw filename and Fast, Balanced or Smallest compression.
Existing archives are never overwritten by this workflow. Encryption is
optional: tick Encrypt archive, acknowledge the temporary plaintext working
copy, choose a password and save a separate recovery key. Keep that key safe.
Rat-Trap does not claim secure deletion of temporary plaintext traces.

VERSIONED BACKUP
Choose a new/empty folder or an existing Rat-Trap backup repository.
These live repositories are NOT encrypted. Each completed save adds a version;
matching data can be reused and earlier versions stay. Nothing is pruned
automatically. To repeat, select the repository and Save another version.
Choose the source again: the app does not guess which folder you mean.

SUCCESS AND RECOVERY
After a save completes, the item and its exact snapshot events are recorded
in your selected project. Originals stay where they are. Open workspace or
open a timeline version to use the existing check and restore tools.
No automatic restore, calendar linking, scheduling, upload or source deletion.

If files were saved but the Library update failed, the app tells you where
they are. Do not save again just to repair the listing. Use Add archive /
protected file or Add backup repository; Refresh selected updates an existing
repository entry. Interrupted backup work remains for Backups & history to
inspect/resume. An interrupted encrypted build can leave its recovery-key
file; check the output before deciding what to do with that key.
If a backup resumes an earlier interrupted job, the app tells you. Check the
recovered version and save again to capture edits made since that job began.

LIBRARY PRIVACY
The local catalogue is unencrypted metadata: names, paths, projects, notes
and timestamps. Encryption of a file does not encrypt its Library record.
Never put passwords or recovery keys in notes. Catalogue entries are references,
not independent backups. Close Rat-Trap before backing up the whole Library
directory, and back up its referenced files separately.

PREVIEW SAFETY
This is an unsigned local Windows x64 preview. The installed application name
is still Rat-Trap Desktop Preview 2; no Python, account or Codex is required.
Use copies first. Keep originals and independent backups. Test restoring to
a separate folder and compare the contents before relying on stored data.
Library registration checks identity, not a full restore or integrity test.
The archive workflow checks source filesystem metadata for changes but is
not an operating-system snapshot of running applications. Close editors first.
Only ordinary local-drive paths are supported; no network shares or links.
Nothing is uploaded automatically; local cloud-sync folders follow their own
service's behaviour. See PRIVACY.md.

If Windows or organisational policy blocks the preview, do not disable your
security protection. Stop and ask your administrator or support.
Uninstall preserves the catalogue and your stored work.

SUPPORT AND LICENCES
ollett123123@outlook.com -- quote 5.7.0-desktop-preview.2-library.4.
Never send confidential files, passwords, recovery keys or your personal
Library catalogue in support reports. See SUPPORT.md.
Read Legal/LICENSE.md and Legal/COMMERCIAL-LICENSE.md. Existing terms remain.
Keep Legal and policy files with an extracted portable payload.
BUILD-MANIFEST.json records build evidence; it is not a publisher signature.

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
