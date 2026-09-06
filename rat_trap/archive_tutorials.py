"""Owned, fictional practice data for the compression and restore lessons.

This is a caller-side safety boundary around the ordinary archive engine, not
a different compressor. Nothing here accepts a user source or output path.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from . import gmw_tool


ALLOWED_PROFILES = ("fast", "balanced", "smallest")
PRACTICE_FILES = MappingProxyType({
    "projects/aurora-notes.txt": (
        "Aurora practice project\nThis is fictional tutorial content, not your files.\n\n"
        + "Sample checklist: review the design, label the files, keep a separate backup.\n" * 64
    ).encode("utf-8"),
    "documents/garden.txt": (
        "Fictional garden journal\n"
        + "Monday: water the herbs. Tuesday: label the seed trays. Wednesday: check the soil.\n" * 48
    ).encode("utf-8"),
    "documents/shopping.txt": b"Fictional shopping list\nBread, apples, tea and notebooks.\n",
})


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _directory_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _ordinary(path: Path) -> bool:
    return not path.is_symlink() and not getattr(path, "is_junction", lambda: False)()


@dataclass(frozen=True)
class FileCheck:
    path: str
    expected_sha256: str
    actual_sha256: str | None
    matches: bool


@dataclass(frozen=True)
class RestoreVerification:
    ok: bool
    file_count: int
    matched_files: int
    total_bytes: int
    missing_files: tuple[str, ...]
    changed_files: tuple[str, ...]
    unexpected_files: tuple[str, ...]
    unsafe_paths: tuple[str, ...]
    checks: tuple[FileCheck, ...]


@dataclass(frozen=True)
class _OwnedFile:
    identity: tuple[int, int, int, int]
    sha256: str


class ArchivePractice:
    """One mutable practice session; only one operation can own it at a time.

    Cleanup is deliberately conservative: changed files, replacements, links,
    unexpected entries and non-empty directories are retained. This is not a
    defence against a malicious process racing filesystem changes, nor secure
    deletion. All source content is public, made-up tutorial text.
    """

    def __init__(self, root: Path):
        self._root = root
        self._source = root / "sample-files"
        self._archive = root / "Practice archive.gmw"
        self._restored = root / "restored-files"
        self._lock = threading.Lock()
        self._files: dict[Path, _OwnedFile] = {}
        self._directories: dict[Path, tuple[int, int]] = {}
        self._profile: str | None = None
        self.archive_metadata: gmw_tool.Metadata | None = None
        self.restore_metadata: gmw_tool.Metadata | None = None
        self._record_directory(root)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def source(self) -> Path:
        return self._source

    @property
    def archive(self) -> Path:
        return self._archive

    @property
    def restored(self) -> Path:
        return self._restored

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @property
    def profile(self) -> str | None:
        return self._profile

    def _record_directory(self, path: Path) -> None:
        value = path.lstat()
        if not stat.S_ISDIR(value.st_mode) or not _ordinary(path):
            raise ValueError("Practice directory is not an ordinary folder")
        self._directories[path] = _directory_identity(value)

    def _owned_path(self, path: Path) -> bool:
        if not path.is_relative_to(self.root):
            return False
        try:
            for ancestor in (path, *path.parents):
                if ancestor != self.root and not ancestor.is_relative_to(self.root):
                    continue
                if not _ordinary(ancestor):
                    return False
                if ancestor in self._directories:
                    value = ancestor.lstat()
                    if not stat.S_ISDIR(value.st_mode) or _directory_identity(value) != self._directories[ancestor]:
                        return False
                elif ancestor != path:
                    return False
            return True
        except OSError:
            return False

    def _read_regular(self, path: Path, expected: _OwnedFile | None = None) -> tuple[bytes, _OwnedFile]:
        if not self._owned_path(path):
            raise ValueError("Practice file or a parent folder was replaced or linked")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("Practice files must be ordinary files with one link")
        if expected is not None and _identity(before) != expected.identity:
            raise ValueError("Practice file was replaced or changed")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _identity(opened) != _identity(before) or opened.st_nlink != 1:
                raise ValueError("Practice file changed while opening it")
            data = stream.read()
            if _identity(os.fstat(stream.fileno())) != _identity(before):
                raise ValueError("Practice file changed while reading it")
        after = path.lstat()
        if not self._owned_path(path) or _identity(after) != _identity(before) or after.st_nlink != 1:
            raise ValueError("Practice file changed while reading it")
        record = _OwnedFile(_identity(after), _digest(data))
        if expected is not None and record.sha256 != expected.sha256:
            raise ValueError("Practice file contents changed")
        return data, record

    def _record_file(self, path: Path, expected_data: bytes | None = None) -> None:
        data, record = self._read_regular(path)
        if expected_data is not None and data != expected_data:
            raise ValueError("Practice output did not match the sample contents")
        self._files[path] = record

    def _file_is_intact(self, path: Path) -> bool:
        expected = self._files.get(path)
        if expected is None:
            return False
        try:
            self._read_regular(path, expected)
            return True
        except (OSError, ValueError):
            return False

    def _source_is_intact(self) -> bool:
        try:
            expected = {"": {"projects", "documents"}, "projects": {"aurora-notes.txt"},
                        "documents": {"garden.txt", "shopping.txt"}}
            for relative, children in expected.items():
                directory = self.source / relative
                if directory not in self._directories or not self._owned_path(directory):
                    return False
                if {entry.name for entry in directory.iterdir()} != children:
                    return False
            return all(self._file_is_intact(self.source / relative) for relative in PRACTICE_FILES)
        except OSError:
            return False

    def source_is_intact(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            return self._source_is_intact()
        finally:
            self._lock.release()

    def archive_is_intact(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            return self._file_is_intact(self.archive)
        finally:
            self._lock.release()

    def _claim(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("A practice operation is already running")

    def _require_absent(self, path: Path) -> None:
        if not self._owned_path(path.parent):
            raise ValueError("Practice output parent was replaced or linked")
        if os.path.lexists(path):
            raise FileExistsError("Practice output already exists; start a fresh tutorial to try again")

    def _stage(self) -> Path:
        if not self._owned_path(self.root):
            raise ValueError("Practice folder was replaced or linked")
        stage = Path(tempfile.mkdtemp(prefix=".practice-operation-", dir=self.root))
        self._record_directory(stage)
        return stage

    def create_archive(self, profile: str = "balanced") -> gmw_tool.Metadata:
        if profile not in ALLOWED_PROFILES:
            raise ValueError("Choose fast, balanced or smallest for the practice archive")
        self._claim()
        try:
            if not self._source_is_intact():
                raise ValueError("Practice source changed; exit and start a fresh tutorial")
            self._require_absent(self.archive)
            stage = self._stage()
            staged_archive = stage / "archive.gmw"
            metadata = gmw_tool.compress_folder(self.source, staged_archive, profile=profile)
            self._record_file(staged_archive)
            if not self._source_is_intact():
                raise ValueError("Practice source changed during compression")
            self._require_absent(self.archive)
            # Windows rename is exclusive, including on filesystems without
            # hard links. POSIX uses exclusive link publication instead.
            if os.name == "nt":
                os.rename(staged_archive, self.archive)
            else:
                os.link(staged_archive, self.archive)
                staged_archive.unlink()
            self._files.pop(staged_archive)
            self._record_file(self.archive)
            self._profile = profile
            self.archive_metadata = metadata
            self._remove_empty_directory(stage)
            return metadata
        finally:
            self._lock.release()

    def _register_restored_tree(self, base: Path) -> None:
        self._record_directory(base)
        for name in ("projects", "documents"):
            self._record_directory(base / name)
        for relative, expected in PRACTICE_FILES.items():
            self._record_file(base / relative, expected)

    def _publish_restored(self, staged: Path) -> None:
        self._require_absent(self.restored)
        if os.name == "nt":
            # Unlike POSIX rename, Windows rename refuses even an existing
            # empty destination directory.
            os.rename(staged, self.restored)
            for path in tuple(self._files):
                if path.is_relative_to(staged):
                    self._files.pop(path)
            for path in tuple(self._directories):
                if path.is_relative_to(staged):
                    self._directories.pop(path)
            self._register_restored_tree(self.restored)
        else:
            # Exclusive publication fallback for source tests on other OSes.
            # A pre-existing folder/file is never merged into or replaced.
            self.restored.mkdir(exist_ok=False)
            self._record_directory(self.restored)
            for name in ("projects", "documents"):
                directory = self.restored / name
                directory.mkdir(exist_ok=False)
                self._record_directory(directory)
            for relative, expected in PRACTICE_FILES.items():
                origin, output = staged / relative, self.restored / relative
                os.link(origin, output)
                origin.unlink()
                self._files.pop(origin)
                self._record_file(output, expected)
            for name in ("projects", "documents", ""):
                self._remove_empty_directory(staged / name)

    def restore_archive(self) -> gmw_tool.Metadata:
        self._claim()
        try:
            if not self._file_is_intact(self.archive):
                raise ValueError("Practice archive changed; exit and start a fresh tutorial")
            self._require_absent(self.restored)
            stage = self._stage()
            staged = stage / "restored-files"
            metadata = gmw_tool.extract_archive(self.archive, staged)
            self._register_restored_tree(staged)
            report = self._verify_tree(staged)
            if not report.ok or not self._file_is_intact(self.archive):
                raise ValueError("Practice restore did not match the original sample files")
            self._publish_restored(staged)
            self.restore_metadata = metadata
            self._remove_empty_directory(stage)
            return metadata
        finally:
            self._lock.release()

    def _verify_tree(self, base: Path) -> RestoreVerification:
        missing, changed, unsafe, unexpected, checks = [], [], [], [], []
        matched, total = 0, 0
        expected_children = {"": {"projects", "documents"}, "projects": {"aurora-notes.txt"},
                             "documents": {"garden.txt", "shopping.txt"}}
        for relative, expected in expected_children.items():
            directory = base / relative
            if directory not in self._directories or not self._owned_path(directory):
                unsafe.append(relative or ".")
                continue
            try:
                unexpected.extend((Path(relative) / entry.name).as_posix()
                                  for entry in directory.iterdir() if entry.name not in expected)
            except OSError:
                unsafe.append(relative or ".")
        for relative, expected in PRACTICE_FILES.items():
            path, actual = base / relative, None
            try:
                data, record = self._read_regular(path, self._files.get(path))
                actual = record.sha256
                total += len(data)
                if data == expected:
                    matched += 1
                else:
                    changed.append(relative)
            except FileNotFoundError:
                missing.append(relative)
            except (OSError, ValueError):
                # If the ordinary owned file changed, read its new bytes for
                # a useful comparison; never read a replacement or link.
                record = self._files.get(path)
                try:
                    current = path.lstat()
                    same_inode = record is not None and (current.st_dev, current.st_ino) == record.identity[:2]
                    if not same_inode:
                        raise ValueError("Restored file was replaced")
                    data, new_record = self._read_regular(path)
                    actual = new_record.sha256
                    total += len(data)
                    if data == expected:
                        matched += 1
                    else:
                        changed.append(relative)
                except (OSError, ValueError):
                    unsafe.append(relative)
            checks.append(FileCheck(relative, _digest(expected), actual,
                                    actual == _digest(expected) and relative not in changed))
        ok = matched == len(PRACTICE_FILES) and not (missing or changed or unexpected or unsafe)
        return RestoreVerification(ok, len(PRACTICE_FILES), matched, total,
                                   tuple(missing), tuple(changed), tuple(sorted(unexpected)),
                                   tuple(sorted(set(unsafe))), tuple(checks))

    def verify_restored(self) -> RestoreVerification:
        self._claim()
        try:
            return self._verify_tree(self.restored)
        finally:
            self._lock.release()

    def _remove_empty_directory(self, path: Path) -> None:
        try:
            if path in self._directories and self._owned_path(path):
                path.rmdir()
                self._directories.pop(path)
        except OSError:
            pass

    def cleanup(self) -> bool:
        """Return False while an operation owns the session; otherwise clean safely."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            for path, expected in tuple(self._files.items()):
                try:
                    self._read_regular(path, expected)
                    path.unlink()
                    self._files.pop(path)
                except (OSError, ValueError):
                    pass
            for path in sorted(self._directories, key=lambda item: len(item.parts), reverse=True):
                self._remove_empty_directory(path)
            return True
        finally:
            self._lock.release()


def create_practice(parent: Path | None = None, with_archive: bool = False) -> ArchivePractice:
    """Create a fresh child under temporary storage, never reuse a user folder."""
    root = Path(tempfile.mkdtemp(prefix="rat-trap-archive-tutorial-", dir=parent)).resolve()
    practice = ArchivePractice(root)
    try:
        practice.source.mkdir()
        practice._record_directory(practice.source)
        for name in ("projects", "documents"):
            directory = practice.source / name
            directory.mkdir()
            practice._record_directory(directory)
        for relative, content in PRACTICE_FILES.items():
            path = practice.source / relative
            with path.open("xb") as stream:
                stream.write(content)
            practice._record_file(path, content)
        if with_archive:
            practice.create_archive("balanced")
        return practice
    except BaseException:
        practice.cleanup()
        raise
