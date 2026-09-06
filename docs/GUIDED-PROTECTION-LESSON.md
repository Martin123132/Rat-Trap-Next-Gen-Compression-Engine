# Protect a file and recover it

The third guided update adds **Protect a file and recover it** to **Show me
how…**. The Vault search, compression and restore lessons remain available;
backup history is still marked as coming later.

## Try the lesson

Let any operation finish, close Rat-Trap, then run the installer in the parent
workspace's `outputs/00 - START HERE` folder. Open the existing **Rat-Trap
Desktop Preview 2** Start-menu entry. Choose **Show me how…**, **Protect a file
and recover it**, then **Start guided practice**.

The thirteen steps use the real Secure files workspace: select a fictional
source, choose a generated `.rtsf` destination, acknowledge the disposable
practice password, choose a separate practice recovery-key folder, protect,
review, select the sealed sample, select a new plaintext destination, restore
with the password, recover a second copy with only the key, compare both
copies, and finish. Only the highlighted action is enabled; Back and Exit stay
available. Longer explanations and results can be scrolled.

The normal Sealed File engine performs real encryption and restoration. The
password restore supplies only the generated password; the second operation
supplies only the matching `.rtrk` key and omits the password argument entirely.
The final check independently compares both recovered copies with the known
fictional contents' SHA-256 hash. Missing, changed, unexpected or unsafe output
prevents a success result. The comparison is a practice aid, not a new general
verification feature for all personal files.

## Credentials and plaintext

No personal source, password or key is requested. The generated practice
password is held in process memory, not shown, logged, copied to the clipboard
or written as a password file. The recovery key is a real disposable `.rtrk`
file in a separate sibling folder. Its contents are not displayed. An opaque
sealed filename avoids exposing the original fictional filename in that name.

A matching recovery key is an alternative credential: anyone with it can
unlock the corresponding Sealed File without its password. For real files,
keep strong unique passwords and recovery keys safe. Losing both means Rat-Trap
cannot unlock that encrypted copy. Keep independent backups. The temporary key
folder demonstrates separation only; it is not a secure backup location.

The source, restored copies and the engine's temporary intermediate are
plaintext. Clearing a Python password reference is not secure memory erasure.
Cleanup is not secure disk erasure. This stage does not change the existing
encryption, key derivation, compression, archive format or credential dialogs.

## Preserving existing work

Practice accepts only its generated paths. Original paths, nested Secure files
tab, acknowledgements, other settings, results and workspace position are
restored on Exit. Ordinary dialogs and unrelated direct callbacks are blocked
during practice. Completed actions become read-only reviews: Back never
overwrites an existing sealed file, key or restored copy. Load a fresh sample
to repeat the actual operation.

Back and Exit wait for an active worker. A stale completion cannot advance a
different session. Cleanup removes only unchanged, identity-and-hash-recorded
files and empty owned directories; modified or unexpected data is preserved.
Linked or substituted paths are refused. There is no recursive folder removal.
A crash or force-quit may leave fictional temporary files. Ownership checks
are conservative safety checks, not protection against a hostile same-user
process continuously racing filesystem changes.

## Private release scope

Support version: `5.7.0-desktop-preview.2-tutorial.3`.
Numeric application and installer version: `5.7.0.5`.
Publisher: **TWO HANDS NETWORK LTD**.

The installation identity, folder, executable and Start-menu entry are unchanged.
This remains an unsigned private preview, not a Store release or automatic
updater. No additional public portable ZIP is introduced. Do not disable Windows
security if it blocks the installer; report the message instead.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe windows_guided_preview.py --tutorial-self-test
.\scripts\build_windows_guided_protection.ps1
.\scripts\build_windows_guided_protection_installer.ps1
.\scripts\test_windows_guided_protection_installer.ps1
```

The installer harness upgrades the preceding `5.7.0.4` preview to `5.7.0.5`
under a fresh isolated QA identity, never the ordinary installation. Prior
release artifacts and records are retained. Tk internal geometry and workflow
tests are not a substitute for native visual acceptance or a clean Windows 11
test. Actual verification results are recorded separately with release hashes.

Verified on 6 September 2026: **422 source tests passed**, including 45 new
protection-lesson tests. All three packaged self-tests passed and passed again
from the upgraded isolated installation. **224 installer checks passed**, with
zero cleanup errors. The ordinary user installation was not run or modified.
See the [sanitized QA record](../packaging/direct/qa-results-guided-protection.json).
