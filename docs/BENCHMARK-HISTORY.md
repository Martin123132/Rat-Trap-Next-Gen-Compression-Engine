# Rat-Trap benchmark history and evidence status

This file preserves what was measured, what can safely be inferred, and which
results may be used for current product decisions.

## Evidence labels

| Label | Meaning |
|---|---|
| `historical_unvalidated` | A genuine recorded result whose environment or equivalence was not fully captured |
| `round_trip_verified` | A repeatable run that restored paths and bytes and compared an exact tree digest |
| `claim_ready_with_scope` | Suitable for a public claim only with the named corpus, method, machine/date, and limitations |
| `commercial_narrative` | Positioning or ambition, not a benchmark measurement |

## 2025 historical campaign

The repository contains a substantial campaign using Tiny Shakespeare,
CIFAR-10, Speech Commands, and UCI Adult data. It tested GMW Zstandard levels,
tar.gz, tar.bz2, tar.xz, and—in the final matrix—raw Zstandard, Brotli, and LZ4.
The main exact ten-method output is preserved in
[`benchmarks/historical/2025-benchmark-record.json`](../benchmarks/historical/2025-benchmark-record.json).

The record is real and useful for provenance. It is labelled
`historical_unvalidated`, because:

- one trial was recorded per final cell;
- CPU, RAM, OS, Python and dependency versions were not captured;
- dataset hashes and exact file manifests were not saved;
- the main matrix did not verify archive restoration;
- GMW used an in-memory tar stream while some comparators used intermediate
  disk I/O;
- raw-codec comparators did not preserve directory/archive semantics;
- repeated byte concatenation distorted the large raw-codec timings.

The 2025 README headline calculations have the following status:

| Claim | Evidence status |
|---|---|
| Up to 93x faster | Arithmetically present for image GMW Zstd-1 versus tar.xz (`122.9488 / 1.3124 = 93.68`) but historical and narrowly scoped |
| 4.5x image speedup | Present for GMW Zstd-3 versus tar.gz (`11.4635 / 2.5405 = 4.51`) with historical scope |
| 26.8x audio speedup | Present for GMW Zstd-3 versus tar.xz (`236.6967 / 8.8216 = 26.83`) with historical scope |
| 4x to 8x faster than tar.gz across the board | Not supported; fastest-profile rows range about 3.20x to 8.73x |
| Text output 4x smaller than LZ4 | Not supported by the preserved cells |
| Structured output 1.6x smaller than LZ4 | Supported for the named historical fastest GMW profile |

Words such as “undisputed,” projections of industry savings, and claims that
another format is obsolete are commercial narrative. They are not transformed
into evidence by appearing next to a benchmark table.

Historical source locations:

| Commit | Artifact | Role |
|---|---|---|
| `a4d8f61fbc85bb527acf15f26bd9ce2461fe9bcd` | `benchmark the compression ratio and time for both methods.` | Initial transcript and direct GMW/tar.gz run |
| `f3f0fd58f9642b924f5cc22366fdfebb41746735` | `benchmarking 2.0 full run` | Main exact and rounded campaign output |
| `732b6121176ea3af265fec2be99c030e26ca3860` | `Rat-Trap 2.0 benchmarking single code` | Consolidated harness |
| `21b9705283e55ca9a011106122782515eff9ddb3` | `Rat-Trap 4.0` | Fixed-block dedup results and analysis |
| `92a39264205612897496062343da0eeb6a5ead7a` | `Rat-Trap 4.2` | SQLite summary and implementation material |

## 2026 controlled engine selection

The current application profiles were selected using a corrected,
category-isolated beta corpus and equivalent folder archives. Accepted runs
had to restore the same paths, file count, byte count, and SHA-256 tree digest.

The diagnostic corpus contains:

- text;
- structured data;
- PNG images;
- real RIFF/WAVE audio;
- deterministic high-entropy exact duplicates;
- many small files;
- a precompressed ZIP.

Across the complete 464-file, 36,991,791-byte folder:

| Profile | Archive bytes | Saved | Compress median | Extract median | Exact restore |
|---|---:|---:|---:|---:|---|
| Fast, solid Zstd-3 | 29,267,301 | 20.88% | 0.761 s | 2.277 s | Yes |
| Balanced, hybrid Zstd-6 | 12,224,927 | 66.95% | 1.257 s | 2.130 s | Yes |
| Smallest, hybrid Zstd-19 | 11,885,225 | 67.87% | 9.766 s | 2.836 s | Yes |

Balanced became the default because Smallest saved only another 339,702 bytes
while taking roughly 7.8 times as long to create on this run.

Queryable Vault validation on the same folder recorded:

- schema 1 search Vault: 16,367,616 bytes, 464 files, exact restore;
- median filename/content queries around 1.8–1.9 ms;
- schema 2 structured Vault: 21,803,008 bytes and exact restore;
- 49,305 typed rows across three structured sources;
- median typed text filter 48.8 ms and numeric SQL query 17.1 ms.

The controlled corpus is deliberately compact and includes a large exact
duplicate fixture. These numbers describe this test, not an expected saving
for every folder.

## Evidence locations

Human-readable methodology and full current tables:

- [`BENCHMARK-AUDIT.md`](../BENCHMARK-AUDIT.md)

Machine-readable current evidence, preserved externally with hashes in the
5.1 manifest:

- `Rat-Trap-Beta-Categories-baseline.json`
- `Rat-Trap-Beta-Categories-hybrid.json`
- `Rat-Trap-Beta-4.4-final.json`
- `Rat-Trap-Vault-Beta-benchmark.json`
- `Rat-Trap-Structured-Beta-benchmark.json`

The arbitrary `D:\AIOS` trial is intentionally excluded from product evidence.
It was a quick application check, not a representative corpus.

## Rule for future benchmark claims

A new comparison enters the evidence lane only when it records:

1. source revision and command;
2. hardware, OS, runtime, and codec versions;
3. corpus provenance, file manifest, and hashes;
4. archive-equivalent semantics;
5. warmups, repetition count, all samples, and summary statistic;
6. compression and extraction timing boundaries;
7. exact round-trip verification;
8. failures and excluded rows as data, not deleted observations.

Public copy may select Rat-Trap’s strongest truthful rows. The backend evidence
must retain the full matrix, including competitor wins and Rat-Trap losses.
