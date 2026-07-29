# Rat-Trap 5.3.0 third-party notices

Rat-Trap's own source is governed by [`LICENSE.md`](LICENSE.md). The frozen
Windows application also contains the following separately licensed runtime
components:

| Component | Version | Licence |
|---|---:|---|
| Python | 3.13.13 | Python Software Foundation License Version 2 and notices in the Python licence file |
| Tcl/Tk | 8.6 | Tcl/Tk licence terms |
| PyInstaller bootloader and run-time hooks | 6.21.0 | GPL-2.0-or-later with Bootloader Exception; run-time hooks under Apache-2.0 |
| PyInstaller Hooks Contrib | 2026.6 | Apache-2.0 |
| PyFastCDC | 0.2.1 | MIT |
| typing_extensions | 4.15.0 | PSF-2.0 |
| python-zstandard | 0.25.0 | BSD-3-Clause |
| cryptography | 49.0.0 | Apache-2.0 OR BSD-3-Clause |
| OpenSSL (statically linked by the cryptography wheel) | 4.0.1 | Apache-2.0 |
| CFFI | 2.1.0 | MIT-0 |
| pycparser | 3.0 | BSD-3-Clause |

The Windows release ZIP contains the upstream licence texts copied from the
pinned build environment under `THIRD-PARTY-LICENSES`. The OpenSSL licence is
the Apache License 2.0 text shipped with the statically linked cryptography
wheel. The ZIP also carries the cryptography wheel and Rust component SBOMs
under `SBOM`.

Pycparser is a dependency of CFFI in the pinned build environment and may be a
build-only rather than frozen runtime component; its licence is included
conservatively. The cryptography Rust SBOM is the component-level inventory
for its compiled Rust dependencies.

These upstream licences apply only to their respective components. They do
not grant additional rights to Rat-Trap source or replace Rat-Trap's
PolyForm Noncommercial terms.
