"""Real Sealed File practice using fictional data and disposable credentials.

This module is not a secure credential store. The sample and restored copies
are plaintext, the password lives in process memory, and cleanup is ordinary
conservative deletion, not secure erasure. No personal input paths are accepted.
"""

from __future__ import annotations

import dataclasses
import os
import secrets
import tempfile
from pathlib import Path

from . import sealed_file
from .archive_tutorials import ArchivePractice, FileCheck, RestoreVerification, _digest


PRACTICE_NAME = "aurora-private-notes.txt"
PRACTICE_BYTES = (
    "Aurora fictional private notes\n\n"
    "This is made-up tutorial content, not one of your files or secrets.\n"
    "A password and a separate recovery key can each unlock the Sealed File.\n"
    "Keep recovery keys separate and safe. Keep independent backups.\n"
    "Restored copies and this original are plaintext. Cleanup is not secure erasure.\n"
).encode("utf-8")


class ProtectionPractice:
    """One owned practice session with non-overwriting, one-at-a-time actions.

    Ownership checks reject changed files, replacements and linked paths. They
    are deliberately conservative, not a defence against a hostile process
    continuously racing filesystem changes under the same operating-system user.
    """

    def __init__(self, root: Path):
        self._owner = ArchivePractice(root)
        self._source = root / "sample-source" / PRACTICE_NAME
        self._sealed = root / "sealed-files" / ("RT-" + secrets.token_hex(16) + ".rtsf")
        self._recovery_key = root / "separate-recovery-key" / "Practice recovery key.rtrk"
        self._password_output = root / "password-restored"
        self._recovery_output = root / "recovery-restored"
        self._practice_password = "Practice-only-" + secrets.token_urlsafe(24)
        self.seal_result: sealed_file.SealResult | None = None
        self.password_result: sealed_file.UnsealResult | None = None
        self.recovery_result: sealed_file.UnsealResult | None = None

    def __getstate__(self):
        raise TypeError("Practice credentials must not be serialized")

    @property
    def root(self) -> Path:
        return self._owner.root

    @property
    def source(self) -> Path:
        return self._source

    @property
    def sealed(self) -> Path:
        return self._sealed

    @property
    def recovery_key(self) -> Path:
        return self._recovery_key

    @property
    def password_output(self) -> Path:
        return self._password_output

    @property
    def recovery_output(self) -> Path:
        return self._recovery_output

    @property
    def practice_password(self) -> str:
        return self._practice_password

    @property
    def busy(self) -> bool:
        return self._owner.busy

    def _intact(self, path: Path) -> bool:
        if not self._owner._lock.acquire(blocking=False):
            return False
        try:
            return self._owner._file_is_intact(path)
        finally:
            self._owner._lock.release()

    def source_is_intact(self) -> bool:
        return self._intact(self.source)

    def sealed_is_intact(self) -> bool:
        return self._intact(self.sealed)

    def key_is_intact(self) -> bool:
        return self._intact(self.recovery_key)

    def password_output_is_intact(self) -> bool:
        return self._output_is_intact(self.password_output)

    def recovery_output_is_intact(self) -> bool:
        return self._output_is_intact(self.recovery_output)

    def _output_is_intact(self, directory: Path) -> bool:
        if not self._owner._lock.acquire(blocking=False):
            return False
        try:
            return self._directory_has_sample_only(directory) and self._owner._file_is_intact(directory / PRACTICE_NAME)
        finally:
            self._owner._lock.release()

    def _directory_has_sample_only(self, directory: Path) -> bool:
        try:
            return (directory in self._owner._directories
                    and self._owner._owned_path(directory)
                    and {item.name for item in directory.iterdir()} == {PRACTICE_NAME})
        except OSError:
            return False

    def _publish_file(self, staged: Path, output: Path) -> None:
        expected = self._owner._files[staged]
        self._owner._read_regular(staged, expected)
        self._owner._require_absent(output)
        # os.rename is exclusive on Windows; POSIX uses exclusive link/unlink.
        # Retain the pre-publication identity: never adopt a raced replacement.
        if os.name == "nt":
            os.rename(staged, output)
        else:
            os.link(staged, output)
            staged.unlink()
        self._owner._files.pop(staged)
        self._owner._read_regular(output, expected)
        self._owner._files[output] = expected

    def seal(self) -> sealed_file.SealResult:
        self._owner._claim()
        try:
            if not self._owner._file_is_intact(self.source) or not self._practice_password:
                raise ValueError("Practice source changed; exit and start a fresh tutorial")
            self._owner._require_absent(self.sealed)
            self._owner._require_absent(self.recovery_key)
            stage = self._owner._stage()
            sealed_directory = stage / "sealed"
            key_directory = stage / "separate-key"
            for directory in (sealed_directory, key_directory):
                directory.mkdir()
                self._owner._record_directory(directory)
            staged_sealed = sealed_directory / self.sealed.name
            staged_key = key_directory / self.recovery_key.name
            try:
                result = sealed_file.seal_file(
                    self.source, staged_sealed, password=self._practice_password,
                    recovery_key_output=staged_key, allow_plaintext_temp=True,
                    allow_recovery_same_directory=False,
                )
            except Exception:
                # Engine exception text is deliberately not forwarded to GUI logs.
                raise ValueError("Practice protection failed; exit and start a fresh tutorial") from None
            self._owner._record_file(staged_sealed)
            self._owner._record_file(staged_key)
            if not self._owner._file_is_intact(self.source):
                raise ValueError("Practice source changed during protection")
            self._owner._require_absent(self.sealed)
            self._owner._require_absent(self.recovery_key)
            self._publish_file(staged_key, self.recovery_key)
            self._publish_file(staged_sealed, self.sealed)
            self.seal_result = dataclasses.replace(
                result, sealed_file=dataclasses.replace(result.sealed_file, path=str(self.sealed)),
                source=str(self.source), recovery_key_path=str(self.recovery_key),
            )
            self._owner._remove_empty_directory(key_directory)
            self._owner._remove_empty_directory(sealed_directory)
            self._owner._remove_empty_directory(stage)
            return self.seal_result
        finally:
            self._owner._lock.release()

    def _publish_restored(self, staged: Path, output: Path) -> None:
        self._owner._require_absent(output)
        original = staged / PRACTICE_NAME
        expected_file = self._owner._files[original]
        expected_directory = self._owner._directories[staged]
        if not self._directory_has_sample_only(staged):
            raise ValueError("Practice output changed before publication")
        self._owner._read_regular(original, expected_file)
        if os.name == "nt":
            os.rename(staged, output)
            self._owner._directories.pop(staged)
            self._owner._files.pop(original)
            self._owner._directories[output] = expected_directory
            try:
                self._owner._read_regular(output / PRACTICE_NAME, expected_file)
            except (OSError, ValueError):
                self._owner._directories.pop(output)
                raise ValueError("Practice output changed during publication") from None
            self._owner._files[output / PRACTICE_NAME] = expected_file
        else:
            output.mkdir(exist_ok=False)
            self._owner._record_directory(output)
            self._publish_file(original, output / PRACTICE_NAME)
            self._owner._remove_empty_directory(staged)

    def _restore(self, *, recovery: bool) -> sealed_file.UnsealResult:
        self._owner._claim()
        try:
            if not self._owner._file_is_intact(self.sealed):
                raise ValueError("Practice Sealed File changed; exit and start a fresh tutorial")
            if recovery and not self._owner._file_is_intact(self.recovery_key):
                raise ValueError("Practice recovery key changed; exit and start a fresh tutorial")
            if not recovery and not self._practice_password:
                raise ValueError("Practice password is no longer available; start a fresh tutorial")
            output = self.recovery_output if recovery else self.password_output
            self._owner._require_absent(output)
            stage = self._owner._stage()
            restored = stage / "restored"
            try:
                # Recovery intentionally omits the password argument entirely.
                credential = {"recovery_key": self.recovery_key} if recovery else {"password": self._practice_password}
                result = sealed_file.unseal_file(
                    self.sealed, restored, **credential,
                    allow_plaintext_temp=True, allow_plaintext_output=True, replace=False,
                )
            except Exception:
                raise ValueError("Practice restoration failed; exit and start a fresh tutorial") from None
            self._owner._record_directory(restored)
            self._owner._record_file(restored / PRACTICE_NAME, PRACTICE_BYTES)
            if not self._directory_has_sample_only(restored):
                raise ValueError("Practice restore contains unexpected entries")
            if not self._owner._file_is_intact(self.sealed) or (recovery and not self._owner._file_is_intact(self.recovery_key)):
                raise ValueError("Practice encrypted input changed during restoration")
            self._publish_restored(restored, output)
            result = dataclasses.replace(result, output=str(output / PRACTICE_NAME))
            if recovery:
                self.recovery_result = result
            else:
                self.password_result = result
            self._owner._remove_empty_directory(stage)
            return result
        finally:
            self._owner._lock.release()

    def restore_with_password(self) -> sealed_file.UnsealResult:
        return self._restore(recovery=False)

    def restore_with_recovery(self) -> sealed_file.UnsealResult:
        return self._restore(recovery=True)

    def verify_restored(self) -> RestoreVerification:
        self._owner._claim()
        try:
            missing, changed, unexpected, unsafe, checks = [], [], [], [], []
            matched, total = 0, 0
            for directory in (self.password_output, self.recovery_output):
                path = directory / PRACTICE_NAME
                relative, actual = path.relative_to(self.root).as_posix(), None
                try:
                    if directory not in self._owner._directories:
                        if os.path.lexists(directory):
                            unsafe.append(directory.name)
                        else:
                            missing.append(relative)
                        continue
                    if not self._owner._owned_path(directory):
                        unsafe.append(directory.name)
                        continue
                    # Issue labels never include unknown filenames (which could
                    # contain a secret typed or introduced by another process).
                    if any(item.name != PRACTICE_NAME for item in directory.iterdir()):
                        unexpected.append(directory.name + "/<unexpected entry>")
                    expected = self._owner._files.get(path)
                    if expected is None:
                        unsafe.append(relative)
                        continue
                    data, record = self._owner._read_regular(path, expected)
                    actual = record.sha256
                    total += len(data)
                    if data == PRACTICE_BYTES:
                        matched += 1
                    else:
                        changed.append(relative)
                except FileNotFoundError:
                    missing.append(relative)
                except (OSError, ValueError):
                    changed.append(relative)
                finally:
                    checks.append(FileCheck(relative, _digest(PRACTICE_BYTES), actual,
                                            actual == _digest(PRACTICE_BYTES)))
            ok = matched == 2 and not (missing or changed or unexpected or unsafe)
            return RestoreVerification(ok, 2, matched, total, tuple(missing), tuple(changed),
                                       tuple(unexpected), tuple(unsafe), tuple(checks))
        finally:
            self._owner._lock.release()

    def cleanup(self) -> bool:
        """Remove only unchanged owned files; never claim secure erasure."""
        if self._owner.cleanup():
            self._practice_password = ""
            return True
        return False


def create_practice(parent: Path | None = None) -> ProtectionPractice:
    """Generate a fresh child folder with one public, fictional plaintext file."""
    root = Path(tempfile.mkdtemp(prefix="rat-trap-protection-tutorial-", dir=parent)).resolve()
    practice = ProtectionPractice(root)
    try:
        for directory in (practice.source.parent, practice.sealed.parent, practice.recovery_key.parent):
            directory.mkdir()
            practice._owner._record_directory(directory)
        with practice.source.open("xb") as stream:
            stream.write(PRACTICE_BYTES)
        practice._owner._record_file(practice.source, PRACTICE_BYTES)
        return practice
    except BaseException:
        practice.cleanup()
        raise
