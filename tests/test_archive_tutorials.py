"""Real sample-archive round trips and conservative practice ownership."""

import dataclasses
import hashlib
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import archive_tutorials as lessons


class ArchivePracticeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rat-trap-archive-practice-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.sentinel = self.base / "unrelated.txt"
        self.sentinel.write_bytes(b"Generated stand-in for unrelated user data")

    def practice(self, with_archive=False):
        practice = lessons.create_practice(self.base, with_archive=with_archive)
        self.addCleanup(practice.cleanup)
        return practice

    def test_each_session_is_fresh_contained_and_source_data_deterministic(self):
        first, second = self.practice(), self.practice()
        self.assertNotEqual(first.root, second.root)
        for practice in (first, second):
            self.assertEqual(practice.root.parent, self.base.resolve())
            self.assertEqual(practice.archive.parent, practice.root)
            self.assertFalse(practice.archive.is_relative_to(practice.source))
            self.assertEqual(practice.restored.parent, practice.root)
            self.assertFalse(practice.archive.exists())
            self.assertFalse(practice.restored.exists())
            self.assertTrue(practice.source_is_intact())
            self.assertFalse(practice.archive_is_intact())
            self.assertFalse(practice.busy)
            self.assertIsNone(practice.archive_metadata)
            self.assertIsNone(practice.profile)
            for relative, content in lessons.PRACTICE_FILES.items():
                self.assertEqual((practice.source / relative).read_bytes(), content)

    def test_paths_cannot_be_redirected_to_a_user_folder(self):
        practice = self.practice()
        for name in ("root", "source", "archive", "restored", "profile"):
            with self.subTest(name=name), self.assertRaises(AttributeError):
                setattr(practice, name, self.base)

    def test_all_supported_profiles_use_real_engine_and_match_every_restored_byte(self):
        for profile in lessons.ALLOWED_PROFILES:
            with self.subTest(profile=profile):
                practice = self.practice()
                compressed = practice.create_archive(profile)
                self.assertEqual(compressed.profile, profile)
                self.assertEqual(compressed.format, "GMW-SOLID-2")
                self.assertEqual(compressed.file_count, len(lessons.PRACTICE_FILES))
                self.assertEqual(compressed.total_bytes, sum(map(len, lessons.PRACTICE_FILES.values())))
                self.assertIs(practice.archive_metadata, compressed)
                self.assertEqual(practice.profile, profile)
                self.assertTrue(practice.archive_is_intact())
                archive_before = practice.archive.read_bytes()
                restored = practice.restore_archive()
                self.assertIs(practice.restore_metadata, restored)
                self.assertEqual(restored.file_count, compressed.file_count)
                report = practice.verify_restored()
                self.assertTrue(report.ok, report)
                self.assertEqual(report.file_count, len(lessons.PRACTICE_FILES))
                self.assertEqual(report.matched_files, report.file_count)
                self.assertEqual(report.total_bytes, compressed.total_bytes)
                self.assertEqual(practice.archive.read_bytes(), archive_before)
                self.assertTrue(practice.source_is_intact())
                self.assertTrue(practice.archive_is_intact())
                for check in report.checks:
                    self.assertTrue(check.matches)
                    expected = hashlib.sha256(lessons.PRACTICE_FILES[check.path]).hexdigest()
                    self.assertEqual(check.expected_sha256, expected)
                    self.assertEqual(check.actual_sha256, expected)
                    self.assertEqual((practice.restored / check.path).read_bytes(), lessons.PRACTICE_FILES[check.path])
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    report.ok = False

    def test_restore_lesson_can_start_with_a_real_balanced_sample_archive(self):
        practice = self.practice(with_archive=True)
        self.assertEqual(practice.archive_metadata.profile, "balanced")
        self.assertEqual(practice.profile, "balanced")
        self.assertTrue(practice.archive_is_intact())
        self.assertFalse(practice.restored.exists())
        practice.restore_archive()
        self.assertTrue(practice.verify_restored().ok)

    def test_unsupported_profiles_do_not_start_the_engine_or_create_any_output(self):
        practice = self.practice()
        for profile in ("vault", "deduplicate", "custom", "", None, "Balanced", "../outside"):
            with self.subTest(profile=profile), mock.patch.object(lessons.gmw_tool, "compress_folder") as engine:
                with self.assertRaises(ValueError):
                    practice.create_archive(profile)
                engine.assert_not_called()
                self.assertFalse(practice.archive.exists())
                self.assertFalse(practice.busy)

    def test_repeat_create_refuses_existing_archive_and_preserves_bytes(self):
        practice = self.practice(with_archive=True)
        original = practice.archive.read_bytes()
        with mock.patch.object(lessons.gmw_tool, "compress_folder") as engine:
            with self.assertRaises(FileExistsError):
                practice.create_archive("smallest")
            engine.assert_not_called()
        self.assertEqual(practice.archive.read_bytes(), original)
        self.assertTrue(practice.archive_is_intact())

    def test_existing_unowned_archive_is_never_overwritten_or_cleaned(self):
        practice = self.practice()
        practice.archive.write_bytes(b"Generated unowned destination")
        with mock.patch.object(lessons.gmw_tool, "compress_folder") as engine:
            with self.assertRaises(FileExistsError):
                practice.create_archive()
            engine.assert_not_called()
        practice.cleanup()
        self.assertEqual(practice.archive.read_bytes(), b"Generated unowned destination")

    def test_repeat_restore_refuses_existing_destination_and_preserves_files(self):
        practice = self.practice(with_archive=True)
        practice.restore_archive()
        with mock.patch.object(lessons.gmw_tool, "extract_archive") as engine:
            with self.assertRaises(FileExistsError):
                practice.restore_archive()
            engine.assert_not_called()
        self.assertTrue(practice.verify_restored().ok)

    def test_even_empty_existing_restore_directory_is_not_merged_or_removed(self):
        practice = self.practice(with_archive=True)
        practice.restored.mkdir()
        with mock.patch.object(lessons.gmw_tool, "extract_archive") as engine:
            with self.assertRaises(FileExistsError):
                practice.restore_archive()
            engine.assert_not_called()
        practice.cleanup()
        self.assertTrue(practice.restored.is_dir())

    def test_source_edits_and_unexpected_entries_block_compression(self):
        for change in ("edit", "extra-file", "extra-directory"):
            with self.subTest(change=change):
                practice = self.practice()
                if change == "edit":
                    (practice.source / "documents/shopping.txt").write_bytes(b"Generated changed content")
                elif change == "extra-file":
                    (practice.source / "documents/unrelated.txt").write_bytes(b"Do not read this extra fixture")
                else:
                    (practice.source / "unrelated-directory").mkdir()
                self.assertFalse(practice.source_is_intact())
                with mock.patch.object(lessons.gmw_tool, "compress_folder") as engine:
                    with self.assertRaises(ValueError):
                        practice.create_archive()
                    engine.assert_not_called()

    def test_same_bytes_in_replaced_source_or_archive_are_rejected_and_retained(self):
        for kind in ("source", "archive"):
            with self.subTest(kind=kind):
                practice = self.practice(with_archive=True)
                target = practice.archive if kind == "archive" else practice.source / "documents/shopping.txt"
                content = target.read_bytes()
                replacement = practice.root / "generated-replacement"
                replacement.write_bytes(content)
                replacement.replace(target)
                integrity = practice.archive_is_intact if kind == "archive" else practice.source_is_intact
                self.assertFalse(integrity())
                practice.cleanup()
                self.assertEqual(target.read_bytes(), content)

    def test_modified_archive_never_reaches_restore_engine(self):
        practice = self.practice(with_archive=True)
        practice.archive.write_bytes(b"Generated changed archive")
        self.assertFalse(practice.archive_is_intact())
        with mock.patch.object(lessons.gmw_tool, "extract_archive") as engine:
            with self.assertRaises(ValueError):
                practice.restore_archive()
            engine.assert_not_called()
        self.assertFalse(practice.restored.exists())

    def test_source_and_archive_hard_links_are_rejected_and_not_unlinked_by_cleanup(self):
        for kind in ("source", "archive"):
            with self.subTest(kind=kind):
                practice = self.practice(with_archive=True)
                target = practice.archive if kind == "archive" else practice.source / "documents/shopping.txt"
                link = self.base / f"generated-hardlink-{kind}"
                try:
                    os.link(target, link)
                except OSError as exc:
                    self.skipTest(f"Hard links unavailable: {exc}")
                integrity = practice.archive_is_intact if kind == "archive" else practice.source_is_intact
                self.assertFalse(integrity())
                practice.cleanup()
                self.assertTrue(target.exists())
                self.assertTrue(link.exists())
                link.unlink()

    @unittest.skipUnless(os.name == "nt", "Windows directory junction boundary")
    def test_replaced_source_junction_is_not_traversed_for_reads_or_cleanup(self):
        import _winapi

        practice = self.practice()
        outside = self.base / "outside-generated-tree"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_bytes(b"Outside fixture")
        original = practice.root / "original-sample-files"
        practice.source.rename(original)
        _winapi.CreateJunction(str(outside), str(practice.source))
        try:
            self.assertFalse(practice.source_is_intact())
            with mock.patch.object(lessons.gmw_tool, "compress_folder") as engine:
                with self.assertRaises(ValueError):
                    practice.create_archive()
                engine.assert_not_called()
            practice.cleanup()
            self.assertEqual(sentinel.read_bytes(), b"Outside fixture")
            self.assertTrue((original / "documents/shopping.txt").exists())
        finally:
            if practice.source.is_junction():
                practice.source.rmdir()

    def test_replaced_ordinary_source_directory_with_identical_files_is_rejected(self):
        practice = self.practice()
        original = practice.root / "original-sample-files"
        practice.source.rename(original)
        for relative, content in lessons.PRACTICE_FILES.items():
            path = practice.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.assertFalse(practice.source_is_intact())
        practice.cleanup()
        self.assertTrue((practice.source / "documents/shopping.txt").exists())
        self.assertTrue((original / "documents/shopping.txt").exists())

    def test_verification_reports_changed_missing_and_extra_files_without_claiming_success(self):
        practice = self.practice(with_archive=True)
        practice.restore_archive()
        changed = practice.restored / "documents/shopping.txt"
        changed.write_bytes(b"Generated post-restore edit")
        missing = practice.restored / "documents/garden.txt"
        missing.unlink()
        extra = practice.restored / "unrelated.txt"
        extra.write_bytes(b"Generated unrelated restore output")
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertEqual(report.matched_files, 1)
        self.assertIn("documents/shopping.txt", report.changed_files)
        self.assertIn("documents/garden.txt", report.missing_files)
        self.assertIn("unrelated.txt", report.unexpected_files)
        check = next(item for item in report.checks if item.path == "documents/shopping.txt")
        self.assertEqual(check.actual_sha256, hashlib.sha256(changed.read_bytes()).hexdigest())
        self.assertFalse(check.matches)
        practice.cleanup()
        self.assertTrue(changed.exists())
        self.assertTrue(extra.exists())

    def test_verification_never_follows_replaced_restored_file(self):
        practice = self.practice(with_archive=True)
        practice.restore_archive()
        target = practice.restored / "documents/shopping.txt"
        replacement = practice.root / "generated-replacement"
        replacement.write_bytes(target.read_bytes())
        replacement.replace(target)
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertIn("documents/shopping.txt", report.unsafe_paths)
        check = next(item for item in report.checks if item.path == "documents/shopping.txt")
        self.assertIsNone(check.actual_sha256)
        practice.cleanup()
        self.assertTrue(target.exists())

    def test_verification_compares_contents_when_only_a_restored_timestamp_changed(self):
        practice = self.practice(with_archive=True)
        practice.restore_archive()
        target = practice.restored / "documents/shopping.txt"
        before = target.stat()
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
        report = practice.verify_restored()
        self.assertTrue(report.ok, report)
        self.assertTrue(all(check.matches for check in report.checks))
        # Cleanup stays stricter than a content comparison and conservatively
        # retains an owned file whose metadata was changed after restoration.
        practice.cleanup()
        self.assertTrue(target.exists())

    def test_verification_before_restore_is_not_success(self):
        practice = self.practice(with_archive=True)
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertEqual(report.matched_files, 0)

    def test_cleanup_removes_only_unchanged_owned_files_and_is_idempotent(self):
        practice = self.practice(with_archive=True)
        practice.restore_archive()
        self.assertTrue(practice.cleanup())
        self.assertFalse(practice.root.exists())
        self.assertTrue(practice.cleanup())
        self.assertEqual(list(self.base.iterdir()), [self.sentinel])

    def test_cleanup_preserves_changed_owned_files_and_unexpected_nested_file(self):
        practice = self.practice(with_archive=True)
        practice.restore_archive()
        changed = practice.source / "documents/shopping.txt"
        changed.write_bytes(b"Generated user edit")
        extra = practice.root / "unrelated" / "retained.gmw"
        extra.parent.mkdir()
        extra.write_bytes(b"Generated unowned archive")
        practice.cleanup()
        self.assertEqual(changed.read_bytes(), b"Generated user edit")
        self.assertEqual(extra.read_bytes(), b"Generated unowned archive")
        self.assertFalse(practice.archive.exists())
        self.assertFalse(practice.restored.exists())
        self.assertTrue(self.sentinel.exists())

    def test_busy_worker_owns_files_until_completion_and_other_actions_are_rejected(self):
        practice = self.practice()
        entered, finish = threading.Event(), threading.Event()
        real_compress = lessons.gmw_tool.compress_folder
        outcomes = []

        def blocked(*args, **kwargs):
            entered.set()
            if not finish.wait(10):
                raise RuntimeError("Generated test worker timeout")
            return real_compress(*args, **kwargs)

        def worker():
            try:
                outcomes.append(practice.create_archive())
            except BaseException as exc:
                outcomes.append(exc)

        with mock.patch.object(lessons.gmw_tool, "compress_folder", side_effect=blocked):
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(practice.busy)
                self.assertFalse(practice.cleanup())
                self.assertTrue(practice.source.exists())
                self.assertFalse(practice.source_is_intact())
                self.assertFalse(practice.archive_is_intact())
                for action in (practice.create_archive, practice.restore_archive, practice.verify_restored):
                    with self.assertRaises(RuntimeError):
                        action()
            finally:
                finish.set()
                thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertFalse(isinstance(outcomes[0], BaseException), outcomes)
        self.assertFalse(practice.busy)
        self.assertTrue(practice.archive_is_intact())
        self.assertTrue(practice.cleanup())
        self.assertFalse(practice.root.exists())

    def test_engine_failure_releases_session_and_cleanup_does_not_remove_unowned_output(self):
        practice = self.practice()

        def fail(_source, output, **_kwargs):
            output.write_bytes(b"Generated unconfirmed partial output")
            raise RuntimeError("Generated compression failure")

        with mock.patch.object(lessons.gmw_tool, "compress_folder", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "Generated compression failure"):
                practice.create_archive()
        self.assertFalse(practice.busy)
        self.assertIsNone(practice.archive_metadata)
        self.assertIsNone(practice.profile)
        self.assertFalse(practice.archive.exists())
        self.assertTrue(practice.source_is_intact())
        staged = list(practice.root.glob(".practice-operation-*/archive.gmw"))
        self.assertEqual(len(staged), 1)
        practice.cleanup()
        self.assertEqual(staged[0].read_bytes(), b"Generated unconfirmed partial output")

    def test_newly_appearing_archive_destination_is_preserved_at_publication(self):
        practice = self.practice()
        real_compress = lessons.gmw_tool.compress_folder

        def create_collision(*args, **kwargs):
            metadata = real_compress(*args, **kwargs)
            practice.archive.write_bytes(b"Generated destination that appeared while compressing")
            return metadata

        with mock.patch.object(lessons.gmw_tool, "compress_folder", side_effect=create_collision):
            with self.assertRaises(FileExistsError):
                practice.create_archive()
        practice.cleanup()
        self.assertEqual(practice.archive.read_bytes(), b"Generated destination that appeared while compressing")

    def test_newly_appearing_restore_destination_is_preserved_at_publication(self):
        practice = self.practice(with_archive=True)
        real_extract = lessons.gmw_tool.extract_archive

        def create_collision(*args, **kwargs):
            metadata = real_extract(*args, **kwargs)
            practice.restored.mkdir()
            (practice.restored / "unrelated.txt").write_bytes(b"Generated new destination file")
            return metadata

        with mock.patch.object(lessons.gmw_tool, "extract_archive", side_effect=create_collision):
            with self.assertRaises(FileExistsError):
                practice.restore_archive()
        practice.cleanup()
        self.assertEqual((practice.restored / "unrelated.txt").read_bytes(), b"Generated new destination file")

    def test_source_changed_during_compression_does_not_publish_archive(self):
        practice = self.practice()
        real_compress = lessons.gmw_tool.compress_folder

        def change_source(*args, **kwargs):
            metadata = real_compress(*args, **kwargs)
            (practice.source / "documents/shopping.txt").write_bytes(b"Generated concurrent sample edit")
            return metadata

        with mock.patch.object(lessons.gmw_tool, "compress_folder", side_effect=change_source):
            with self.assertRaisesRegex(ValueError, "changed during compression"):
                practice.create_archive()
        self.assertFalse(practice.archive.exists())
        self.assertFalse(practice.busy)

    def test_parent_file_cannot_be_reused_as_practice_folder(self):
        before = self.sentinel.read_bytes()
        with self.assertRaises(OSError):
            lessons.create_practice(self.sentinel)
        self.assertEqual(self.sentinel.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
