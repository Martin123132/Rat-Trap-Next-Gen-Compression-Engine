"""Sample-only protection/recovery using the real authenticated file engine."""

import dataclasses
import hashlib
import json
import os
import pickle
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import protection_tutorials as lessons
from rat_trap import sealed_file


class ProtectionPracticeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rat-trap-protection-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.sentinel = self.base / "unrelated.txt"
        self.sentinel.write_bytes(b"Generated unrelated-data stand-in")

    def practice(self, sealed=False):
        practice = lessons.create_practice(self.base)
        self.addCleanup(practice.cleanup)
        if sealed:
            practice.seal()
        return practice

    def test_fresh_contained_sessions_and_separate_key_location(self):
        first, second = self.practice(), self.practice()
        self.assertNotEqual(first.root, second.root)
        self.assertNotEqual(first.sealed.name, second.sealed.name)
        self.assertTrue(first.practice_password != second.practice_password)
        self.assertGreaterEqual(len(first.practice_password), 24)
        for practice in (first, second):
            self.assertEqual(practice.root.parent, self.base.resolve())
            self.assertEqual(practice.source.read_bytes(), lessons.PRACTICE_BYTES)
            self.assertRegex(practice.sealed.name, r"^RT-[0-9a-f]{32}\.rtsf$")
            self.assertEqual(len({practice.source.parent, practice.sealed.parent, practice.recovery_key.parent}), 3)
            self.assertTrue(practice.source_is_intact())
            self.assertFalse(practice.sealed_is_intact())
            self.assertFalse(practice.key_is_intact())
            self.assertFalse(practice.password_output.exists())
            self.assertFalse(practice.recovery_output.exists())
            self.assertNotEqual(practice.password_output, practice.recovery_output)
            self.assertFalse(practice.busy)
            self.assertIsNone(practice.seal_result)
            self.assertIsNone(practice.password_result)
            self.assertIsNone(practice.recovery_result)

    def test_public_paths_and_password_are_read_only(self):
        practice = self.practice()
        for name in ("root", "source", "sealed", "recovery_key", "password_output", "recovery_output", "practice_password"):
            with self.subTest(name=name), self.assertRaises(AttributeError):
                setattr(practice, name, self.base)

    def test_no_password_in_repr_results_report_or_generated_files_and_pickle_refused(self):
        practice = self.practice(sealed=True)
        practice.restore_with_password()
        practice.restore_with_recovery()
        report = practice.verify_restored()
        secret = practice.practice_password
        representations = [repr(practice), repr(practice.seal_result), repr(practice.password_result),
                           repr(practice.recovery_result), repr(report),
                           json.dumps(practice.seal_result.as_dict()),
                           json.dumps(practice.password_result.as_dict()),
                           json.dumps(practice.recovery_result.as_dict()),
                           json.dumps(dataclasses.asdict(report))]
        self.assertFalse(any(secret in value for value in representations))
        self.assertFalse(any(secret.encode() in path.read_bytes() for path in practice.root.rglob("*") if path.is_file()))
        with self.assertRaises(TypeError):
            pickle.dumps(practice)
        self.assertTrue(practice.cleanup())
        self.assertEqual(practice.practice_password, "")

    def test_real_password_and_recovery_round_trips_and_independent_verification(self):
        practice = self.practice()
        with mock.patch.object(lessons.sealed_file, "seal_file", wraps=sealed_file.seal_file) as seal:
            created = practice.seal()
        self.assertTrue(seal.call_args.kwargs["allow_plaintext_temp"])
        self.assertFalse(seal.call_args.kwargs["allow_recovery_same_directory"])
        self.assertIs(practice.seal_result, created)
        self.assertEqual(created.source, str(practice.source))
        self.assertEqual(created.sealed_file.path, str(practice.sealed))
        self.assertEqual(created.recovery_key_path, str(practice.recovery_key))
        self.assertTrue(created.source_retained)
        self.assertTrue(created.sealed_file.content_verified)
        original_ciphertext, original_key = practice.sealed.read_bytes(), practice.recovery_key.read_bytes()
        self.assertNotIn(lessons.PRACTICE_BYTES, original_ciphertext)
        self.assertNotIn(lessons.PRACTICE_NAME.encode(), original_ciphertext)
        password_result = practice.restore_with_password()
        with mock.patch.object(lessons.sealed_file, "unseal_file", wraps=sealed_file.unseal_file) as restore:
            recovery_result = practice.restore_with_recovery()
        self.assertNotIn("password", restore.call_args.kwargs)
        self.assertEqual(restore.call_args.kwargs["recovery_key"], practice.recovery_key)
        self.assertTrue(restore.call_args.kwargs["allow_plaintext_temp"])
        self.assertTrue(restore.call_args.kwargs["allow_plaintext_output"])
        self.assertFalse(restore.call_args.kwargs["replace"])
        self.assertIs(practice.password_result, password_result)
        self.assertIs(practice.recovery_result, recovery_result)
        for result, folder in ((password_result, practice.password_output), (recovery_result, practice.recovery_output)):
            self.assertEqual(Path(result.output), folder / lessons.PRACTICE_NAME)
            self.assertEqual(Path(result.output).read_bytes(), lessons.PRACTICE_BYTES)
            self.assertTrue(result.sealed_source_retained)
        report = practice.verify_restored()
        self.assertTrue(report.ok, report)
        self.assertEqual((report.file_count, report.matched_files, report.total_bytes), (2, 2, 2 * len(lessons.PRACTICE_BYTES)))
        self.assertEqual(len(report.checks), 2)
        for check in report.checks:
            self.assertTrue(check.matches)
            self.assertEqual(check.expected_sha256, hashlib.sha256(lessons.PRACTICE_BYTES).hexdigest())
            self.assertEqual(check.actual_sha256, check.expected_sha256)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.ok = False
        self.assertTrue(practice.source_is_intact())
        self.assertTrue(practice.sealed_is_intact())
        self.assertTrue(practice.key_is_intact())
        self.assertTrue(practice.password_output_is_intact())
        self.assertTrue(practice.recovery_output_is_intact())
        self.assertEqual(practice.sealed.read_bytes(), original_ciphertext)
        self.assertEqual(practice.recovery_key.read_bytes(), original_key)

    def test_recovery_really_works_without_session_password(self):
        practice = self.practice(sealed=True)
        practice._practice_password = ""
        result = practice.restore_with_recovery()
        self.assertEqual(Path(result.output).read_bytes(), lessons.PRACTICE_BYTES)
        with self.assertRaises(ValueError):
            practice.restore_with_password()

    def test_actual_wrong_password_is_rejected_without_plaintext_output(self):
        practice = self.practice(sealed=True)
        output = self.base / "wrong-password-output"
        with self.assertRaises(ValueError):
            sealed_file.unseal_file(practice.sealed, output, password="Intentionally incorrect practice password!",
                                    allow_plaintext_temp=True, allow_plaintext_output=True)
        self.assertFalse(output.exists())
        self.assertTrue(practice.sealed_is_intact())

    def test_actual_wrong_recovery_key_is_rejected_without_plaintext_output(self):
        first, second = self.practice(sealed=True), self.practice(sealed=True)
        output = self.base / "wrong-key-output"
        with self.assertRaises(ValueError):
            sealed_file.unseal_file(first.sealed, output, recovery_key=second.recovery_key,
                                    allow_plaintext_temp=True, allow_plaintext_output=True)
        self.assertFalse(output.exists())
        self.assertTrue(first.sealed_is_intact())
        self.assertTrue(second.key_is_intact())

    def test_actual_ciphertext_tampering_is_rejected_without_plaintext_output(self):
        practice = self.practice(sealed=True)
        tampered = self.base / "tampered.rtsf"
        data = bytearray(practice.sealed.read_bytes())
        data[-1] ^= 1
        tampered.write_bytes(data)
        output = self.base / "tampered-output"
        with self.assertRaises(ValueError):
            sealed_file.unseal_file(tampered, output, password=practice.practice_password,
                                    allow_plaintext_temp=True, allow_plaintext_output=True)
        self.assertFalse(output.exists())

    def test_modified_source_is_not_processed_or_cleaned(self):
        practice = self.practice()
        practice.source.write_bytes(b"Generated changed source")
        with mock.patch.object(lessons.sealed_file, "seal_file") as engine:
            with self.assertRaises(ValueError):
                practice.seal()
            engine.assert_not_called()
        self.assertFalse(practice.source_is_intact())
        practice.cleanup()
        self.assertEqual(practice.source.read_bytes(), b"Generated changed source")

    def test_existing_sealed_or_key_files_are_never_overwritten(self):
        for field in ("sealed", "recovery_key"):
            with self.subTest(field=field):
                practice = self.practice()
                path = getattr(practice, field)
                path.write_bytes(b"Generated unowned file")
                with mock.patch.object(lessons.sealed_file, "seal_file") as engine:
                    with self.assertRaises(FileExistsError):
                        practice.seal()
                    engine.assert_not_called()
                practice.cleanup()
                self.assertEqual(path.read_bytes(), b"Generated unowned file")

    def test_replay_refuses_existing_sealed_file_and_both_restore_outputs(self):
        practice = self.practice(sealed=True)
        practice.restore_with_password()
        practice.restore_with_recovery()
        with mock.patch.object(lessons.sealed_file, "seal_file") as seal, mock.patch.object(lessons.sealed_file, "unseal_file") as restore:
            for action in (practice.seal, practice.restore_with_password, practice.restore_with_recovery):
                with self.assertRaises(FileExistsError):
                    action()
            seal.assert_not_called()
            restore.assert_not_called()
        self.assertTrue(practice.verify_restored().ok)

    def test_existing_even_empty_restore_folder_is_never_merged_or_cleaned(self):
        practice = self.practice(sealed=True)
        for output, action in ((practice.password_output, practice.restore_with_password),
                               (practice.recovery_output, practice.restore_with_recovery)):
            output.mkdir()
            with mock.patch.object(lessons.sealed_file, "unseal_file") as engine:
                with self.assertRaises(FileExistsError):
                    action()
                engine.assert_not_called()
        practice.cleanup()
        self.assertTrue(practice.password_output.is_dir())
        self.assertTrue(practice.recovery_output.is_dir())

    def test_tampered_owned_sealed_file_and_key_are_rejected_before_engine(self):
        for field, action_name in (("sealed", "restore_with_password"), ("recovery_key", "restore_with_recovery")):
            with self.subTest(field=field):
                practice = self.practice(sealed=True)
                path = getattr(practice, field)
                path.write_bytes(b"Generated tampered input")
                with mock.patch.object(lessons.sealed_file, "unseal_file") as engine:
                    with self.assertRaises(ValueError):
                        getattr(practice, action_name)()
                    engine.assert_not_called()
                practice.cleanup()
                self.assertEqual(path.read_bytes(), b"Generated tampered input")

    def test_identical_bytes_replacement_is_not_adopted_or_removed(self):
        practice = self.practice(sealed=True)
        replacement = practice.root / "replacement.rtsf"
        content = practice.sealed.read_bytes()
        replacement.write_bytes(content)
        os.replace(replacement, practice.sealed)
        self.assertFalse(practice.sealed_is_intact())
        with self.assertRaises(ValueError):
            practice.restore_with_password()
        practice.cleanup()
        self.assertEqual(practice.sealed.read_bytes(), content)

    def test_hard_link_input_is_rejected_and_both_links_preserved(self):
        practice = self.practice()
        duplicate = self.base / "source-hard-link.txt"
        try:
            os.link(practice.source, duplicate)
        except OSError as error:
            self.skipTest(f"Hard links unavailable: {type(error).__name__}")
        self.assertFalse(practice.source_is_intact())
        with self.assertRaises(ValueError):
            practice.seal()
        practice.cleanup()
        self.assertTrue(practice.source.exists())
        self.assertEqual(duplicate.read_bytes(), lessons.PRACTICE_BYTES)

    def test_changed_recovery_directory_identity_is_not_followed(self):
        practice = self.practice()
        original = practice.recovery_key.parent
        moved = practice.root / "moved-original-key-directory"
        original.rename(moved)
        original.mkdir()
        sentinel = original / "unrelated.txt"
        sentinel.write_bytes(b"Generated replacement-folder data")
        with mock.patch.object(lessons.sealed_file, "seal_file") as engine:
            with self.assertRaises(ValueError):
                practice.seal()
            engine.assert_not_called()
        practice.cleanup()
        self.assertTrue(original.is_dir())
        self.assertTrue(moved.is_dir())
        self.assertEqual(sentinel.read_bytes(), b"Generated replacement-folder data")

    @unittest.skipUnless(os.name == "nt", "Windows junction ownership boundary")
    def test_junction_replaced_input_parents_are_never_followed_or_cleaned(self):
        import _winapi

        for field, integrity_name, action_name in (
                ("source", "source_is_intact", "seal"),
                ("sealed", "sealed_is_intact", "restore_with_password"),
                ("recovery_key", "key_is_intact", "restore_with_recovery")):
            with self.subTest(field=field):
                practice = self.practice(sealed=field != "source")
                path = getattr(practice, field)
                original = path.parent
                moved = practice.root / ("moved-" + original.name)
                outside = self.base / ("outside-generated-" + field)
                outside.mkdir()
                sentinel = outside / path.name
                sentinel.write_bytes(path.read_bytes())
                original.rename(moved)
                _winapi.CreateJunction(str(outside), str(original))
                try:
                    self.assertFalse(getattr(practice, integrity_name)())
                    with mock.patch.object(lessons.sealed_file, "seal_file") as seal, mock.patch.object(lessons.sealed_file, "unseal_file") as unseal:
                        with self.assertRaises(ValueError):
                            getattr(practice, action_name)()
                        seal.assert_not_called()
                        unseal.assert_not_called()
                    practice.cleanup()
                    self.assertTrue(sentinel.exists())
                    self.assertTrue((moved / path.name).exists())
                    self.assertTrue(original.is_junction())
                finally:
                    if original.is_junction():
                        original.rmdir()

    def test_verification_reports_missing_changed_and_unexpected_without_unknown_names(self):
        practice = self.practice(sealed=True)
        before = practice.verify_restored()
        self.assertFalse(before.ok)
        self.assertEqual(len(before.missing_files), 2)
        practice.restore_with_password()
        self.assertFalse(practice.verify_restored().ok)
        practice.restore_with_recovery()
        changed = practice.password_output / lessons.PRACTICE_NAME
        changed.write_bytes(b"Generated modified restored sample")
        unexpected = practice.recovery_output / "unknown-name-must-not-be-in-report.txt"
        unexpected.write_bytes(b"Generated extra file")
        report = practice.verify_restored()
        self.assertFalse(report.ok)
        self.assertEqual(report.matched_files, 1)
        self.assertEqual(len(report.changed_files), 1)
        self.assertEqual(report.unexpected_files, ("recovery-restored/<unexpected entry>",))
        self.assertNotIn(unexpected.name, repr(report))
        self.assertFalse(practice.password_output_is_intact())
        self.assertFalse(practice.recovery_output_is_intact())
        practice.cleanup()
        self.assertEqual(changed.read_bytes(), b"Generated modified restored sample")
        self.assertTrue(unexpected.exists())

    def test_cleanup_is_idempotent_preserves_unrelated_files_and_clears_password(self):
        practice = self.practice(sealed=True)
        practice.restore_with_password()
        practice.restore_with_recovery()
        self.assertTrue(practice.cleanup())
        self.assertFalse(practice.root.exists())
        self.assertTrue(practice.cleanup())
        self.assertEqual(practice.practice_password, "")
        self.assertEqual(self.sentinel.read_bytes(), b"Generated unrelated-data stand-in")

    def test_busy_operation_refuses_cleanup_and_other_operations(self):
        practice = self.practice()
        entered, release = threading.Event(), threading.Event()
        failures = []
        actual = sealed_file.seal_file

        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Test release timed out")
            return actual(*args, **kwargs)

        def run():
            try:
                practice.seal()
            except Exception as error:
                failures.append(type(error).__name__)

        with mock.patch.object(lessons.sealed_file, "seal_file", side_effect=delayed):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(practice.busy)
                self.assertFalse(practice.cleanup())
                self.assertTrue(bool(practice.practice_password))
                self.assertTrue(practice.source.exists())
                for action in (practice.seal, practice.restore_with_password, practice.restore_with_recovery, practice.verify_restored):
                    with self.assertRaises(RuntimeError):
                        action()
                self.assertFalse(practice.source_is_intact())
            finally:
                release.set()
                thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertFalse(practice.busy)
        self.assertTrue(practice.sealed_is_intact())

    def test_engine_failure_text_cannot_expose_disposable_password(self):
        practice = self.practice()
        with mock.patch.object(lessons.sealed_file, "seal_file", side_effect=RuntimeError(practice.practice_password)):
            with self.assertRaises(ValueError) as captured:
                practice.seal()
        self.assertFalse(practice.practice_password in str(captured.exception))
        self.assertFalse(practice.practice_password in repr(captured.exception))
        self.assertFalse(practice.busy)
        self.assertIsNone(practice.seal_result)

    @unittest.skipUnless(os.name == "nt", "Windows exclusive rename publication")
    def test_racing_destination_creation_is_preserved_during_seal(self):
        practice = self.practice()
        actual = os.rename

        def race(source, destination):
            if Path(destination) == practice.sealed:
                practice.sealed.write_bytes(b"Generated raced destination")
            return actual(source, destination)

        with mock.patch.object(lessons.os, "rename", side_effect=race):
            with self.assertRaises(FileExistsError):
                practice.seal()
        self.assertIsNone(practice.seal_result)
        practice.cleanup()
        self.assertEqual(practice.sealed.read_bytes(), b"Generated raced destination")

    @unittest.skipUnless(os.name == "nt", "Windows exclusive rename publication")
    def test_post_publication_replacement_is_not_adopted_or_cleaned(self):
        practice = self.practice()
        actual = os.rename

        def race(source, destination):
            value = actual(source, destination)
            if Path(destination) == practice.sealed:
                replacement = practice.root / "replacement-after-publication.txt"
                replacement.write_bytes(b"Generated replacement after publication")
                os.replace(replacement, practice.sealed)
            return value

        with mock.patch.object(lessons.os, "rename", side_effect=race):
            with self.assertRaises(ValueError):
                practice.seal()
        self.assertFalse(practice.sealed_is_intact())
        practice.cleanup()
        self.assertEqual(practice.sealed.read_bytes(), b"Generated replacement after publication")

    @unittest.skipUnless(os.name == "nt", "Windows exclusive directory rename publication")
    def test_racing_restore_folder_is_never_merged_or_removed(self):
        practice = self.practice(sealed=True)
        actual = os.rename

        def race(source, destination):
            if Path(destination) == practice.password_output:
                practice.password_output.mkdir()
            return actual(source, destination)

        with mock.patch.object(lessons.os, "rename", side_effect=race):
            with self.assertRaises(FileExistsError):
                practice.restore_with_password()
        self.assertIsNone(practice.password_result)
        practice.cleanup()
        self.assertTrue(practice.password_output.is_dir())
        self.assertEqual(list(practice.password_output.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows exclusive directory rename publication")
    def test_post_publication_restore_folder_replacement_is_not_adopted(self):
        practice = self.practice(sealed=True)
        actual = os.rename
        moved = practice.root / "moved-restored-files"

        def race(source, destination):
            value = actual(source, destination)
            if Path(destination) == practice.password_output:
                actual(practice.password_output, moved)
                practice.password_output.mkdir()
                (practice.password_output / lessons.PRACTICE_NAME).write_bytes(lessons.PRACTICE_BYTES)
            return value

        with mock.patch.object(lessons.os, "rename", side_effect=race):
            with self.assertRaises(ValueError):
                practice.restore_with_password()
        self.assertIsNone(practice.password_result)
        self.assertFalse(practice.password_output_is_intact())
        practice.cleanup()
        self.assertEqual((practice.password_output / lessons.PRACTICE_NAME).read_bytes(), lessons.PRACTICE_BYTES)
        self.assertEqual((moved / lessons.PRACTICE_NAME).read_bytes(), lessons.PRACTICE_BYTES)

    def test_parent_file_is_never_reused_as_a_practice_folder(self):
        with self.assertRaises(OSError):
            lessons.create_practice(self.sentinel)
        self.assertEqual(self.sentinel.read_bytes(), b"Generated unrelated-data stand-in")


if __name__ == "__main__":
    unittest.main()
