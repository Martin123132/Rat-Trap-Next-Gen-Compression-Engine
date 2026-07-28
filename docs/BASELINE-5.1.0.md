# Rat-Trap 5.1.0 preserved baseline

Status: release baseline
Baseline date: 18 July 2026
Preserved in Git as: `v5.1.0`
Previous repository commit: `c9cae34e0eebdcfc16b9530efe3dccb9aa92c474`

## Purpose

This document freezes the source, Windows executable, test corpus, benchmark
evidence, archive formats, and known limitations that make up Rat-Trap 5.1.0.
It is the point from which later product work must be measured.

The baseline is deliberately not a promise that every machine or folder will
produce the same compression ratio or timing. It is a record of exactly what
was built and verified on the release machine.

## Product included in the baseline

Rat-Trap 5.1.0 exposes four application profiles:

| Profile | Engine | Intended use |
|---|---|---|
| Fast | `GMW-SOLID-2`, Zstandard level 3 | Quick portable archives |
| Balanced | `GMW-SOLID-2`, Zstandard level 6, exact whole-file deduplication | Recommended general-purpose archive |
| Smallest | `GMW-SOLID-2`, Zstandard level 19, exact whole-file deduplication | Smaller output when creation time matters less |
| Queryable Vault | `GMW-VAULT-1`, schema 2 | Search, preview, selective restore, and typed structured queries |

The Windows application can create, inspect, extract, verify, search, and
export supported archives. The original file bytes remain canonical in a
Vault; full-text and relational tables are derived indexes.

## Acceptance evidence

The source test suite passed:

```text
python -m unittest discover -s tests -v
16 tests passed
```

The preserved `Rat-Trap.exe` passed:

- packaged `--self-test`;
- `--self-test-folder` against all four profiles;
- exact restored-tree verification against the 464-file beta corpus.

The folder-level profile result used to select the default was:

| Profile | Original | Archive | Saved | Compress median | Extract median |
|---|---:|---:|---:|---:|---:|
| Balanced | 36,991,791 B | 12,224,927 B | 66.95% | 1.257 s | 2.130 s |

This result used three repetitions and an exact SHA-256 tree comparison after
each extraction. The detailed category matrix, Vault checks, limitations, and
machine-readable evidence are described in
[`BENCHMARK-AUDIT.md`](../BENCHMARK-AUDIT.md).

## Preserved Windows build

| Item | Value |
|---|---|
| Python | 3.13.13, 64-bit |
| pip | 26.0.1 |
| PyInstaller | 6.21.0 |
| zstandard | 0.25.0 |
| Executable size | 13,170,175 bytes |
| Executable SHA-256 | `35FB3B557415FB6D6284D5FC91CB8F862BB5590ED950C9D369B5056516DBB5BE` |
| Release ZIP size | 12,964,249 bytes |
| Release ZIP SHA-256 | `6108F98D8A61D442FC90D68F33981ED8D46B9463910020D3B62D5CE2CAECF1FC` |
| Authenticode | Not signed |

Exact artifact hashes and the 13-file release inventory are in
[`release-manifests/5.1.0.json`](../release-manifests/5.1.0.json).
`requirements-build-5.1.0.txt` pins the complete installed package set used by
the build.
PyInstaller embeds timestamps and platform details, so a source-equivalent
rebuild is not guaranteed to be byte-for-byte identical.

## Re-running the gate

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\verify_5_1_baseline.ps1
```

The verifier checks versions and preserved hashes, runs the Python tests,
checks the executable inside the release ZIP, and runs both packaged
self-tests. Paths can be overridden when the evidence or beta folder is kept
elsewhere:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\verify_5_1_baseline.ps1 `
  -OutputsDir D:\RatTrapEvidence `
  -FixtureFolder D:\Rat-Trap-Beta-Test-Data
```

The release assembly can be recreated without changing the preserved output:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\package_windows_release_5_1.ps1 `
  -DestinationDir D:\RatTrapBuild
```

## Archive compatibility frozen here

The compatibility contract is maintained in
[`GMW-FORMAT-REGISTRY.md`](GMW-FORMAT-REGISTRY.md). In short:

- current writers emit `GMW-SOLID-2` or `GMW-VAULT-1` schema 2;
- 5.1 reads `GMW-SOLID-2`, Vault schemas 1 and 2, and
  `GMW-SQLITE-1`;
- future readers must continue to read every officially released 4.2+
  format;
- unknown mandatory versions must fail closed;
- incompatible changes require a new format family or major marker;
- migrations create a new archive and verify it; they do not modify the only
  copy in place.

## Security boundary

Rat-Trap 5.1.0 does **not** encrypt, authenticate, or digitally sign `.gmw`
archives. Checksums and restore verification detect many forms of accidental
damage, but they are not a substitute for authenticated encryption against a
malicious editor. Encryption is future work and must use a new authenticated
envelope/version so old readers cannot misinterpret encrypted data.

## Historical repository paths

Three historical filenames end in a full stop or colon and cannot be checked
out on Windows:

- `benchmark the compression ratio and time for both methods.`
- `rat_trap/GMW Tool GUI - Complete graphical interface for all GMW archive operations.`
- `rat_trap/GMW Tool v4: SQLite-backed content lake for LLM ingestion.`

Their exact contents remain recoverable from full Git history. At the parent
commit their blob IDs are respectively:

- `b2c1e7b6fcc14d1b61b73a36351bebf4cd826fd5`
- `1d9d0651e036c03e3324a48bf4a6a674e52eb2d6`
- `fd3e3535ae346289321db1535bbc17d2ec4147f1`

The latter two have Windows-safe equivalents in
`rat_trap/gmw_gui_complete.py` and `rat_trap/gmw_tool_v4.py`. The benchmark
record has been normalized into
[`benchmarks/historical/2025-benchmark-record.json`](../benchmarks/historical/2025-benchmark-record.json).

## Known baseline limitations

- The executable is unsigned and distributed as a portable ZIP.
- Encryption and password recovery do not exist in 5.1.
- Whole-file deduplication does not find shifted or partial duplicate regions.
- Vault chunking is fixed-size, not content-defined.
- The solid checksum covers the compressed payload, not its JSON footer.
- The legacy `GMW-SQLITE-1` integrity model is weaker than the current Vault.
- There are no committed golden archive fixtures for every old release.
- Product version strings are duplicated in several source/resource files.
- `.gmw` identifies several archive families, so dispatch must remain strict.
- The preserved 5.1 legacy fallback does not explicitly require
  `metadata.format == "GMW-SQLITE-1"` after solid/Vault detection. A
  sufficiently similar unknown SQLite database can reach legacy processing;
  this must be hardened in the next reader.

These are constraints for later stages, not omissions from this preserved
baseline.
