import dataclasses
import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool, library, library_health as health, repository_engine as engine, vault_engine

FIXTURES = Path(__file__).parent / "fixtures" / "formats"


class LibraryHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = library.LibraryStore(self.base / "catalogue" / "library.sqlite3")
        self.project = self.store.create_project("Health tests")
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "needle.txt").write_bytes(b"Generated older data" * 100)
        (self.source / "empty.txt").write_bytes(b"")

    def vault(self, profile="vault"):
        path = self.base / (profile + ".gmw")
        gmw_tool.compress_folder(self.source, path, profile=profile)
        return self.store.register(path, project_id=self.project.id)

    def repository(self):
        path = self.base / "repository"
        engine.init_repository(path)
        first = engine.create_snapshot(path, self.source, label="First")
        (self.source / "needle.txt").write_bytes(b"Generated second version" * 100)
        second = engine.create_snapshot(path, self.source, label="Second")
        return self.store.register(path, project_id=self.project.id), first, second

    def fingerprint(self, root):
        paths = root.rglob("*") if root.is_dir() else [root]
        return {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                for path in paths if path.is_file()}

    def test_vault_verified_source_unchanged_receipt_persists(self):
        item = self.vault()
        before = self.fingerprint(Path(item.path))
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Verified", result.detail)
        self.assertEqual(result.availability, "Located")
        self.assertEqual(result.file_count, 2)
        self.assertEqual(before, self.fingerprint(Path(item.path)))
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(item.path + suffix).exists())
        self.assertEqual(health.latest_results(self.store, [item])[item.id], result)
        self.assertEqual(self.store.timeline()[0].title, "Library health check")
        self.assertEqual(self.store.get_item(item.id), item)

    def test_repository_verifies_all_versions_without_recovery_or_cache_writes(self):
        item, _, _ = self.repository()
        before = self.fingerprint(Path(item.path))
        with mock.patch.object(engine, "_recover_ready_jobs_locked", side_effect=AssertionError("No recovery")), \
             mock.patch.object(engine, "_ensure_catalog_locked", side_effect=AssertionError("No rebuild")):
            result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Verified", result.detail)
        self.assertEqual((result.snapshot_count, result.file_count), (2, 4))
        self.assertEqual(before, self.fingerprint(Path(item.path)))

    def test_missing_repository_cache_is_not_rebuilt(self):
        item, _, _ = self.repository()
        cache = Path(item.path) / engine._CATALOG_NAME
        cache.unlink()
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Verified", result.detail)
        self.assertIn("Cache", result.detail)
        self.assertFalse(cache.exists())

    def test_busy_repository_read_lock_refused_without_writes(self):
        item, _, _ = self.repository()
        before = self.fingerprint(Path(item.path))
        with engine._repository_lock(Path(item.path)):
            result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertIn("busy", result.detail)
        self.assertEqual(before, self.fingerprint(Path(item.path)))

    def test_pending_work_is_reported_not_recovered(self):
        item, _, _ = self.repository()
        job = Path(item.path) / "staging" / "jobs" / "generated-pending"
        job.mkdir()
        (job / "sentinel.txt").write_bytes(b"Keep pending work")
        before = self.fingerprint(Path(item.path))
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertIn("Pending", result.detail)
        self.assertEqual(before, self.fingerprint(Path(item.path)))

    def test_pack_corruption_detected_and_not_repaired(self):
        item, _, _ = self.repository()
        pack = next((Path(item.path) / "packs").rglob("*.rtpack"))
        with closing(sqlite3.connect(pack)) as connection:
            connection.execute("UPDATE objects SET data=zeroblob(length(data))")
            connection.commit()
        before = self.fingerprint(Path(item.path))
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention", result.detail)
        self.assertIn("checksum", result.detail)
        self.assertEqual(before, self.fingerprint(Path(item.path)))

    def test_missing_pack_does_not_verify_from_cache(self):
        item, _, _ = self.repository()
        next((Path(item.path) / "packs").rglob("*.rtpack")).unlink()
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertIn("missing", result.detail)

    def test_known_deleted_snapshot_is_attention_not_silent_success(self):
        item, first, _ = self.repository()
        (Path(item.path) / "manifests" / (first.manifest_sha256 + ".rtsnap.json")).unlink()
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertIn("Previously listed", result.detail)

    def test_bad_snapshot_file_hash_detected_even_with_valid_chunks(self):
        item, first, _ = self.repository()
        manifest = Path(item.path) / "manifests" / (first.manifest_sha256 + ".rtsnap.json")
        data = json.loads(manifest.read_bytes())
        next(e for e in data["entries"] if e["kind"] == "file" and e["size"])["sha256"] = "0" * 64
        data["inventory"]["tree_sha256"] = hashlib.sha256(engine._canonical_json(data["entries"])).hexdigest()
        digest = engine._manifest_hash(data)
        replacement = manifest.with_name(digest + ".rtsnap.json")
        replacement.write_bytes(engine._canonical_json(data))
        manifest.unlink()
        # New registration has no historical snapshot pin to trigger first.
        self.store.remove_item(item.id)
        item = self.store.register(item.path)
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertIn("file checksum", result.detail)

    def test_vault_corrupt_payload_detected_even_when_registered_that_way(self):
        item = self.vault()
        with closing(sqlite3.connect(item.path)) as connection:
            connection.execute("UPDATE objects SET data=zeroblob(length(data))")
            connection.commit()
        self.store.remove_item(item.id)
        item = self.store.register(item.path)
        result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertEqual(result.file_count, 0)

    def test_changed_and_missing_storage_are_distinct(self):
        item = self.vault()
        with closing(sqlite3.connect(item.path)) as connection:
            connection.execute("UPDATE objects SET data=zeroblob(length(data))")
            connection.commit()
        result = health.check_item(self.store, item)
        self.assertEqual((result.status, result.availability), ("Needs attention", "Changed"))
        Path(item.path).unlink()
        result = health.check_item(self.store, item)
        self.assertEqual((result.status, result.availability), ("Needs attention", "Missing"))

    def test_locked_items_never_inspected_or_decrypted(self):
        path = self.base / "locked.gmw"
        shutil.copyfile(FIXTURES / "rat-trap-encrypted-1-5.3.gmw", path)
        item = self.store.register(path)
        with mock.patch.object(self.store, "inspect_item", side_effect=AssertionError("No protected reads")):
            result = health.check_item(self.store, item)
        self.assertEqual((result.status, result.availability), ("Locked", "Located"))

    def test_ordinary_archives_are_not_marked_verified(self):
        item = self.vault("balanced")
        with mock.patch.object(self.store, "inspect_item", side_effect=AssertionError("Unsupported contents")):
            result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Not checked")
        self.assertEqual(result.availability, "Located")

    def test_cancelled_vault_never_publishes_verified(self):
        item = self.vault()
        cancel = threading.Event()
        original = vault_engine._stream_file
        def interrupt(*args, **kwargs):
            cancel.set()
            return original(*args, **kwargs)
        with mock.patch.object(vault_engine, "_stream_file", interrupt):
            result = health.check_item(self.store, item, cancel=cancel)
        self.assertEqual(result.status, "Not checked")
        self.assertIn("Cancelled", result.detail)
        self.assertEqual(health.latest_results(self.store, [item])[item.id].status, "Not checked")

    def test_pre_cancelled_library_does_not_read_or_write(self):
        self.vault()
        before = self.store.catalog_path.read_bytes()
        cancel = threading.Event()
        cancel.set()
        report = health.check_library(self.store, cancel=cancel)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.results, ())
        self.assertEqual(before, self.store.catalog_path.read_bytes())

    def test_repository_changed_during_check_does_not_verify(self):
        item, _, _ = self.repository()
        original = engine._load_pack_index
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (Path(item.path) / "packs" / "appeared.txt").write_bytes(b"Changed")
            return result
        with mock.patch.object(engine, "_load_pack_index", changed):
            result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertIn("changed during", result.detail)

    def test_limits_are_attention_not_verified(self):
        item, _, _ = self.repository()
        with mock.patch.object(health, "MAX_OBJECTS", 0):
            result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Needs attention")
        self.assertIn("limit", result.detail)
        with mock.patch.object(health, "MAX_ITEMS", 0):
            report = health.check_library(self.store)
        self.assertTrue(report.limited)
        self.assertEqual(report.results, ())

    def test_receipt_failure_does_not_hide_result_or_modify_storage(self):
        item = self.vault()
        with mock.patch.object(self.store, "record_health", side_effect=library.LibraryError("locked catalogue")):
            result = health.check_item(self.store, item)
        self.assertEqual(result.status, "Verified")
        self.assertIn("locked catalogue", result.receipt_error)
        self.assertEqual(self.store.latest_health_receipts(), {})

    def test_cached_health_read_does_not_inspect_storage(self):
        item = self.vault()
        result = health.check_item(self.store, item)
        with mock.patch.object(self.store, "inspect_item", side_effect=AssertionError("No background scan")):
            self.assertEqual(health.latest_results(self.store, [item])[item.id], result)
        self.assertIsNone(health.parse_receipt(result.receipt(), dataclasses.replace(item, path=item.path + ".moved")))

    def test_damaged_or_spoofed_receipts_are_not_green(self):
        item = self.vault()
        result = health.check_item(self.store, item)
        for raw in ("nonsense", "{}", result.receipt().replace('"Verified"', '"Everything safe"'),
                    result.receipt().replace(result.fingerprint, ""),
                    result.receipt().replace('"file_count": 2', '"file_count": true')):
            self.assertIsNone(health.parse_receipt(raw, item))

    def test_newer_availability_failure_supersedes_previous_verified(self):
        item = self.vault()
        self.assertEqual(health.check_item(self.store, item).status, "Verified")
        Path(item.path).unlink()
        current = self.store.refresh(item.id)
        result = health.latest_results(self.store, [current])[item.id]
        self.assertEqual((result.status, result.availability), ("Needs attention", "Missing"))

    def test_repository_cancellation_at_object_boundary_is_not_verified(self):
        item, _, _ = self.repository()
        cancel = threading.Event()
        original = engine._load_pack_index
        def stop(*args, **kwargs):
            cancel.set()
            return original(*args, **kwargs)
        with mock.patch.object(engine, "_load_pack_index", stop):
            result = health.check_item(self.store, item, cancel=cancel)
        self.assertEqual(result.status, "Not checked")
        self.assertIn("Cancelled", result.detail)

    def test_all_projects_and_healthy_items_survive_another_failure(self):
        missing = self.vault()
        healthy, _, _ = self.repository()
        self.store.assign_project(healthy.id, self.store.create_project("Other project").id)
        Path(missing.path).unlink()
        report = health.check_library(self.store)
        self.assertEqual({r.item_id: r.status for r in report.results}, {missing.id: "Needs attention", healthy.id: "Verified"})

    def test_pack_sidecar_and_orphan_pin_are_not_ignored(self):
        item, _, _ = self.repository()
        pack = next((Path(item.path) / "packs").rglob("*.rtpack"))
        sidecar = Path(str(pack) + "-wal")
        sidecar.write_bytes(b"Generated active writer")
        self.assertEqual(health.check_item(self.store, item).status, "Needs attention")
        sidecar.unlink()
        (Path(item.path) / "refs" / "pins" / ("0" * 32 + ".json")).write_text("{}")
        self.assertEqual(health.check_item(self.store, item).status, "Needs attention")


if __name__ == "__main__":
    unittest.main()
