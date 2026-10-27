"""Library catalogue tests use fictional temp data and public format fixtures."""

import concurrent.futures
import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rat_trap import library, repository_engine


FIXTURES = Path(__file__).parent / "fixtures" / "formats"


def tree_bytes(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = library.LibraryStore(self.root / "catalog" / "library.sqlite3")

    def fixture(self, name="gmw-solid-2-4.3.gmw", output=None):
        output = self.root / (output or name)
        shutil.copyfile(FIXTURES / name, output)
        return output

    def repository(self):
        source = self.root / "fictional-source"
        source.mkdir()
        (source / "secret-filename-not-in-library.txt").write_text("fictional first revision", encoding="utf-8")
        repository = self.root / "repository"
        repository_engine.init_repository(repository)
        first = repository_engine.create_snapshot(repository, source, label="First checkpoint")
        (source / "secret-filename-not-in-library.txt").write_text("fictional second revision", encoding="utf-8")
        second = repository_engine.create_snapshot(repository, source, label="Second checkpoint")
        return repository, source, first, second

    def test_constructor_and_empty_reads_do_not_create_anything(self):
        self.assertEqual(self.store.list_projects(), [])
        self.assertEqual(self.store.list_items(), [])
        self.assertEqual(self.store.timeline(), [])
        self.assertFalse(self.store.catalog_path.parent.exists())

    def test_default_path_is_local_appdata_and_constructor_never_scans(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            result = library.LibraryStore()
        self.assertEqual(result.catalog_path, self.root / "Two Hands Network Ltd" / "Rat-Trap" / "Library" / "library.sqlite3")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_projects_persist_and_uuid_survives_rename(self):
        project = self.store.create_project(" Project Alpha ", "A local test")
        renamed = self.store.rename_project(project.id, "Project Beta", "Updated")
        self.assertEqual(renamed.id, project.id)
        self.assertEqual(renamed.name, "Project Beta")
        self.assertEqual(library.LibraryStore(self.store.catalog_path).list_projects(), [renamed])
        self.assertEqual(len(project.id), 32)

    def test_project_text_validation_does_not_initialize_catalog(self):
        for name in ("", " \t", "a" * 201, "bad\x00name"):
            with self.subTest(name=repr(name)), self.assertRaises(library.LibraryError):
                self.store.create_project(name)
        self.assertFalse(self.store.catalog_path.exists())

    def test_registration_hash_and_search_and_duplicate_are_stable(self):
        source = self.fixture()
        before = source.read_bytes()
        project = self.store.create_project("Artwork")
        item = self.store.register(source, label="Milestone One", project_id=project.id)
        self.assertEqual(item.identity, "sha256:" + hashlib.sha256(before).hexdigest())
        self.assertEqual(item.kind, "archive")
        self.assertFalse(item.protected)
        self.assertEqual(self.store.list_items(project.id, "MILESTONE"), [item])
        self.assertEqual(self.store.register(source).id, item.id)
        self.assertEqual(len(self.store.timeline()), 1)
        self.assertEqual(source.read_bytes(), before)

    def test_all_fixture_families_are_classified_without_decryption(self):
        fixtures = list(FIXTURES.glob("*.gmw")) + list(FIXTURES.glob("*.rtsf"))
        self.assertGreaterEqual(len(fixtures), 8)
        kinds = set()
        with mock.patch("rat_trap.secure_engine.decrypt_file", side_effect=AssertionError("must not decrypt")):
            for source in fixtures:
                with self.subTest(name=source.name):
                    result = library.inspect_storage(source)
                    kinds.add(result.kind)
                    self.assertEqual(result.identity, "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertTrue({"archive", "vault", "protected_archive", "sealed_file"}.issubset(kinds))

    def test_plain_sqlite_is_not_a_vault(self):
        path = self.root / "other.db"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE customer_data (name TEXT)")
        before = path.read_bytes()
        with self.assertRaises(library.LibraryError):
            self.store.register(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.store.catalog_path.exists())

    def test_disguised_and_recovery_key_files_are_rejected(self):
        for name, content in (("plain.gmw", b"not archive"), ("unsafe.rtrk", b"a recovery key"), ("plain.rtsf", b"not protected")):
            path = self.root / name
            path.write_bytes(content)
            with self.subTest(name=name), self.assertRaises(library.LibraryError):
                self.store.register(path)
        self.assertFalse(self.store.catalog_path.exists())

    def test_protected_catalogue_contains_no_inner_filenames_or_recovery_material(self):
        source = next(FIXTURES.glob("*.rtsf"))
        item = self.store.register(source, label="Private envelope")
        note = self.store.add_note("Outer note only", item_id=item.id)
        payload = self.store.catalog_path.read_bytes()
        self.assertTrue(item.protected)
        self.assertIn(b"Private envelope", payload)
        self.assertIn(b"Outer note only", payload)
        self.assertNotIn(b"duplicate-a.bin", payload)
        self.assertNotIn(b"people.csv", payload)
        self.assertNotIn(b"RTRK1", payload)
        self.assertEqual(note.kind, "note")

    def test_notes_use_explicit_calendar_dates_and_no_file_mtime_inference(self):
        item = self.store.register(self.fixture())
        note = self.store.add_note("Finished drafting", item_id=item.id, event_date="2024-02-29")
        self.assertEqual(note.occurred_at, "2024-02-29")
        self.assertEqual(note.date_source, "user-entered date")
        for value in ("2025-02-29", "today", "2024-2-1", "2026-01-01T08:00:00"):
            with self.subTest(value=value), self.assertRaises(library.LibraryError):
                self.store.add_note("bad", item_id=item.id, event_date=value)
        self.assertEqual({event.kind for event in self.store.timeline()}, {"registered", "note"})

    def test_note_validation_and_mismatched_project_rollback(self):
        first = self.store.create_project("First")
        second = self.store.create_project("Second")
        item = self.store.register(self.fixture(), project_id=first.id)
        for kwargs in ({}, {"item_id": "missing"}, {"project_id": "missing"}, {"item_id": item.id, "project_id": second.id}):
            with self.subTest(kwargs=kwargs), self.assertRaises(library.LibraryError):
                self.store.add_note("note", **kwargs)
        with self.assertRaises(library.LibraryError):
            self.store.add_note("x" * 8001, project_id=first.id)
        self.assertEqual(len(self.store.timeline()), 1)

    def test_assign_and_delete_project_preserve_storage_and_items(self):
        project = self.store.create_project("Alpha")
        source = self.fixture()
        item = self.store.register(source)
        self.store.assign_project(item.id, project.id)
        self.store.add_note("Project context", project_id=project.id)
        self.assertEqual(len(self.store.timeline(project_id=project.id)), 2)
        self.store.delete_project(project.id)
        self.assertIsNone(self.store.get_item(item.id).project_id)
        self.assertTrue(source.is_file())

    def test_remove_item_only_forgets_metadata(self):
        source = self.fixture()
        before = source.read_bytes()
        item = self.store.register(source)
        self.store.add_note("old note", item_id=item.id)
        self.store.remove_item(item.id)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.store.list_items(), [])
        self.assertEqual(self.store.timeline(), [])

    def test_missing_original_is_retained_and_relink_keeps_identity_and_history(self):
        source = self.fixture()
        item = self.store.register(source)
        note = self.store.add_note("Keep this", item_id=item.id)
        moved = self.root / "moved.gmw"
        source.rename(moved)
        self.assertEqual(self.store.refresh(item.id).status, "missing")
        result = self.store.relink(item.id, moved)
        self.assertEqual(result.id, item.id)
        self.assertEqual(result.status, "available")
        self.assertEqual(result.identity, item.identity)
        self.assertIn(note.id, {event.id for event in self.store.timeline(item_id=item.id)})

    def test_relink_rejects_different_bytes_and_duplicate_location(self):
        first = self.store.register(self.fixture())
        other = self.fixture("gmw-sqlite-1-4.2.gmw")
        with self.assertRaises(library.IdentityMismatchError):
            self.store.relink(first.id, other)
        duplicate = self.fixture(output="copy.gmw")
        self.store.register(duplicate)
        with self.assertRaises(library.LibraryError):
            self.store.relink(first.id, duplicate)
        self.assertEqual(self.store.get_item(first.id), first)

    def test_changed_and_corrupt_paths_do_not_create_fake_versions(self):
        source = self.fixture()
        item = self.store.register(source)
        shutil.copyfile(FIXTURES / "gmw-sqlite-1-4.2.gmw", source)
        self.assertEqual(self.store.refresh(item.id).status, "changed")
        self.assertEqual(self.store.get_item(item.id).identity, item.identity)
        with self.assertRaises(library.IdentityMismatchError):
            self.store.register(source)
        source.write_bytes(b"damaged")
        self.assertEqual(self.store.refresh(item.id).status, "error")
        self.assertEqual(len(self.store.timeline()), 1)

    def test_repository_reads_manifests_without_catalogue_or_lock_side_effects(self):
        repository, source, first, second = self.repository()
        (repository / "catalog.sqlite3").unlink()
        lock = repository / "locks" / "repository.lock"
        lock.unlink(missing_ok=True)
        before = tree_bytes(repository)
        with mock.patch.object(repository_engine, "repository_info", side_effect=AssertionError("mutating")), mock.patch.object(repository_engine, "list_snapshots", side_effect=AssertionError("mutating")):
            item = self.store.register(repository)
            inspection = library.inspect_storage(repository)
            self.store.refresh(item.id)
        self.assertEqual(tree_bytes(repository), before)
        self.assertEqual({entry.snapshot_id for entry in inspection.repository_snapshots}, {first.snapshot_id, second.snapshot_id})
        self.assertEqual(len(self.store.timeline(item_id=item.id)), 3)
        self.assertNotIn(b"secret-filename-not-in-library.txt", self.store.catalog_path.read_bytes())
        self.assertNotIn(str(source).encode(), self.store.catalog_path.read_bytes())

    def test_snapshot_refresh_is_idempotent_and_new_snapshots_are_added(self):
        repository, source, first, second = self.repository()
        item = self.store.register(repository)
        old_ids = {e.id for e in self.store.timeline()}
        self.store.refresh(item.id)
        self.assertEqual({e.id for e in self.store.timeline()}, old_ids)
        third = repository_engine.create_snapshot(repository, source, label="Third checkpoint")
        self.store.refresh(item.id)
        events = self.store.timeline(item_id=item.id)
        self.assertEqual(len(events), 4)
        self.assertEqual({e.snapshot_id for e in events if e.kind == "snapshot"}, {first.snapshot_id, second.snapshot_id, third.snapshot_id})
        self.assertEqual({e.date_source for e in events if e.kind == "snapshot"}, {"repository manifest"})

    def test_readonly_repository_snapshot_info_preserves_pins(self):
        repository, _, first, second = self.repository()
        repository_engine.pin_snapshot(repository, first.snapshot_id)
        before = tree_bytes(repository)
        inspection = library.inspect_storage(repository)
        by_id = {snapshot.snapshot_id: snapshot for snapshot in inspection.repository_snapshots}
        self.assertTrue(by_id[first.snapshot_id].pinned)
        self.assertFalse(by_id[second.snapshot_id].pinned)
        self.assertEqual(by_id[first.snapshot_id].manifest_sha256, first.manifest_sha256)
        self.assertEqual(tree_bytes(repository), before)

    def test_repository_identity_mismatch_is_not_relinked(self):
        repository, _, _, _ = self.repository()
        item = self.store.register(repository)
        other = self.root / "other-repository"
        repository_engine.init_repository(other)
        with self.assertRaises(library.IdentityMismatchError):
            self.store.relink(item.id, other)

    def test_manifest_checksum_tampering_is_refused_without_source_modifications(self):
        repository, _, _, _ = self.repository()
        manifest = next((repository / "manifests").glob("*.json"))
        payload = json.loads(manifest.read_bytes())
        payload["source"]["label"] = "Altered"
        manifest.write_bytes(repository_engine._canonical_json(payload))
        before = tree_bytes(repository)
        with self.assertRaises(library.LibraryError):
            self.store.register(repository)
        self.assertEqual(tree_bytes(repository), before)
        self.assertFalse(self.store.catalog_path.exists())

    def test_preview_repository_bounds_are_enforced(self):
        repository, _, _, _ = self.repository()
        with mock.patch.object(library, "MAX_SNAPSHOTS", 1), self.assertRaises(library.LibraryError):
            library.inspect_storage(repository)
        with mock.patch.object(library, "MAX_MANIFEST_BYTES", 32), self.assertRaises(library.LibraryError):
            library.inspect_storage(repository)

    def test_catalogue_cannot_be_inside_the_registered_repository(self):
        repository, _, _, _ = self.repository()
        nested = library.LibraryStore(repository / "library.sqlite3")
        before = tree_bytes(repository)
        with self.assertRaises(library.LibraryError):
            nested.register(repository)
        self.assertEqual(tree_bytes(repository), before)

    def test_unrelated_and_empty_existing_catalogues_are_not_overwritten(self):
        self.store.catalog_path.parent.mkdir()
        for content in (b"", b"important non-database file"):
            self.store.catalog_path.write_bytes(content)
            with self.subTest(content=content), self.assertRaises(library.LibraryError):
                self.store.create_project("No overwrite")
            self.assertEqual(self.store.catalog_path.read_bytes(), content)

    def test_future_schema_and_trigger_injection_are_rejected_before_write(self):
        self.store.create_project("Initial")
        with closing(sqlite3.connect(self.store.catalog_path)) as connection, connection:
            connection.execute("PRAGMA user_version=999")
        before = self.store.catalog_path.read_bytes()
        with self.assertRaises(library.LibraryError):
            self.store.create_project("Rejected")
        self.assertEqual(self.store.catalog_path.read_bytes(), before)
        with closing(sqlite3.connect(self.store.catalog_path)) as connection, connection:
            connection.execute("PRAGMA user_version=1")
            connection.execute("CREATE TRIGGER unexpected AFTER INSERT ON projects BEGIN DELETE FROM projects; END")
        before = self.store.catalog_path.read_bytes()
        with self.assertRaises(library.LibraryError):
            self.store.create_project("Rejected")
        self.assertEqual(self.store.catalog_path.read_bytes(), before)

    def test_catalogue_wal_format_is_refused_without_opening_sidecars(self):
        self.store.create_project("Initial")
        with closing(sqlite3.connect(self.store.catalog_path)) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
        before = tree_bytes(self.store.catalog_path.parent)
        with self.assertRaises(library.LibraryError):
            self.store.list_projects()
        self.assertEqual(tree_bytes(self.store.catalog_path.parent), before)

    def test_sqlite_source_sidecars_are_refused(self):
        source = self.fixture("gmw-sqlite-1-4.2.gmw")
        sidecar = Path(str(source) + "-wal")
        sidecar.write_bytes(b"active data must not be ignored")
        before = tree_bytes(self.root)
        with self.assertRaises(library.LibraryError):
            self.store.register(source)
        self.assertEqual(tree_bytes(self.root), before)

    def test_catalogue_hardlink_is_refused_without_altering_target(self):
        self.store.create_project("Initial")
        linked = self.root / "catalog-hardlink.db"
        try:
            os.link(self.store.catalog_path, linked)
        except OSError:
            self.skipTest("Hard links unavailable")
        before = linked.read_bytes()
        with self.assertRaises(library.LibraryError):
            library.LibraryStore(linked).create_project("Denied")
        self.assertEqual(linked.read_bytes(), before)

    def test_symbolic_links_and_unsafe_catalogue_sidecars_are_refused(self):
        source = self.fixture()
        linked = self.root / "linked.gmw"
        try:
            linked.symlink_to(source)
        except OSError:
            self.skipTest("Symbolic-link permission unavailable")
        with self.assertRaises(library.LibraryError):
            self.store.register(linked)
        self.store.create_project("Initial")
        Path(str(self.store.catalog_path) + "-journal").symlink_to(source)
        before = source.read_bytes()
        with self.assertRaises(library.LibraryError):
            self.store.create_project("Denied")
        self.assertEqual(source.read_bytes(), before)

    def test_changed_during_hashing_is_not_registered(self):
        source = self.fixture()
        signature = library._signature(source)
        with mock.patch.object(library, "_signature", side_effect=[signature, (*signature[:3], signature[3] + 1)]), self.assertRaises(library.LibraryError):
            self.store.register(source)
        self.assertFalse(self.store.catalog_path.exists())

    def test_threaded_mutations_use_independent_connections_and_atomic_notes(self):
        project = self.store.create_project("Shared")
        def add(index):
            return self.store.add_note(f"Note {index}", project_id=project.id)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            result = list(executor.map(add, range(20)))
        self.assertEqual(len({note.id for note in result}), 20)
        self.assertEqual(len(self.store.timeline(project_id=project.id)), 20)
        with closing(sqlite3.connect(self.store.catalog_path)) as connection, connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_public_records_are_json_serializable(self):
        project = self.store.create_project("Alpha")
        item = self.store.register(self.fixture(), project_id=project.id)
        note = self.store.add_note("A note", item_id=item.id)
        for record in (project, item, note, library.inspect_storage(item.path)):
            self.assertIsInstance(json.dumps(record.as_dict()), str)

    def test_catalogue_guard_is_serialized_with_concurrent_journal_writes(self):
        project = self.store.create_project("Concurrent catalogue")
        original = self.store._guard_catalog

        def guarded(*args, **kwargs):
            self.assertTrue(library._INIT_LOCK._is_owned(), "Guard must share the transaction lock")
            return original(*args, **kwargs)

        def work(index):
            if index % 2:
                return self.store.add_note(f"Concurrent note {index}", project_id=project.id)
            return self.store.timeline(project_id=project.id)

        with mock.patch.object(self.store, "_guard_catalog", side_effect=guarded):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(work, range(80)))
        self.assertEqual(len(self.store.timeline(project_id=project.id)), 40)

    def test_timeline_item_filter_runs_before_limit(self):
        selected = self.store.register(self.fixture())
        other = self.store.register(self.fixture(output="other.gmw"))
        note = self.store.add_note("Old matching note", item_id=selected.id, event_date="2020-01-01")
        self.store.add_note("New nonmatching note", item_id=other.id)
        events = self.store.timeline(item_ids=[selected.id], limit=2)
        self.assertEqual({event.item_id for event in events}, {selected.id})
        self.assertIn(note.id, {event.id for event in events})
        self.assertEqual(self.store.timeline(item_ids=[]), [])
        for ids in (["invalid"], "not-list"):
            with self.assertRaises(library.LibraryError):
                self.store.timeline(item_ids=ids)

    def test_corrupt_catalogue_item_metadata_is_not_used_for_routing(self):
        item = self.store.register(self.fixture())
        with closing(sqlite3.connect(self.store.catalog_path)) as connection, connection:
            connection.execute("UPDATE items SET kind='untrusted-handler' WHERE id=?", (item.id,))
        with self.assertRaises(library.LibraryError):
            self.store.get_item(item.id)
        with self.assertRaises(library.LibraryError):
            self.store.list_items()

    def test_reparse_guard_is_enforced_without_symlink_privileges(self):
        source = self.fixture()
        original = Path.lstat
        def simulated_reparse(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == source:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with mock.patch.object(Path, "lstat", simulated_reparse), self.assertRaises(library.LibraryError):
            self.store.register(source)
        self.assertFalse(self.store.catalog_path.exists())

    def test_oversized_sqlite_metadata_is_rejected_before_loading_values(self):
        source = self.fixture("gmw-sqlite-1-4.2.gmw")
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute("UPDATE metadata SET value=? WHERE key='format'", ('"' + "x" * 20000 + '"',))
        with self.assertRaisesRegex(library.LibraryError, "inspection limit"):
            self.store.register(source)

    def test_inspect_item_checks_known_snapshot_hashes_without_writing(self):
        repository, _, first, _ = self.repository()
        item = self.store.register(repository)
        before = self.store.catalog_path.read_bytes()
        inspection = self.store.inspect_item(item.id)
        self.assertEqual(self.store.catalog_path.read_bytes(), before)
        self.assertIn(first.snapshot_id, {snapshot.snapshot_id for snapshot in inspection.snapshots})
        manifest = repository / "manifests" / (first.manifest_sha256 + ".rtsnap.json")
        value = json.loads(manifest.read_bytes())
        value["source"]["label"] = "Different contents, same snapshot ID"
        replacement_hash = repository_engine._manifest_hash(value)
        manifest.unlink()
        (manifest.parent / (replacement_hash + ".rtsnap.json")).write_bytes(repository_engine._canonical_json(value))
        with self.assertRaisesRegex(library.LibraryError, "different contents"):
            self.store.inspect_item(item.id)
        self.assertEqual(self.store.catalog_path.read_bytes(), before)
        with self.assertRaisesRegex(library.LibraryError, "different contents"):
            self.store.refresh(item.id)
        self.assertEqual(self.store.catalog_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
