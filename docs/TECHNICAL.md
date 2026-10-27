# Rat-Trap technical documentation and evidence

This is the engineering and buyer-diligence entry point. The
[product page](../README.md) explains Rat-Trap's customer benefits; this page
connects those features to their implementations, format specifications,
complete benchmark record and release checks. Successful, losing, failed and
historical results remain part of the record.

## Current application and qualification

The latest recorded Library application is
**`5.7.0-desktop-preview.2-library.6`**, with numeric application/installer
version **`5.7.0.12`** and base engine version **`5.7.0`**. Its installed product
name remains **Rat-Trap Desktop Preview 2**, published by
**TWO HANDS NETWORK LTD**. These identify different layers of the same current
application, not three different downloads.

The [Library plans release record](../release-manifests/library-plans.json)
identifies the application and original local installer hashes, build inputs,
runtime, dependency versions and qualification on 21 October 2026. The public
installer uses the same application but was rebuilt with an uninstall-shortcut
safeguard; its exact hash and separate qualification are in the
[public release notes](releases/5.7.0-preview.12.md). The
[sanitized installer QA record](../packaging/direct/qa-results-library-plans.json)
contains the individual lifecycle checks. The recorded results are:

- 704 source tests ran: 703 passed and one was skipped because native Windows
  symbolic-link creation permission was unavailable.
- Nine packaged self-test entry points passed and passed again on the
  isolated installed application.
- 230 installer lifecycle checks passed, with no cleanup errors, including
  the specific `5.7.0.11` to `5.7.0.12` upgrade under a fresh QA identity.
- All five guided practices are available: Vault search, folder compression,
  archive restoration, file protection/recovery and backup history.
- Library adds project organisation, timeline, cross-Library filename search,
  supported single-file restore, manual storage health checks and saved manual
  backup plans. See the [Library guide](LIBRARY.md) and
  [plan validation](LIBRARY-PLANS-VALIDATION.md).

Separate [public-installer validation](releases/5.7.0-preview.12-validation.md)
records 243 passing checks for an isolated QA build of the rebuilt Setup recipe
and the earlier intermittent shortcut-removal failure, including its repeat.
It covers the specific public
`5.7.0.6` to `5.7.0.12` path under an isolated QA identity.

The previous publicly released `5.7.0.6` qualification remains in the
[guided-history record](../release-manifests/guided-history.json) and its
[installer QA record](../packaging/direct/qa-results-guided-history.json).

These are functional and release-qualification results, **not competitive
compression benchmarks, independent security certification or a guarantee of
data recovery under every failure condition**. The app and installer are
unsigned. This record does not establish clean Windows 11 acceptance,
SmartScreen/wizard acceptance, native visual review or accessibility
certification. The minimum installer target is Windows 10 x64; the recorded
checks ran on the development Windows host.

Release records and earlier stage documents are immutable historical evidence.
Their references to private builds, former download names and local artifact
directories describe the stage at which they were written. They do not select
the current public download; use the [product page](../README.md) for that.
Local `build/`, `dist/` and parent-workspace paths in manifests are evidence
identifiers, not promised files in a source checkout. Byte-for-byte rebuild
reproducibility is not claimed.

Source-file hashes identify the exact build-workspace bytes. Git settings
may change source text line endings in a checkout or locally generated
archive. Compare canonical content when investigating a newline-only
difference; do not silently rewrite a recorded hash. Golden recovery-key
fixtures and frozen evidence JSON are exempted from Git text conversion.

## Architecture: choose the storage model deliberately

| Workflow | Representation and implementation | What it provides | Important boundary |
|---|---|---|---|
| Portable folder archive | `GMW-SOLID-2`; [solid engine](../rat_trap/solid_engine.py) | A compressed tar stream; Balanced/Smallest reuse eligible exact whole-file duplicates | Not a queryable database; whole-file reuse is not content-defined chunking |
| Queryable Vault | `GMW-VAULT-1` schema 2; [Vault engine](../rat_trap/vault_engine.py) and [structured data](../rat_trap/structured_data.py) | SQLite, independently compressed fixed-size objects, filename/text search and typed data tables | Derived indexes consume additional space; shifted regions are not deduplicated through content-defined boundaries |
| Backup history | Repository schema 1; [repository engine](../rat_trap/repository_engine.py) | Content-defined chunks reused across snapshots, checksum-named manifests, sealed packs and rebuildable catalog | A folder repository, not a portable `.gmw`; currently unencrypted and manually triggered |
| Protected portable archive or Vault | `RAT-TRAP-ENCRYPTED-1`; [secure engine](../rat_trap/secure_engine.py) | Authenticated encryption of the complete inner archive, with password and independent recovery-key access | Unlocking may create a complete plaintext temporary working copy |
| Individual Sealed File | `.rtsf` profile 1; [Sealed File implementation](../rat_trap/sealed_file.py) | One opaque encrypted file containing one original, with its own `.rtrk` recovery key | Copy-only protection; does not remove the source or force every file on the computer to use Rat-Trap |

The current Windows entry point is
[`windows_library_preview.py`](../windows_library_preview.py), which adds
the Library workspace through [`library_app.py`](../rat_trap/library_app.py).
[`guided_app.py`](../rat_trap/guided_app.py) adds safe fictional practices to
the existing desktop and Windows workflow layers. The tutorial wrappers use
the production engines; they do not replace them with simulated results.
The supported CLI is [`rat_trap/cli.py`](../rat_trap/cli.py), with dispatch in
[`gmw_tool.py`](../rat_trap/gmw_tool.py).

### Format specifications and compatibility

- [GMW format registry](GMW-FORMAT-REGISTRY.md): exact family detection,
  supported readers/writers and compatibility policy.
- [Repository format](REPOSITORY-FORMAT.md): chunk identity, pack/manifest
  layout, commit boundaries, restore, verification and retention.
- [Authenticated archive format](SECURE-ARCHIVE-FORMAT.md): the fixed
  AES-256-GCM-SIV, Argon2id and recovery-key suite, parser and security model.
- [Sealed File format](SEALED-FILE-FORMAT.md): authenticated single-file
  constraints, opaque naming and restore rules.
- [Queryable Vault guide](../VAULT-README.md): schema, indexing, SQL surface,
  supported data sources and encrypted-Vault behavior.
- [Compatibility fixture set](../tests/fixtures/formats/README.md) and
  [manifest](../tests/fixtures/formats/manifest.json): reconstruction and
  interoperability fixtures with expected hashes. Published test passwords
  and keys are deliberately public and must never protect private files.

The `.gmw` extension covers several families; the reader validates content
and schema rather than trusting the filename. Historical raw-tar drafts,
`GMW-DEDUP-1` and the spatial `MBT2` experiment are not supported modern folder
archive families. Original experiments remain available as history.

### Exact feature boundaries

**Search and tables.** Vault filename search includes binary-file names.
Supported detected text up to 16 MiB can be content-indexed; this is not OCR
or speech recognition. Structured imports support CSV, TSV, JSON, JSONL,
NDJSON and supported UCI data, subject to 64 MiB per source, 250,000 rows and
256 columns. Files that exceed indexing limits can still be stored and
restored as originals. SQL accepts the constrained read-only query surface,
not arbitrary database modification. Repository history search covers stored
paths, filenames, labels and generations; it is not cross-snapshot full-text
content indexing. Encrypted Vault search authenticates and materializes the
whole Vault before SQLite opens it; it is not querying encrypted pages in
place.

**Backup and restore.** Repository schema 1 has no scheduling, VSS snapshot,
remote-storage protocol, cloud synchronization or automatic off-site copy.
Atomic publication of a snapshot does not freeze a changing multi-file
source. Repository restore verifies a separate new folder before publication;
do not generalize that transactional behavior to every legacy archive
extractor. ACL preservation is not implemented. Unsupported links, reparse
points, alternate streams, sparse files, NTFS-compressed files and EFS inputs
are refused where documented by the repository safety model. Retention uses
an explicit preview/apply plan and recoverable trash; moving data to trash
does not free disk space. Pack compaction and permanent trash expiry are not
implemented.

**Library.** Its schema-v1 local catalogue contains unencrypted project names,
storage identities and locations, notes, health receipts and explicitly saved
backup-plan source paths. It is not another copy of the files. Library-wide
search does not automatically unlock protected content. Direct Library restore
currently covers one file from an unencrypted Vault or an exact backup
snapshot, into a new destination. The manual health check covers supported
Vaults and completed versioned backups, not the backup cache, trash, original
source folders or locked contents. Results are historical, not continuous
monitoring. Saved backup plans run only on explicit confirmation; there is no
background scheduler or automatic retention. See [health scope](LIBRARY-HEALTH.md),
[direct restore](LIBRARY-RESTORE.md) and [saved plans](LIBRARY-PLANS.md).

**Protection.** Live repositories and ordinary unencrypted archives are not
authenticated-encryption containers. Hash checks alone are not authentication
against an attacker able to rewrite the archive or repository. Protected
archives and Sealed Files require complete authentication before successful
unlock. Temporary plaintext cleanup is best-effort, not secure erasure. A
matching recovery key grants access independently of the password; keep it
separately. Losing both credentials makes the protected data unrecoverable.
Documented formats can be implemented by compatible software; the Rat-Trap
workflow is not an exclusive technical lock-in mechanism.

**Windows integration.** The installer is per-user and does not require
administrator privileges. Desktop shortcuts and `.gmw`/`.rtsf` Open-with
registration are optional and initially off. Opening a supported file only
preselects a workspace; it does not automatically decrypt or extract it.
Recovery keys are not registered as openable files. No default-application
takeover or automatic updater is included. See [privacy](../PRIVACY.md) and
[support](../SUPPORT.md) before sharing diagnostics.

## Benchmarks: full record, with version and workload attached

Start with the [benchmark audit](../BENCHMARK-AUDIT.md) for complete controlled
tables and the [benchmark history](BENCHMARK-HISTORY.md) for evidence labels,
historical comparisons, failures and excluded claims. The
[two-lane publication policy](PRODUCT-EVIDENCE-LANES.md) explains how selected
product claims trace back to this complete evidence.

| Evidence campaign | What was measured | How to interpret it |
|---|---|---|
| 2025 original campaign | GMW tar/Zstandard variants, tar.gz, tar.bz2, tar.xz and raw-codec comparators across text, image, audio and structured workloads | Preserved historical measurements; not a current rerun. Environment, corpus freezing, repetitions and archive-equivalence gaps are explicitly recorded |
| July 2026 Rat-Trap 4.4 engine selection | Seven isolated diagnostic categories, then three application profiles on a 464-file, 36,991,791-byte folder | Accepted archive runs required exact restoration. The compact corpus deliberately includes a large exact-duplicate fixture; aggregate ratios are not representative of every folder |
| Rat-Trap 5.0 Vault validation | Search-only Vault size, indexing, queries, verification, extraction and export on the corrected corpus | A separately useful search/storage tradeoff, not a smaller-container claim than the Balanced archive |
| Rat-Trap 5.1 Structured Vault validation | Typed sources/rows, filters, SQL and exact restoration on the same corpus | Additional relational representation increases size. Query timings and limits belong to this dataset and implementation |
| Rat-Trap 5.7 guided tutorial.4 qualification | Source tests, compatibility/safety workflows, packaged self-tests and installer lifecycle | Historical functional evidence, not a new compression or competitor benchmark matrix |
| Rat-Trap 5.7 Library plans qualification | Source and focused tests, packaged self-tests and installer lifecycle | Current functional evidence, not a new compression or competitor benchmark matrix |

For example, the historical 4.4 Balanced profile stored 36,991,791 source
bytes in 12,224,927 archive bytes: **66.95% saved on that exact corpus**.
The full audit also shows categories where XZ creates smaller archives and
where already compressed data changes little. The figure includes the
deliberate duplicate fixture and is neither a current universal savings claim
nor a claim that Rat-Trap beats all competing products. Recorded timings must
retain their original workload and environment limitations.

### Machine-readable and original evidence

The [2025 machine-readable campaign record](../benchmarks/historical/2025-benchmark-record.json)
preserves exact captured cells, source commit/blob hashes, comparator
semantics and the `historical_unvalidated` label. The
[original-materials index](../historical/README.md) locates the preserved
full-run transcript, consolidated harness and original implementations.
The [project history index](HISTORICAL-PROJECT-NARRATIVE.md) locates the
original implementations and earlier README history without replacing them.

The [published controlled results](../benchmarks/results/2026-07-18/README.md)
provide all five JSON records, with explicitly documented private-path
redactions and original/derivative hashes. The original raw files remain
unchanged outside the source tree; their exact byte sizes and SHA-256 hashes
are recorded under `artifacts` in the
[5.1.0 manifest](../release-manifests/5.1.0.json):

| Raw result filename | Evidence contained |
|---|---|
| [Category baseline](../benchmarks/results/2026-07-18/Rat-Trap-Beta-Categories-baseline.json) | Full category baseline matrix and repeated timing samples |
| [Category hybrid](../benchmarks/results/2026-07-18/Rat-Trap-Beta-Categories-hybrid.json) | Focused hybrid/whole-file reuse matrix |
| [Final 4.4 profiles](../benchmarks/results/2026-07-18/Rat-Trap-Beta-4.4-final.json) | Three final application profiles, three repetitions and round-trip status |
| [5.0 Vault](../benchmarks/results/2026-07-18/Rat-Trap-Vault-Beta-benchmark.json) | Schema-1 Vault sizes, query samples and restore/export checks |
| [5.1 Structured Vault](../benchmarks/results/2026-07-18/Rat-Trap-Structured-Beta-benchmark.json) | Schema-2 Vault rows, filters, SQL and restoration results |

An original hash identifies evidence; it is not itself a public download.
The original Vault JSON files contain machine-specific absolute source and
output paths. The public derivatives replace exactly four such strings,
retain every result cell and map back to the original hashes. Raw build/lifecycle logs
and private filesystem paths are not publication material merely because a
manifest records their hashes.

The original corpus ZIP and full empirical Vaults are also external
artifacts, not committed compatibility fixtures. Dataset terms are distinct
from the Rat-Trap software license. In particular, the
[corpus builder's source notes](../benchmarks/build_beta_data.py) flag its
CIFAR image subset for local evaluation pending redistribution clarification;
do not assume the full beta ZIP is cleared for public redistribution.

### Inspecting and repeating methods

The maintained harnesses are
[`benchmark_engines.py`](../benchmarks/benchmark_engines.py),
[`benchmark_vault.py`](../benchmarks/benchmark_vault.py) and
[`benchmark_structured_vault.py`](../benchmarks/benchmark_structured_vault.py).
Use their `--help` output for inputs and profile choices. The
[corpus builder](../benchmarks/build_beta_data.py) records sources and emits
a file manifest; inspect download sizes and source terms before running it.

Run future measurements into a new output directory using copies of data.
Record the source revision, complete hardware/runtime/codec environment,
corpus hashes, all samples, timing boundaries and exact restore verification.
Separate equivalent folder archives from raw codecs. Retain failures and
losing rows. Re-running today's harness with today's engine produces **new
evidence**; it does not recreate a frozen 4.4/5.0/5.1 run automatically.
No benchmarks were rerun to prepare this documentation index.

## Running source and tests

The recorded Windows application environment is **64-bit Python 3.13.13**
with the 13 exact pins in
[`requirements-build-5.7.0.txt`](../requirements-build-5.7.0.txt).
The broader Python declaration in [`pyproject.toml`](../pyproject.toml) is
package metadata, not a statement that every runtime/platform combination
has passed the Windows release gate. Tkinter and SQLite FTS5 are required
for their respective features. Source use is governed by [LICENSE.md](../LICENSE.md).

From a fresh checkout in PowerShell, using that Python runtime:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build-5.7.0.txt
.\.venv\Scripts\python.exe windows_library_preview.py
```

The following commands run against the source checkout without requiring the
CLI package to be installed:

```powershell
.\.venv\Scripts\python.exe -m rat_trap.cli --help
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe windows_library_preview.py --self-test
.\.venv\Scripts\python.exe windows_library_preview.py --ui-self-test
.\.venv\Scripts\python.exe windows_library_preview.py --tutorial-self-test
.\.venv\Scripts\python.exe windows_library_preview.py --backup-plans-self-test
```

Tests create temporary fictional fixtures, including intentionally corrupted
archives. Windows- and Tk-dependent tests need an appropriate Windows desktop
session; a headless or other-platform run is not equivalent to the recorded
Windows qualification. Do not point destructive test fixtures at personal
data. The `--ui-self-test` and `--library-self-test` modes share the Library
UI harness; their separate invocation is not two independent test implementations.

### Windows packaging is a separate release operation

The [Library plans application builder](../scripts/build_windows_library_plans.ps1)
and [installer builder](../scripts/build_windows_library_plans_installer.ps1)
use the pinned environment above and, for Setup, the pinned NSIS compiler.
The separate [installer lifecycle harness](../scripts/test_windows_library_plans_installer.ps1)
requires recorded previous-release artifacts. It intentionally fails when those
inputs are missing. A plain source clone does not contain the historical
`build/` and `dist/` qualification inputs; byte-for-byte reproducible
clean-checkout installer builds are not claimed.

Within a prepared release workspace, the
[Library plans build instructions](LIBRARY-PLANS.md#build-and-test) use fresh output
directories and record payload/source hashes. The lifecycle harness installs
and removes a fresh **QA** product identity; it is not a read-only unit test
and must be run deliberately. It does not install or remove the normal user
application. The older root `build_windows.ps1` targets the base Windows
interface, not the current Library entry point. Do not confuse that output
with the qualified Library installer.

## Earlier release gates and ownership

For the progression of implemented guarantees, see the
[5.1 baseline](BASELINE-5.1.0.md),
[compatibility gate](COMPATIBILITY-GATE.md),
[repository gate](REPOSITORY-GATE-5.2.0.md),
[secure archive gate](SECURE-ARCHIVE-GATE-5.3.0.md),
[Sealed File gate](SEALED-FILE-GATE-5.4.0.md),
[Windows integration gate](WINDOWS-INTEGRATION-GATE-5.5.0.md) and
[Windows reliability gate](WINDOWS-RELIABILITY-GATE-5.7.0.md).
Each gate's test count and qualification applies to its own stage.
The [publisher](COMPANY-PUBLISHER-GATE-5.6.0.md) and
[Store submission](STORE-SUBMISSION-GATE-5.6.0.md) records describe distinct
distribution prerequisites; source publication does not imply Store approval
or code signing.

Rat-Trap is source-available under its existing
[noncommercial license](../LICENSE.md), with
[commercial licensing](../COMMERCIAL-LICENSE.md) handled by
**TWO HANDS NETWORK LTD**. Public repository visibility does not grant
unrestricted commercial use. [Credits](../NOTICE.md) and
[third-party notices](../THIRD-PARTY-NOTICES.md) remain part of the project.
