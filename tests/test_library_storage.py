"""Store-a-folder integration checks using generated, disposable files only."""
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool, library, library_storage, repository_engine, secure_engine


class StoreFolderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-store-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "Source 日本"
        self.source.mkdir()
        (self.source / "note.txt").write_bytes(b"Original revision\n" * 200)
        (self.source / "empty").mkdir()
        self.store = library.LibraryStore(self.base / "catalogue" / "library.sqlite3")
        self.project = self.store.create_project("Generated project")

    def request(self, **changes):
        request = library_storage.StoreRequest(self.source, self.base / "saved.gmw", self.project.id)
        return dataclasses.replace(request, **changes)

    def save(self, **changes):
        return library_storage.store_folder(self.store, self.request(**changes))

    def test_archive_round_trip_and_reopened_catalogue(self):
        original = (self.source / "note.txt").read_bytes()
        result = self.save()
        self.assertIsNone(result.catalogue_error)
        self.assertFalse(result.encrypted)
        self.assertEqual(result.item.project_id, self.project.id)
        self.assertEqual(result.file_count, 1)
        reopened = library.LibraryStore(self.store.catalog_path)
        self.assertEqual(reopened.get_item(result.item.id), result.item)
        events = reopened.timeline(project_id=self.project.id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Archive saved to Library")
        restored = self.base / "restored"
        gmw_tool.extract_archive(result.path, restored)
        self.assertEqual((restored / "note.txt").read_bytes(), original)
        self.assertTrue((restored / "empty").is_dir())
        self.assertEqual((self.source / "note.txt").read_bytes(), original)

    def test_two_backup_versions_restore_exact_older_contents(self):
        destination = self.base / "versions"
        original = (self.source / "note.txt").read_bytes()
        first = self.save(mode="backup", destination=destination, snapshot_label="First")
        (self.source / "note.txt").write_bytes(b"Second revision")
        (self.source / "new.txt").write_bytes(b"New file")
        second = self.save(mode="backup", destination=destination, snapshot_label="Second")
        self.assertEqual(first.item.id, second.item.id)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        reopened = library.LibraryStore(self.store.catalog_path)
        events = [e for e in reopened.timeline() if e.kind == "snapshot"]
        self.assertEqual({e.snapshot_id for e in events}, {first.snapshot_id, second.snapshot_id})
        reopened.refresh(first.item.id)
        self.assertEqual(len(reopened.timeline()), 3)
        restored = self.base / "old-version"
        repository_engine.restore_snapshot(destination, first.snapshot_id, restored)
        self.assertEqual((restored / "note.txt").read_bytes(), original)
        self.assertFalse((restored / "new.txt").exists())
        self.assertEqual((self.source / "note.txt").read_bytes(), b"Second revision")
        self.assertEqual((self.source / "new.txt").read_bytes(), b"New file")

    def test_encryption_round_trip_does_not_store_credentials(self):
        password = "disposable test passphrase only"
        recovery = self.base / "independent-recovery.rtrk"
        result = library_storage.store_folder(self.store, self.request(), encryption={
            "encryption_password": password, "recovery_key_output": recovery,
            "allow_plaintext_temp": True})
        self.assertTrue(result.encrypted)
        self.assertTrue(result.item.protected)
        self.assertTrue(secure_engine.is_encrypted_archive(result.path))
        self.assertTrue(recovery.is_file())
        restored = self.base / "unlocked"
        gmw_tool.extract_archive(result.path, restored, password=password, allow_plaintext_temp=True)
        self.assertEqual((restored / "note.txt").read_bytes(), (self.source / "note.txt").read_bytes())
        catalog = self.store.catalog_path.read_bytes()
        self.assertNotIn(password.encode(), catalog)
        self.assertNotIn(recovery.name.encode(), catalog)
        self.assertNotIn(b"note.txt", catalog)

    def test_existing_archive_is_not_replaced(self):
        result = self.save()
        before = result.path.read_bytes()
        with self.assertRaisesRegex(library.LibraryError, "never overwritten"):
            self.save()
        self.assertEqual(result.path.read_bytes(), before)
        self.assertEqual(len(self.store.timeline()), 1)

    def test_destination_race_does_not_replace_other_file(self):
        original = gmw_tool.compress_folder
        destination = self.base / "saved.gmw"

        def race(*args, **kwargs):
            result = original(*args, **kwargs)
            destination.write_bytes(b"Another process owns this")
            return result

        with mock.patch.object(gmw_tool, "compress_folder", side_effect=race), self.assertRaises(OSError):
            self.save()
        self.assertEqual(destination.read_bytes(), b"Another process owns this")
        self.assertEqual(self.store.timeline(), [])

    def test_invalid_destinations_have_no_storage_or_catalogue_writes(self):
        for changes in (
            {"destination": self.source / "recursive.gmw"},
            {"destination": self.base / "missing-parent" / "file.gmw"},
            {"destination": self.store.catalog_path.parent / "file.gmw"},
            {"destination": self.base / "wrong.db"},
            {"project_id": "missing"}, {"mode": "unknown"}, {"profile": "vault"},
            {"mode": "backup", "destination": self.base},
        ):
            with self.subTest(changes=changes), mock.patch.object(gmw_tool, "compress_folder") as archive, mock.patch.object(repository_engine, "init_repository") as initialize:
                with self.assertRaises((library.LibraryError, OSError)):
                    self.save(**changes)
                archive.assert_not_called()
                initialize.assert_not_called()
        self.assertEqual(self.store.list_items(), [])

    def test_catalogue_may_not_be_inside_source(self):
        store = library.LibraryStore(self.source / "catalogue" / "library.sqlite3")
        project = store.create_project("Inside source")
        with self.assertRaisesRegex(library.LibraryError, "catalogue"):
            library_storage.store_folder(store, self.request(project_id=project.id))

    def test_unrelated_nonempty_directory_is_not_initialized(self):
        target = self.base / "unrelated"
        target.mkdir()
        (target / "keep.txt").write_bytes(b"Keep")
        with self.assertRaises(library.LibraryError):
            self.save(mode="backup", destination=target)
        self.assertEqual([p.name for p in target.iterdir()], ["keep.txt"])

    def test_another_projects_repository_is_not_modified(self):
        first = self.save(mode="backup", destination=self.base / "versions")
        other = self.store.create_project("Other")
        with self.assertRaisesRegex(library.LibraryError, "another project"):
            self.save(mode="backup", destination=first.path, project_id=other.id)
        self.assertEqual(len(repository_engine.list_snapshots(first.path)), 1)

    def test_known_repository_identity_checked_before_snapshot(self):
        first = self.save(mode="backup", destination=self.base / "versions")
        with mock.patch.object(self.store, "inspect_item", side_effect=library.IdentityMismatchError("changed")), mock.patch.object(repository_engine, "create_snapshot") as create:
            with self.assertRaises(library.IdentityMismatchError):
                self.save(mode="backup", destination=first.path)
            create.assert_not_called()

    def test_failed_archive_is_not_registered_or_published(self):
        with mock.patch.object(gmw_tool, "compress_folder", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.save()
        self.assertFalse((self.base / "saved.gmw").exists())
        self.assertEqual(self.store.timeline(), [])
        self.assertFalse(list(self.base.glob(".rat-trap-library-*")))

    def test_failed_snapshot_does_not_claim_success(self):
        with mock.patch.object(repository_engine, "create_snapshot", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.save(mode="backup", destination=self.base / "versions")
        self.assertEqual(self.store.timeline(), [])
        self.assertTrue((self.base / "versions" / "repository.json").exists())

    def test_saved_archive_survives_catalogue_failure_and_can_be_registered(self):
        with mock.patch.object(self.store, "record_saved", side_effect=library.LibraryError("catalogue locked")):
            result = self.save()
        self.assertIsNone(result.item)
        self.assertIn("catalogue locked", result.catalogue_error)
        self.assertTrue(result.path.is_file())
        self.assertEqual(self.store.timeline(), [])
        registered = self.store.register(result.path, project_id=self.project.id)
        self.assertEqual(registered.project_id, self.project.id)

    def test_published_snapshot_survives_catalogue_failure(self):
        with mock.patch.object(self.store, "record_saved", side_effect=library.LibraryError("full")):
            result = self.save(mode="backup", destination=self.base / "versions")
        self.assertIsNotNone(result.catalogue_error)
        self.assertEqual(repository_engine.list_snapshots(result.path)[0].snapshot_id, result.snapshot_id)
        item = self.store.register(result.path, project_id=self.project.id)
        self.assertEqual([e.snapshot_id for e in self.store.timeline() if e.kind == "snapshot"], [result.snapshot_id])

    def test_source_changed_during_archive_is_not_published(self):
        original = gmw_tool.compress_folder

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.source / "note.txt").write_bytes(b"User changed content during save")
            return result

        with mock.patch.object(gmw_tool, "compress_folder", side_effect=changed):
            with self.assertRaisesRegex(library.LibraryError, "source changed"):
                self.save()
        self.assertFalse((self.base / "saved.gmw").exists())
        self.assertEqual(self.store.timeline(), [])

    def test_encryption_not_supported_for_backup_and_no_key_overwrite(self):
        options = {"encryption_password": "disposable test password", "recovery_key_output": self.base / "key.rtrk", "allow_plaintext_temp": True}
        with self.assertRaisesRegex(library.LibraryError, "not encrypted"):
            library_storage.store_folder(self.store, self.request(mode="backup", destination=self.base / "versions"), encryption=options)
        self.assertFalse((self.base / "versions").exists())
        for recovery in (self.source / "key.rtrk", self.store.catalog_path, self.base / "saved.gmw"):
            with self.subTest(recovery=recovery), self.assertRaises(library.LibraryError):
                library_storage.store_folder(self.store, self.request(), encryption={**options, "recovery_key_output": recovery})

    def test_record_saved_rolls_back_wrong_snapshot_and_is_idempotent(self):
        result = self.save(mode="backup", destination=self.base / "versions")
        events = self.store.timeline()
        with self.assertRaises(library.LibraryError):
            self.store.record_saved(result.path, project_id=self.project.id, identity=result.item.identity, snapshot_id="0" * 32)
        self.assertEqual(self.store.timeline(), events)
        self.store.record_saved(result.path, project_id=self.project.id, identity=result.item.identity, snapshot_id=result.snapshot_id)
        self.assertEqual(self.store.timeline(), events)

    def test_reparse_source_is_refused_without_writes(self):
        with mock.patch.object(repository_engine, "_enumerate_source", side_effect=repository_engine.RepositoryError("reparse point")):
            with self.assertRaises(repository_engine.RepositoryError):
                self.save()
        self.assertFalse((self.base / "saved.gmw").exists())

    def test_resumed_backup_reports_earlier_job_without_claiming_new_version(self):
        first = self.save(mode="backup", destination=self.base / "versions")
        earlier = repository_engine.list_snapshots(first.path)[0]
        (self.source / "note.txt").write_bytes(b"Changes since the interrupted job")
        with mock.patch.object(repository_engine, "create_snapshot", return_value=dataclasses.replace(earlier, resumed=True)):
            resumed = self.save(mode="backup", destination=first.path)
        self.assertTrue(resumed.resumed)
        self.assertEqual(resumed.snapshot_id, first.snapshot_id)
        self.assertEqual(len([e for e in self.store.timeline() if e.kind == "snapshot"]), 1)
        self.assertEqual((self.source / "note.txt").read_bytes(), b"Changes since the interrupted job")


if __name__ == "__main__":
    unittest.main()
