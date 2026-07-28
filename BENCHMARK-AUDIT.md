# Rat-Trap engine benchmark audit

Date: 18 July 2026
Repository commit reviewed: `c9cae34e0eebdcfc16b9530efe3dccb9aa92c474`

## Decision

Rat-Trap 4.4 uses a hybrid solid archive as its recommended engine:

1. Inventory the folder and hash same-sized files that may be duplicates.
2. Store each exact duplicate file payload once using a safe archive reference.
3. Stream the remaining tar payload through Zstandard level 6.

This retains the repository's strongest general-purpose design while fixing
its exact-duplicate weakness. Fast uses ordinary solid Zstandard level 3 and
skips the hash pass. Smallest uses the hybrid design at Zstandard level 19.
Existing v4.2 SQLite and earlier solid GMW archives remain readable.

## What the repository evidence supports

- The runnable v2 experiment's useful idea is whole-folder tar data compressed
  as one Zstandard stream. It exploits patterns across files.
- The v3/v4 experiments independently compress fixed-size blocks and reuse
  exact blocks. V4 stores them in SQLite, which adds database and per-file
  overhead.
- Several later "versions" are prose or patch text rather than runnable,
  comparable programs.
- The committed v4.2 benchmark cannot support its headline claims: its
  Zstandard baseline fails extraction, some baselines do not preserve folder
  semantics, and reported sizes are inconsistent with the source sizes.
- Consequently, engine selection uses new equivalent-archive tests. Every
  accepted row must restore the same paths, file count, byte count, and SHA-256
  tree digest.

## Corrected public beta corpus

The seven isolated categories contain 462 files and 36,886,704 bytes. Sources
and terms are recorded in `benchmarks/build_beta_data.py` and the beta pack's
README and manifest.

Two data-quality problems were fixed before benchmarking:

- The speech sampler had selected 96 AppleDouble `._*.wav` metadata files.
  It now rejects `__MACOSX`/AppleDouble entries and verifies RIFF/WAVE headers.
  The corrected set contains 96 real WAVs totalling 3,035,170 bytes.
- The original duplicate fixture repeated a small PNG bundle within every
  file, allowing ordinary short-window compression to look like file
  deduplication. It now uses three exact copies of one deterministic,
  high-entropy 8 MiB block. A single copy retains 100.002% under Zstd-6, so the
  category cleanly measures cross-file reuse.

## Category-isolated results

The baseline matrix tested 17 configurations across seven categories, three
times each: 357 verified create/extract cycles. It covered Zstandard levels,
XZ, four fixed-block sizes, multithreading, extension ordering, a 128 MiB
window, and long-distance matching. A focused hybrid pass added 189 verified
cycles.

Archive bytes are shown below; retained percentage is in parentheses. Lower is
better.

| Category (original bytes) | Solid Zstd-6 | Hybrid Zstd-6 | Solid Zstd-6, 128 MiB window | SQLite blocks, 4 MiB | Solid XZ-6 |
|---|---:|---:|---:|---:|---:|
| Text (1,115,394) | 406,068 (36.4%) | 406,066 (36.4%) | 406,066 (36.4%) | 434,176 (38.9%) | 364,672 (32.7%) |
| Structured (5,987,094) | 663,765 (11.1%) | 663,763 (11.1%) | 663,440 (11.1%) | 696,320 (11.6%) | 474,476 (7.9%) |
| PNG images (228,843) | 227,203 (99.3%) | 227,201 (99.3%) | 227,201 (99.3%) | 425,984 (186.1%) | 226,952 (99.2%) |
| WAV audio (3,035,170) | 1,873,869 (61.7%) | 1,873,867 (61.7%) | 1,873,862 (61.7%) | 2,027,520 (66.8%) | 1,622,218 (53.4%) |
| Exact duplicates (25,165,824) | 25,171,525 (100.0%) | 8,391,063 (33.3%) | 8,392,437 (33.3%) | 8,425,472 (33.5%) | 25,170,859 (100.0%) |
| 256 small files (1,115,394) | 420,117 (37.7%) | 420,116 (37.7%) | 420,116 (37.7%) | 1,105,920 (99.2%) | 377,719 (33.9%) |
| Precompressed ZIP (238,985) | 226,772 (94.9%) | 226,771 (94.9%) | 226,770 (94.9%) | 253,952 (106.3%) | 226,556 (94.8%) |

Summing the seven independent category archives gives the following practical
comparison. Times are sums of each category's three-run median.

| Method | Archive bytes | Weighted retained | Compress | Extract |
|---|---:|---:|---:|---:|
| Hybrid Zstd-19 | 11,863,100 | 32.16% | 9.436 s | 1.900 s |
| **Hybrid Zstd-6** | **12,208,847** | **33.10%** | **1.307 s** | **1.972 s** |
| Solid Zstd-6, 128 MiB window | 12,209,892 | 33.10% | 0.726 s | 1.883 s |
| Hybrid Zstd-3 | 12,463,263 | 33.79% | 1.052 s | 2.039 s |
| SQLite blocks, 4 MiB | 13,369,344 | 36.24% | 1.627 s | 1.649 s |
| Solid XZ-6 | 28,463,452 | 77.16% | 15.584 s | 2.165 s |
| Ordinary solid Zstd-6 | 28,989,319 | 78.59% | 0.857 s | 1.997 s |

The hybrid is within 1-2 bytes of ordinary solid Zstd-6 on every category
without duplicates, but removes 16,780,462 bytes on the duplicate category.
It is 1,045 bytes smaller than the 128 MiB-window result and avoids requiring a
large decoder window. It is 1,160,497 bytes smaller than the best SQLite block
configuration in the aggregate. Extension ordering and long-distance matching
did not produce a useful size gain.

## Final application-profile check

The complete corrected beta folder includes its README and manifest: 464 files
and 36,991,791 bytes. Each profile was run three times and every restored tree
was SHA-256 verified.

| Application profile | Archive bytes | Saved | Compress median | Extract median |
|---|---:|---:|---:|---:|
| Fast, solid Zstd-3 | 29,267,301 | 20.88% | 0.761 s | 2.277 s |
| **Balanced, hybrid Zstd-6** | **12,224,927** | **66.95%** | **1.257 s** | **2.130 s** |
| Smallest, hybrid Zstd-19 | 11,885,225 | 67.87% | 9.766 s | 2.836 s |

Smallest saves only another 339,702 bytes (0.92 percentage points) while taking
about 7.8 times as long to compress. Balanced is therefore the default.

## Validation status and limits

Assessment: **Ready to share** for selecting the Rat-Trap 4.4 application
engine.

- Results apply to lossless folder archiving, not media transcoding.
- The beta corpus is diagnostic and deliberately compact; ratios are not
  promises for unrelated folders.
- Exact whole-file deduplication does not find shifted or partial duplicate
  regions inside otherwise different files.
- Timings are from this Windows machine and should be remeasured on release
  hardware when performance claims are published.
- The previously tested `D:\AIOS` folder is intentionally excluded because it
  was an arbitrary folder, not a representative Rat-Trap workload.

Machine-readable evidence:

- `Rat-Trap-Beta-Categories-baseline.json`
- `Rat-Trap-Beta-Categories-hybrid.json`
- `Rat-Trap-Beta-4.4-final.json`

## Rat-Trap 5.0 Queryable Vault validation

The Vault is a separate SQLite/FTS5 workflow, not a replacement for the
Balanced archive. It was built and tested against the same corrected beta
folder (464 files, 36,991,791 bytes).

| Metric | Result |
|---|---:|
| Vault size | 16,367,616 bytes |
| Retained | 44.25% |
| Build time | 2.791 s |
| Filenames searchable | 464 |
| Text contents indexed | 264 files |
| Unique compressed objects | 463 |
| Duplicate data reused | 16,777,216 bytes |
| Median filename/content query | 1.8-1.9 ms |
| Full object verification | 0.355 s |
| Full extraction | 1.055 s |
| ZIP export | 1.856 s |

The Vault is 4,142,689 bytes larger than the 12,224,927-byte Balanced archive,
which is the expected cost of SQLite tables and the full-text index. Search
found binary filenames, Shakespeare phrases, and extensionless UCI structured
text. Full restoration, selective extraction and ZIP export all passed.

Machine-readable Vault evidence: `Rat-Trap-Vault-Beta-benchmark.json`.

## Rat-Trap 5.1 Structured Vault validation

Version 5.1 materialises recognised structured sources as typed relational
SQLite tables while retaining the original compressed files. The corrected
beta corpus contains UCI train/test data plus a JSON manifest. UCI `.names`
metadata was applied to both splits so columns such as `age`, `workclass`, and
`hours_per_week` are directly queryable.

| Metric | Result |
|---|---:|
| Source files / bytes | 464 / 36,991,791 |
| Structured Vault size | 21,803,008 bytes |
| Retained | 58.94% |
| Build time | 8.712 s |
| Relational sources | 3 |
| Queryable rows | 49,305 |
| `adult.data` | 32,561 rows × 15 columns |
| `adult.test` | 16,281 rows × 15 columns |
| JSON manifest | 463 rows × 3 columns |
| Median typed text filter | 48.8 ms |
| Median numeric SQL query | 17.1 ms |
| Full verification | 0.641 s |
| Full extraction | 1.559 s |

The 5.1 Vault is larger than the 5.0 search-only Vault because 49,305 rows are
stored as directly queryable SQLite values. The entire 464-file tree restored
to the same SHA-256 digest. Typed filtering, read-only SQL, and result export
were also verified. These timings describe this compact beta corpus and are
not performance promises for unrelated datasets.

Machine-readable evidence: `Rat-Trap-Structured-Beta-benchmark.json`.
