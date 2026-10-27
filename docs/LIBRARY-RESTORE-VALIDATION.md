# Direct Library restore validation

Local Windows preview, 21 October 2026. Engine 5.7.0; application/installer
5.7.0.10; support `5.7.0-desktop-preview.2-library.4`.

## Automated checks

- Focused backend and Library interface suite: **72 tests passed**, 193.624
  seconds (24 direct-restore/engine-selection tests and 48 Library UI tests).
- Full regression discovery: **638 tests run, 637 passed and one skipped**,
  1055.156 seconds, with resource warnings treated as errors. No failures.
  The native symbolic-link test is skipped because Windows did not grant
  symlink creation permission; a separate focused probe confirmed that reason.
- Source `--library-restore-self-test` passed using generated disposable data.
- Seven packaged self-tests passed: engine, UI, tutorials, Library, Store a
  folder, Library search and Library restore. All seven also passed after the
  application was installed under the isolated QA identity.
- Build receipt verified **37 source hashes**, 58 payload files and 53 Legal
  files, with pinned Python 3.13.13 x64 and the existing 13 dependencies.
- **228 installer lifecycle checks passed**, zero failed checks and zero
  cleanup errors. Actual 5.7.0.9 to 5.7.0.10 upgrade, repair, optional integration,
  locked-file refusal, and ordinary uninstall were exercised. Settings and
  generated user-file sentinels were preserved; normal app state was unchanged.

## Restore-specific coverage

Generated Vault and two-version backup fixtures test exact old bytes, nested
paths, zero-byte and Unicode filenames, only the selected file's objects being
read, and unchanged whole-snapshot restore behaviour. Repeated restores to
different new destinations create distinct receipts without colliding with
the original snapshot timeline event. Vault source bytes/modification time and
absence of new SQLite sidecars are checked.

Failure checks cover existing files and empty folders, a destination appearing
at publication, catalogue/repository destination overlap, missing parent
directories, ordinary archive refusal, unsafe member paths, changed file sizes,
missing files, replaced archives, active SQLite sidecars, changed/deleted
snapshot pins, reassigned projects, corrupted staged bytes, unexpected extra
files, sources changing after extraction, disk failure and receipt failure.
A disconnected progress callback does not turn a completed restore into a
reported failure. Failed pre-publication tests leave no success receipt.

UI tests exercise cancellation before restore, exact-version confirmation,
older-version output, explicit directory reveal (never file execution), receipt
display, missing snapshot refusal, unsupported archive guidance, parent-folder
selection, existing-destination refusal and truthful receipt-failure reporting.
Existing busy/tutorial guards and high-DPI geometry cover the added controls.

The first focused run found an incorrect test expectation about Windows CRLF
translation in a generated text fixture; restored bytes were correct. The
expectation was corrected, and the final focused run above passed in full.

## Evidence and limits

The sanitized lifecycle report is
[qa-results-library-restore.json](../packaging/direct/qa-results-library-restore.json).
Raw local evidence remains in ignored `build/` directories; it contains local
paths and is not publication-ready. Artifact and relative source hashes are
recorded in the separate restore release manifest.

The executable is an unsigned Windows x64 GUI build. This was same-host
Windows 10 build 19045 / PowerShell 7.6.5, not a clean Windows VM/Windows 11
qualification, interactive installer/SmartScreen assessment, independent
security audit, signing or Microsoft Store approval. The normal app has not
been installed/updated automatically and no remote release was published.

Checksums validate the selected restored file, not every file in the containing
archive or repository. Publication uses Windows no-replace rename; this new
Library workflow deliberately refuses non-Windows publication. It does not
provide a live-source filesystem snapshot, secure deletion of temporary data,
an encrypted catalogue, or protection from a hostile administrator/same-account
writer. See [LIBRARY-RESTORE.md](LIBRARY-RESTORE.md) for privacy and recovery.
