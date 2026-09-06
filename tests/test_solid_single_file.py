import hashlib
import os
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from rat_trap import solid_engine


class SolidSingleFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_unicode_incompressible_file_round_trip_and_inspection(self) -> None:
        source = self.root / "résumé-資料.bin"
        payload = random.Random(20260729).randbytes(300_000)
        source.write_bytes(payload)
        archive = self.root / "sealed-inner.gmw"

        created = solid_engine.compress_file(source, archive)
        inspected = solid_engine.inspect_single_file(archive)

        self.assertEqual(created.format, "GMW-SOLID-2")
        self.assertEqual(created.profile, "sealed-file")
        self.assertEqual(created.compressor, "zstd")
        self.assertEqual(created.compression_level, 6)
        self.assertEqual(created.file_count, 1)
        self.assertEqual(created.directory_count, 0)
        self.assertEqual(created.total_bytes, len(payload))
        self.assertFalse(created.whole_file_dedup)
        self.assertEqual(inspected.metadata, created)
        self.assertEqual(inspected.name, source.name)
        self.assertEqual(inspected.size, len(payload))
        self.assertEqual(
            inspected.sha256, hashlib.sha256(payload).hexdigest()
        )

        output = self.root / "explicit-output.bin"
        extracted = solid_engine.extract_single_file(
            archive,
            output,
            expected=inspected,
        )
        self.assertEqual(extracted, inspected)
        self.assertEqual(output.read_bytes(), payload)

    def test_empty_file_and_safe_nested_stored_name(self) -> None:
        source = self.root / "empty.txt"
        source.write_bytes(b"")
        archive = self.root / "empty.gmw"
        solid_engine.compress_file(
            source,
            archive,
            stored_name="nested/empty-α.txt",
        )

        inspected = solid_engine.inspect_single_file(archive)
        self.assertEqual(inspected.name, "nested/empty-α.txt")
        self.assertEqual(inspected.size, 0)
        self.assertEqual(
            inspected.sha256, hashlib.sha256(b"").hexdigest()
        )

        output = self.root / "restored-empty.txt"
        solid_engine.extract_single_file(archive, output)
        self.assertEqual(output.read_bytes(), b"")

    def test_input_aliases_nonregular_sources_and_unsafe_names_are_refused(
        self,
    ) -> None:
        source = self.root / "source.bin"
        original = b"source must survive"
        source.write_bytes(original)

        with self.assertRaisesRegex(ValueError, "must not replace"):
            solid_engine.compress_file(source, source)
        self.assertEqual(source.read_bytes(), original)

        hardlink = self.root / "source-hardlink.bin"
        os.link(source, hardlink)
        with self.assertRaisesRegex(ValueError, "must not replace"):
            solid_engine.compress_file(source, hardlink)
        self.assertEqual(source.read_bytes(), original)

        with self.assertRaisesRegex(ValueError, "unsafe path"):
            solid_engine.compress_file(
                source,
                self.root / "unsafe-name.gmw",
                stored_name="../escape.bin",
            )

        directory = self.root / "directory"
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, "ordinary"):
            solid_engine.compress_file(
                directory,
                self.root / "directory.gmw",
            )

        symlink = self.root / "source-link.bin"
        try:
            symlink.symlink_to(source)
        except OSError:
            pass
        else:
            with self.assertRaisesRegex(ValueError, "ordinary"):
                solid_engine.compress_file(
                    symlink,
                    self.root / "symlink.gmw",
                )

    def test_same_size_content_change_is_detected_and_not_published(
        self,
    ) -> None:
        source = self.root / "changing.bin"
        source.write_bytes(b"A" * 128_000)
        archive = self.root / "changing.gmw"
        original_addfile = solid_engine.tarfile.TarFile.addfile

        def mutate_then_add(
            tar,
            tarinfo,
            fileobj=None,
        ):
            with open(source, "r+b") as changing:
                changing.seek(0)
                changing.write(b"B" * 128_000)
                changing.flush()
                os.fsync(changing.fileno())
            return original_addfile(tar, tarinfo, fileobj)

        with (
            mock.patch.object(
                solid_engine,
                "_source_matches_snapshot",
                return_value=True,
            ),
            mock.patch.object(
                solid_engine.tarfile.TarFile,
                "addfile",
                new=mutate_then_add,
            ),
            self.assertRaisesRegex(ValueError, "changed"),
        ):
            solid_engine.compress_file(source, archive)

        self.assertFalse(archive.exists())
        self.assertEqual(
            list(self.root.glob(".changing.gmw.*.rat-trap-build")),
            [],
        )

    def test_source_path_identity_change_is_not_published(self) -> None:
        source = self.root / "replaced.bin"
        source.write_bytes(b"stable bytes")
        archive = self.root / "replaced.gmw"

        with (
            mock.patch.object(
                solid_engine,
                "_source_matches_snapshot",
                side_effect=(True, True, False),
            ),
            self.assertRaisesRegex(ValueError, "changed"),
        ):
            solid_engine.compress_file(source, archive)

        self.assertFalse(archive.exists())
        self.assertEqual(
            list(self.root.glob(".replaced.gmw.*.rat-trap-build")),
            [],
        )

    def test_existing_extract_destination_is_preserved_unless_replace_is_true(
        self,
    ) -> None:
        source = self.root / "source.txt"
        source.write_bytes(b"new protected content")
        archive = self.root / "one.gmw"
        solid_engine.compress_file(source, archive)
        output = self.root / "output.txt"
        output.write_bytes(b"existing content")

        with self.assertRaises(FileExistsError):
            solid_engine.extract_single_file(archive, output)
        self.assertEqual(output.read_bytes(), b"existing content")

        solid_engine.extract_single_file(archive, output, replace=True)
        self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_expected_mismatch_and_archive_alias_publish_nothing(self) -> None:
        source = self.root / "source.txt"
        source.write_bytes(b"expected identity")
        archive = self.root / "one.gmw"
        solid_engine.compress_file(source, archive)
        inspected = solid_engine.inspect_single_file(archive)
        output = self.root / "mismatch.txt"

        with self.assertRaisesRegex(ValueError, "no longer matches"):
            solid_engine.extract_single_file(
                archive,
                output,
                expected=replace(inspected, sha256="0" * 64),
            )
        self.assertFalse(output.exists())
        self.assertEqual(
            list(self.root.glob(".mismatch.txt.*.rat-trap-part")),
            [],
        )

        archive_before = archive.read_bytes()
        alias = self.root / "archive-hardlink.gmw"
        os.link(archive, alias)
        with self.assertRaisesRegex(ValueError, "must not replace"):
            solid_engine.extract_single_file(
                archive,
                alias,
                replace=True,
            )
        self.assertEqual(archive.read_bytes(), archive_before)

    def test_multi_entry_and_directory_archives_are_not_single_files(
        self,
    ) -> None:
        source = self.root / "tree"
        source.mkdir()
        (source / "a.txt").write_text("a", encoding="utf-8")
        (source / "b.txt").write_text("b", encoding="utf-8")
        multi = self.root / "multi.gmw"
        solid_engine.compress_folder(
            source,
            multi,
            whole_file_dedup=False,
        )

        with self.assertRaisesRegex(ValueError, "exact one-file"):
            solid_engine.inspect_single_file(multi)
        multi_output = self.root / "multi-output.txt"
        with self.assertRaisesRegex(ValueError, "exact one-file"):
            solid_engine.extract_single_file(multi, multi_output)
        self.assertFalse(multi_output.exists())

        (source / "b.txt").unlink()
        (source / "empty-directory").mkdir()
        with_directory = self.root / "with-directory.gmw"
        solid_engine.compress_folder(
            source,
            with_directory,
            whole_file_dedup=False,
        )
        with self.assertRaisesRegex(ValueError, "exact one-file"):
            solid_engine.inspect_single_file(with_directory)


if __name__ == "__main__":
    unittest.main()
