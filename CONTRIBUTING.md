# Run from source and contribute

Rat-Trap's current Windows entry point is `windows_library_preview.py`.
The [Windows installer](docs/WINDOWS.md) is for people who just want the app;
these instructions are for source users and contributors.

## Development setup

Use **64-bit Python 3.13 on Windows** with Tkinter. Python 3.13.13 is the
recorded release runtime. Package metadata requires Python 3.12 or later;
that floor is not a claim that every Python/platform combination has been
qualified. SQLite FTS5 is required for Vault full-text search.

From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build-5.7.0.txt
.\.venv\Scripts\python.exe windows_library_preview.py
.\.venv\Scripts\python.exe -m rat_trap.cli --help
```

The pinned requirements describe the recorded Windows release environment,
including packaging tools. Running from the checkout does not need a package
installation. To install the CLI into your virtual environment, use
` .\.venv\Scripts\python.exe -m pip install . `.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe windows_library_preview.py --self-test
.\.venv\Scripts\python.exe windows_library_preview.py --ui-self-test
.\.venv\Scripts\python.exe windows_library_preview.py --tutorial-self-test
.\.venv\Scripts\python.exe windows_library_preview.py --library-self-test
.\.venv\Scripts\python.exe windows_library_preview.py --backup-plans-self-test
```

Windows/Tk tests require an appropriate desktop session; a headless run is
not equivalent. Tests use temporary fictional data. The published passwords
and recovery keys in `tests/fixtures/formats/` are deliberate public test
vectors, never credentials for real files.

Installer lifecycle scripts are a separate opt-in operation that installs
and removes a fresh QA identity. Do not run them as an ordinary read-only
check. Read [the packaging boundary](docs/TECHNICAL.md#windows-packaging-is-a-separate-release-operation)
before using any release builder: the historical scripts require artifacts
outside a public clone.

## Find the right files

- `rat_trap/`: current engines, interfaces and tutorial implementations.
- `windows_library_preview.py`: current desktop entry point.
- `tests/`: functional, format, safety, UI and packaging checks.
- `docs/TECHNICAL.md`: formats, limitations and complete evidence navigation.
- `benchmarks/`: measurement tools and published historical results.
- `historical/`: preserved original experiments, not current entry points.
- `release-manifests/`: frozen qualification records.
- `packaging/`, `scripts/` and `store/`: release assets, workstation
  recipes and historical Store submission drafts; not Store approval.

## Changes and reports

Keep changes focused and include a fictional reproduction and relevant tests.
Archive and encryption changes need particular care around compatibility,
exact restoration, authentication, safe output publication and recovery.
Do not silently rewrite historical benchmark records or release manifests.
New measurements belong in a separately identified campaign with corpus
hashes, environment details, all samples, failures and restoration checks.

Do not commit personal datasets, private archives, recovery keys, signing
certificates, tokens or raw local diagnostics. The downloaded beta corpus
is not cleared for wholesale redistribution; its builder documents source
terms. Public issue reports must use non-confidential examples. Report
security defects through [SECURITY.md](SECURITY.md).

The existing [licence](LICENSE.md), [commercial terms](COMMERCIAL-LICENSE.md)
and [credits](NOTICE.md) remain unchanged. Public availability means
source-available, not unrestricted commercial use. Discuss substantial
contributions and any needed rights arrangements with the maintainers before
starting.
