# Library-wide search validation

Local Windows preview, 21 October 2026. Engine 5.7.0; application/installer
5.7.0.9; support `5.7.0-desktop-preview.2-library.3`.

## Automated checks

- Final focused suite: **62 tests passed**, 133.383 seconds. Includes 21 search
  backend tests and 41 Library UI/workflow tests.
- Full regression discovery: **602 tests run, 601 passed and one skipped**,
  735.655 seconds. The skip is the existing native Windows symlink-permission
  check. Deterministic path-safety tests passed. The final focused run above
  also covers the extra search edge-case tests added during full discovery.
- Source search self-test passed against generated archive, Vault and two
  repository snapshots, using the actual Tk worker/result path.
- Six final packaged self-tests passed: engine, UI, tutorials, Library,
  Store a folder and Library search. These six modes also passed after install.
- Build receipt verifies **36 source hashes**, 58 payload files and 53 legal
  files. Windows x64 GUI executable, pinned Python 3.13.13 and 13 dependencies.
- **227 installer lifecycle checks passed**, no failed checks or cleanup errors.
  Tested actual 5.7.0.8 → 5.7.0.9 under a fresh isolated QA product identity.
  Normal app installation was not updated. Generated archives, recovery-key
  sentinel files, existing options and unrelated associations were preserved.

## Search-specific coverage

Tests exercise legacy SQLite archives, solid archives with and without exact
duplicate files, Zstandard and XZ profiles, both Vault schema generations,
multiple projects and two exact repository versions. Unicode case folding,
literal wildcard characters and older notes beyond the timeline display limit
are covered. Searching file contents is deliberately excluded.

Protected archives/sealed files are not opened for filename searches. Hashes
and modification times confirm read-only source/catalogue discovery. Tests
cover missing and replaced sources, sources changing during scans, active
SQLite sidecars, corrupt/over-limit streams, result limits and cooperative
cancellation. Hits from unfinished/failed sources are discarded; healthy
sources remain searchable when another fails. Removed snapshots cannot route
to a newer version. Vault routing selects the exact filename without preview,
extraction or execution. Busy/tutorial guards and high-DPI geometry remain
covered by the Library UI suite.

The solid reader now closes its decompression stream if initial tar parsing
fails, including a bounded-output failure. No archive format or compression
profile was changed. Catalogue schema remains v1; no migration or permanent
filename index is introduced.

## Evidence and limits

The sanitized report is [qa-results-library-search.json](../packaging/direct/qa-results-library-search.json).
Raw local evidence is kept in the ignored build directory and contains local
paths; do not publish it. Release artifact hashes and relative source hashes
are recorded separately in the search release manifest.

This was same-host Windows 10 build 19045, PowerShell 7.6.5. It is not a clean
VM/Windows 11 certification, interactive installer/SmartScreen assessment,
security audit, signing or Microsoft Store approval. The executable remains
unsigned. Manual testing should use disposable copies and a separate restore
destination, keeping originals and independent backups.

Search has explicit preview bounds and may stream-decompress solid archives;
it is not an instant indexed lookup or a complete payload verification.
See [LIBRARY-SEARCH.md](LIBRARY-SEARCH.md) for privacy, coverage and limits.
