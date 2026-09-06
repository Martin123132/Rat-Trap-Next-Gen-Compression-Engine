"""Owned fictional data for the real repository backup-history walkthrough.

This is a caller-side safety boundary, not another repository implementation.
The practice repository is unencrypted. Cleanup is conservative ordinary
deletion, not secure erasure or protection from a hostile same-user process
continuously racing filesystem changes.
"""

from __future__ import annotations

import dataclasses
import os
import re
import stat
import tempfile
from pathlib import Path
from types import MappingProxyType

from . import repository_engine
from .archive_tutorials import ArchivePractice, FileCheck, RestoreVerification, _digest, _identity, _ordinary


CHANGED_NAME = "aurora-notes.txt"
FIRST_LABEL = "First backup — original sample"
SECOND_LABEL = "Second backup — changed sample"
FIRST_FILES = MappingProxyType({
    CHANGED_NAME: b"Aurora fictional project\nVersion 1: the meeting is on Monday.\nKeep the original design notes.\n",
    "checklist.txt": b"Fictional practice checklist\nLabel the files. Keep an independent backup.\n",
})
SECOND_FILES = MappingProxyType({
    **FIRST_FILES,
    CHANGED_NAME: b"Aurora fictional project\nVersion 2: the meeting is now on Thursday.\nThe design notes have changed.\n",
})
_REPOSITORY_DIRECTORIES = ("", "manifests", "packs", "locks", "staging", "staging/jobs", "refs", "refs/pins", "trash")


class HistoryPractice:
    """One sample-only, non-overwriting, one-operation-at-a-time session."""

    def __init__(self, root: Path):
        self._owner = ArchivePractice(root)
        self._source = root / "sample-files"
        self._repository = root / "Practice backup history"
        self._restored = root / "restored-first-version"
        self._source_version = 1
        self.first_snapshot: repository_engine.SnapshotInfo | None = None
        self.second_snapshot: repository_engine.SnapshotInfo | None = None
        self.history: tuple[repository_engine.SnapshotInfo, ...] = ()
        self.restore_result: repository_engine.RestoreResult | None = None

    @property
    def root(self) -> Path:
        return self._owner.root

    @property
    def source(self) -> Path:
        return self._source

    @property
    def repository(self) -> Path:
        return self._repository

    @property
    def restored(self) -> Path:
        return self._restored

    @property
    def source_version(self) -> int:
        return self._source_version

    @property
    def busy(self) -> bool:
        return self._owner.busy

    def _tree_is_intact(self, base: Path) -> bool:
        """Check exact recorded membership without descending into unknown paths."""
        try:
            if base not in self._owner._directories or not self._owner._owned_path(base):
                return False
            directories = {p for p in self._owner._directories if p.is_relative_to(base)}
            files = {p for p in self._owner._files if p.is_relative_to(base)}
            for directory in directories:
                if not self._owner._owned_path(directory):
                    return False
                expected = {p.name for p in directories | files if p.parent == directory}
                if {p.name for p in directory.iterdir()} != expected:
                    return False
            return all(self._owner._file_is_intact(path) for path in files)
        except OSError:
            return False

    def _source_is_intact(self) -> bool:
        expected = FIRST_FILES if self.source_version == 1 else SECOND_FILES
        if not self._tree_is_intact(self.source):
            return False
        try:
            return all(self._owner._read_regular(self.source / name, self._owner._files[self.source / name])[0] == data
                       for name, data in expected.items())
        except (OSError, ValueError, KeyError):
            return False

    def _intact(self, check) -> bool:
        if not self._owner._lock.acquire(blocking=False):
            return False
        try:
            return check()
        finally:
            self._owner._lock.release()

    def source_is_intact(self) -> bool:
        return self._intact(self._source_is_intact)

    def repository_is_intact(self) -> bool:
        return self._intact(lambda: self._tree_is_intact(self.repository))

    def restored_is_intact(self) -> bool:
        return self._intact(lambda: self._tree_is_intact(self.restored))

    def _capture_repository(self, base: Path, snapshots: tuple[repository_engine.SnapshotInfo, ...]) -> None:
        """Adopt only the expected completed engine layout, never unknown entries."""
        for relative in _REPOSITORY_DIRECTORIES:
            path = base / relative
            if path in self._owner._directories:
                if not self._owner._owned_path(path):
                    raise ValueError("Practice repository folder was replaced or linked")
            else:
                self._owner._record_directory(path)
        packs, shards = set(), set()
        for shard in (base / "packs").iterdir():
            if (re.fullmatch(r"[0-9a-f]{2}", shard.name) is None
                    or not _ordinary(shard) or not stat.S_ISDIR(shard.lstat().st_mode)):
                raise ValueError("Practice repository contains an unexpected pack folder")
            names = {p.name for p in shard.iterdir()}
            if not names or any(re.fullmatch(shard.name + r"[0-9a-f]{30}\.rtpack", name) is None for name in names):
                raise ValueError("Practice repository contains unexpected pack entries")
            shards.add(shard)
            packs.update(shard.name + "/" + name for name in names)
        if len(packs) != sum(s.new_pack_file_bytes > 0 for s in snapshots):
            raise ValueError("Practice repository contains unexpected pack entries")
        for shard in shards:
            if shard in self._owner._directories:
                if not self._owner._owned_path(shard):
                    raise ValueError("Practice pack folder was replaced or linked")
            else:
                self._owner._record_directory(shard)
        files = {"repository.json", "catalog.sqlite3", "locks/repository.lock"}
        files.update("packs/" + name for name in packs)
        files.update("manifests/" + s.manifest_sha256 + ".rtsnap.json" for s in snapshots)
        paths = {base / name for name in files}
        directories = {base / name for name in _REPOSITORY_DIRECTORIES} | shards
        for directory in directories:
            expected = {p.name for p in paths | directories if p.parent == directory}
            if {p.name for p in directory.iterdir()} != expected:
                raise ValueError("Practice repository contains unexpected entries")
        for path in paths:
            # Only the disposable catalogue may be replaced by a new snapshot.
            # Existing canonical files must retain their exact owned identity.
            previous = self._owner._files.get(path)
            if previous is not None and path.name != "catalog.sqlite3":
                self._owner._read_regular(path, previous)
            else:
                self._owner._record_file(path)
        if not self._tree_is_intact(base):
            raise ValueError("Practice repository changed while recording its outputs")

    def _clean_tree(self, base: Path) -> None:
        for path, expected in tuple(self._owner._files.items()):
            if path.is_relative_to(base):
                try:
                    self._owner._read_regular(path, expected)
                    path.unlink()
                    self._owner._files.pop(path)
                except (OSError, ValueError):
                    pass
        for path in sorted(tuple(self._owner._directories), key=lambda p: len(p.parts), reverse=True):
            if path.is_relative_to(base):
                self._owner._remove_empty_directory(path)

    def _copy_tree(self, source: Path, output: Path) -> None:
        if not self._tree_is_intact(source):
            raise ValueError("Practice repository changed; start a fresh tutorial")
        self._owner._require_absent(output)
        directories = sorted((p for p in self._owner._directories if p.is_relative_to(source)), key=lambda p: len(p.parts))
        for original in directories:
            target = output / original.relative_to(source)
            target.mkdir(exist_ok=False)
            self._owner._record_directory(target)
        for original, expected in tuple(self._owner._files.items()):
            if original.is_relative_to(source):
                data, _ = self._owner._read_regular(original, expected)
                target = output / original.relative_to(source)
                with target.open("xb") as stream:
                    stream.write(data)
                self._owner._record_file(target, data)
        if not self._tree_is_intact(source) or not self._tree_is_intact(output):
            raise ValueError("Practice repository changed while copying its owned files")

    def _move_tree(self, source: Path, output: Path) -> None:
        if not self._tree_is_intact(source):
            raise ValueError("Practice output changed before publication")
        self._owner._require_absent(output)
        if os.name != "nt":
            # Exclusive fallback: POSIX rename can replace an existing empty dir.
            self._copy_tree(source, output)
            self._clean_tree(source)
            return
        files = {p: v for p, v in self._owner._files.items() if p.is_relative_to(source)}
        directories = {p: v for p, v in self._owner._directories.items() if p.is_relative_to(source)}
        os.rename(source, output)
        for old, value in files.items():
            self._owner._files.pop(old)
            self._owner._files[output / old.relative_to(source)] = value
        for old, value in directories.items():
            self._owner._directories.pop(old)
            self._owner._directories[output / old.relative_to(source)] = value
        if not self._tree_is_intact(output):
            raise ValueError("Practice output changed during publication")

    def _snapshot(self, *, second: bool) -> repository_engine.SnapshotInfo:
        self._owner._claim()
        try:
            if not self._source_is_intact() or self.source_version != (2 if second else 1):
                raise ValueError("Practice source is not at the expected version")
            if second:
                if self.first_snapshot is None or self.second_snapshot is not None or not self._tree_is_intact(self.repository):
                    raise ValueError("A second practice backup needs one unchanged first backup")
            else:
                if self.first_snapshot is not None:
                    raise ValueError("The first practice backup already exists")
                self._owner._require_absent(self.repository)
            stage = self._owner._stage()
            staged_repository = stage / "repository"
            if second:
                self._copy_tree(self.repository, staged_repository)
            else:
                staged_repository.mkdir(exist_ok=False)
                self._owner._record_directory(staged_repository)
                repository_engine.init_repository(staged_repository)
            snapshot = repository_engine.create_snapshot(
                staged_repository, self.source, label=SECOND_LABEL if second else FIRST_LABEL,
            )
            snapshots = (self.first_snapshot, snapshot) if second else (snapshot,)
            self._capture_repository(staged_repository, snapshots)
            if not self._source_is_intact():
                raise ValueError("Practice source changed during backup")
            # This is the real engine's verified, fully completed repository.
            listed = tuple(repository_engine.list_snapshots(staged_repository))
            if ({s.snapshot_id for s in listed} != {s.snapshot_id for s in snapshots}
                    or len(listed) != len(snapshots) or not self._tree_is_intact(staged_repository)):
                raise ValueError("Practice repository history changed during backup")
            if second:
                retired = stage / "previous-repository"
                self._move_tree(self.repository, retired)
                try:
                    self._move_tree(staged_repository, self.repository)
                except BaseException:
                    if not os.path.lexists(self.repository) and self._tree_is_intact(retired):
                        self._move_tree(retired, self.repository)
                    raise
                self.second_snapshot = snapshot
                self._clean_tree(retired)
            else:
                self._move_tree(staged_repository, self.repository)
                self.first_snapshot = snapshot
            self._owner._remove_empty_directory(stage)
            return snapshot
        finally:
            self._owner._lock.release()

    def create_first_backup(self) -> repository_engine.SnapshotInfo:
        return self._snapshot(second=False)

    def create_second_backup(self) -> repository_engine.SnapshotInfo:
        return self._snapshot(second=True)

    def change_sample(self) -> None:
        self._owner._claim()
        try:
            if (self.first_snapshot is None or self.source_version != 1 or not self._source_is_intact()
                    or not self._tree_is_intact(self.repository)):
                raise ValueError("Changing the sample requires its unchanged first backup")
            path = self.source / CHANGED_NAME
            expected = self._owner._files[path]
            self._owner._read_regular(path, expected)
            # Write only through the verified original handle; never replace a
            # pathname that might now identify an unrelated file.
            with path.open("r+b") as stream:
                if _identity(os.fstat(stream.fileno())) != expected.identity or not self._owner._file_is_intact(path):
                    raise ValueError("Practice sample changed while opening it")
                stream.write(SECOND_FILES[CHANGED_NAME])
                stream.truncate()
                stream.flush()
                written = os.fstat(stream.fileno())
            if (_identity(path.lstat()) != _identity(written)
                    or (written.st_dev, written.st_ino) != expected.identity[:2]):
                raise ValueError("Practice sample was replaced during its change")
            self._owner._record_file(path, SECOND_FILES[CHANGED_NAME])
            self._source_version = 2
            if not self._source_is_intact() or not self._tree_is_intact(self.repository):
                raise ValueError("Practice data changed during the sample edit")
        finally:
            self._owner._lock.release()

    def list_history(self) -> tuple[repository_engine.SnapshotInfo, ...]:
        self._owner._claim()
        try:
            if (self.first_snapshot is None or self.second_snapshot is None or self.source_version != 2
                    or not self._tree_is_intact(self.repository) or not self._source_is_intact()):
                raise ValueError("Practice history needs two intact backups")
            snapshots = tuple(repository_engine.list_snapshots(self.repository))
            if (len(snapshots) != 2
                    or {s.snapshot_id for s in snapshots} != {self.first_snapshot.snapshot_id, self.second_snapshot.snapshot_id}
                    or not self._tree_is_intact(self.repository) or not self._source_is_intact()):
                raise ValueError("Practice history changed while reading it")
            self.history = snapshots
            return snapshots
        finally:
            self._owner._lock.release()

    def _capture_sample_tree(self, base: Path) -> None:
        self._owner._record_directory(base)
        if {p.name for p in base.iterdir()} != set(FIRST_FILES):
            raise ValueError("Practice restore contains unexpected entries")
        for name, data in FIRST_FILES.items():
            self._owner._record_file(base / name, data)

    def restore_older(self) -> repository_engine.RestoreResult:
        self._owner._claim()
        try:
            if (self.first_snapshot is None or self.second_snapshot is None or self.source_version != 2
                    or not self._tree_is_intact(self.repository) or not self._source_is_intact()):
                raise ValueError("Restoring the first version needs two intact practice backups")
            self._owner._require_absent(self.restored)
            stage = self._owner._stage()
            staged = stage / "restored"
            result = repository_engine.restore_snapshot(self.repository, self.first_snapshot.snapshot_id, staged)
            self._capture_sample_tree(staged)
            if not self._tree_is_intact(self.repository) or not self._source_is_intact():
                raise ValueError("Practice data changed during restoration")
            self._move_tree(staged, self.restored)
            self.restore_result = dataclasses.replace(result, destination=str(self.restored))
            self._owner._remove_empty_directory(stage)
            return self.restore_result
        finally:
            self._owner._lock.release()

    def verify_restored(self) -> RestoreVerification:
        self._owner._claim()
        try:
            missing, changed, unexpected, unsafe, checks = [], [], [], [], []
            matched, total = 0, 0
            if not self._source_is_intact() or self.source_version != 2:
                unsafe.append("current-sample/<changed or unsafe>")
            if not self._tree_is_intact(self.repository):
                unsafe.append("backup-history/<changed or unsafe>")
            for directory, expected_files, prefix in (
                (self.restored, FIRST_FILES, "restored-first-version"),
                (self.source, SECOND_FILES, "current-sample"),
            ):
                directory_safe = directory in self._owner._directories and self._owner._owned_path(directory)
                if directory_safe:
                    try:
                        if {p.name for p in directory.iterdir()} != set(expected_files):
                            unexpected.append(prefix + "/<missing or unexpected entry>")
                    except OSError:
                        unsafe.append(prefix + "/<unreadable directory>")
                        directory_safe = False
                for name, expected in expected_files.items():
                    path, actual = directory / name, None
                    relative = prefix + "/" + name
                    try:
                        if not directory_safe:
                            if not os.path.lexists(directory):
                                missing.append(relative)
                            else:
                                unsafe.append(relative)
                            continue
                        owned = self._owner._files.get(path)
                        if owned is None:
                            unsafe.append(relative)
                            continue
                        data, record = self._owner._read_regular(path, owned)
                        actual = record.sha256
                        total += len(data)
                        if data == expected:
                            matched += 1
                        else:
                            changed.append(relative)
                    except FileNotFoundError:
                        missing.append(relative)
                    except (OSError, ValueError):
                        changed.append(relative)
                    finally:
                        checks.append(FileCheck(relative, _digest(expected), actual, actual == _digest(expected)))
            count = len(FIRST_FILES) + len(SECOND_FILES)
            ok = matched == count and not (missing or changed or unexpected or unsafe)
            return RestoreVerification(ok, count, matched, total, tuple(missing), tuple(changed),
                                       tuple(unexpected), tuple(unsafe), tuple(checks))
        finally:
            self._owner._lock.release()

    def cleanup(self) -> bool:
        return self._owner.cleanup()


def create_practice(parent: Path | None = None) -> HistoryPractice:
    """Always create a fresh child; never accept a user source or repository."""
    root = Path(tempfile.mkdtemp(prefix="rat-trap-history-tutorial-", dir=parent)).resolve()
    practice = HistoryPractice(root)
    try:
        practice.source.mkdir(exist_ok=False)
        practice._owner._record_directory(practice.source)
        for name, data in FIRST_FILES.items():
            path = practice.source / name
            with path.open("xb") as stream:
                stream.write(data)
            practice._owner._record_file(path, data)
        return practice
    except BaseException:
        practice.cleanup()
        raise
