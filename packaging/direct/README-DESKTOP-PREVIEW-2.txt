RAT-TRAP DESKTOP PREVIEW 2
Preview application: 5.7.0-desktop-preview.2
Based on the Rat-Trap 5.7.0 engines
TWO HANDS NETWORK LTD

WHAT THIS IS

This is a separate, unsigned Windows 64-bit preview with easier file selection,
clearer operation status, and actions for completed results. It preserves the
earlier Desktop Preview 1 and the frozen Rat-Trap 5.7.0 beta; it does not replace
them. Its executable is named Rat-Trap-Desktop-Preview-2.exe.

This is not a Microsoft Store release, a signed installer, or a certified final
product. Compression algorithms and archive formats are unchanged. Interface changes
do not imply better compression ratios, new encryption, or different security
guarantees. Results depend on your files and the operation you choose.

OPEN THE PREVIEW

1. Save the portable ZIP in a folder you can find, such as Downloads.
2. Right-click the ZIP and select Extract All. Choose a NEW folder.
3. Open that folder and double-click Rat-Trap-Desktop-Preview-2.exe.

Extract everything first; do not run the application from inside the ZIP.
Keep the Legal folder and other included documents with the executable. No
separate Python installation, Rat-Trap account, or internet connection is
needed for operations on local files. This package installs no file-type
associations and does not replace an earlier Rat-Trap installation.

WHAT CHANGED IN PREVIEW 2

File selection: pickers start from a useful existing folder where possible.
You can reuse the last completed result during the same application session.
These conveniences do not create a new persistent recent-file history.

Progress: the interface shows the operation's reported stage and elapsed time.
Elapsed time is time already spent, not an estimate of time remaining. Where
the engine does not provide measurable progress, the preview does not invent
a completion percentage or an estimated finish time.

Completion: the result panel offers actions appropriate to the output. Open
archive selects a supported archive inside Rat-Trap; it does not automatically
decrypt, extract, or restore it. Show in folder opens Windows File Explorer
only when you explicitly click that action. Review the selected path and
operation before starting more work.

Windows compatibility: single-file protection now handles Windows' synthesized
execute permission bits for .exe, .com, .bat and .cmd filenames. Previously,
the source-change guard could incorrectly reject an unchanged file. File
identity, read/write permission, modification and content checks remain active.
The fix does not execute these files or change archive formats.

WINDOWS MAY WARN OR BLOCK

The preview is not Authenticode-signed. Windows, SmartScreen, antivirus
software, or an organisation's policies may warn about or block it. A warning
alone does not establish whether a download is safe or unsafe. Obtain the
preview from a trusted supplier. If blocked or uncertain, stop and ask your
administrator or the support contact below. Do not disable security protection
to run the preview.

SHA256SUMS.txt lists checksums for every other file in this package. These can
detect damaged or changed files. Checksums delivered with a download do not
independently prove its publisher and do not replace a digital signature.

TEST WITH COPIES ONLY

Keep independent backups of important data. For a first test:

1. Put COPIES of a few ordinary files in a small test folder.
2. Choose the appropriate compression/archive operation in the preview.
3. Save the output outside the input folder, under a new name.
4. After completion, review the result panel and select the archive to inspect.
5. Restore into a different, empty test folder.
6. Compare the restored files with your originals, including their contents.

Do not overwrite originals or use a preview archive as your only backup.
Keep enough free space for both the operation and restored files. Wait for
work to finish before closing the preview or disconnecting storage. A timer
that is still running does not prove that an underlying operation is healthy.

ENCRYPTION AND RECOVERY ARE SEPARATE CHOICES

Compression alone is not encryption. Encryption is optional and must be
explicitly selected for supported formats. A .gmw archive is not necessarily
encrypted, and a live repository is not encrypted just because Rat-Trap
created it. Read the operation's prompts before relying on protection.

Keep passwords and .rtrk recovery-key files safe and separate from protected
data. A matching recovery key can unlock that data. Losing the required
password and recovery material can make it unrecoverable. Do not send recovery
keys or passwords to support. Restoration can produce unencrypted files.

UPDATES, PRIVACY, AND REMOVAL

This portable preview has no automatic updater. Download later previews only
from a trusted source and extract them into separate folders. Local processing
does not automatically upload your files or diagnostics. If you choose a
network drive or cloud-synchronised folder, that storage service's behaviour
still applies. Read PRIVACY.md for details.

To remove the preview, close it and delete only its extracted application
folder. First move out any archives, restored files, recovery keys, or other
data you saved inside that folder. Files stored elsewhere are not removed
automatically. Local diagnostics may remain under:
%LOCALAPPDATA%\Two Hands Network Ltd\Rat-Trap\Diagnostics

SUPPORT AND LICENCES

Support and licensing: TWO HANDS NETWORK LTD
Email: ollett123123@outlook.com

Describe the version as "Rat-Trap Desktop Preview 2 (5.7.0-desktop-preview.2)".
Include your Windows version, what you tried, and a small reproduction using
non-confidential test files. Remove personal information from screenshots and
error reports. Never send passwords, recovery keys, private archives, or
confidential data. See SUPPORT.md for additional guidance.

Read Legal\LICENSE.md and Legal\COMMERCIAL-LICENSE.md before use. Personal and
non-commercial use is covered by the included public licence; commercial use
requires a separate written agreement with TWO HANDS NETWORK LTD.

Legal contains the recorded 5.7.0 dependency licences, notices, and software
bills of materials. Legal\README-WINDOWS.txt is preserved from that baseline;
this README-FIRST.txt describes the separate Desktop Preview 2 package.

Compressor designed and built by Glyn Evans.
Motion-TimeSpace work by Martin Ollett.
