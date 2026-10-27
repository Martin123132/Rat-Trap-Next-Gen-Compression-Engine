# Building the Library preview

The Library stage keeps the 5.7.0 engine and the existing Desktop Preview 2
installation identity. Its numeric Windows version is `5.7.0.7`; the support
label is `5.7.0-desktop-preview.2-library.1`.

These new recipes use source in this checkout and a pinned local toolchain.
They do **not** require an old private MSIX or app payload, modify an earlier
build, install the normal app, sign, publish, or change file associations.

## Toolchain

Use Windows x64, PowerShell 5.1 or later, Python 3.13.13 x64 including Tk, and
a dedicated `.venv` containing `requirements-build-5.7.0.txt`'s exact 13 pins.
The script rejects additional distributions other than pip and the editable
Rat-Trap metadata. Preparing this environment is an explicit maintainer step;
the scripts never download or install dependencies.

For the installer, supply the official NSIS 3.12 portable toolchain. The
compiler SHA-256 is
`B043E554AFEFBFC56315669D0B4779793AEAE67F0F2A7A790E2EA91F05298EFF`
and its adjacent COPYING hash is
`388357C1215FF403C5EBDE3A5ECD273E68F8B79A579996775245D1EE65442ABA`.
The default compiler path is
`build\tools\portable\nsis-3.12\makensis.exe`.

## Build and validate

From the repository root:

```powershell
.\scripts\build_windows_library.ps1 -ValidateOnly
.\scripts\build_windows_library.ps1 -DestinationDirectory .\dist\library-local-1
.\scripts\build_windows_library_installer.ps1 -PayloadDirectory .\dist\library-local-1 -DestinationDirectory .\dist\library-installer-local-1 -ValidateOnly
.\scripts\build_windows_library_installer.ps1 -PayloadDirectory .\dist\library-local-1 -DestinationDirectory .\dist\library-installer-local-1
```

App and normal installer outputs must be new immediate children of `dist`. Use a new directory name
for each build. No earlier release is overwritten. Failed app staging and
build logs are retained under new ignored directories for diagnosis.

The app builder runs four modes against the packaged executable:
`--self-test`, `--ui-self-test`, `--tutorial-self-test`, and
`--library-self-test`. Passing is a same-host automated check, not proof of
clean-machine compatibility, visual acceptance, or production data safety.

The payload has checksums and a `BUILD-MANIFEST.json` with relative source
hashes, dependency inventory, actual runtime versions, and successful test
mode names. Absolute input paths exist only in ignored local build evidence.
The installer excludes the build receipt and any portable ZIP. Neither file
checksums nor the receipt replace a publisher signature.

## Licences and upgrade compatibility

Licences and cryptography SBOMs are collected from installed distributions,
not extracted from an old binary. The prior 20 Legal paths are retained so
an in-place upgrade does not strand installer-owned notices. Additional
build-tool and vendored notices are included conservatively; they do not
claim all build tools are bundled at runtime. Python's Windows LICENSE
includes its bundled-runtime notices. SQLite's public-domain notice links
to the [upstream copyright statement](https://sqlite.org/copyright.html).

Existing project licence documents remain unchanged. The old
`Legal/README-WINDOWS.txt` is retained as a legacy packaging document; the
current first-run instructions are `README-FIRST.txt` and
`README-PORTABLE.txt`.

The installer retains `TwoHandsNetwork.RatTrap.DesktopPreview2`, the existing
per-user path, and the original optional Open with/desktop choices. It never
sets a default file association or adds one for recovery keys. Uninstall
preserves user files, the catalogue, and independently stored work.

## Isolated lifecycle qualification

The separate QA harness deliberately needs the recorded 5.7.0.6 payload to
test an actual previous-version upgrade. This is a *qualification input*,
not a requirement of either clean-source build script.

```powershell
.\scripts\test_windows_library_installer.ps1 -PayloadDirectory .\dist\library-local-1
```

The harness creates a new QA identity and tests install, previous-version
upgrade, optional integration, locked-file refusal, repair and uninstall.
It observes the normal app only; it must never install or remove that app.
All generated data is disposable QA data. Reports retain the identity,
exact hashes, checks and cleanup outcome under `build/library-qa`.

This does not claim byte-for-byte reproducibility, clean Windows 11 coverage,
a security audit, signing, Store certification, or a remote release.

