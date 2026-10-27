# Library-wide search

Application 5.7.0.9, support `5.7.0-desktop-preview.2-library.3`.

Open **Library & timeline → Search entire Library**. Enter a literal part of
a filename, project name/description, stored-item label/location or timeline
note and click Search. Matching is Unicode case-insensitive. `%`, `_` and SQL
syntax are plain text, not operators. All projects are searched, independent
of the stored-item filters above. Filesystem folders outside registered storage
are not scanned. Uncheck Include filenames for a faster catalogue-only search.

Results identify the project, containing storage and full exact snapshot ID
when there is a real backup version. Ordinary archives have no invented dates
or version history. Open result shows a note, selects a project, opens the
containing archive workspace, selects the exact backup snapshot, or selects
the exact matching filename in the existing Vault preview/extract workspace.
Nothing is automatically extracted, restored, decrypted or executed.

## Privacy and compatibility

Search results exist only in application memory until cleared, replaced or the
app exits. No persistent filename index, catalogue migration, credentials,
telemetry or upload is introduced. The existing v1 catalogue stays compatible.
Library labels, locations and user notes remain unencrypted, including labels
and notes for locked items. Never enter secrets in those fields.

Encrypted archives and sealed files are skipped for inner-filename searches:
there is no unlock prompt, decrypted metadata cache or password handling in
this feature. File contents are not searched; existing Search Vault remains
the separate full-text facility. A Vault hit selects a filename but does not
preview its bytes until the user explicitly requests that action.

## Read-only discovery and bounds

Each explicit search checks source identities. Sources are not repaired or
reindexed. Repository manifests are read directly; the recovery-capable
repository catalogue APIs are not used. SQLite sources are immutable/read-only;
active journal/WAL/SHM sidecars are refused. Solid archives require streaming
decompression to read filenames, without extraction or temporary plaintext files.
Search can therefore take longer than an indexed lookup.

A source's filename hits are retained only after the entire bounded scan and
final identity check succeed. Before a result opens, identity and any exact
snapshot checksum are checked again. An unavailable snapshot never becomes
"latest". A moved item may be explicitly relinked to the same storage identity.
These checks do not provide an atomic filesystem snapshot or defend against
an adversary continually changing files under the same Windows account.

Preview limits: 500 displayed matches; 1,000 registered items considered for
filename reads; 250,000 filename entries and 32 MiB of filename text per stored
item; 2 GiB expanded tar stream per solid archive. Existing repository manifest
and SQLite inspection bounds also apply. Failures/limits/cancellation are
visible in the search status and report box. Do not interpret an incomplete
search's missing result as proof a file is absent. Cancel is cooperative and
may wait for the current identity/metadata read. No partial hits from an
unfinished or failing source are retained.

This is discovery, not a full integrity audit: repository/Vault payloads are
not verified by filename searches. Use Verify and a restore comparison, and
keep an independent backup. This unsigned local preview is not Microsoft Store
approval, a clean-machine qualification or an independent security audit.

## Building and checking

Use the existing pinned local Python and NSIS toolchains:

```powershell
.\scripts\build_windows_library_search.ps1 -ValidateOnly
.\scripts\build_windows_library_search.ps1 -DestinationDirectory .\dist\library-search-NEW
.\scripts\build_windows_library_search_installer.ps1 -PayloadDirectory .\dist\library-search-NEW -DestinationDirectory .\dist\library-search-installer-NEW
.\scripts\test_windows_library_search_installer.ps1 -PayloadDirectory .\dist\library-search-NEW
```

Output directories must be new direct children of dist. The lifecycle harness
tests 5.7.0.8 → 5.7.0.9 under a fresh, isolated QA identity; it observes but does
not update the normal installed app. Raw reports contain local paths and are
not publication-ready. The build runs the five existing packaged self-tests
plus `--library-search-self-test`, using generated disposable data.
