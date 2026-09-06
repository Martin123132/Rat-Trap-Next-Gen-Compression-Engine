# Rat-Trap format compatibility fixtures

Five small folder archives, one encrypted schema-1 archive envelope, and one
5.4 Sealed File turn Rat-Trap's reader-compatibility policy into an executable
test. Every test run checks the committed byte size and SHA-256, inspects the
format, restores it, and compares its output with the expected inner archive,
single file, or canonical source tree.

## Provenance classification

The fixtures are **deterministic compatibility reconstructions**, not archived
customer data and not benchmark evidence. No small `.gmw` samples produced by
the original 4.2–4.4 releases survived in the workspace or their release ZIPs.
The reconstruction script therefore uses the preserved 5.1 format
implementations and deliberately emits the metadata/schema shape of each
supported release:

- 4.2: only the original nine `GMW-SQLITE-1` metadata keys;
- 4.3: `GMW-SOLID-2` without the later dedup metadata fields;
- 4.4: `GMW-SOLID-2` with exact whole-file deduplication;
- 5.0: the unchanged base Vault schema without schema-2 structured tables;
- 5.1: the current Vault schema 2 with a typed CSV table;
- 5.3: a deterministic `RAT-TRAP-ENCRYPTED-1` schema-1 envelope over the
  committed 4.3 solid fixture;
- 5.4: a deterministic `.rtsf` Sealed File using that unchanged encrypted
  schema-1 envelope around an exact one-file `GMW-SOLID-2` inner archive with
  profile `sealed-file`.

The generators ran twice with identical bytes and hashes. Their Python,
SQLite, Zstandard, fixed timestamps, archive hashes, source bytes, and
original-writer executable references are recorded in `manifest.json`.

The encrypted fixtures deliberately have public test credentials. The 5.3
fixture's `.rtrk` and JSON interoperability vector publish every key, salt,
nonce, identifier, canonical JSON value, derived key, AAD value, ciphertext,
and output hash needed for an independent implementation check. The 5.4
fixture commits its `.rtsf`, independent `.rtrk`, and exact decrypted inner
`.gmw` so both password and recovery-key readers can be checked byte for byte.
Never use either fixture's credentials for private data.

The workspace also retains authentic large schema-1 and schema-2 beta Vaults.
Their hashes are recorded in the manifest as external empirical evidence, but
their 16–22 MB payloads are not duplicated in Git.

## Regeneration policy

Normal tests never regenerate fixtures. To reconstruct them deliberately:

```powershell
python tests\fixtures\formats\generate_fixtures.py --replace
python tests\fixtures\formats\generate_fixtures.py --secure-only --replace
python tests\fixtures\formats\generate_fixtures.py --sealed-only --replace
```

`--replace` is mandatory when golden files already exist. A regenerated
archive must be reviewed as a compatibility change; update `manifest.json`
only after verifying the reason for every changed byte or semantic field.

Do not describe these reconstructed fixtures as archives emitted by the
original frozen executables. The executable hashes are provenance references
for future work should authentic tiny samples be produced and independently
verified.
