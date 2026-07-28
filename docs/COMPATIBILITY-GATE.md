# Rat-Trap 5.1.1 compatibility gate

Status: release acceptance record

Gate date: 28 July 2026

## Outcome

Rat-Trap 5.1.1 preserves the supported 4.2–5.1 archive families while making
SQLite dispatch fail closed. A file is read only after its family marker,
supported schema version, metadata types, and required database structure have
been validated.

Supported reader inputs:

| Archive family | Compatibility sample | Reader result |
|---|---|---|
| `GMW-SQLITE-1` | 4.2 metadata shape | Inspect, restore, ZIP export |
| `GMW-SOLID-2` | 4.3 metadata shape | Inspect, restore, ZIP export |
| `GMW-SOLID-2` | 4.4 whole-file dedup shape | Inspect, restore, ZIP export |
| `GMW-VAULT-1` schema 1 | 5.0 base Vault shape | Inspect, verify, restore, ZIP export |
| `GMW-VAULT-1` schema 2 | 5.1 structured Vault shape | Inspect, verify, query, restore, ZIP export |

The deprecated `rat_trap.gmw_tool_v4` module now delegates reading and
extraction to the maintained safe engine. Its public nine-field metadata
shape, `main(argv=None)` entry point, and nine-key on-disk writer shape remain
compatible.

## Rejection and integrity cases

The automated gate covers:

- an unknown SQLite family marker;
- an unrelated or structurally incomplete SQLite database;
- an ambiguous database containing both legacy and Vault family structures;
- a future Vault schema;
- an incomplete Vault schema;
- invalid Vault metadata types;
- a changed legacy compressed chunk whose content digest no longer matches;
- a missing legacy file row whose actual inventory no longer matches metadata;
- unsafe archive paths;
- corrupt Vault objects and oversized chunk metadata.

Rejected dispatch inputs do not create extraction or ZIP outputs. Legacy
chunk verification detects corruption during restore; a late failure can
leave files already restored before the bad chunk, so restore remains an
all-files-verified operation rather than a transactional directory swap.

## Fixture provenance

The five small committed archives under `tests/fixtures/formats/` are
**deterministic compatibility reconstructions**. They deliberately reproduce
the supported metadata/schema shapes, but they were not emitted by the frozen
4.2–5.1 executables and must not be cited as historical performance evidence.
`manifest.json` records their SHA-256 hashes, expected source tree, generator
environment, construction method, and original executable reference hashes.

Two authentic larger beta Vaults are retained outside Git as empirical
evidence:

| Archive | Schema | Bytes | SHA-256 |
|---|---:|---:|---|
| `Rat-Trap-Beta-Queryable-Vault.gmw` | 1 | 16,367,616 | `F095309B3A6FFDA902340E9085A280EC474C0BE8865B475405613825E96796E2` |
| `Rat-Trap-Beta-Structured-Vault-5.1.gmw` | 2 | 21,803,008 | `762753311679FFDCD2A692EE1162BB65FBE0A9D567C59394E6BD5B2161B0E3C9` |

## Acceptance commands

```powershell
python -m unittest discover -s tests -v
python -m compileall -q rat_trap tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
.\dist\5.1.1\Rat-Trap.exe --self-test
.\dist\5.1.1\Rat-Trap.exe --self-test-folder <beta-folder>
```

The final source-test count, executable/ZIP hashes, packaged self-test result,
and signing status are recorded in `release-manifests/5.1.1.json`.

## Boundary

This gate proves compatibility against the committed samples and corruption
cases. It does not make `.gmw` archives encrypted or authenticated, and it
does not turn reconstructed fixtures into original release artifacts. Those
limits are kept explicit so commercial product claims and technical evidence
remain separate.
