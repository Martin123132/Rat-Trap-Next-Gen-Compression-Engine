"""Generated-data checks for exact, single-file, no-overwrite Library restore."""
import dataclasses
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool, library, library_search, library_restore as restore, repository_engine, vault_engine


@unittest.skipUnless(os.name == "nt", "Windows atomic no-replace publication")
class LibraryRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = library.LibraryStore(self.base / "catalogue" / "library.sqlite3")
        self.project = self.store.create_project("Restore qualification")
        self.source = self.base / "source"
        (self.source / "nested").mkdir(parents=True)
        (self.source / "nested" / "needle.txt").write_bytes(b"Exact OLD bytes\x00\xff")
        (self.source / "unrelated.bin").write_bytes(b"Unselected file")
        (self.source / "empty-directory").mkdir()
        self.destination = self.base / "restored"

    def vault(self, profile="vault"):
        path = self.base / (profile + ".gmw")
        gmw_tool.compress_folder(self.source, path, profile=profile)
        item = self.store.register(path, project_id=self.project.id)
        hit, = [h for h in library_search.search_library(self.store, "needle.txt").results if h.item_id == item.id]
        return item, hit

    def repository(self):
        path = self.base / "repository"
        repository_engine.init_repository(path)
        first = repository_engine.create_snapshot(path, self.source, label="Older version")
        (self.source / "nested" / "needle.txt").write_bytes(b"NEW bytes")
        second = repository_engine.create_snapshot(path, self.source, label="Latest version")
        item = self.store.register(path, project_id=self.project.id)
        hit = next(h for h in library_search.search_library(self.store, "needle.txt").results if h.snapshot_id == first.snapshot_id)
        return item, hit, first, second

    def run_restore(self, hit, destination=None, **kwargs):
        return restore.restore_file(self.store, restore.RestoreRequest(hit, destination or self.destination), **kwargs)

    def assert_output(self, result):
        self.assertEqual(result.path.read_bytes(), b"Exact OLD bytes\x00\xff")
        self.assertEqual([p.relative_to(result.destination).as_posix() for p in result.destination.rglob("*") if p.is_file()], ["nested/needle.txt"])
        self.assertFalse((result.destination / "empty-directory").exists())
        self.assertEqual(result.sha256, hashlib.sha256(result.path.read_bytes()).hexdigest())
        self.assertIsNone(result.catalogue_error)
        self.assertEqual(result.event.title, "File restored")
        self.assertIn(str(result.path), result.event.detail)
        self.assertEqual(self.store.get_item(result.event.item_id).project_id, self.project.id)

    def test_vault_only_selected_file_source_bytes_and_mtime_unchanged(self):
        item, hit = self.vault()
        before = (Path(item.path).read_bytes(), Path(item.path).stat().st_mtime_ns)
        result = self.run_restore(hit)
        self.assert_output(result)
        self.assertEqual(before, (Path(item.path).read_bytes(), Path(item.path).stat().st_mtime_ns))
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(item.path + suffix).exists())
        self.assertEqual((self.source / "nested" / "needle.txt").read_bytes(), result.path.read_bytes())

    def test_exact_old_backup_not_latest_and_repeat_receipts_do_not_collide(self):
        item, hit, first, second = self.repository()
        result = self.run_restore(hit)
        self.assert_output(result)
        self.assertEqual(result.snapshot_id, first.snapshot_id)
        self.assertNotEqual(result.snapshot_id, second.snapshot_id)
        self.assertIn(first.snapshot_id, result.event.detail)
        self.assertIsNone(result.event.snapshot_id)
        self.assert_output(self.run_restore(hit, self.base / "again"))
        self.assertEqual(len([e for e in self.store.timeline() if e.title == "File restored"]), 2)
        self.assertEqual(len([e for e in self.store.timeline() if e.kind == "snapshot"]), 2)
        self.assertEqual((self.source / "nested" / "needle.txt").read_bytes(), b"NEW bytes")

    def test_existing_empty_folder_is_not_merged(self):
        _, hit = self.vault()
        self.destination.mkdir()
        with self.assertRaisesRegex(library.LibraryError, "NEW"):
            self.run_restore(hit)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_existing_file_is_not_replaced(self):
        _, hit = self.vault()
        self.destination.write_bytes(b"Keep this")
        with self.assertRaises(library.LibraryError):
            self.run_restore(hit)
        self.assertEqual(self.destination.read_bytes(), b"Keep this")

    def test_no_missing_parent_or_catalogue_destination(self):
        for path in (self.base / "missing" / "new", self.store.catalog_path.parent / "new"):
            with self.subTest(path=path), self.assertRaises(library.LibraryError):
                restore.validate_destination(self.store, path)

    def test_registered_repositories_are_protected_across_projects(self):
        item, _, _, _ = self.repository()
        other = self.store.create_project("Other")
        self.store.assign_project(item.id, other.id)
        with self.assertRaisesRegex(library.LibraryError, "registered storage"):
            restore.validate_destination(self.store, Path(item.path) / "restore")

    def test_ordinary_archives_are_not_directly_restored(self):
        _, hit = self.vault("balanced")
        with self.assertRaisesRegex(library.LibraryError, "unencrypted Vaults"):
            self.run_restore(hit)
        self.assertFalse(self.destination.exists())

    def test_non_file_and_unsafe_paths_refused(self):
        _, hit = self.vault()
        changes = [{"kind": "Note"}, {"member": "../escape"}, {"member": "C:/escape"},
                   {"member": "nested/file:stream"}, {"member": "CON"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises((library.LibraryError, repository_engine.RepositoryError)):
                self.run_restore(dataclasses.replace(hit, **change))
        self.assertFalse(self.destination.exists())

    def test_missing_file_or_changed_size_refused(self):
        _, hit = self.vault()
        for change in ({"member": "missing.txt"}, {"size": hit.size + 1}):
            with self.assertRaises(library.LibraryError):
                self.run_restore(dataclasses.replace(hit, **change))
        self.assertFalse(self.destination.exists())

    def test_stale_archive_and_active_sidecar_refused(self):
        item, hit = self.vault()
        sidecar = Path(item.path + "-wal")
        sidecar.write_bytes(b"Active writer sentinel")
        with self.assertRaises(library.LibraryError):
            self.run_restore(hit)
        sidecar.unlink()
        Path(item.path).write_bytes(b"Replaced archive")
        with self.assertRaises(library.LibraryError):
            self.run_restore(hit)
        self.assertFalse(self.destination.exists())

    def test_deleted_snapshot_and_wrong_pin_never_substitute_latest(self):
        item, hit, first, _ = self.repository()
        with self.assertRaises(library.LibraryError):
            self.run_restore(dataclasses.replace(hit, manifest_sha256="0" * 64))
        (Path(item.path) / "manifests" / (first.manifest_sha256 + ".rtsnap.json")).unlink()
        with self.assertRaises(library.LibraryError):
            self.run_restore(hit)
        self.assertFalse(self.destination.exists())

    def test_project_reassignment_requires_fresh_search(self):
        item, hit = self.vault()
        self.store.assign_project(item.id, self.store.create_project("Moved").id)
        with self.assertRaisesRegex(library.LibraryError, "project changed"):
            self.run_restore(hit)

    def test_checksum_failure_no_publication_or_receipt(self):
        _, hit = self.vault()
        before = self.store.timeline()
        original = vault_engine.extract_vault
        def corrupt(*args, **kwargs):
            result = original(*args, **kwargs)
            (Path(args[1]) / hit.member).write_bytes(b"X" * hit.size)
            return result
        with mock.patch.object(vault_engine, "extract_vault", corrupt), self.assertRaisesRegex(library.LibraryError, "checksum"):
            self.run_restore(hit)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.store.timeline(), before)
        self.assertEqual(list(self.base.glob(".rat-trap-library-restore-*")), [])

    def test_extra_file_in_staging_refused(self):
        _, hit = self.vault()
        original = vault_engine.extract_vault
        def extra(*args, **kwargs):
            original(*args, **kwargs)
            (Path(args[1]) / "unexpected.exe").write_bytes(b"Generated inert data")
        with mock.patch.object(vault_engine, "extract_vault", extra), self.assertRaisesRegex(library.LibraryError, "exactly"):
            self.run_restore(hit)
        self.assertFalse(self.destination.exists())

    def test_source_replaced_after_extraction_refused(self):
        item, hit = self.vault()
        original = vault_engine.extract_vault
        def changed(*args, **kwargs):
            original(*args, **kwargs)
            Path(item.path).write_bytes(b"Changed after extraction")
        with mock.patch.object(vault_engine, "extract_vault", changed), self.assertRaises(library.LibraryError):
            self.run_restore(hit)
        self.assertFalse(self.destination.exists())

    def test_destination_appears_at_atomic_publication_is_preserved(self):
        _, hit = self.vault()
        original = restore._publish
        def raced(staged, destination):
            destination.mkdir()
            (destination / "keep.txt").write_bytes(b"Race winner")
            original(staged, destination)
        with mock.patch.object(restore, "_publish", raced), self.assertRaises(OSError):
            self.run_restore(hit)
        self.assertEqual((self.destination / "keep.txt").read_bytes(), b"Race winner")
        self.assertFalse((self.destination / hit.member).exists())
        self.assertFalse(any(e.title == "File restored" for e in self.store.timeline()))

    def test_disk_failure_no_destination_or_success_receipt(self):
        _, hit = self.vault()
        with mock.patch.object(vault_engine, "extract_vault", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.run_restore(hit)
        self.assertFalse(self.destination.exists())
        self.assertFalse(any(e.title == "File restored" for e in self.store.timeline()))

    def test_receipt_failure_preserves_successful_verified_output(self):
        _, hit = self.vault()
        with mock.patch.object(self.store, "record_restored", side_effect=library.LibraryError("catalogue locked")):
            result = self.run_restore(hit)
        self.assertEqual(result.path.read_bytes(), b"Exact OLD bytes\x00\xff")
        self.assertIsNone(result.event)
        self.assertIn("catalogue locked", result.catalogue_error)

    def test_disconnected_progress_callback_does_not_hide_success(self):
        _, hit = self.vault()
        self.assert_output(self.run_restore(hit, progress=mock.Mock(side_effect=RuntimeError("UI closed"))))

    def test_receipt_validates_identity_and_snapshot_type(self):
        item, hit = self.vault()
        args = dict(identity=item.identity, project_id=item.project_id, member=hit.member,
                    destination=str(self.destination), sha256="a" * 64)
        for change in ({"identity": "wrong"}, {"sha256": "bad"}, {"snapshot_id": 123}):
            with self.assertRaises(library.LibraryError):
                self.store.record_restored(item.id, **(args | change))

    def test_repository_selection_reads_only_selected_objects(self):
        item, hit, first, _ = self.repository()
        original = repository_engine._ObjectReader.read
        reads = []
        def recording(reader, object_id, size):
            reads.append(object_id)
            return original(reader, object_id, size)
        manifest = library._json_object((Path(item.path) / "manifests" / (first.manifest_sha256 + ".rtsnap.json")).read_bytes())
        entry = next(e for e in manifest["entries"] if e["path"] == hit.member)
        with mock.patch.object(repository_engine._ObjectReader, "read", recording):
            self.assert_output(self.run_restore(hit))
        self.assertEqual(reads, [chunk[0] for chunk in entry["chunks"]])

    def test_repository_whole_restore_still_restores_everything(self):
        item, _, first, _ = self.repository()
        result = repository_engine.restore_snapshot(Path(item.path), first.snapshot_id, self.destination)
        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.directory_count, 2)
        self.assertTrue((self.destination / "empty-directory").is_dir())
        self.assertTrue((self.destination / "unrelated.bin").is_file())

    def test_repository_selection_rejects_bad_pin_and_absent_paths(self):
        item, _, first, _ = self.repository()
        for kwargs in ({"paths": []}, {"paths": "needle.txt"}, {"paths": ["missing"]},
                       {"expected_manifest_sha256": "0" * 64}, {"expected_manifest_sha256": "bad"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(repository_engine.RepositoryError):
                repository_engine.restore_snapshot(Path(item.path), first.snapshot_id, self.destination, **kwargs)
            self.assertFalse(self.destination.exists())

    def test_zero_byte_and_unicode_filename(self):
        (self.source / "nested" / "空 Straße.txt").write_bytes(b"")
        self.vault()
        hit, = library_search.search_library(self.store, "空 Straße").results
        result = self.run_restore(hit)
        self.assertEqual(result.path.read_bytes(), b"")
        self.assertEqual(result.size, 0)
        self.assertEqual(result.sha256, hashlib.sha256(b"").hexdigest())


if __name__ == "__main__":
    unittest.main()
