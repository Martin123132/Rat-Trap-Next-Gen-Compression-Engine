"""Task-based tutorial copy and disposable, non-confidential practice data."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import vault_engine


@dataclass(frozen=True)
class TutorialSpec:
    id: str
    title: str
    description: str
    available: bool = False


TUTORIALS = (
    TutorialSpec("vault-search", "Find a file inside a Vault", "Search indexed text, choose a result and preview it without restoring the whole folder.", True),
    TutorialSpec("compress", "Compress a folder", "Choose a folder, create an archive and understand the result.", True),
    TutorialSpec("restore", "Restore your files", "Restore into a new folder and check the recovered files.", True),
    TutorialSpec("protect", "Protect a file and recover it", "Understand passwords, Sealed Files and separate recovery keys.", True),
    TutorialSpec("history", "Browse backup history", "Save two versions, choose an older snapshot and check its restored contents.", True),
)


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    where: str
    action: str
    why: str
    expect: str


VAULT_SEARCH_STEPS = (
    Step("navigate", "Open the search workspace", "You are practising with sample data only.", "Click Search Vault in the left sidebar.", "A Vault stores files plus an index for finding them. Ordinary archives are not automatically searchable Vaults.", "The real search screen will open. Your previous selections will be restored when you exit."),
    Step("load", "Choose a practice Vault", "You are in Search Vault.", "Click Load practice Vault beside the Vault field.", "We will create a tiny, unencrypted Vault containing three made-up documents in a private temporary folder.", "The Vault path will appear. Your own files will not be read or changed."),
    Step("query", "Tell Rat-Trap what to find", "The practice Vault is selected; no search has run yet.", "Type aurora in the Find box, then click Next below.", "Vault search looks at filenames and supported indexed text. It does not need to restore the whole collection.", "Next becomes available when the practice word is correct. The extension filter stays empty."),
    Step("search", "Run the search", "Your search word is ready.", "Click the highlighted Search button.", "Rat-Trap will read the practice Vault's index using its normal search engine.", "Wait for the actual result. This step only advances after the expected document appears."),
    Step("select", "Choose the matching document", "The result list shows the match inside the Vault.", "Click projects/aurora-notes.txt, then click Next below.", "Selecting a result tells Rat-Trap which stored file you want to inspect.", "One row will be selected. Selection alone does not export or open an external program."),
    Step("preview", "Read it inside Rat-Trap", "The matching document is selected.", "Click Preview selected.", "Rat-Trap reads this file's content for an in-app preview, not a full-folder restore.", "The preview pane will show the Aurora launch checklist. Nothing is exported to your folders."),
    Step("finish", "You found it", "You are reading the real preview of a file stored inside a Vault.", "Read the preview, then choose Finish tutorial.", "For your own files, create an archive using the Queryable Vault profile, then use this same Search Vault screen.", "We will return to your previous screen and remove only unchanged practice files. Compression alone is not encryption."),
)

COMPRESS_STEPS = (
    Step("navigate", "Open the compression workspace", "This lesson uses made-up files only.", "Click Create archive in the sidebar.", "An archive stores compressed copies together; the original folder is kept.", "The real creation screen opens. Your previous settings return when you exit."),
    Step("load", "Choose the folder to compress", "You are in Create archive.", "Click Load sample folder beside Source folder.", "In normal use this button opens a folder picker. Here it prepares fictional documents in a fresh temporary folder.", "A sample source path appears. No personal folder is selected or read."),
    Step("destination", "Save outside the source folder", "The sample source is ready.", "Click Use safe archive location beside Save archive.", "Saving outside the source avoids putting an archive inside the folder it is compressing.", "Practice Archive.gmw is selected beside, not inside, sample-files. Nothing has been compressed yet."),
    Step("profile", "Choose a compression setting", "The source and archive location are selected.", "Choose Balanced, Fast or Smallest in Format, then click Next.", "Balanced is a starting point; Fast prioritises speed; Smallest spends more time trying to reduce size. Results depend on the files.", "The selected setting is used for the sample. Encryption stays off for this lesson; compression is not encryption."),
    Step("create", "Create the sample archive", "Your practice choices are ready.", "Click Create.", "The normal compression engine writes a new archive while keeping the source files.", "Wait for actual file and byte totals below. Revisiting a completed run reviews its result without overwriting it."),
    Step("finish", "Understand the result", "Your sample archive has been created.", "Read the size result below, then choose Finish tutorial.", "Space saved compares archive size with original bytes. This fictional text sample is not a benchmark; photos, video and ZIPs may shrink much less or grow.", "Your previous screen returns. Next, choose Restore your files in Show me how to practise recovery and checking. Keep independent backups."),
)

RESTORE_STEPS = (
    Step("navigate", "Open the restore workspace", "This lesson uses its own fictional sample archive.", "Click Extract archive in the sidebar.", "Restoring recovers copies of stored files into a folder. It does not remove the archive.", "The real restore screen opens. You can take this lesson without completing compression first."),
    Step("load", "Choose an archive to restore", "You are in Extract archive.", "Click Load sample archive beside Archive.", "In normal use you choose your archive here. This lesson creates a fresh sample archive and keeps known originals for comparison.", "The practice archive path appears. No personal archive is opened."),
    Step("destination", "Choose a separate empty location", "The practice archive is selected.", "Click Use separate restore folder beside Destination.", "A new destination avoids replacing existing files and lets you compare the restored copies with the originals.", "The absent restored-files folder is selected. Extraction creates it; your personal folders are not used."),
    Step("extract", "Restore the files", "The archive and safe destination are ready.", "Click Extract files.", "The normal restore engine reconstructs the files from the archive.", "A real extraction result appears. Successful extraction is not yet the independent comparison taught in the next step."),
    Step("verify", "Check the recovered contents", "The sample files have been restored.", "Click Check restored files below.", "Rat-Trap compares every restored sample file with the known source hashes and checks for missing, unexpected or changed files.", "Only a matching result completes this lesson. This check belongs to guided practice; for personal backups use verification and compare restored copies."),
    Step("finish", "The restored files match", "The independent sample comparison passed.", "Read the matched-file count below, then choose Finish tutorial.", "You have practised both restoration and checking the result. An archive should never be your only copy of important data.", "Your previous screen returns. Only unchanged generated practice files are removed; your original files are untouched."),
)

PROTECT_STEPS = (
    Step("navigate", "Open the security workspace", "This lesson protects one fictional sample file.", "Click Secure files in the sidebar.", "A Sealed File encrypts a copy of its contents and original name. Encryption is different from compression.", "The Protect one file tab opens. Your previous selections return when you exit."),
    Step("load", "Choose the sample file", "You are in Protect one file.", "Click Load sample file beside File to protect.", "In normal use this selects your file. Here it creates a made-up document and a disposable password in memory.", "No personal file is selected, and no real password is requested."),
    Step("destination", "Choose the protected copy", "The fictional source is ready.", "Click Use sample sealed location beside Save sealed file.", "The opaque .rtsf name does not reveal the original filename; the source is kept separately.", "A new sample destination is selected. Nothing is encrypted yet."),
    Step("password", "Understand the password", "The lesson has generated a disposable password for this session.", "Tick Use a disposable practice password, then click Next.", "For real files, use a strong unique password and keep it safe. Here the password is supplied internally, never displayed or copied.", "This acknowledgment enables practice only. Do not enter a real password anywhere in this lesson."),
    Step("key", "Keep the recovery key separate", "A password and a recovery key provide two ways to unlock the file.", "Click Use separate practice key folder.", "Anyone holding the matching .rtrk key can unlock the Sealed File without its password. Keep real keys somewhere safe and separate, such as another protected device.", "A separate temporary key folder is selected for practice. It is a layout example, not a secure backup location."),
    Step("seal", "Protect the sample", "The sample source, sealed destination and key location are ready.", "Click Protect file.", "The normal Sealed File engine compresses, encrypts and authenticates the copy using the disposable password.", "The source stays intact. Temporary plaintext is used; secure deletion is not claimed. Wait for the actual result below."),
    Step("open", "Try both ways to recover", "The protected sample and matching recovery key were created.", "Read the result, then click Next to open Open / restore.", "A matching recovery key is an alternative credential, not a second password you must also supply.", "First you will restore using the practice password, then recover another copy using only the key."),
    Step("restore-load", "Select the protected sample", "You are in Open / restore.", "Click Use sample Sealed File beside Sealed file.", "In normal use you select your .rtsf here. Merely selecting it does not decrypt or launch anything.", "Only the protected file created by this lesson is selected."),
    Step("restore-destination", "Keep plaintext copies separate", "The protected sample is selected.", "Click Use password restore folder beside Restore into.", "Restoring writes ordinary plaintext. Choose a separate destination, and protect the restored copy if it contains sensitive information.", "A new sample folder is selected. The original source and Sealed File are not replaced."),
    Step("password-restore", "Unlock with the password", "The lesson will supply its disposable password to the normal restore engine.", "Click Restore plaintext copy.", "For your real files the app asks for your password or matching recovery key. This practice run does not open a credential dialog.", "A real plaintext sample copy is restored. No external viewer or executable is launched."),
    Step("recovery", "Recover without the password", "The password-based restore has completed.", "Click Recover sample without password below.", "This operation passes only the matching practice recovery key, not the password, to the normal engine.", "A second plaintext copy is restored into a different sample folder. Nothing from the first restore is overwritten."),
    Step("verify", "Check both recovered copies", "Both restore operations have completed.", "Click Check both recovered files below.", "The lesson independently compares both recovered files against the original fictional content's SHA-256 hash.", "Only matching contents complete the lesson. A missing, changed, unexpected or unsafe output prevents a success result."),
    Step("finish", "Know what to keep safe", "Both recovered sample files match the original contents.", "Read the result, then choose Finish tutorial.", "If you lose both the password and matching recovery key, Rat-Trap cannot unlock that copy for you. Keep independent backups and protect your keys.", "Your previous settings return. Unchanged practice files are removed and the password reference is discarded; no secure memory or disk erasure is promised."),
)

HISTORY_STEPS = (
    Step("navigate", "Open backups and history", "You will practise with two versions of a fictional folder.", "Click Backups & history in the sidebar.", "A repository keeps snapshots: saved versions you can return to later. It is different from a portable .gmw archive.", "The real backup workspace opens. Previous paths, history and settings return when you exit."),
    Step("load", "Choose the sample folder", "You are in Backups & history.", "Click Load sample folder beside Folder to back up.", "This creates two made-up documents. No personal folder or existing repository is used.", "The original sample version appears as the selected source. Nothing has been backed up yet."),
    Step("repository", "Choose where backups live", "The sample source is ready.", "Click Use sample repository beside Repository.", "Backups belong outside the source folder. This temporary repository is unencrypted; backups are not automatically protected just because Rat-Trap created them.", "A new practice repository location is selected. The next action initializes it and saves the first snapshot."),
    Step("first", "Save the first version", "The original sample and separate repository are selected.", "Click Back up now.", "The normal repository engine creates and verifies a snapshot of the folder as it is now.", "Wait for the first backup result. The source files remain in place."),
    Step("change", "Make a sample change", "The first backup contains the original sample contents.", "Click Change the sample file below.", "This stands in for editing a document after a backup. Only the known fictional Aurora note is changed; the checklist stays the same.", "The sample source becomes version two. The first saved snapshot still contains version one."),
    Step("second", "Save the changed version", "The current sample contains the new note.", "Click Back up now again.", "A second snapshot records the new state. Unchanged data can be reused; the first snapshot is kept.", "Two saved versions now exist. This tiny sample is an illustration, not a compression benchmark."),
    Step("history", "Read the saved history", "Both real backup operations have completed.", "Click Open / refresh near Repository.", "The app asks the repository for its saved snapshots, rather than inventing a result list.", "The Snapshots table shows the first and second backups. Newest is listed first; a newer backup does not erase the older one."),
    Step("select", "Choose the older snapshot", "The table contains both sample versions.", "Select First backup — original sample, then click Next.", "Choosing an older snapshot tells Rat-Trap which saved state to restore. Selecting a row alone changes no file.", "Next enables only for the first backup. The current changed sample is not rolled back."),
    Step("destination", "Keep the restored copy separate", "The older sample snapshot is selected.", "Click Use separate restore folder below.", "Restoring into a new folder lets you inspect old contents without replacing today's files.", "A new, previously absent practice destination is selected. No folder picker opens during practice."),
    Step("restore", "Recover the older version", "The first snapshot and a separate destination are ready.", "Click Restore selected… beneath the table.", "The normal repository restore engine reconstructs and verifies the chosen snapshot.", "The older files appear in their own practice folder. The current source and both snapshots remain intact."),
    Step("verify", "Compare old and current contents", "The older snapshot has been restored.", "Click Check the older files below.", "The lesson compares recovered files with the original version's SHA-256 hashes and checks that the current sample still contains the newer version.", "Only matching old copies and an unchanged current sample complete this lesson. The changed note's two versions are explained in the result."),
    Step("finish", "You recovered an earlier version", "The old files match, and the current sample still has its newer contents.", "Read the result, then choose Finish tutorial.", "For real work, select the required snapshot and restore into a separate folder first. Keep independent backups; history on one drive is not protection against losing that drive.", "Previous settings and history return. Only unchanged generated practice files are removed; no secure deletion or repository encryption is implied."),
)

STEPS_BY_ID = {"vault-search": VAULT_SEARCH_STEPS, "compress": COMPRESS_STEPS, "restore": RESTORE_STEPS, "protect": PROTECT_STEPS, "history": HISTORY_STEPS}

DEMO_QUERY = "aurora"
DEMO_PATH = "projects/aurora-notes.txt"
DEMO_MARKER = "Aurora launch checklist"
DEMO_FILES = {
    DEMO_PATH: "Aurora launch checklist\n\n1. Review the sample design.\n2. Share the made-up project notes.\n3. Keep an independent backup.\n\nThis is fictional tutorial content, not one of your files.\n",
    "documents/garden.txt": "Garden notes\nWater the herbs and label the seed trays.\nFictional practice data.\n",
    "documents/shopping.txt": "Shopping list\nBread, apples and tea.\nFictional practice data.\n",
}


def _ordinary(path: Path) -> bool:
    return not path.is_symlink() and not getattr(path, "is_junction", lambda: False)()


def _owned_ordinary(root: Path, path: Path) -> bool:
    return path.is_relative_to(root) and all(_ordinary(p) for p in (path, *path.parents)
                                           if p == root or p.is_relative_to(root))


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass(frozen=True)
class DemoVault:
    root: Path
    source: Path
    archive: Path
    owned_files: tuple[tuple[Path, str], ...]
    archive_identity: tuple[int, int, int, int] | None = None

    def is_intact(self) -> bool:
        """Reject replaced/linked/changed practice inputs before opening a Vault."""
        try:
            if not _owned_ordinary(self.root, self.archive):
                return False
            before = self.archive.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or _identity(before) != self.archive_identity:
                return False
            with self.archive.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if _identity(opened) != self.archive_identity or opened.st_nlink != 1:
                    return False
                digest = hashlib.sha256(stream.read()).hexdigest()
            return digest == dict(self.owned_files).get(self.archive) and _identity(self.archive.lstat()) == self.archive_identity and _owned_ordinary(self.root, self.archive)
        except OSError:
            return False

    def cleanup(self) -> None:
        """No recursive deletion: preserve anything changed/added by a user."""
        if not self.root.exists() or not _ordinary(self.root):
            return
        for path, expected_hash in self.owned_files:
            if not _owned_ordinary(self.root, path):
                continue
            try:
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash:
                    path.unlink()
            except OSError:
                pass
        for path in (self.source / "projects", self.source / "documents", self.source, self.root):
            try:
                if _owned_ordinary(self.root, path):
                    path.rmdir()  # Empty directories only.
            except OSError:
                pass


def create_demo(parent: Path | None = None) -> DemoVault:
    root = Path(tempfile.mkdtemp(prefix="rat-trap-tutorial-", dir=parent)).absolute()
    source = root / "sample-files"
    archive = root / "Practice Vault.gmw"
    owned: list[tuple[Path, str]] = []
    try:
        for relative, content in DEMO_FILES.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = content.encode("utf-8")
            with path.open("xb") as stream:
                stream.write(data)
            owned.append((path, hashlib.sha256(data).hexdigest()))
        vault_engine.create_vault(source, archive)
        owned.append((archive, hashlib.sha256(archive.read_bytes()).hexdigest()))
        return DemoVault(root, source, archive, tuple(owned), _identity(archive.lstat()))
    except BaseException:
        DemoVault(root, source, archive, tuple(owned)).cleanup()
        raise
