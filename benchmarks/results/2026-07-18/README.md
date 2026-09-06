# Controlled benchmark evidence — July 2026

These five files are **publication derivatives of existing recorded runs**,
not new measurements. The originals informed Rat-Trap 4.4 engine selection,
5.0 Queryable Vault validation and 5.1 Structured Vault validation. They do
not benchmark the current 5.7 engine or tutorial.4 interface against today's
competing products.

Start with the [technical index](../../../docs/TECHNICAL.md),
[complete benchmark audit](../../../BENCHMARK-AUDIT.md) and
[evidence history](../../../docs/BENCHMARK-HISTORY.md). The
[original 2025 campaign](../../historical/2025-benchmark-record.json) remains
separate and retains its historical evidence label.

## What is included

| File | Recorded grain and coverage |
|---|---|
| [Category baseline](Rat-Trap-Beta-Categories-baseline.json) | 17 methods × 7 categories = 119 rows, each with three create/extract samples; 357 verified cycles |
| [Category hybrid matrix](Rat-Trap-Beta-Categories-hybrid.json) | 9 methods × 7 categories = 63 rows, each with three create/extract samples; 189 verified cycles |
| [Final 4.4 profiles](Rat-Trap-Beta-4.4-final.json) | 3 profiles on the complete beta folder, three repetitions each |
| [5.0 Vault](Rat-Trap-Vault-Beta-benchmark.json) | Search-only Vault build, three queries with 20 timing samples each, verification, extraction and ZIP export |
| [5.1 Structured Vault](Rat-Trap-Structured-Beta-benchmark.json) | Three typed sources, 49,305 rows, reported filter/SQL medians and complete restore validation |

All recorded methods, rows, numeric fields, samples, metadata, booleans and
hashes are retained, including any failure fields present in the originals.
The publication process does not select favorable cells or manufacture
missing trial samples. In particular, the Structured Vault record stores
reported medians rather than all per-query samples; this copy does not add
samples that were not captured.

The controlled category corpus is 462 files and 36,886,704 bytes. The final
folder, including its README and manifest, is 464 files and 36,991,791 bytes.
Do not mix sums of seven independent archives with a single whole-folder
archive. Retained percentage means archive bytes divided by original bytes;
space saved is 100 minus retained percentage. Category summary times in the
audit are sums of the per-category medians, not a separately timed one-pass
archive. The deliberate high-entropy duplicate fixture is a large fraction
of the corpus, so aggregate savings are workload-specific.

## Original evidence and derivative integrity

Before publication, every original file's size and SHA-256 was checked
against the [5.1.0 release manifest](../../../release-manifests/5.1.0.json).
The original bytes remain unchanged outside the source tree. Published
files use UTF-8 with LF line endings. Apart from that newline normalization,
only the four path strings described below were changed; numeric spellings
and the remainder of the JSON text were preserved.

Verification compared the complete parsed objects after restoring those
four original path values, and compared the JSON text with only the stated
redactions and newline normalization applied. Thus numerical results,
sample order, result order, tree hashes and failure information are
unchanged. These checks establish faithful publication of the recorded
results; they do not resolve historical methodological gaps.

### Rat-Trap-Beta-Categories-baseline.json

- Original bytes: `85483`
- Original SHA-256: `21B1BE3E2725FEAB0878B9CB7A7DEC40E04EEEB2429DCE1D99110AAC7E288695`
- Published bytes: `82825`
- Published SHA-256: `2B5D1C5A7CAD9A5ED8892D4A950AF1843CB3129C24FD3DBA26D117D37A5D9ED7`
- Redacted JSON pointers: none; newline normalization only.

### Rat-Trap-Beta-Categories-hybrid.json

- Original bytes: `45590`
- Original SHA-256: `8D17B0AAA877EEABCBC71E95FD74B97F43D650652992B7AEAC32C65715A26F08`
- Published bytes: `44172`
- Published SHA-256: `61FB7256BAD5D7FC0A5C8A669D2325610380D7FCBDD181078FBCE7C35F1290A5`
- Redacted JSON pointers: none; newline normalization only.

### Rat-Trap-Beta-4.4-final.json

- Original bytes: `2537`
- Original SHA-256: `D6439B284058FBA23AEDEE5FD3B30A87E03043236BFA154F9DB4266C3142FBB6`
- Published bytes: `2457`
- Published SHA-256: `B7DEB1A17856AD2A037CC8AA6372C71E093AD140BEEF93AA704907462449985C`
- Redacted JSON pointers: none; newline normalization only.

### Rat-Trap-Vault-Beta-benchmark.json

- Original bytes: `4638`
- Original SHA-256: `D8736A72CABC0FEF06818E5DD79B1DD757AF5B50ED8FC7A0EDFD61A265AC4B76`
- Published bytes: `4440`
- Published SHA-256: `E6799D4C9C8124B19E0605177FFC0FEAD2CFC8A83F496CB72925CCF2A25F9F87`
- Redacted JSON pointers: `/source`, `/vault`.

### Rat-Trap-Structured-Beta-benchmark.json

- Original bytes: `3199`
- Original SHA-256: `46940C3F3B1D50D581921BBDF2780F0D35D55D9FF4E4D5D28A2BAEA5B2807F19`
- Published bytes: `3021`
- Published SHA-256: `4EF1731BB1561371948BE71099664FE159EBB85594B220D85948CD8614792BE5`
- Redacted JSON pointers: `/source`, `/vault`.

The published hashes above describe the LF bytes committed to Git. A local
checkout configured to convert line endings can have a different working-file
hash; compare the raw repository file or normalize only CRLF to LF.

## Exact path redactions

Only these values changed. The bracketed prefix is a deliberate placeholder,
not a runnable filesystem location. The original machine/account path prefix
is not repeated in public documentation.

| File | JSON pointer | Published replacement |
|---|---|---|
| `Rat-Trap-Vault-Beta-benchmark.json` | `/source` | `[REDACTED_LOCAL_WORKSPACE]/work/Rat-Trap-Beta-Test-Data` |
| `Rat-Trap-Vault-Beta-benchmark.json` | `/vault` | `[REDACTED_LOCAL_WORKSPACE]/outputs/Rat-Trap-Beta-Queryable-Vault.gmw` |
| `Rat-Trap-Structured-Beta-benchmark.json` | `/source` | `[REDACTED_LOCAL_WORKSPACE]/work/Rat-Trap-Beta-Test-Data` |
| `Rat-Trap-Structured-Beta-benchmark.json` | `/vault` | `[REDACTED_LOCAL_WORKSPACE]/outputs/Rat-Trap-Beta-Structured-Vault-5.1.gmw` |

All corpus-relative file names, query text, output counts and content hashes
remain intact. The prefix replaces only the private workstation location;
it does not hide which dataset or output Vault was measured.

## Scope and limitations

- These are historical July 2026 runs, published without rerunning them.
  Refer to each JSON's recorded timestamp/version when available; the folder
  date is the campaign label, not a claim that every operation had the same
  timestamp.
- Controlled archive rows record exact round-trip verification. A successful
  check on this corpus is not a guarantee for unrelated files or all storage
  hardware.
- The records do not capture a complete CPU/RAM/OS/runtime/source-revision
  provenance tuple for every operation. Later build manifests supply their
  own build information, not missing benchmark-machine evidence.
- Vault build, verify and extraction numbers are recorded observations, not
  all repeated medians. Query timing repetition differs between the two
  Vault records. Do not imply every number used the same timing protocol.
- Already compressed media, larger data, partial duplicates and different
  machines can yield materially different results. The full audit retains
  competitor/alternative wins and small or negative savings.
- No raw source corpus, empirical Vault or beta corpus ZIP is included here.
  Dataset redistribution terms are separate from the software license. The
  [corpus builder](../../build_beta_data.py) flags its CIFAR image subset for
  local evaluation pending redistribution clarification.
- Current functional test totals and installer QA live in the
  [guided-history release record](../../../release-manifests/guided-history.json),
  not in this performance matrix.
