# Store-folder validation

Local Windows x64 checks for application **5.7.0.8**, support
**5.7.0-desktop-preview.2-library.2**, on 20–21 October 2026.
This remains an unsigned preview with the unchanged 5.7.0 storage engines.

## Source tests

- Full discovery: **577 tests in 521.682 seconds**, passed with one native
  Windows symlink-permission skip. This run preceded the final resumed-backup
  disclosure and catalogue-lock changes below.
- Final focused run: **92 tests in 70.868 seconds**, passed with the same skip:
  38 Library backend, 19 Store-folder backend and 35 Library interface tests.
- The intermediate 91-test run exposed a concurrent rollback-journal guard
  race. The fix serializes short same-process catalogue checks/transactions;
  it does not relax link, reparse-point or schema validation. A deterministic
  concurrent guard-lock regression was added and passed in the final run.
- Repeated final-code concurrency stress: **40 tests in 35.562 seconds**,
  all passed (20 repetitions each of the two concurrent-catalogue tests).
- The final resumed-backup tests check that completing an earlier ready job
  keeps its exact ID and explicitly warns that it can represent older source
  contents. It is not silently described as a fresh capture of current files.

These are separate runs, not one combined test count. Full discovery was not
repeated after those final narrow fixes; the focused run covers the final
Library code. Tests use generated data, temporary catalogues and fixture copies.

Commands from the repository root:

```powershell
.\.venv\Scripts\python.exe -W error::ResourceWarning -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -W error::ResourceWarning -m unittest tests.test_library_storage tests.test_library tests.test_library_app -q
.\.venv\Scripts\python.exe windows_library_preview.py --store-folder-self-test
```

## Coverage

Archive create/extract and encrypted create/unlock compare recovered bytes.
The versioned acceptance test saves a folder, edits and adds files, saves
again, reopens the catalogue and restores the exact first version separately.
The earlier bytes match and current source files remain unchanged.

Other cases cover no-overwrite publication including a competing destination,
source changes, overlapping paths, unrelated directories, failed engine calls,
successful publication with failed catalogue registration, project ownership,
idempotent snapshot events, cancellation, busy/tutorial guards, capture of the
original project during asynchronous work, draft preservation and exact-version
workspace routing. The compact/high-DPI geometry checks include the new controls.

## Packaging and qualification

The final executable runs all five packaged modes successfully:
`--self-test`, `--ui-self-test`, `--tutorial-self-test`, `--library-self-test`
and `--store-folder-self-test`. Its receipt records 35 checked source hashes,
the pinned runtime/dependencies and payload checksums.

Final installer hashes and isolated lifecycle results are recorded in
`release-manifests/library-store.json` and the sanitised
`packaging/direct/qa-results-library-store.json`. Raw reports stay under ignored
`build/library-qa` because they contain local paths. Qualification uses the
recorded 5.7.0.7 payload and a fresh QA identity, not the normal installed app.

The build ran under PowerShell 7.6.5. An attempted Windows PowerShell 5.1
preflight was blocked by the host execution policy; that policy was not changed,
and this stage does not claim a successful 5.1 preflight.

## Limits

Same-host Windows 10 build 19045 only: not a clean VM, Windows 11 qualification,
interactive-wizard visual acceptance, cryptographic audit, SmartScreen
reputation, signing or Store approval. No automatic source deletion, scheduling,
calendar integration, normal-user app installation or GitHub publication is part
of this stage. Keep originals and independent backups; manually test with copies.
