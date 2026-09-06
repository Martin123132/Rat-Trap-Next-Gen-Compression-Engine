"""Real fictional repository history plus conservative ownership boundaries."""

import dataclasses
import hashlib
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import history_tutorials as lessons
from rat_trap import repository_engine


class HistoryPracticeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rat-trap-history-tests-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.sentinel = self.base / "unrelated.txt"
        self.sentinel.write_bytes(b"Fictional unrelated-data stand-in")

    def practice(self, *, first=False, second=False, restored=False):
        practice = lessons.create_practice(self.base)
        self.addCleanup(practice.cleanup)
        if first or second or restored:
            practice.create_first_backup()
        if second or restored:
            practice.change_sample()
            practice.create_second_backup()
        if restored:
            practice.restore_older()
        return practice

    def assert_source(self, practice, expected):
        self.assertEqual({p.name: p.read_bytes() for p in practice.source.iterdir()}, dict(expected))

    def assert_sentinel(self):
        self.assertEqual(self.sentinel.read_bytes(), b"Fictional unrelated-data stand-in")

    def test_fresh_sessions_paths_and_known_fictional_data(self):
        first, second = self.practice(), self.practice()
        self.assertNotEqual(first.root, second.root)
        for practice in (first, second):
            self.assertEqual(practice.root.parent, self.base.resolve())
            self.assertTrue(practice.source_is_intact())
            self.assertFalse(practice.repository_is_intact())
            self.assertFalse(practice.restored_is_intact())
            self.assertFalse(practice.repository.exists())
            self.assertFalse(practice.restored.exists())
            self.assertEqual(practice.source_version, 1)
            self.assertIsNone(practice.first_snapshot)
            self.assertIsNone(practice.second_snapshot)
            self.assertIsNone(practice.restore_result)
            self.assertEqual(practice.history, ())
            self.assertFalse(practice.busy)
            self.assert_source(practice, lessons.FIRST_FILES)
        self.assert_sentinel()

    def test_public_paths_version_and_sample_maps_are_read_only(self):
        practice = self.practice()
        for name in ("root", "source", "repository", "restored", "source_version"):
            with self.subTest(name=name), self.assertRaises(AttributeError):
                setattr(practice, name, self.base)
        with self.assertRaises(TypeError):
            lessons.FIRST_FILES[lessons.CHANGED_NAME] = b"changed"
        with self.assertRaises(TypeError):
            lessons.SECOND_FILES[lessons.CHANGED_NAME] = b"changed"

    def test_real_two_snapshots_history_and_independent_old_and_current_checks(self):
        practice = self.practice()
        with mock.patch.object(lessons.repository_engine, "init_repository", wraps=repository_engine.init_repository) as init:
            with mock.patch.object(lessons.repository_engine, "create_snapshot", wraps=repository_engine.create_snapshot) as create:
                first = practice.create_first_backup()
                practice.change_sample()
                second = practice.create_second_backup()
        self.assertEqual(init.call_count, 1)
        self.assertEqual(create.call_count, 2)
        for call, label in zip(create.call_args_list, (lessons.FIRST_LABEL, lessons.SECOND_LABEL)):
            self.assertTrue(call.args[0].is_relative_to(practice.root))
            self.assertEqual(call.args[1], practice.source)
            self.assertEqual(call.kwargs, {"label": label})
        self.assertIs(practice.first_snapshot, first)
        self.assertIs(practice.second_snapshot, second)
        self.assertEqual((first.file_count, first.changed_file_count, first.unchanged_file_count), (2, 2, 0))
        self.assertEqual((second.file_count, second.changed_file_count, second.unchanged_file_count), (2, 1, 1))
        self.assertEqual(second.parent_snapshot_id, first.snapshot_id)
        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(first.source_path, str(practice.source))
        self.assertGreater(second.reused_bytes, 0)
        self.assertEqual(practice.source_version, 2)
        self.assert_source(practice, lessons.SECOND_FILES)
        history = practice.list_history()
        self.assertIs(practice.history, history)
        self.assertEqual(tuple(s.snapshot_id for s in history), (second.snapshot_id, first.snapshot_id))
        self.assertEqual(tuple(s.label for s in history), (lessons.SECOND_LABEL, lessons.FIRST_LABEL))
        with mock.patch.object(lessons.repository_engine, "restore_snapshot", wraps=repository_engine.restore_snapshot) as restore:
            result = practice.restore_older()
        self.assertEqual(restore.call_args.args[:2], (practice.repository, first.snapshot_id))
        self.assertTrue(restore.call_args.args[2].is_relative_to(practice.root))
        self.assertIs(result, practice.restore_result)
        self.assertEqual(result.destination, str(practice.restored))
        self.assertEqual(result.snapshot_id, first.snapshot_id)
        self.assertEqual(result.file_count, 2)
        self.assertEqual({p.name: p.read_bytes() for p in practice.restored.iterdir()}, dict(lessons.FIRST_FILES))
        report = practice.verify_restored()
        self.assertTrue(report.ok, report)
        self.assertEqual((report.file_count, report.matched_files), (4, 4))
        self.assertEqual(report.total_bytes, sum(map(len, lessons.FIRST_FILES.values())) + sum(map(len, lessons.SECOND_FILES.values())))
        self.assertEqual(len(report.checks), 4)
        for check in report.checks:
            expected = lessons.FIRST_FILES if check.path.startswith("restored-first-version/") else lessons.SECOND_FILES
            self.assertEqual(check.expected_sha256, hashlib.sha256(expected[check.path.split("/")[-1]]).hexdigest())
            self.assertEqual(check.actual_sha256, check.expected_sha256)
            self.assertTrue(check.matches)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.ok = False
        self.assertTrue(practice.source_is_intact())
        self.assertTrue(practice.repository_is_intact())
        self.assertTrue(practice.restored_is_intact())
        self.assertTrue(practice.cleanup())
        self.assertFalse(practice.root.exists())
        self.assert_sentinel()

    def test_operation_order_rejects_without_creating_outputs(self):
        practice = self.practice()
        for operation in (practice.change_sample, practice.create_second_backup, practice.list_history, practice.restore_older):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation()
        self.assertFalse(practice.repository.exists())
        practice.create_first_backup()
        with self.assertRaises(ValueError):
            practice.create_second_backup()
        self.assert_source(practice, lessons.FIRST_FILES)

    def test_repeated_mutations_do_not_create_third_snapshot_or_overwrite_restore(self):
        practice = self.practice(restored=True)
        before = (practice.restored / lessons.CHANGED_NAME).read_bytes()
        for operation in (practice.create_first_backup, practice.change_sample, practice.create_second_backup, practice.restore_older):
            with self.subTest(operation=operation.__name__), self.assertRaises((ValueError, FileExistsError)):
                operation()
        self.assertEqual(len(practice.list_history()), 2)
        self.assertEqual((practice.restored / lessons.CHANGED_NAME).read_bytes(), before)

    def test_repeated_reads_do_not_change_repository_or_old_results(self):
        practice = self.practice(restored=True)
        original = dict(practice._owner._files)
        first = practice.list_history()
        self.assertEqual(practice.list_history(), first)
        self.assertTrue(practice.verify_restored().ok)
        self.assertTrue(practice.verify_restored().ok)
        self.assertEqual(practice._owner._files, original)

    def test_preexisting_repository_file_is_not_overwritten(self):
        practice = self.practice()
        practice.repository.write_bytes(b"Unrelated repository pathname")
        with self.assertRaises(FileExistsError):
            practice.create_first_backup()
        self.assertTrue(practice.cleanup())
        self.assertEqual(practice.repository.read_bytes(), b"Unrelated repository pathname")

    def test_preexisting_empty_repository_directory_is_not_adopted(self):
        practice = self.practice()
        practice.repository.mkdir()
        with self.assertRaises(FileExistsError):
            practice.create_first_backup()
        practice.cleanup()
        self.assertTrue(practice.repository.is_dir())

    def test_preexisting_restore_directory_and_file_are_retained(self):
        practice = self.practice(second=True)
        practice.restored.mkdir()
        sentinel = practice.restored / "keep.txt"
        sentinel.write_bytes(b"Keep this unrelated output")
        with mock.patch.object(lessons.repository_engine, "restore_snapshot") as restore:
            with self.assertRaises(FileExistsError):
                practice.restore_older()
        restore.assert_not_called()
        practice.cleanup()
        self.assertEqual(sentinel.read_bytes(), b"Keep this unrelated output")

    def test_modified_source_refuses_first_backup_and_is_retained(self):
        practice = self.practice()
        target = practice.source / lessons.CHANGED_NAME
        target.write_bytes(b"Modified externally")
        with mock.patch.object(lessons.repository_engine, "init_repository") as init:
            with self.assertRaises(ValueError):
                practice.create_first_backup()
        init.assert_not_called()
        self.assertFalse(practice.source_is_intact())
        practice.cleanup()
        self.assertEqual(target.read_bytes(), b"Modified externally")

    def test_unexpected_source_entry_blocks_backup_without_reading_it(self):
        practice = self.practice()
        extra = practice.source / "private-unexpected.txt"
        extra.write_bytes(b"Do not include this file")
        with mock.patch.object(lessons.repository_engine, "create_snapshot") as create:
            with self.assertRaises(ValueError):
                practice.create_first_backup()
        create.assert_not_called()
        self.assertNotIn(extra, practice._owner._files)
        practice.cleanup()
        self.assertEqual(extra.read_bytes(), b"Do not include this file")

    def test_hardlinked_source_is_rejected_and_neither_link_deleted(self):
        practice = self.practice()
        target = practice.source / lessons.CHANGED_NAME
        alias = self.base / "sample-alias.txt"
        os.link(target, alias)
        self.assertFalse(practice.source_is_intact())
        with self.assertRaises(ValueError):
            practice.create_first_backup()
        practice.cleanup()
        self.assertTrue(target.exists())
        self.assertEqual(alias.read_bytes(), lessons.FIRST_FILES[lessons.CHANGED_NAME])

    def test_replaced_source_with_identical_bytes_is_not_adopted_or_deleted(self):
        practice = self.practice()
        target = practice.source / lessons.CHANGED_NAME
        old = practice.source / "moved-original.txt"
        target.rename(old)
        target.write_bytes(lessons.FIRST_FILES[lessons.CHANGED_NAME])
        self.assertFalse(practice.source_is_intact())
        with self.assertRaises(ValueError):
            practice.create_first_backup()
        practice.cleanup()
        self.assertTrue(target.exists())
        self.assertTrue(old.exists())

    def test_source_junction_is_refused_without_engine_call(self):
        practice = self.practice()
        ordinary = Path.is_junction
        with mock.patch.object(Path, "is_junction", lambda path: path == practice.source or ordinary(path)):
            self.assertFalse(practice.source_is_intact())
            with mock.patch.object(lessons.repository_engine, "create_snapshot") as create:
                with self.assertRaises(ValueError):
                    practice.create_first_backup()
            create.assert_not_called()
            practice.cleanup()
            self.assertTrue((practice.source / lessons.CHANGED_NAME).exists())

    def test_changed_repository_refuses_all_later_reads_and_writes(self):
        practice = self.practice(second=True)
        target = practice.repository / "catalog.sqlite3"
        target.write_bytes(b"Changed catalogue, do not repair")
        with mock.patch.object(lessons.repository_engine, "list_snapshots") as listing:
            with self.assertRaises(ValueError):
                practice.list_history()
        listing.assert_not_called()
        with self.assertRaises(ValueError):
            practice.restore_older()
        self.assertFalse(practice.repository_is_intact())
        practice.cleanup()
        self.assertEqual(target.read_bytes(), b"Changed catalogue, do not repair")

    def test_unknown_repository_file_and_directory_are_never_adopted(self):
        practice = self.practice(first=True)
        extra = practice.repository / "external.txt"
        directory = practice.repository / "external-folder"
        extra.write_bytes(b"Foreign data")
        directory.mkdir()
        with self.assertRaises(ValueError):
            practice.change_sample()
        self.assertNotIn(extra, practice._owner._files)
        self.assertNotIn(directory, practice._owner._directories)
        practice.cleanup()
        self.assertTrue(directory.exists())
        self.assertEqual(extra.read_bytes(), b"Foreign data")

    def test_replaced_repository_directory_is_not_followed_or_deleted(self):
        practice = self.practice(first=True)
        retired = practice.root / "untracked-original"
        practice.repository.rename(retired)
        practice.repository.mkdir()
        extra = practice.repository / "external.txt"
        extra.write_bytes(b"Replacement data")
        with self.assertRaises(ValueError):
            practice.change_sample()
        practice.cleanup()
        self.assertTrue((retired / "repository.json").exists())
        self.assertEqual(extra.read_bytes(), b"Replacement data")

    def test_source_edit_changes_only_the_known_file_after_first_backup(self):
        practice = self.practice(first=True)
        repository_records = {p: v for p, v in practice._owner._files.items() if p.is_relative_to(practice.repository)}
        unchanged = practice._owner._files[practice.source / "checklist.txt"]
        practice.change_sample()
        self.assertEqual(practice.source_version, 2)
        self.assert_source(practice, lessons.SECOND_FILES)
        self.assertEqual(practice._owner._files[practice.source / "checklist.txt"], unchanged)
        self.assertEqual(repository_records, {p: v for p, v in practice._owner._files.items() if p.is_relative_to(practice.repository)})

    def test_second_backup_engine_failure_leaves_first_repository_untouched(self):
        practice = self.practice(first=True)
        practice.change_sample()
        records = {p: v for p, v in practice._owner._files.items() if p.is_relative_to(practice.repository)}
        with mock.patch.object(lessons.repository_engine, "create_snapshot", side_effect=ValueError("Injected engine failure")):
            with self.assertRaisesRegex(ValueError, "Injected engine failure"):
                practice.create_second_backup()
        self.assertIsNone(practice.second_snapshot)
        self.assertFalse(practice.busy)
        self.assertTrue(practice.repository_is_intact())
        self.assertEqual(records, {p: v for p, v in practice._owner._files.items() if p.is_relative_to(practice.repository)})
        self.assert_source(practice, lessons.SECOND_FILES)
        practice.cleanup()
        self.assertFalse(practice.root.exists())

    def test_stage_unknown_file_is_rejected_and_retained_without_publication(self):
        practice = self.practice()
        actual = repository_engine.create_snapshot
        introduced = []

        def injected(repository, source, **kwargs):
            result = actual(repository, source, **kwargs)
            extra = repository / "private-external-name.txt"
            extra.write_bytes(b"Unowned staged data")
            introduced.append(extra)
            return result

        with mock.patch.object(lessons.repository_engine, "create_snapshot", side_effect=injected):
            with self.assertRaises(ValueError):
                practice.create_first_backup()
        self.assertIsNone(practice.first_snapshot)
        self.assertFalse(practice.repository.exists())
        self.assertNotIn(introduced[0], practice._owner._files)
        practice.cleanup()
        self.assertEqual(introduced[0].read_bytes(), b"Unowned staged data")

    def test_unknown_pack_entry_is_rejected_and_not_adopted(self):
        practice = self.practice()
        actual = repository_engine.create_snapshot
        introduced = []

        def injected(repository, source, **kwargs):
            result = actual(repository, source, **kwargs)
            extra = repository / "packs" / "not-a-pack-folder"
            extra.mkdir()
            introduced.append(extra)
            return result

        with mock.patch.object(lessons.repository_engine, "create_snapshot", side_effect=injected):
            with self.assertRaises(ValueError):
                practice.create_first_backup()
        self.assertNotIn(introduced[0], practice._owner._directories)
        practice.cleanup()
        self.assertTrue(introduced[0].is_dir())

    def test_read_side_effect_does_not_get_adopted(self):
        practice = self.practice(second=True)
        actual = repository_engine.list_snapshots
        extra = practice.repository / "unexpected-after-read.txt"

        def injected(repository):
            result = actual(repository)
            extra.write_bytes(b"Added while listing")
            return result

        with mock.patch.object(lessons.repository_engine, "list_snapshots", side_effect=injected):
            with self.assertRaises(ValueError):
                practice.list_history()
        self.assertEqual(practice.history, ())
        self.assertNotIn(extra, practice._owner._files)
        practice.cleanup()
        self.assertEqual(extra.read_bytes(), b"Added while listing")

    def test_wrong_history_ids_cannot_be_displayed_as_success(self):
        practice = self.practice(second=True)
        with mock.patch.object(lessons.repository_engine, "list_snapshots", return_value=[practice.first_snapshot] * 2):
            with self.assertRaises(ValueError):
                practice.list_history()
        self.assertEqual(practice.history, ())

    def test_source_change_during_first_snapshot_prevents_publication(self):
        practice = self.practice()
        actual = repository_engine.create_snapshot
        changed = practice.source / lessons.CHANGED_NAME

        def injected(repository, source, **kwargs):
            result = actual(repository, source, **kwargs)
            changed.write_bytes(b"External late source edit")
            return result

        with mock.patch.object(lessons.repository_engine, "create_snapshot", side_effect=injected):
            with self.assertRaises(ValueError):
                practice.create_first_backup()
        self.assertIsNone(practice.first_snapshot)
        self.assertFalse(practice.repository.exists())
        practice.cleanup()
        self.assertEqual(changed.read_bytes(), b"External late source edit")

    def test_source_change_blocks_history_before_engine_read(self):
        practice = self.practice(second=True)
        (practice.source / lessons.CHANGED_NAME).write_bytes(b"Changed after backup")
        with mock.patch.object(lessons.repository_engine, "list_snapshots") as listing:
            with self.assertRaises(ValueError):
                practice.list_history()
        listing.assert_not_called()

    def test_original_repository_changed_during_second_snapshot_is_retained(self):
        practice = self.practice(first=True)
        practice.change_sample()
        actual = repository_engine.create_snapshot
        changed = practice.repository / "repository.json"

        def injected(repository, source, **kwargs):
            result = actual(repository, source, **kwargs)
            changed.write_bytes(b"External original repository change")
            return result

        with mock.patch.object(lessons.repository_engine, "create_snapshot", side_effect=injected):
            with self.assertRaises(ValueError):
                practice.create_second_backup()
        self.assertIsNone(practice.second_snapshot)
        practice.cleanup()
        self.assertEqual(changed.read_bytes(), b"External original repository change")

    def test_failed_second_publication_rolls_back_intact_first_repository(self):
        practice = self.practice(first=True)
        practice.change_sample()
        actual = practice._move_tree

        def injected(source, output):
            if source.name == "repository" and output == practice.repository:
                raise OSError("Injected second publication failure")
            return actual(source, output)

        with mock.patch.object(practice, "_move_tree", side_effect=injected):
            with self.assertRaisesRegex(OSError, "Injected second publication failure"):
                practice.create_second_backup()
        self.assertIsNone(practice.second_snapshot)
        self.assertTrue(practice.repository_is_intact())
        self.assertEqual([s.snapshot_id for s in repository_engine.list_snapshots(practice.repository)],
                         [practice.first_snapshot.snapshot_id])
        self.assert_source(practice, lessons.SECOND_FILES)
        practice.cleanup()
        self.assertFalse(practice.root.exists())

    def test_replaced_published_output_preserves_unknown_replacement(self):
        practice = self.practice(second=True)
        actual = practice._move_tree
        replacement = practice.restored / lessons.CHANGED_NAME

        def injected(source, output):
            if output != practice.restored:
                return actual(source, output)
            rename = lessons.os.rename

            def replace_after_rename(origin, destination):
                rename(origin, destination)
                target = Path(destination) / lessons.CHANGED_NAME
                rename(target, Path(destination) / "untracked-original.txt")
                target.write_bytes(lessons.FIRST_FILES[lessons.CHANGED_NAME])

            with mock.patch.object(lessons.os, "rename", side_effect=replace_after_rename):
                return actual(source, output)

        if os.name != "nt":
            # The exclusive-copy path is tested by normal non-Windows runs;
            # this check targets Windows directory-rename publication.
            return
        with mock.patch.object(practice, "_move_tree", side_effect=injected):
            with self.assertRaises(ValueError):
                practice.restore_older()
        self.assertIsNone(practice.restore_result)
        self.assertFalse(practice.restored_is_intact())
        practice.cleanup()
        self.assertEqual(replacement.read_bytes(), lessons.FIRST_FILES[lessons.CHANGED_NAME])
        self.assertTrue((practice.restored / "untracked-original.txt").exists())

    def test_verification_rejects_changed_repository_even_with_good_files(self):
        practice = self.practice(restored=True)
        (practice.repository / "repository.json").write_bytes(b"Changed repository")
        report = practice.verify_restored()
        self.assertEqual(report.matched_files, 4)
        self.assertFalse(report.ok)
        self.assertIn("backup-history/<changed or unsafe>", report.unsafe_paths)

    def test_raced_existing_repository_output_is_never_replaced(self):
        practice = self.practice()
        actual = repository_engine.create_snapshot

        def injected(repository, source, **kwargs):
            result = actual(repository, source, **kwargs)
            practice.repository.write_bytes(b"Raced unrelated output")
            return result

        with mock.patch.object(lessons.repository_engine, "create_snapshot", side_effect=injected):
            with self.assertRaises(FileExistsError):
                practice.create_first_backup()
        self.assertIsNone(practice.first_snapshot)
        practice.cleanup()
        self.assertEqual(practice.repository.read_bytes(), b"Raced unrelated output")

    def test_raced_restore_output_is_never_merged_or_replaced(self):
        practice = self.practice(second=True)
        actual = repository_engine.restore_snapshot

        def injected(repository, snapshot, output):
            result = actual(repository, snapshot, output)
            practice.restored.mkdir()
            (practice.restored / "keep.txt").write_bytes(b"Raced restore output")
            return result

        with mock.patch.object(lessons.repository_engine, "restore_snapshot", side_effect=injected):
            with self.assertRaises(FileExistsError):
                practice.restore_older()
        self.assertIsNone(practice.restore_result)
        practice.cleanup()
        self.assertEqual((practice.restored / "keep.txt").read_bytes(), b"Raced restore output")

    def test_wrong_restored_contents_are_not_published_or_owned(self):
        practice = self.practice(second=True)
        actual = repository_engine.restore_snapshot
        altered = []

        def injected(repository, snapshot, output):
            result = actual(repository, snapshot, output)
            target = output / lessons.CHANGED_NAME
            target.write_bytes(b"Wrong recovered file")
            altered.append(target)
            return result

        with mock.patch.object(lessons.repository_engine, "restore_snapshot", side_effect=injected):
            with self.assertRaises(ValueError):
                practice.restore_older()
        self.assertFalse(practice.restored.exists())
        self.assertNotIn(altered[0], practice._owner._files)
        practice.cleanup()
        self.assertEqual(altered[0].read_bytes(), b"Wrong recovered file")

    def test_verification_before_restore_reports_missing_old_files(self):
        practice = self.practice(second=True)
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertEqual(report.matched_files, 2)
        self.assertEqual(len(report.missing_files), 2)
        self.assertEqual(len(report.checks), 4)

    def test_verification_rejects_tampered_restored_copy_and_preserves_it(self):
        practice = self.practice(restored=True)
        target = practice.restored / lessons.CHANGED_NAME
        target.write_bytes(b"Edited recovered data")
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertEqual(report.matched_files, 3)
        self.assertIn("restored-first-version/" + lessons.CHANGED_NAME, report.changed_files)
        self.assertFalse(practice.restored_is_intact())
        practice.cleanup()
        self.assertEqual(target.read_bytes(), b"Edited recovered data")

    def test_verification_does_not_succeed_if_current_changed_source_is_lost(self):
        practice = self.practice(restored=True)
        target = practice.source / lessons.CHANGED_NAME
        target.write_bytes(lessons.FIRST_FILES[lessons.CHANGED_NAME])
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertIn("current-sample/<changed or unsafe>", report.unsafe_paths)
        self.assertIn("current-sample/" + lessons.CHANGED_NAME, report.changed_files)

    def test_verification_unknown_name_is_redacted_and_preserved(self):
        practice = self.practice(restored=True)
        extra = practice.restored / "do-not-echo-private-name.txt"
        extra.write_bytes(b"Do not read this")
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertNotIn(extra.name, repr(report))
        self.assertNotIn(extra, practice._owner._files)
        practice.cleanup()
        self.assertEqual(extra.read_bytes(), b"Do not read this")

    def test_replaced_restore_directory_fails_verification_and_is_retained(self):
        practice = self.practice(restored=True)
        original = practice.root / "moved-restored-original"
        practice.restored.rename(original)
        practice.restored.mkdir()
        for name, data in lessons.FIRST_FILES.items():
            (practice.restored / name).write_bytes(data)
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertEqual(report.matched_files, 2)
        self.assertEqual(len(report.unsafe_paths), 2)
        practice.cleanup()
        self.assertTrue((practice.restored / lessons.CHANGED_NAME).exists())
        self.assertTrue((original / lessons.CHANGED_NAME).exists())

    def test_busy_lock_blocks_cleanup_checks_and_other_mutations(self):
        practice = self.practice()
        entered, release = threading.Event(), threading.Event()
        actual = repository_engine.create_snapshot
        result, errors = [], []

        def blocked(repository, source, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Test worker timeout")
            return actual(repository, source, **kwargs)

        def run():
            try:
                result.append(practice.create_first_backup())
            except BaseException as error:
                errors.append(error)

        with mock.patch.object(lessons.repository_engine, "create_snapshot", side_effect=blocked):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(10))
                self.assertTrue(practice.busy)
                self.assertFalse(practice.cleanup())
                for check in (practice.source_is_intact, practice.repository_is_intact, practice.restored_is_intact):
                    self.assertFalse(check())
                for operation in (practice.create_first_backup, practice.change_sample, practice.create_second_backup,
                                  practice.list_history, practice.restore_older, practice.verify_restored):
                    with self.subTest(operation=operation.__name__), self.assertRaises(RuntimeError):
                        operation()
                self.assertTrue(practice.source.exists())
            finally:
                release.set()
                worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(result), 1)
        self.assertTrue(practice.cleanup())
        self.assertFalse(practice.root.exists())

    def test_cleanup_keeps_unknown_root_file_and_directory(self):
        practice = self.practice(restored=True)
        extra = practice.root / "keep.txt"
        extra.write_bytes(b"Unowned file")
        directory = practice.root / "keep-folder"
        directory.mkdir()
        self.assertTrue(practice.cleanup())
        self.assertFalse(practice.source.exists())
        self.assertFalse(practice.repository.exists())
        self.assertFalse(practice.restored.exists())
        self.assertEqual(extra.read_bytes(), b"Unowned file")
        self.assertTrue(directory.exists())
        self.assert_sentinel()


if __name__ == "__main__":
    unittest.main()
