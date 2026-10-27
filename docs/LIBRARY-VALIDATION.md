# Library preview validation

Local Windows x64 qualification for application **5.7.0.7**,
support label **5.7.0-desktop-preview.2-library.1**, on 20 October 2026.
The engine remains 5.7.0. This is an unsigned preview, not a Store release.

## Source checks

- Full existing-plus-Library discovery: **549 tests**, 448.625 seconds,
  passed with one native-symlink permission skip.
- After the final Library routing and duplicate-registration fixes:
  **63 focused tests**, 46.892 seconds, passed with the same permission skip.
  This includes all 37 Library backend tests and all 26 Library UI tests,
  including two regressions added after the full run.
- Source `--library-self-test` and `--tutorial-self-test` both exited 0.
  The latter exercises the five established lessons with the Library subclass
  and an isolated catalogue, without replacing the legacy class's globals.
- Compilation checks passed for all new Python modules and tests.

Commands (from the repository root):

```powershell
.\.venv\Scripts\python.exe -W error::ResourceWarning -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -W error::ResourceWarning -m unittest tests.test_library tests.test_library_app -q
.\.venv\Scripts\python.exe windows_library_preview.py --library-self-test
.\.venv\Scripts\python.exe windows_library_preview.py --tutorial-self-test
```

The full run preceded the final two UI fixes; the focused run verified the
final Library implementation. Do not describe these as one 612-test suite.
The skipped native-symlink test reflects Windows permission availability;
deterministic reparse-point and hard-link refusal checks passed.

## Coverage

Checks cover lazy catalogue creation, durable IDs, projects, dated notes,
idempotent snapshot events, metadata-only deletion, moved-file identity,
missing and damaged sources, bounded parsers, future or injected catalogue
schemas, source sidecars, protected-file metadata boundaries and concurrency.

UI checks cover existing-format routing, exact older snapshot selection,
refusal to substitute a missing version, no implicit unlock/restore/execute,
cached views without source reads, project filters, duplicate registration,
draft preservation, failed-operation status and busy/tutorial action guards.
Compact 960×640 and three Tk scaling settings were checked geometrically;
this is not a claim of human visual acceptance on every display.

Tests used generated data and copies of checked-in format fixtures, not
personal source folders. Existing release recipes and evidence are retained.

## Packaged qualification

See the new `release-manifests/library-preview.json` for the completed
payload/installer hashes and qualification results, and the corresponding
build receipt and lifecycle report it identifies. No earlier release manifest
is repurposed for this stage.

The clean-source builder collects licences from the pinned installed
environment and checked-in notices; it does not require a historical private
MSIX or executable. Its read-only preflight passed on PowerShell 7 and
Windows PowerShell 5.1. The old 5.7.0.6 payload is used only to test upgrade.

## Boundaries

These are same-host checks, not clean-machine or Windows 11 qualification,
a cryptographic audit, SmartScreen reputation, publisher signing or Store
certification. They do not prove arbitrary future upgrades or production
data safety. No GitHub publication or normal-user app installation is part
of this stage. Retain originals and independent backups.
