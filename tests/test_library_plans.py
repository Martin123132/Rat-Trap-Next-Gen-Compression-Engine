"""Manual plans use disposable data; never the real Library or user folders."""
import dataclasses
import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from rat_trap import library, library_plans as plans, repository_engine as engine


class BackupPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rat-trap-plan-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "Source 日本"
        self.source.mkdir()
        (self.source / "note.txt").write_bytes(b"First version")
        (self.source / "empty").mkdir()
        self.target = self.base / "versions"
        self.store = library.LibraryStore(self.base / "catalog" / "library.sqlite3")
        self.project = self.store.create_project("Generated project")

    def save(self, **changes):
        args = dict(name="Daily work", source=str(self.source), destination=str(self.target), project_id=self.project.id)
        args.update(changes)
        return plans.save_plan(self.store, **args)

    def run_first(self):
        result = plans.run_plan(self.store, self.save())
        self.assertEqual(result.plan.last_status, "Succeeded", result)
        self.assertIsNotNone(result.saved)
        return result

    def fingerprint(self, root):
        return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                for p in root.rglob("*") if p.is_file()}

    def test_save_only_and_reopen_does_not_inspect_storage(self):
        plan = self.save()
        self.assertFalse(self.target.exists())
        reopened = library.LibraryStore(self.store.catalog_path)
        with mock.patch.object(library, "inspect_storage", side_effect=AssertionError("Source read")), mock.patch.object(engine, "create_snapshot") as create:
            self.assertEqual(plans.list_plans(reopened), [plan])
            create.assert_not_called()
        self.assertEqual(self.store.timeline(), [])
        self.assertEqual(plan.last_status, "Never run")

    def test_two_runs_restore_older_bytes_and_keep_history(self):
        first = self.run_first()
        (self.source / "note.txt").write_bytes(b"Second version")
        (self.source / "new.txt").write_bytes(b"New file")
        second = plans.run_plan(self.store, first.plan)
        self.assertEqual(second.plan.last_status, "Succeeded")
        self.assertNotEqual(first.saved.snapshot_id, second.saved.snapshot_id)
        self.assertEqual(len(library.inspect_storage(self.target).snapshots), 2)
        restored = self.base / "restore"
        engine.restore_snapshot(self.target, first.saved.snapshot_id, restored)
        self.assertEqual((restored / "note.txt").read_bytes(), b"First version")
        self.assertFalse((restored / "new.txt").exists())
        self.assertEqual((self.source / "note.txt").read_bytes(), b"Second version")
        receipts = [e for e in self.store.timeline() if e.title == "Backup plan run"]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(e.kind == "note" and e.snapshot_id is None for e in receipts))
        self.assertEqual(plans.get_plan(self.store, first.plan.id), second.plan)

    def test_existing_repository_keeps_config_and_versions(self):
        engine.init_repository(self.target, zstd_level=3)
        old = engine.create_snapshot(self.target, self.source)
        config = (self.target / "repository.json").read_bytes()
        plan = self.save()
        self.assertTrue(plan.repository_identity)
        result = plans.run_plan(self.store, plan)
        self.assertEqual(result.plan.last_status, "Succeeded")
        self.assertEqual(config, (self.target / "repository.json").read_bytes())
        self.assertIn(old.snapshot_id, {s.snapshot_id for s in library.inspect_storage(self.target).snapshots})

    def test_empty_destination_can_be_explicitly_saved_and_initialized(self):
        self.target.mkdir()
        plan = self.save()
        self.assertIsNotNone(plan.destination_identity)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(plans.run_plan(self.store, plan).plan.last_status, "Succeeded")

    def test_failed_attempt_keeps_previous_success(self):
        first = self.run_first()
        self.source.rename(self.base / "moved-source")
        result = plans.run_plan(self.store, first.plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        self.assertEqual(result.plan.last_success_snapshot, first.saved.snapshot_id)
        self.assertEqual(result.plan.last_snapshot_id, "")
        self.assertEqual(len(library.inspect_storage(self.target).snapshots), 1)

    def test_source_replacement_is_not_silently_accepted(self):
        plan = self.save()
        self.source.rename(self.base / "old-source")
        self.source.mkdir()
        (self.source / "unexpected.txt").write_bytes(b"New folder")
        result = plans.run_plan(self.store, plan)
        self.assertIn("replaced", result.plan.last_detail)
        self.assertFalse(self.target.exists())

    def test_new_destination_appearing_is_preserved(self):
        plan = self.save()
        self.target.mkdir()
        (self.target / "user.txt").write_bytes(b"Do not touch")
        before = self.fingerprint(self.target)
        result = plans.run_plan(self.store, plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        self.assertEqual(before, self.fingerprint(self.target))

    def test_existing_backup_missing_never_recreated(self):
        first = self.run_first()
        self.target.rename(self.base / "moved-repository")
        result = plans.run_plan(self.store, first.plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        self.assertFalse(self.target.exists())

    def test_replaced_repository_is_refused_and_unchanged(self):
        first = self.run_first()
        self.target.rename(self.base / "old-repository")
        engine.init_repository(self.target)
        before = self.fingerprint(self.target)
        result = plans.run_plan(self.store, first.plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        self.assertEqual(before, self.fingerprint(self.target))

    def test_parent_identity_change_is_refused(self):
        plan = self.save()
        actual = plans._directory_id
        def changed(path):
            value = actual(path)
            return (value[0], value[1] + 1) if path == self.target.parent else value
        with mock.patch.object(plans, "_directory_id", side_effect=changed):
            result = plans.run_plan(self.store, plan)
        self.assertIn("parent/drive changed", result.plan.last_detail)
        self.assertFalse(self.target.exists())

    def test_pending_work_is_not_recovered_or_modified(self):
        first = self.run_first()
        pending = self.target / "staging" / "jobs" / "generated-pending"
        pending.mkdir()
        (pending / "do-not-touch.txt").write_bytes(b"Pending data")
        before = self.fingerprint(self.target)
        with mock.patch.object(engine, "_recover_ready_jobs_locked") as recover:
            result = plans.run_plan(self.store, first.plan)
            recover.assert_not_called()
        self.assertIn("Pending", result.plan.last_detail)
        self.assertEqual(before, self.fingerprint(self.target))

    def test_locked_preflight_runs_before_recovery_and_cache_mutations(self):
        first = self.run_first()
        original = engine._repository_lock
        @contextmanager
        def pending_on_lock(root):
            with original(root):
                (root / "staging" / "jobs" / "appeared").mkdir()
                yield
        with mock.patch.object(engine, "_repository_lock", pending_on_lock), mock.patch.object(engine, "_ensure_catalog_locked") as cache, mock.patch.object(engine, "_recover_ready_jobs_locked") as recover:
            result = plans.run_plan(self.store, first.plan)
        cache.assert_not_called()
        recover.assert_not_called()
        self.assertIn("Pending", result.plan.last_detail)

    def test_require_new_refuses_existing_repository_without_modification(self):
        engine.init_repository(self.target)
        before = self.fingerprint(self.target)
        with self.assertRaises(engine.RepositoryError):
            engine.init_repository(self.target, require_new=True)
        self.assertEqual(before, self.fingerprint(self.target))

    def test_deleted_project_cannot_run(self):
        plan = self.save()
        self.store.delete_project(self.project.id)
        result = plans.run_plan(self.store, plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        self.assertFalse(self.target.exists())
        self.assertIn("Project was removed", result.record_error)

    def test_repository_reassigned_to_other_project_is_refused(self):
        first = self.run_first()
        other = self.store.create_project("Other project")
        self.store.assign_project(first.saved.item.id, other.id)
        before = self.fingerprint(self.target)
        result = plans.run_plan(self.store, first.plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        self.assertEqual(before, self.fingerprint(self.target))

    def test_edit_rename_preserves_success_but_new_source_resets_it(self):
        first = self.run_first()
        renamed = self.save(name="Renamed", previous=first.plan)
        self.assertEqual(renamed.last_success_snapshot, first.plan.last_success_snapshot)
        new_source = self.base / "another-source"
        new_source.mkdir()
        updated = self.save(name="New source", source=str(new_source), previous=renamed)
        self.assertEqual(updated.last_status, "Never run")
        self.assertEqual(updated.last_success_snapshot, "")
        self.assertEqual(len([e for e in self.store.timeline() if e.title == "Backup plan run"]), 1)

    def test_duplicate_and_stale_plan_changes_are_refused(self):
        plan = self.save()
        with self.assertRaises(library.LibraryError):
            self.save()
        changed = self.save(previous=plan, name="Changed")
        for action in (lambda: plans.run_plan(self.store, plan), lambda: plans.delete_plan(self.store, plan),
                       lambda: self.save(previous=plan, name="Stale")):
            with self.assertRaises(library.LibraryError):
                action()
        self.assertEqual(plans.get_plan(self.store, plan.id), changed)
        self.assertFalse(self.target.exists())

    def test_removing_plan_only_forgets_settings(self):
        first = self.run_first()
        before, events = self.fingerprint(self.target), self.store.timeline()
        plans.delete_plan(self.store, first.plan)
        self.assertEqual(plans.list_plans(self.store), [])
        self.assertEqual(self.fingerprint(self.target), before)
        self.assertEqual(self.store.timeline(), events)
        self.assertEqual(len(self.store.list_items()), 1)

    def test_active_operation_blocks_run_edit_remove_and_acknowledgement(self):
        plan = self.save()
        with plans._operation_lock(self.store):
            for action in (lambda: plans.run_plan(self.store, plan), lambda: plans.delete_plan(self.store, plan),
                           lambda: self.save(previous=plan), lambda: plans.acknowledge_interrupted(self.store, plan)):
                with self.assertRaises(library.LibraryError):
                    action()
        self.assertFalse(self.target.exists())

    def test_interrupted_marker_requires_explicit_review(self):
        plan = self.save()
        running = dataclasses.replace(plan, last_status="Running / review required")
        with self.store._connection(write=True) as connection:
            plans._put(connection, running)
        with self.assertRaises(library.LibraryError):
            plans.run_plan(self.store, running)
        with self.assertRaises(library.LibraryError):
            plans.delete_plan(self.store, running)
        reviewed = plans.acknowledge_interrupted(self.store, running)
        self.assertEqual(reviewed.last_status, "Needs attention")
        self.assertEqual(reviewed.last_success_at, "")
        self.assertFalse(self.target.exists())
        self.assertEqual(plans.run_plan(self.store, reviewed).plan.last_status, "Succeeded")

    def test_library_registration_failure_keeps_successful_backup(self):
        plan = self.save()
        with mock.patch.object(self.store, "record_saved", side_effect=OSError("Generated catalogue failure")):
            result = plans.run_plan(self.store, plan)
        self.assertIsNotNone(result.saved)
        self.assertEqual(result.plan.last_status, "Saved; Library needs attention")
        self.assertEqual(len(library.inspect_storage(self.target).snapshots), 1)
        self.assertTrue(result.plan.last_success_snapshot)
        self.assertIn("do not back up again", result.plan.last_detail)

    def test_result_write_failure_does_not_hide_saved_snapshot(self):
        plan = self.save()
        original = plans._put
        def fail_final(connection, value):
            if value.last_status == "Succeeded":
                raise OSError("Generated result receipt failure")
            return original(connection, value)
        with mock.patch.object(plans, "_put", side_effect=fail_final):
            result = plans.run_plan(self.store, plan)
        self.assertIsNotNone(result.saved)
        self.assertIn("receipt", result.record_error)
        self.assertEqual(plans.get_plan(self.store, plan.id).last_status, "Running / review required")
        self.assertEqual(len(library.inspect_storage(self.target).snapshots), 1)

    def test_detached_progress_callback_does_not_turn_save_into_failure(self):
        plan = self.save()
        result = plans.run_plan(self.store, plan, progress=mock.Mock(side_effect=RuntimeError("Detached UI")))
        self.assertEqual(result.plan.last_status, "Succeeded")

    def test_overlap_and_missing_project_are_rejected_before_saving(self):
        for changes in ({"destination": str(self.source / "inside")}, {"project_id": "0" * 32},
                        {"source": str(self.store.catalog_path.parent)}, {"destination": str(self.store.catalog_path.parent / "backup")}):
            with self.subTest(changes=changes), self.assertRaises(library.LibraryError):
                self.save(**changes)
        self.assertEqual(plans.list_plans(self.store), [])

    def test_damaged_metadata_is_rejected_before_source_access(self):
        plan = self.save()
        raw = json.loads(plans._encode(plan))
        raw["last_status"] = "Verified"
        with self.store._connection(write=True) as connection:
            connection.execute("UPDATE library_meta SET value=? WHERE key=?", (json.dumps(raw), plans.PREFIX + plan.id))
        with mock.patch.object(library, "inspect_storage", side_effect=AssertionError("must not inspect")):
            with self.assertRaises(library.LibraryError):
                plans.list_plans(self.store)

    def test_destination_changed_after_confirmation_does_not_create_version(self):
        first = self.run_first()
        original = engine._repository_lock
        @contextmanager
        def reassign_on_lock(root):
            with original(root):
                other = self.store.create_project("Concurrent assignment")
                self.store.assign_project(first.saved.item.id, other.id)
                yield
        with mock.patch.object(engine, "_repository_lock", reassign_on_lock), mock.patch.object(engine, "_recover_ready_jobs_locked") as recover:
            result = plans.run_plan(self.store, first.plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        recover.assert_not_called()
        self.assertEqual(len(library.inspect_storage(self.target).snapshots), 1)

    def test_initial_identity_record_failure_never_creates_snapshot(self):
        plan = self.save()
        original = plans._put
        def fail_pin(connection, value):
            if value.repository_identity and value.last_status == "Running / review required":
                raise OSError("Generated pin record failure")
            return original(connection, value)
        with mock.patch.object(plans, "_put", side_effect=fail_pin), mock.patch.object(engine, "create_snapshot") as create:
            result = plans.run_plan(self.store, plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        create.assert_not_called()
        self.assertEqual(len(library.inspect_storage(self.target).snapshots), 0)

    def test_replaced_empty_destination_is_not_adopted(self):
        self.target.mkdir()
        plan = self.save()
        self.target.rename(self.base / "original-empty-target")
        self.target.mkdir()
        result = plans.run_plan(self.store, plan)
        self.assertEqual(result.plan.last_status, "Needs attention")
        self.assertEqual(list(self.target.iterdir()), [])

    def test_preview_plan_limit_is_enforced(self):
        self.save()
        other = self.base / "another"
        with mock.patch.object(plans, "MAX_PLANS", 1):
            with self.assertRaises(library.LibraryError):
                self.save(destination=str(other))


if __name__ == "__main__":
    unittest.main()
