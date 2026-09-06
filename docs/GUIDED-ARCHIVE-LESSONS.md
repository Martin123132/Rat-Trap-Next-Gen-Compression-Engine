# Compression and restore lessons

The second guided update adds two ready lessons to **Show me how…**:

- **Compress a folder** — source, safe archive location, compression profile,
  actual creation and interpreting the size result.
- **Restore your files** — archive, separate destination, actual extraction
  and a separate SHA-256 comparison of the recovered sample contents.

**Find a file inside a Vault** remains available. Protection/recovery and
backup-history walkthroughs are still explicitly marked as coming later.

## Try the lessons

Close Rat-Trap after any active operation finishes. Use the installer in the
parent workspace's `outputs/00 - START HERE` folder, then open the existing
**Rat-Trap Desktop Preview 2** Start-menu entry. Click **Show me how…**, choose
a lesson and press **Start guided practice**.

Each lesson prepares its own three fictional documents in a new temporary
folder. Restore can be taken independently; it makes its own sample archive.
No lesson reads a personal source folder or opens a personal archive.

The compression lesson uses the normal Fast, Balanced or Smallest engine
profile. Its archive destination is outside the sample source. Encryption is
off for this lesson and unrelated controls are disabled. The real byte totals
appear inside the workspace. The sample contains repetitive text: its savings
are an educational example, not a benchmark or a prediction for personal data.
Already-compressed media may save much less space or grow after archiving.

The restore lesson creates a separate, previously absent destination. After
extraction, click **Check restored files** to compare actual restored bytes
against the original fictional content's SHA-256 hashes. Missing, changed,
unexpected or unsafe paths prevent the lesson from reporting a match. The
comparison does not rely only on the extraction operation's success message.
This explicit comparison button is a practice aid, not a new general-purpose
verification claim for every archive or file type.

## Back, Exit and keeping existing work

Back revisits an instruction. If an archive or restored folder already exists
from the current run, its action changes to **Review created archive** or
**Review restored files**; reviewing never overwrites it. To try a different
compression profile, go Back and load a fresh sample folder.

Back and Exit wait for an active worker before changing state or cleaning up
its files. Escape requests Exit. Previous paths (including quoted paths),
profile/encryption selections, search results, completion details and workspace
scroll positions are restored on exit. The tutorial's profile list and width
are temporary, so the normal Queryable Vault option returns afterward.

Only unchanged, individually recorded practice files are removed, followed by
empty owned directories. Changed or unexpected files are preserved. Cleanup
does not recursively remove folders, follow substituted links/junctions, or
run while a worker owns the practice session. A crash or force-quit may leave
fictional temporary files; no secure-deletion guarantee is made.

The coach's explanation scrolls separately from Back/Next/Exit. Workspace
scrolling brings the current control into view horizontally and vertically;
result panes have their own scrollbars. Larger display scaling is included in
internal layout checks, but native visual acceptance is a separate check.

## Build and release scope

Application support label: `5.7.0-desktop-preview.2-tutorial.2`.
Numeric application/installer version: `5.7.0.4`.
Publisher: **TWO HANDS NETWORK LTD**.

The app retains its existing installation identity, filename, folder and
Start-menu entry. This is an unsigned private preview, not a Store release,
automatic updater, new compression format or encryption change. Do not disable
Windows security protection if it blocks Setup; report the message instead.
Use independent backups and copies for any personal-file tests.

The implementation extends `rat_trap/guided_app.py` and the tutorial catalogue;
sample ownership and engine wrappers are in `rat_trap/archive_tutorials.py`.
The existing compression/encryption/restore engine modules were not edited for
this stage. Prior tutorial source was hash-verified and privately copied before
editing; prior binaries, installer builders and release records remain intact.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe windows_guided_preview.py --tutorial-self-test
.\scripts\build_windows_guided_lessons.ps1
.\scripts\build_windows_guided_lessons_installer.ps1
.\scripts\test_windows_guided_lessons_installer.ps1
```

The new installer lifecycle harness upgrades the prior guided `5.7.0.3` build
to `5.7.0.4` under one fresh QA-labelled identity, not the ordinary installation.
Private build payloads stay under `dist`; no extra public portable ZIP is added.
The only current handoff remains `outputs/00 - START HERE/Install Rat-Trap.exe`.

Verified on 6 September 2026: **377 source tests passed**, including 47 new
archive-lesson tests. All three packaged self-test entry points passed, then
passed again from the upgraded QA installation. **224 installer lifecycle
checks passed**, with no cleanup errors. The normal user installation was not
run or replaced by these checks. See the
[sanitized QA record](../packaging/direct/qa-results-guided-lessons.json).
