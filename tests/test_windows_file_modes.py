"""Windows stat/fstat compatibility checks using generated, inert test bytes.

No file named like a program is ever executed. These tests retain the source
identity/content guards while ignoring only Windows' synthetic execute bits.
"""

import hashlib
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rat_trap import sealed_file, solid_engine


class FileSnapshotModeTests(unittest.TestCase):
    @staticmethod
    def value(**changes):
        fields = dict(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=1_234_567_890_123_456_789,
            st_mode=stat.S_IFREG | 0o666,
            st_nlink=1,
        )
        fields.update(changes)
        return SimpleNamespace(**fields)

    def test_windows_masks_only_synthetic_execute_bits(self):
        # Keep all Path/file-system work outside the os.name patch.
        with mock.patch.object(solid_engine.os, "name", "nt"):
            expected = solid_engine._RegularFileSnapshot.from_stat(self.value())
            for execute_bits in (
                stat.S_IXUSR,
                stat.S_IXGRP,
                stat.S_IXOTH,
                stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
            ):
                with self.subTest(execute_bits=oct(execute_bits)):
                    actual = solid_engine._RegularFileSnapshot.from_stat(
                        self.value(st_mode=stat.S_IFREG | 0o666 | execute_bits)
                    )
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual.mode, stat.S_IFREG | 0o666)

    def test_windows_retains_every_other_identity_and_permission_field(self):
        changes = [
            {"st_dev": 12},
            {"st_ino": 23},
            {"st_size": 4097},
            {"st_mtime_ns": 1_234_567_890_123_456_790},
            {"st_nlink": 2},
            {"st_mode": stat.S_IFDIR | 0o666},
            {"st_mode": stat.S_IFLNK | 0o666},
            {"st_mode": stat.S_IFREG | 0o666 | stat.S_ISUID},
            {"st_mode": stat.S_IFREG | 0o666 | stat.S_ISGID},
            {"st_mode": stat.S_IFREG | 0o666 | stat.S_ISVTX},
        ]
        for bit in (
            stat.S_IRUSR, stat.S_IWUSR, stat.S_IRGRP,
            stat.S_IWGRP, stat.S_IROTH, stat.S_IWOTH,
        ):
            changes.append({"st_mode": (stat.S_IFREG | 0o666) & ~bit})
        with mock.patch.object(solid_engine.os, "name", "nt"):
            expected = solid_engine._RegularFileSnapshot.from_stat(self.value())
            for fields in changes:
                with self.subTest(fields=fields):
                    actual = solid_engine._RegularFileSnapshot.from_stat(
                        self.value(**fields)
                    )
                    self.assertNotEqual(actual, expected)

    def test_posix_retains_execute_permission_changes(self):
        with mock.patch.object(solid_engine.os, "name", "posix"):
            expected = solid_engine._RegularFileSnapshot.from_stat(self.value())
            for execute_bit in (stat.S_IXUSR, stat.S_IXGRP, stat.S_IXOTH):
                with self.subTest(execute_bit=oct(execute_bit)):
                    mode = stat.S_IFREG | 0o666 | execute_bit
                    actual = solid_engine._RegularFileSnapshot.from_stat(
                        self.value(st_mode=mode)
                    )
                    self.assertEqual(actual.mode, mode)
                    self.assertNotEqual(actual, expected)


@unittest.skipUnless(os.name == "nt", "Exercises real Windows lstat/fstat modes")
class WindowsInertFileModeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="rat-trap-windows-mode-test-"
        )
        self.root = Path(self.temporary.name).resolve()
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.root.name.startswith("rat-trap-windows-mode-test-"))
        self.addCleanup(self.temporary.cleanup)
        self.readonly_paths = []
        # Clear read-only attributes only on exact test-created files, before
        # TemporaryDirectory removes this test's unique temporary directory.
        self.addCleanup(self._restore_test_file_modes)

    def _restore_test_file_modes(self):
        for path in self.readonly_paths:
            self.assertEqual(path.resolve().parent, self.root)
            if path.exists():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)

    def _assert_not_published(self, archive):
        self.assertFalse(archive.exists())
        self.assertEqual(
            list(self.root.glob(f".{archive.name}.*.rat-trap-build")), []
        )

    def test_inert_executable_suffixes_round_trip_with_both_compressors(self):
        payload = b"INERT TEST DATA - NEVER EXECUTED\n" + bytes(range(256)) * 64
        expected_hash = hashlib.sha256(payload).hexdigest()
        suffixes = (
            ".exe", ".EXE", ".com", ".COM", ".bat", ".BAT", ".cmd", ".CMD",
            ".txt", ".dll", ".ps1", ".py", ".exe.txt", ".txt.exe", "",
        )
        for index, suffix in enumerate(suffixes):
            source = self.root / f"inert-{index}{suffix}"
            source.write_bytes(payload)
            original_stat = source.lstat()
            with source.open("rb") as handle:
                snapshot = solid_engine._RegularFileSnapshot.from_stat(
                    os.fstat(handle.fileno())
                )
                self.assertTrue(
                    solid_engine._source_matches_snapshot(source, handle, snapshot)
                )
            for compressor in ("zstd", "xz"):
                with self.subTest(suffix=suffix, compressor=compressor):
                    archive = self.root / f"archive-{index}-{compressor}.gmw"
                    restored = self.root / f"restored-{index}-{compressor}{suffix}"
                    result = solid_engine.compress_file(
                        source, archive, compressor=compressor
                    )
                    info = solid_engine.inspect_single_file(archive)
                    solid_engine.extract_single_file(archive, restored, expected=info)
                    self.assertEqual(result.file_count, 1)
                    self.assertEqual(info.name, source.name)
                    self.assertEqual(info.sha256, expected_hash)
                    self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(), expected_hash)
                    self.assertEqual(source.read_bytes(), payload)
                    after = source.lstat()
                    self.assertEqual(after.st_mode, original_stat.st_mode)
                    self.assertEqual(after.st_ino, original_stat.st_ino)
                    self.assertEqual(after.st_mtime_ns, original_stat.st_mtime_ns)

    def test_readonly_inputs_round_trip_without_changing_source_permissions(self):
        payload = b"INERT READ-ONLY TEST INPUT\n" * 512
        for index, suffix in enumerate((".exe", ".EXE", ".com", ".bat", ".cmd", ".txt")):
            with self.subTest(suffix=suffix):
                source = self.root / f"readonly-{index}{suffix}"
                restored = self.root / f"restored-readonly-{index}{suffix}"
                source.write_bytes(payload)
                self.readonly_paths.extend((source, restored))
                source.chmod(stat.S_IREAD)
                original_stat = source.lstat()
                self.assertFalse(original_stat.st_mode & stat.S_IWUSR)
                archive = self.root / f"readonly-{index}.gmw"
                solid_engine.compress_file(source, archive)
                info = solid_engine.inspect_single_file(archive)
                solid_engine.extract_single_file(archive, restored, expected=info)
                self.assertEqual(info.sha256, hashlib.sha256(payload).hexdigest())
                self.assertEqual(restored.read_bytes(), payload)
                self.assertEqual(source.read_bytes(), payload)
                self.assertEqual(source.lstat().st_mode, original_stat.st_mode)
                self.assertEqual(source.lstat().st_mtime_ns, original_stat.st_mtime_ns)

    def test_inert_exe_seal_and_restore_preserves_source(self):
        source_directory = self.root / "source"
        source_directory.mkdir()
        source = source_directory / "inert.exe"
        payload = b"GENERATED SEALED-FILE TEST INPUT - NOT A PROGRAM\n" * 256
        source.write_bytes(payload)
        original_mode = source.lstat().st_mode
        output = self.root / "sealed" / "inert.rtsf"
        recovery = self.root / "keys" / "inert.rtrk"
        result = sealed_file.seal_file(
            source,
            output,
            password="Generated test password 2026!",
            recovery_key_output=recovery,
            allow_plaintext_temp=True,
        )
        restored_directory = self.root / "restored"
        sealed_file.unseal_file(
            output,
            restored_directory,
            recovery_key=recovery,
            allow_plaintext_temp=True,
            allow_plaintext_output=True,
        )
        self.assertTrue(result.source_retained)
        self.assertEqual((restored_directory / "inert.exe").read_bytes(), payload)
        self.assertEqual(source.read_bytes(), payload)
        self.assertEqual(source.lstat().st_mode, original_mode)

    def test_real_content_mutation_during_compression_read_is_not_published(self):
        source = self.root / "read-changing.exe"
        original = b"A" * 262_144
        changed = b"B" * len(original)
        source.write_bytes(original)
        initial_stat = source.stat()
        archive = self.root / "read-changing.gmw"
        original_read = solid_engine._HashingReader.read
        mutated = False

        def read_then_mutate(reader, size=-1):
            nonlocal mutated
            data = original_read(reader, size)
            if data and not mutated:
                mutated = True
                with source.open("r+b") as writer:
                    writer.write(changed)
                    writer.flush()
                    os.fsync(writer.fileno())
                os.utime(source, ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns))
            return data

        with (
            mock.patch.object(solid_engine._HashingReader, "read", new=read_then_mutate),
            self.assertRaisesRegex(ValueError, "changed"),
        ):
            solid_engine.compress_file(source, archive)
        self.assertTrue(mutated)
        self.assertEqual(source.read_bytes(), changed)
        self._assert_not_published(archive)

    def test_real_same_size_mutation_at_tar_addfile_is_not_published(self):
        source = self.root / "tar-changing.exe"
        original = b"C" * 131_072
        changed = b"D" * len(original)
        source.write_bytes(original)
        initial_stat = source.stat()
        archive = self.root / "tar-changing.gmw"
        original_addfile = solid_engine.tarfile.TarFile.addfile

        def mutate_then_add(tar, tarinfo, fileobj=None):
            with source.open("r+b") as writer:
                writer.write(changed)
                writer.flush()
                os.fsync(writer.fileno())
            os.utime(source, ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns))
            return original_addfile(tar, tarinfo, fileobj)

        with (
            mock.patch.object(solid_engine.tarfile.TarFile, "addfile", new=mutate_then_add),
            self.assertRaisesRegex(ValueError, "changed"),
        ):
            solid_engine.compress_file(source, archive)
        self.assertEqual(source.read_bytes(), changed)
        self._assert_not_published(archive)

    def test_real_readonly_change_is_still_detected(self):
        source = self.root / "permissions-changing.exe"
        payload = b"SOURCE BYTES MUST SURVIVE A PERMISSION CHANGE\n" * 1024
        source.write_bytes(payload)
        self.readonly_paths.append(source)
        archive = self.root / "permissions-changing.gmw"
        original_digest = solid_engine._digest_open_file

        def digest_then_change_permissions(handle, size):
            digest = original_digest(handle, size)
            source.chmod(stat.S_IREAD)
            return digest

        with (
            mock.patch.object(solid_engine, "_digest_open_file", new=digest_then_change_permissions),
            self.assertRaisesRegex(ValueError, "changed"),
        ):
            solid_engine.compress_file(source, archive)
        self.assertFalse(source.stat().st_mode & stat.S_IWUSR)
        self.assertEqual(source.read_bytes(), payload)
        self._assert_not_published(archive)

    def test_real_path_replacement_is_denied_or_detected(self):
        source = self.root / "path-changing.exe"
        retained = self.root / "retained-original.exe"
        original = b"ORIGINAL INERT BYTES\n" * 1024
        replacement = b"REPLACEMENT INERT DATA\n" * 1024
        source.write_bytes(original)
        archive = self.root / "path-changing.gmw"
        original_addfile = solid_engine.tarfile.TarFile.addfile
        rename_denied = False

        def replace_then_add(tar, tarinfo, fileobj=None):
            nonlocal rename_denied
            try:
                source.rename(retained)
            except PermissionError:
                rename_denied = True
                raise
            source.write_bytes(replacement)
            return original_addfile(tar, tarinfo, fileobj)

        with mock.patch.object(solid_engine.tarfile.TarFile, "addfile", new=replace_then_add):
            try:
                solid_engine.compress_file(source, archive)
            except PermissionError:
                self.assertTrue(rename_denied)
                self.assertEqual(source.read_bytes(), original)
                self.assertFalse(retained.exists())
            except ValueError as error:
                self.assertFalse(rename_denied)
                self.assertIn("changed", str(error))
                self.assertEqual(retained.read_bytes(), original)
                self.assertEqual(source.read_bytes(), replacement)
            else:
                self.fail("A denied or detected path replacement must not publish an archive")
        self._assert_not_published(archive)


if __name__ == "__main__":
    unittest.main()
