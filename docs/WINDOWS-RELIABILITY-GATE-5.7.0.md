# Rat-Trap 5.7.0 Windows reliability gate

Date: 30 July 2026

Status: passed for the portable Windows beta and structural development MSIX.
This is not a signed public release or a Microsoft Store submission.

## Purpose

Rat-Trap 5.7.0 hardens the Windows application while TWO HANDS NETWORK LTD is
waiting for Partner Center business verification. The frozen 5.6.0 executable
and MSIX remain unchanged.

## User-visible reliability changes

- Closing the main window is blocked while an archive, backup, protection,
  verification, search, extraction, restore or export operation is active.
- Worker threads publish completion through a thread-safe queue. Only the Tk
  main thread reads that queue, updates controls or schedules another poll.
- Progress text is coalesced instead of placing one UI event into the queue for
  every file, and per-task tokens prevent a stale poller consuming a later
  task's result.
- Background-worker failures always restore the progress indicator and action
  controls before an error is shown.
- Setup, queue creation, thread construction, scheduling, thread start, missing
  result, progress rendering and control-restoration failures are handled.
- Failures in completion callbacks are caught after the controls are restored.
- Tk callback failures that would normally disappear in a windowed executable
  receive a short `RT-XXXXXXXXXX` error reference.
- Startup failures are recorded locally and shown with the same safe reference
  format when a window can be created.
- A new About tab states the publisher, version, privacy boundaries, support
  contact and local diagnostic location.

If the UI poller itself fails while a worker is still active, Rat-Trap does not
wait for that worker on Tk's main thread. It leaves close protection enabled,
reports the degraded state and permits close after the worker is no longer
alive.

There is no cooperative cancellation mechanism for a genuinely hung
operation. Rat-Trap does not claim that an abruptly powered-off computer,
killed process, storage-device failure or operating-system termination can be
made safe by the window close handler.

## Local diagnostic boundary

The new diagnostic component:

- contains no networking or upload code;
- writes rotating JSON-lines records below the current user's local application
  data directory;
- defaults to 256 KiB per file with three backups and enforces hard limits of
  5 MiB and five backups;
- records an event code, timestamp, short support ID, allowlisted bounded
  operational fields and exception type;
- never persists exception messages;
- drops unknown fields and redacts paths, filenames, email addresses, labelled
  credentials, recovery material, long token-like values and free-form text;
- silently disables itself if its directory, file, rollover or shutdown
  operation fails.

There is no claim that diagnostics are anonymous. They are deliberately
minimal local operational records. A user can inspect or delete them while
Rat-Trap is closed.

## Windows package activation boundary

Namespace-aware XML tests prove that the manifest contains exactly two file
associations:

| File type | Activation |
|---|---|
| `.rtsf` | `--open-sealed "%1"` |
| `.gmw` | `--open-archive "%1"` |

Both use single-selection activation and only preselect a screen. Opening an
associated file never authenticates, decrypts, verifies, extracts or replaces
anything automatically. `.rtrk` recovery-key files are explicitly not
associated. No alternate verbs, executable overrides or entry points are
declared.

The packaged application remains a medium-integrity classic desktop
application with `runFullTrust`. Package integrity enforcement is declared.

## Source verification

The complete source test suite passed:

```text
221 tests passed
0 failed
```

This includes 11 diagnostics tests, 19 Windows lifecycle tests, four
namespace-aware manifest tests and all pre-existing archive, security, Sealed
File, repository, Vault, structured-data, compatibility and UI tests. An
independent blocker review also reran 59 focused diagnostics, reliability,
security and Sealed File UI tests with no failure or release blocker.

`python -m compileall -q rat_trap tests` passed. `git diff --check` reported no
whitespace errors; the only messages were normal Git LF-to-CRLF working-copy
notices on Windows.

## Frozen executable verification

Path:

```text
dist/5.7.0/Rat-Trap.exe
```

- Size: 18,038,953 bytes
- SHA-256:
  `2FDBC470CA51E04E7F38459F0C58089BF487965333C6AE21B6E2886CB14AF273`
- File version: 5.7.0
- Product version: 5.7.0
- Company: TWO HANDS NETWORK LTD
- Authenticode: NotSigned
- Packaged self-test: exit code 0
- Packaged beta-folder test: exit code 0
- Beta-folder fixture: 464 files, 36,991,791 bytes

The packaged self-test constructs all eight GUI tabs and exercises compression,
extraction, encrypted archives, password and recovery rotation, tamper
rejection, Sealed Files, repository snapshots, encrypted repository export,
Vault search and structured-data queries.

The packaged beta-folder test ran the `fast`, `balanced`, `smallest` and
`vault` profiles against the preserved beta dataset, extracted each result and
compared a deterministic tree digest, file count and total byte count. It also
performed an encrypted `balanced` archive round trip of the same dataset.

## Development MSIX verification

Path:

```text
dist/msix/5.7.0/development/
  Rat-Trap-Windows-5.7.0-x64-unsigned.msix
```

- Size: 17,909,407 bytes
- SHA-256:
  `A246E1A41D1E0ACEDDA734EDA825DFBDFC4FF1B50E3AA950757F723162C1CF4B`
- Package version: 5.7.0.0
- Entries: 29
- Legal payload entries: 20
- Embedded executable hash matches the frozen executable exactly
- MakeAppx pack and independent unpack verification: passed
- Authenticode: NotSigned
- Temporary packaging residue: zero files

This package uses the explicit non-permanent development identity. It is not a
Store package and is not intended for public installation.

## Store identity gate

The 5.7 Store builder was run while the Partner Center identity remained
pending:

```text
exit code: 1
artifacts created: 0
```

It will not build a Store upload package until the publisher profile says the
identity is assigned and contains the exact Partner Center package Name,
Publisher and PublisherDisplayName. No production identity was guessed.

## Copied beta artifacts

The verified artifacts were copied without changing their bytes to:

```text
../../outputs/Rat-Trap-5.7.0.exe
../../outputs/Rat-Trap-Windows-5.7.0-x64-company-development.msix
```

## Remaining external gates

- Partner Center business verification
- Reserved product name and exact Store identity
- Microsoft signing and certification
- Clean Store screenshots and IARC completion
- Public HTTPS privacy and support locations
- Signed install, upgrade, association, repair and uninstall lifecycle testing
- Windows App Certification Kit testing against the final Store-identity
  package

No commit, tag, push, Store reservation, Store submission or public release was
performed by this gate.
