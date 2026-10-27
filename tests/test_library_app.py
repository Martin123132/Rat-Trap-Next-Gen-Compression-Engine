"""Library navigation and safety checks using disposable catalogs and hidden Tk."""

import dataclasses
import hashlib
import os
import shutil
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from rat_trap import (
    desktop_app,
    desktop_preview2,
    diagnostics,
    guided_app,
    library_app,
    library,
    library_storage,
    repository_engine,
    tutorials,
    windows_app,
)


FIXTURES = Path(__file__).parent / "fixtures" / "formats"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LibraryAppTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-library-ui-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        # Even an accidental default-path lookup cannot touch the real profile.
        self.enterContext(mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.base / "profile")}))
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.log = diagnostics.LocalDiagnostics(self.base / "diagnostics")
        self.addCleanup(self.log.close)
        self.catalog = self.base / "catalog" / "library.sqlite3"
        self.dialogs = {}
        for module, name, result in (
            (windows_app.messagebox, "showerror", None),
            (windows_app.messagebox, "showwarning", None),
            (windows_app.messagebox, "showinfo", None),
            (windows_app.messagebox, "askyesno", False),
            (windows_app.messagebox, "askyesnocancel", None),
            (windows_app.simpledialog, "askstring", None),
            (windows_app.filedialog, "askopenfilename", ""),
            (windows_app.filedialog, "asksaveasfilename", ""),
            (windows_app.filedialog, "askdirectory", ""),
        ):
            self.dialogs[name] = self.enterContext(mock.patch.object(module, name, return_value=result))
        self.reveal = self.enterContext(mock.patch.object(desktop_preview2, "reveal_in_folder"))
        self.startfile = self.enterContext(mock.patch.object(os, "startfile")) if hasattr(os, "startfile") else None
        self.app = library_app.LibraryRatTrapApp(
            self.root, diagnostic_log=self.log, library_path=self.catalog,
        )
        self.root.update_idletasks()
        self.releases = []

    def tearDown(self):
        for release in getattr(self, "releases", []):
            release.set()
        if hasattr(self, "app"):
            if self.app.busy:
                self.wait_idle()
            self.app.tutorial_exit()
        if hasattr(self, "root"):
            for timer in self.root.tk.call("after", "info"):
                self.root.after_cancel(timer)

    def wait_idle(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.root.update()
        self.assertFalse(self.app.busy, "Library worker did not finish")

    def fixture(self, name="gmw-solid-2-4.4-dedup.gmw", *, target=None):
        target = self.base / (target or name)
        shutil.copyfile(FIXTURES / name, target)
        return target

    def select_item(self, item):
        self.app._refresh_library_view()
        self.app.library_tree.selection_set(item.id)
        self.app.library_tree.focus(item.id)
        self.root.update()

    def make_repository(self):
        source = self.base / "generated-source"
        source.mkdir()
        content = source / "work.txt"
        content.write_text("Generated first revision\n", encoding="utf-8")
        repository = self.base / "generated-repository"
        repository_engine.init_repository(repository)
        first = repository_engine.create_snapshot(repository, source, label="First revision")
        content.write_text("Generated second revision\n", encoding="utf-8")
        second = repository_engine.create_snapshot(repository, source, label="Second revision")
        return repository, first, second

    def assert_no_external_open(self):
        self.reveal.assert_not_called()
        if self.startfile is not None:
            self.startfile.assert_not_called()

    def prepare_plan(self):
        project, source, target = self.prepare_store_form("Versioned backup")
        self.app._library_plans_from_store()
        self.app.library_plan_name.set("Generated manual plan")
        self.dialogs["askyesno"].return_value = True
        self.app._library_plan_save()
        self.wait_idle()
        from rat_trap import library_plans
        plan = library_plans.list_plans(self.app.library_store)[0]
        self.app.library_plans_tree.selection_set(plan.id)
        self.root.update()
        return plan, project, source, target

    def test_plan_save_records_settings_without_running(self):
        plan, project, source, target = self.prepare_plan()
        self.assertFalse(target.exists())
        self.assertEqual(plan.project_id, project.id)
        self.assertEqual(self.app.library_store.timeline(), [])
        self.assertIn("No backup was started", self.app.library_plan_result.get())
        self.assert_no_external_open()

    def test_plan_run_uses_saved_fields_and_keeps_two_versions(self):
        plan, project, source, target = self.prepare_plan()
        self.app.library_plan_source.set(str(self.base / "unsaved-source"))
        self.app._library_plan_run()
        self.wait_idle()
        self.assertTrue(target.is_dir())
        self.assertIn("Succeeded", self.app.library_plan_result.get())
        self.assertEqual(len(library.inspect_storage(target).snapshots), 1)
        self.assertIn(str(source), self.dialogs["askyesno"].call_args.args[1])
        self.assertNotIn("unsaved-source", self.dialogs["askyesno"].call_args.args[1])
        (source / "example.txt").write_bytes(b"Generated later revision")
        self.app._library_plan_run()
        self.wait_idle()
        self.assertEqual(len(library.inspect_storage(target).snapshots), 2)
        self.assertEqual(len([e for e in self.app.library_store.timeline() if e.title == "Backup plan run"]), 2)
        self.assertEqual(self.app.library_modes.select(), str(self.app.library_plans_form))
        self.assert_no_external_open()

    def test_plan_confirmation_cancel_never_saves_or_runs(self):
        project, source, target = self.prepare_store_form("Versioned backup")
        self.app._library_plans_from_store()
        self.app._library_plan_save()
        self.assertFalse(self.app.busy)
        from rat_trap import library_plans
        self.assertEqual(library_plans.list_plans(self.app.library_store), [])
        plan, project, source, target = self.prepare_plan_for_existing_source(project, source, target)
        self.dialogs["askyesno"].return_value = False
        self.app._library_plan_run()
        self.assertFalse(self.app.busy)
        self.assertFalse(target.exists())

    def prepare_plan_for_existing_source(self, project, source, target):
        self.app.library_plan_name.set("Generated manual plan")
        self.dialogs["askyesno"].return_value = True
        self.app._library_plan_save()
        self.wait_idle()
        from rat_trap import library_plans
        plan = library_plans.list_plans(self.app.library_store)[0]
        self.app.library_plans_tree.selection_set(plan.id)
        return plan, project, source, target

    def test_plan_edit_and_remove_preserve_backup_and_receipts(self):
        plan, project, source, target = self.prepare_plan()
        self.app._library_plan_run()
        self.wait_idle()
        self.app._library_plan_edit()
        self.app.library_plan_name.set("Renamed plan")
        self.app._library_plan_save()
        self.wait_idle()
        self.assertEqual(self.app._library_plan_selection().name, "Renamed plan")
        self.assertTrue(self.app._library_plan_selection().last_success_at)
        events = self.app.library_store.timeline()
        self.app._library_plan_delete()
        self.assertEqual(self.app._library_plans, {})
        self.assertTrue(target.is_dir())
        self.assertEqual(self.app.library_store.timeline(), events)
        self.assertEqual(len(self.app.library_store.list_items()), 1)

    def test_plan_failure_and_receipt_failure_are_visible(self):
        plan, project, source, target = self.prepare_plan()
        from rat_trap import library_plans
        original = library_plans._put
        def fail_result(connection, value):
            if value.last_status == "Succeeded":
                raise OSError("Generated receipt failure")
            return original(connection, value)
        with mock.patch.object(library_plans, "_put", side_effect=fail_result):
            self.app._library_plan_run()
            self.wait_idle()
        self.assertIn("Saved snapshot:", self.app.library_plan_result.get())
        self.assertIn("receipt", self.app.library_plan_result.get())
        self.assertTrue(target.is_dir())
        self.assertEqual(self.app._library_plan_selection().last_status, "Running / review required")
        self.app._library_plan_review()
        self.assertEqual(self.app._library_plan_selection().last_status, "Needs attention")
        source.rename(self.base / "moved-plan-source")
        self.app._library_plan_run()
        self.wait_idle()
        self.assertIn("Needs attention", self.app.library_plan_result.get())
        self.assertEqual(len(library.inspect_storage(target).snapshots), 1)

    def test_plan_listing_and_health_navigation_never_run_storage(self):
        plan, project, source, target = self.prepare_plan()
        with mock.patch.object(repository_engine, "create_snapshot") as create, mock.patch.object(library, "inspect_storage") as inspect:
            self.app._library_plans_open()
            self.app._library_plan_health()
            self.app._refresh_library_view()
        create.assert_not_called()
        inspect.assert_not_called()
        self.assertEqual(self.app.library_modes.select(), str(self.app.library_health_form))

    def test_plan_controls_reject_busy_and_tutorial_calls(self):
        callbacks = ("_library_plans_open", "_library_plan_new", "_library_plan_edit", "_library_plan_save",
                     "_library_plan_run", "_library_plan_delete", "_library_plan_review", "_library_plan_health",
                     "_library_plan_source_choose", "_library_plan_destination_choose", "_library_plans_from_store")
        from rat_trap import library_plans
        with mock.patch.object(library_plans, "save_plan") as save, mock.patch.object(library_plans, "run_plan") as run:
            self.app.busy = True
            for name in callbacks:
                getattr(self.app, name)()
            self.app.busy = False
            with mock.patch.object(self.app, "_library_guard", return_value=False):
                for name in callbacks:
                    getattr(self.app, name)()
            save.assert_not_called()
            run.assert_not_called()
        self.dialogs["askyesno"].assert_not_called()
        self.dialogs["askdirectory"].assert_not_called()

    def test_library_is_additive_and_has_its_own_support_identity(self):
        self.assertIsInstance(self.app, guided_app.GuidedRatTrapApp)
        self.assertEqual(library_app.SUPPORT_VERSION, "5.7.0-desktop-preview.2-library.6")
        self.assertIn("Library", self.root.title())
        self.assertIn("Library", self.app.pages)
        self.assertIn("Library", self.app.nav_buttons)
        self.assertNotIn("Library", desktop_app.WORKSPACE_NAMES,
                         "The frozen preview's global workspace map must stay untouched")
        self.assertEqual(Path(self.app.library_store.catalog_path), self.catalog)
        self.assertEqual(self.app.library_store.list_items(), [])
        for title in ("Library", "Home", "Create archive", "Secure files", "Search Vault", "Backups & history"):
            with self.subTest(workspace=title):
                self.assertTrue(self.app._go_to(title))
                self.assertEqual(self.app.tabs.select(), str(self.app.pages[title]))
        self.assert_no_external_open()

    def prepare_store_form(self, mode="One-off archive"):
        project = self.app.library_store.create_project("Store workflow")
        self.app._refresh_library_view()
        self.app.library_project_filter.set(f"{project.name} [{project.id[:8]}]")
        source = self.base / "store-source"
        source.mkdir()
        (source / "example.txt").write_bytes(b"Generated version one")
        self.app.store_mode.set(mode)
        self.app.store_source.set(str(source))
        target = self.base / ("store-output.gmw" if mode == "One-off archive" else "store-backups")
        self.app.store_destination.set(str(target))
        self.app._library_store_open()
        return project, source, target

    def test_store_form_archive_success_selects_item_and_timeline(self):
        project, source, target = self.prepare_store_form()
        self.app._library_store_start()
        self.wait_idle()
        self.assertTrue(target.is_file())
        item = self.app.library_store.list_items()[0]
        self.assertEqual(item.project_id, project.id)
        self.assertEqual(self.app.library_tree.selection(), (item.id,))
        self.assertIn("NOT ENCRYPTED", self.app.store_notice.get())
        self.assertIn("Saved to your Library", self.app.store_result.get())
        self.assertEqual((source / "example.txt").read_bytes(), b"Generated version one")
        self.assertEqual(self.app.library_store.timeline()[0].title, "Archive saved to Library")
        self.assert_no_external_open()

    def test_store_form_backup_two_versions_open_exact_older_event(self):
        project, source, target = self.prepare_store_form("Versioned backup")
        self.app._library_store_start()
        self.wait_idle()
        first = next(e for e in self.app.library_store.timeline() if e.kind == "snapshot")
        (source / "example.txt").write_bytes(b"Generated version two")
        self.app._library_store_start()
        self.wait_idle()
        snapshots = [e for e in self.app.library_store.timeline() if e.kind == "snapshot"]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(len(self.app.library_store.list_items()), 1)
        self.app.library_timeline_tree.selection_set(first.id)
        self.app._library_open_event()
        self.wait_idle()
        self.assertEqual(self.app.repository_snapshot_tree.selection(), (first.snapshot_id,))
        self.assert_no_external_open()

    def test_store_form_failure_and_partial_success_are_distinct(self):
        project, source, target = self.prepare_store_form()
        with mock.patch.object(library_storage, "store_folder", side_effect=OSError("disk full")):
            self.app._library_store_start()
            self.wait_idle()
        self.assertIn("did not complete", self.app.store_result.get())
        self.assertEqual(self.app.library_store.timeline(), [])
        with mock.patch.object(self.app.library_store, "record_saved", side_effect=library.LibraryError("locked")):
            self.app._library_store_start()
            self.wait_idle()
        self.assertTrue(target.is_file())
        self.assertIn("Files saved, but Library", self.app.store_result.get())
        self.assertIn("Do not save again", self.app.store_result.get())
        self.assertEqual(self.app.library_store.timeline(), [])
        self.assertIn("needs attention", self.app.status_text.get())

    def test_store_form_requires_project_and_cancel_is_read_only(self):
        self.app._library_store_open()
        self.assertFalse(self.catalog.exists())
        self.app._library_store_choose_source()
        self.app._library_store_choose_destination()
        self.app._library_store_back()
        self.assertFalse(self.catalog.exists())
        self.assertEqual(self.app.store_source.get(), "")
        self.assertEqual(self.app.store_destination.get(), "")

    def test_store_mode_change_clears_incompatible_destination_and_encryption(self):
        self.app.store_destination.set("old.gmw")
        self.app.store_encrypt.set(True)
        self.app.store_mode.set("Versioned backup")
        self.assertEqual(self.app.store_destination.get(), "")
        self.assertFalse(self.app.store_encrypt.get())
        self.assertEqual(str(self.app.store_encryption_box.cget("state")), "disabled")
        self.assertIn("NOT ENCRYPTED", self.app.store_notice.get())

    def test_store_another_version_prefills_repository_but_does_not_guess_source(self):
        project, source, target = self.prepare_store_form("Versioned backup")
        self.app._library_store_start()
        self.wait_idle()
        self.app._library_store_selected_backup()
        self.assertEqual(self.app.store_destination.get(), str(target))
        self.assertEqual(self.app.store_source.get(), "")
        self.assertEqual(self.app.library_modes.select(), str(self.app.library_store_form))

    def test_cancelled_encryption_does_not_save_or_register(self):
        project, source, target = self.prepare_store_form()
        self.app.store_encrypt.set(True)
        with mock.patch.object(self.app, "_new_encryption_options", return_value=None), mock.patch.object(library_storage, "store_folder") as save:
            self.app._library_store_start()
            save.assert_not_called()
        self.assertFalse(target.exists())
        self.assertEqual(self.app.library_store.list_items(), [])

    def test_store_worker_captures_project_and_preserves_new_form_draft(self):
        project, source, target = self.prepare_store_form()
        other = self.app.library_store.create_project("Different project")
        self.app._refresh_library_view()
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = library_storage.store_folder

        def delayed(*args, **kwargs):
            started.set()
            release.wait(10)
            return original(*args, **kwargs)

        with mock.patch.object(library_storage, "store_folder", side_effect=delayed) as save:
            self.app._library_store_start()
            self.assertTrue(started.wait(5))
            self.app._library_store_start()  # A second click must not enqueue another save.
            self.app.library_project_filter.set(f"{other.name} [{other.id[:8]}]")
            self.app.store_source.set("A later draft")
            release.set()
            self.wait_idle()
            self.assertEqual(save.call_count, 1)
        self.assertEqual(self.app.library_store.list_items()[0].project_id, project.id)
        self.assertEqual(self.app._library_project_id(), project.id)
        self.assertEqual(self.app.store_source.get(), "A later draft")
        self.assert_no_external_open()

    def test_store_form_discloses_resumed_backup_state(self):
        self.prepare_store_form("Versioned backup")
        original = library_storage.store_folder

        def resumed(*args, **kwargs):
            return dataclasses.replace(original(*args, **kwargs), resumed=True)

        with mock.patch.object(library_storage, "store_folder", side_effect=resumed):
            self.app._library_store_start()
            self.wait_idle()
        self.assertIn("Resumed an interrupted backup", self.app.store_result.get())
        self.assertIn("earlier job's source state", self.app.store_result.get())

    def test_existing_open_and_completion_do_not_register_without_explicit_add(self):
        archive = self.fixture()
        before = digest(archive)
        self.app._preselect_output_path(archive)
        self.app._publish_completion(desktop_preview2.CompletedOutput(
            archive, "archive", "Generated test result", "Explicit Add remains required",
        ))
        self.assertEqual(self.app.library_store.list_items(), [])
        self.assertEqual(digest(archive), before)
        self.assert_no_external_open()

    def test_explicit_add_persists_one_registration_without_modifying_archive(self):
        archive = self.fixture(target="Unicode 日本 archive.gmw")
        before = (digest(archive), archive.stat().st_mtime_ns)
        self.dialogs["askopenfilename"].return_value = str(archive)
        self.app._library_add_file()
        self.wait_idle()
        items = self.app.library_store.list_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(Path(items[0].path), archive)
        self.assertEqual(items[0].kind, "archive")
        self.assertIn(items[0].id, self.app.library_tree.get_children())
        # A second explicit Add of this same path is idempotent.
        self.app._library_add_file()
        self.wait_idle()
        self.assertEqual([item.id for item in self.app.library_store.list_items()], [items[0].id])
        reopened = library.LibraryStore(self.catalog)
        self.assertEqual(reopened.get_item(items[0].id), self.app.library_store.get_item(items[0].id))
        self.assertEqual((digest(archive), archive.stat().st_mtime_ns), before)
        self.dialogs["showerror"].assert_not_called()
        self.assert_no_external_open()

    def test_cancelled_registration_pickers_leave_catalog_empty(self):
        self.app._library_add_file()
        self.app._library_add_repository()
        self.root.update_idletasks()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.library_store.list_items(), [])
        self.assertEqual(self.app.library_store.timeline(), [])
        self.assert_no_external_open()

    def test_duplicate_add_in_another_project_keeps_assignment_and_reveals_actual_item(self):
        original_project = self.app.library_store.create_project("Already filed here")
        requested_project = self.app.library_store.create_project("Other selected project")
        archive = self.fixture()
        item = self.app.library_store.register(archive, project_id=original_project.id)
        before = (digest(archive), archive.stat().st_mtime_ns)
        self.app._refresh_library_view()
        self.app.library_project_filter.set(f"{requested_project.name} [{requested_project.id[:8]}]")
        self.app.library_query.set("nonmatching active search")
        self.dialogs["askopenfilename"].return_value = str(archive)
        self.app._library_add_file()
        self.wait_idle()
        self.assertEqual([stored.id for stored in self.app.library_store.list_items()], [item.id])
        self.assertEqual(self.app.library_store.get_item(item.id).project_id, original_project.id)
        self.assertEqual(self.app.library_project_filter.get(),
                         f"{original_project.name} [{original_project.id[:8]}]")
        self.assertIn(item.id, self.app.library_tree.get_children())
        self.assertEqual(self.app.library_tree.selection(), (item.id,))
        self.dialogs["showinfo"].assert_called_once()
        self.assertIn("existing project assignment", self.dialogs["showinfo"].call_args.args[1])
        self.assertEqual((digest(archive), archive.stat().st_mtime_ns), before)
        self.assert_no_external_open()

    def test_explicit_repository_registration_lists_both_exact_snapshots(self):
        repository, first, second = self.make_repository()
        before = {path.relative_to(repository).as_posix(): (digest(path), path.stat().st_mtime_ns)
                  for path in repository.rglob("*") if path.is_file()}
        self.dialogs["askdirectory"].return_value = str(repository)
        self.app._library_add_repository()
        self.wait_idle()
        items = self.app.library_store.list_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "repository")
        snapshots = [event for event in self.app.library_store.timeline(item_id=items[0].id)
                     if event.kind == "snapshot"]
        self.assertEqual({event.snapshot_id for event in snapshots}, {first.snapshot_id, second.snapshot_id})
        after = {path.relative_to(repository).as_posix(): (digest(path), path.stat().st_mtime_ns)
                 for path in repository.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assert_no_external_open()

    def test_library_open_preselects_archive_vault_and_sealed_without_executing(self):
        cases = (
            ("gmw-solid-2-4.4-dedup.gmw", "Inspect / export", "inspect_archive"),
            ("gmw-vault-1-schema-2.gmw", "Search Vault", "vault_archive"),
            ("rat-trap-sealed-file-1-5.4.rtsf", "Secure files", "unseal_source"),
            ("rat-trap-encrypted-1-5.3.gmw", "Inspect / export", "inspect_archive"),
        )
        for fixture, page, variable in cases:
            with self.subTest(fixture=fixture):
                path = self.fixture(fixture)
                before = digest(path)
                item = self.app.library_store.register(path)
                self.select_item(item)
                self.app._library_open_selected()
                self.wait_idle()
                self.assertEqual(self.app.tabs.select(), str(self.app.pages[page]))
                self.assertEqual(Path(getattr(self.app, variable).get()), path)
                self.assertEqual(digest(path), before)
                self.dialogs["askstring"].assert_not_called()
                self.assert_no_external_open()
        self.dialogs["showerror"].assert_not_called()

    def test_verified_archive_kind_overrides_misleading_database_extension(self):
        archive = self.fixture(target="solid archive renamed.db")
        before = (digest(archive), archive.stat().st_mtime_ns)
        item = self.app.library_store.register(archive)
        self.assertEqual(item.kind, "archive")
        self.select_item(item)
        self.app._library_open_selected()
        self.wait_idle()
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Inspect / export"]))
        self.assertEqual(Path(self.app.inspect_archive.get()), archive)
        self.assertNotEqual(self.app.vault_archive.get(), str(archive))
        self.assertEqual((digest(archive), archive.stat().st_mtime_ns), before)
        self.dialogs["askstring"].assert_not_called()
        self.dialogs["showerror"].assert_not_called()
        self.assert_no_external_open()

    def test_missing_item_cannot_open_and_relink_keeps_id_and_notes(self):
        archive = self.fixture()
        item = self.app.library_store.register(archive)
        note = self.app.library_store.add_note("Retain this project note", item_id=item.id)
        moved = self.base / "relocated archive.gmw"
        archive.rename(moved)
        self.app.library_store.refresh(item.id)
        self.select_item(item)
        self.app._go_to("Library")
        with mock.patch.object(self.app, "_preselect_output_path") as route:
            self.app._library_open_selected()
            self.wait_idle()
            route.assert_not_called()
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Library"]))
        self.dialogs["askopenfilename"].return_value = str(moved)
        self.app._library_relink_selected()
        self.wait_idle()
        restored = self.app.library_store.get_item(item.id)
        self.assertEqual(Path(restored.path), moved)
        self.assertEqual(restored.status, "available")
        self.assertEqual([event.id for event in self.app.library_store.timeline(item_id=item.id)
                          if event.kind == "note"], [note.id])
        self.assert_no_external_open()

    def test_relink_rejects_different_storage_without_reassigning_the_item(self):
        original = self.fixture()
        item = self.app.library_store.register(original)
        different = self.fixture("gmw-solid-2-4.3.gmw")
        before = digest(different)
        self.select_item(item)
        self.dialogs["askopenfilename"].return_value = str(different)
        self.app._library_relink_selected()
        self.wait_idle()
        self.assertEqual(self.app.library_store.get_item(item.id).path, str(original))
        self.assertEqual(digest(different), before)
        self.dialogs["showwarning"].assert_called_once()
        self.assert_no_external_open()

    def test_remove_from_library_does_not_delete_archive(self):
        archive = self.fixture()
        item = self.app.library_store.register(archive)
        before = (digest(archive), archive.stat().st_mtime_ns)
        self.select_item(item)
        self.dialogs["askyesno"].return_value = True
        self.app._library_remove_selected()
        self.wait_idle()
        self.assertEqual(self.app.library_store.list_items(), [])
        self.assertTrue(archive.is_file())
        self.assertEqual((digest(archive), archive.stat().st_mtime_ns), before)
        self.assert_no_external_open()

    def test_project_filter_assignment_search_and_dated_notes_are_persistent(self):
        first = self.app.library_store.create_project("Project 日本")
        second = self.app.library_store.create_project("Different project")
        archive = self.fixture(target="one.gmw")
        vault = self.fixture("gmw-vault-1-schema-2.gmw", target="two.gmw")
        item = self.app.library_store.register(archive, label="Find this archive", project_id=first.id)
        other = self.app.library_store.register(vault, label="Unrelated Vault", project_id=second.id)
        first_label = f"{first.name} [{first.id[:8]}]"
        self.app._refresh_library_view()
        self.app.library_project_filter.set(first_label)
        self.root.update()
        self.assertEqual(set(self.app.library_tree.get_children()), {item.id})
        self.app.library_query.set("does-not-match")
        self.root.update()
        self.assertEqual(self.app.library_tree.get_children(), ())
        self.app.library_query.set("Find this")
        self.root.update()
        self.assertEqual(set(self.app.library_tree.get_children()), {item.id})
        self.app.library_tree.selection_set(item.id)
        self.root.update()
        self.app.library_note.insert("1.0", "Saved before the generated meeting")
        self.app.library_note_date.set("2026-10-20")
        self.app._library_add_note()
        self.wait_idle()
        notes = [event for event in self.app.library_store.timeline(project_id=first.id) if event.kind == "note"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].item_id, item.id)
        self.assertEqual(notes[0].occurred_at[:10], "2026-10-20")
        self.assertIn("Saved before", notes[0].detail + notes[0].title)
        self.assertFalse(any(event.kind == "note" for event in self.app.library_store.timeline(project_id=second.id)))
        self.app.library_project_filter.set("All projects")
        self.app.library_query.set("")
        self.root.update()
        self.select_item(other)
        self.app.library_assignment.set(first_label)
        self.app._library_assign_project()
        self.wait_idle()
        self.assertEqual(self.app.library_store.get_item(other.id).project_id, first.id)
        self.assertEqual(library.LibraryStore(self.catalog).timeline(project_id=first.id),
                         self.app.library_store.timeline(project_id=first.id))
        self.assert_no_external_open()

    def test_new_project_is_explicit_and_cancel_does_not_create_project(self):
        self.app._library_new_project()
        self.wait_idle()
        self.assertEqual(self.app.library_store.list_projects(), [])
        self.dialogs["askstring"].return_value = "Generated calendar project"
        self.app._library_new_project()
        self.wait_idle()
        projects = self.app.library_store.list_projects()
        self.assertEqual([project.name for project in projects], ["Generated calendar project"])
        self.assertEqual(library.LibraryStore(self.catalog).list_projects(), projects)

    def test_cached_view_and_search_never_reinspect_registered_storage(self):
        item = self.app.library_store.register(self.fixture())
        with mock.patch.object(library, "inspect_storage", side_effect=AssertionError("Unexpected source inspection")) as inspect:
            self.app._refresh_library_view()
            self.app.library_query.set("gmw")
            self.root.update()
            self.app.library_query.set("")
            self.root.update()
            self.assertIn(item.id, self.app.library_tree.get_children())
            inspect.assert_not_called()
        self.dialogs["showerror"].assert_not_called()

    def test_timeline_opens_exact_older_snapshot_without_restoring_anything(self):
        repository, first, second = self.make_repository()
        item = self.app.library_store.register(repository)
        self.select_item(item)
        event = next(event for event in self.app.library_store.timeline(item_id=item.id)
                     if event.snapshot_id == first.snapshot_id)
        self.app.library_timeline_tree.selection_set(event.id)
        self.app.library_timeline_tree.focus(event.id)
        self.root.update()
        with mock.patch.object(repository_engine, "restore_snapshot") as restore:
            self.app._library_open_event()
            self.wait_idle()
            restore.assert_not_called()
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Backups & history"]))
        self.assertEqual(self.app.repository_loaded_path, repository)
        self.assertEqual(self.app.repository_snapshot_tree.selection(), (first.snapshot_id,))
        self.assertNotEqual(self.app.repository_snapshot_tree.selection(), (second.snapshot_id,))
        self.assertEqual(set(self.app.repository_snapshots), {first.snapshot_id, second.snapshot_id})
        self.assert_no_external_open()

    def test_disappeared_timeline_snapshot_does_not_fall_back_to_latest(self):
        repository, first, second = self.make_repository()
        item = self.app.library_store.register(repository)
        self.select_item(item)
        event = next(event for event in self.app.library_store.timeline(item_id=item.id)
                     if event.snapshot_id == first.snapshot_id)
        self.app.library_timeline_tree.selection_set(event.id)
        inspection = library.inspect_storage(repository)
        missing_old = dataclasses.replace(
            inspection,
            snapshots=tuple(snapshot for snapshot in inspection.snapshots if snapshot.snapshot_id != first.snapshot_id),
            repository_snapshots=tuple(snapshot for snapshot in inspection.repository_snapshots
                                       if snapshot.snapshot_id != first.snapshot_id),
        )
        self.app._go_to("Library")
        with mock.patch.object(library, "inspect_storage", return_value=missing_old), mock.patch.object(
            self.app, "_library_render_repository",
        ) as render, mock.patch.object(repository_engine, "restore_snapshot") as restore:
            self.app._library_open_event()
            self.wait_idle()
            render.assert_not_called()
            restore.assert_not_called()
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Library"]))
        self.assertNotEqual(self.app.repository_snapshot_tree.selection(), (second.snapshot_id,))
        self.assertIn("exact snapshot", self.dialogs["showwarning"].call_args.args[1])
        self.assert_no_external_open()

    def test_async_open_keeps_original_selected_item_when_selection_changes(self):
        first_path = self.fixture(target="first.gmw")
        first = self.app.library_store.register(first_path)
        second = self.app.library_store.register(self.fixture("gmw-vault-1-schema-2.gmw"))
        self.select_item(first)
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original_refresh = self.app.library_store.refresh

        def refresh(item_id):
            started.set()
            if not release.wait(15):
                raise TimeoutError("Generated blocked source check was not released")
            return original_refresh(item_id)

        with mock.patch.object(self.app.library_store, "refresh", side_effect=refresh):
            self.app._library_open_selected()
            self.assertTrue(started.wait(5))
            self.assertTrue(self.app.busy)
            self.app.library_tree.selection_set(second.id)
            self.root.update()
            release.set()
            self.wait_idle()
        self.assertEqual(Path(self.app.inspect_archive.get()), first_path)
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Inspect / export"]))
        self.assert_no_external_open()

    def test_invalid_note_preserves_text_and_reports_needs_review(self):
        item = self.app.library_store.register(self.fixture())
        self.select_item(item)
        text = "Do not discard this draft when the date is invalid"
        self.app.library_note.insert("1.0", text)
        self.app.library_note_date.set("2026-02-31")
        self.app._library_add_note()
        self.wait_idle()
        self.assertEqual(self.app.library_note.get("1.0", "end-1c"), text)
        self.assertFalse(any(event.kind == "note" for event in self.app.library_store.timeline()))
        self.dialogs["showwarning"].assert_called_once()
        self.assertEqual(self.app.activity_title.get(), "Needs review")
        self.assertIsNone(self.app.last_output)

    def test_project_only_note_and_privacy_disclosure_do_not_claim_file_encryption(self):
        project = self.app.library_store.create_project("Generated journal")
        self.app._refresh_library_view()
        self.app.library_project_filter.set(f"{project.name} [{project.id[:8]}]")
        self.app.library_note.insert("1.0", "A project note without attached files")
        self.app._library_add_note()
        self.wait_idle()
        events = self.app.library_store.timeline(project_id=project.id)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].item_id)
        self.assertEqual(events[0].project_id, project.id)
        self.app.library_timeline_tree.selection_set(events[0].id)
        with mock.patch.object(self.app, "_library_open_item") as route:
            self.app._library_open_event()
            route.assert_not_called()
        self.assertIn("unencrypted", library_app.PRIVACY_NOTICE.lower())
        self.assertIn("recovery keys", library_app.PRIVACY_NOTICE.lower())
        labels = [widget for widget in guided_app._descendants(self.app.pages["Library"])
                  if isinstance(widget, ttk.Label)]
        self.assertIn(library_app.PRIVACY_NOTICE, [str(widget.cget("text")) for widget in labels])
        self.assert_no_external_open()

    def test_project_note_rename_and_remove_keep_files_and_note_history(self):
        project = self.app.library_store.create_project("Original generated project")
        archive = self.fixture()
        item = self.app.library_store.register(archive, project_id=project.id)
        before = digest(archive)
        self.app._refresh_library_view()
        self.app.library_project_filter.set(f"{project.name} [{project.id[:8]}]")
        self.select_item(item)
        self.app._library_note_for_project()
        self.assertEqual(self.app.library_tree.selection(), ())
        self.assertIn(project.name, self.app.library_note_target.get())
        self.app.library_note.insert("1.0", "Project-wide generated note")
        self.app._library_add_note()
        self.wait_idle()
        note = next(event for event in self.app.library_store.timeline() if event.kind == "note")
        self.assertEqual(note.project_id, project.id)
        self.assertIsNone(note.item_id)
        self.dialogs["askstring"].return_value = "Renamed generated project"
        self.app._library_rename_project()
        self.wait_idle()
        updated = self.app.library_store.list_projects()[0]
        self.assertEqual(updated.id, project.id)
        self.assertEqual(updated.name, "Renamed generated project")
        self.assertEqual(self.app.library_project_filter.get(), f"{updated.name} [{updated.id[:8]}]")
        self.dialogs["askyesno"].return_value = True
        self.app._library_delete_project()
        self.wait_idle()
        self.assertEqual(self.app.library_store.list_projects(), [])
        self.assertIsNone(self.app.library_store.get_item(item.id).project_id)
        self.assertIn(note.id, [event.id for event in self.app.library_store.timeline()])
        self.assertEqual(digest(archive), before)
        self.assert_no_external_open()

    def test_note_save_does_not_erase_a_new_draft_entered_while_worker_runs(self):
        item = self.app.library_store.register(self.fixture())
        self.select_item(item)
        self.app.library_note.insert("1.0", "Save this first note")
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original_add_note = self.app.library_store.add_note

        def add_note(*args, **kwargs):
            started.set()
            if not release.wait(15):
                raise TimeoutError("Generated note worker was not released")
            return original_add_note(*args, **kwargs)

        with mock.patch.object(self.app.library_store, "add_note", side_effect=add_note):
            self.app._library_add_note()
            self.assertTrue(started.wait(5))
            self.app.library_note.delete("1.0", "end")
            self.app.library_note.insert("1.0", "New unsaved draft")
            release.set()
            self.wait_idle()
        self.assertEqual(self.app.library_note.get("1.0", "end-1c"), "New unsaved draft")
        notes = [event for event in self.app.library_store.timeline(item_id=item.id) if event.kind == "note"]
        self.assertEqual([event.detail for event in notes], ["Save this first note"])

    def search_for(self, query, filenames=True):
        self.app.library_search_query.set(query)
        self.app.library_search_filenames.set(filenames)
        self.app._library_search_start()
        self.wait_idle()
        return list(self.app._library_search_results.values())

    def test_search_finds_other_project_despite_filters_and_opens_project(self):
        first = self.app.library_store.create_project("Current project")
        second = self.app.library_store.create_project("Hidden project")
        self.app._refresh_library_view()
        self.app.library_project_filter.set(f"{first.name} [{first.id[:8]}]")
        self.app.library_query.set("not found")
        hits = self.search_for("Hidden", filenames=False)
        self.assertEqual([h.project_id for h in hits], [second.id])
        self.app.library_search_tree.selection_set("0")
        self.app._library_search_open()
        self.assertEqual(self.app.library_project_filter.get(), f"{second.name} [{second.id[:8]}]")
        self.assertEqual(self.app.library_query.get(), "")
        self.assert_no_external_open()

    def test_search_open_exact_backup_version_and_reject_removed_version(self):
        repository, first, second = self.make_repository()
        self.app.library_store.register(repository)
        hits = self.search_for("work.txt")
        key = next(k for k, hit in self.app._library_search_results.items() if hit.snapshot_id == first.snapshot_id)
        self.app.library_search_tree.selection_set(key)
        self.app._library_search_open()
        self.wait_idle()
        self.assertEqual(self.app.repository_snapshot_tree.selection(), (first.snapshot_id,))
        (repository / "manifests" / (first.manifest_sha256 + ".rtsnap.json")).unlink()
        self.app._go_to("Library")
        self.app._library_search_open()
        self.wait_idle()
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Library"]))
        self.assertIn("exact backup version", self.dialogs["showwarning"].call_args.args[1])
        self.assert_no_external_open()

    def test_search_vault_opens_exact_filename_without_preview_or_restore(self):
        self.app.library_store.register(self.fixture("gmw-vault-1-schema-2.gmw"))
        hits = self.search_for(".txt")
        key, hit = next((k, h) for k, h in self.app._library_search_results.items() if h.kind == "File")
        self.app.library_search_tree.selection_set(key)
        with mock.patch.object(self.app, "_start_vault_preview") as preview:
            self.app._library_search_open()
            self.wait_idle()
        self.assertEqual(self.app._selected_vault_paths(), [hit.member])
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Search Vault"]))
        preview.assert_not_called()
        self.assert_no_external_open()

    def test_search_failure_clears_previous_results_and_cancel_state(self):
        project = self.app.library_store.create_project("Needle project")
        self.assertEqual(len(self.search_for("Needle")), 1)
        with mock.patch.object(library_app.library_search, "search_library", side_effect=RuntimeError("Generated failure")):
            self.search_for("Needle")
        self.assertEqual(self.app._library_search_results, {})
        self.assertIsNone(self.app._library_search_cancel)
        self.assertTrue(self.app.library_search_cancel_button.instate(["disabled"]))
        self.assertIn("Search failed", self.app.library_search_status.get())

    def test_search_cancel_works_while_busy_and_informs_partial_results(self):
        entered = threading.Event()
        def work(_store, _query, **kwargs):
            entered.set()
            self.assertTrue(kwargs["cancel"].wait(10))
            return library_app.library_search.SearchReport((), (), 0, 0, False, True)
        with mock.patch.object(library_app.library_search, "search_library", work):
            self.app.library_search_query.set("anything")
            self.app._library_search_start()
            self.assertTrue(entered.wait(3))
            self.assertTrue(self.app.busy)
            self.assertFalse(self.app.library_search_cancel_button.instate(["disabled"]))
            self.app._library_search_stop()
            self.wait_idle()
        self.assertIn("Cancelled", self.app.library_search_status.get())
        self.assertIsNone(self.app._library_search_cancel)

    def test_note_result_shows_full_note_without_opening_files(self):
        project = self.app.library_store.create_project("Notes")
        self.app.library_store.add_note("Searchable private-ish note", project_id=project.id)
        self.search_for("private-ish", filenames=False)
        self.app.library_search_tree.selection_set("0")
        self.app._library_search_open()
        self.assertIn("Searchable private-ish note", self.dialogs["showinfo"].call_args.args[1])
        self.assert_no_external_open()

    def prepare_restore(self):
        repository, first, second = self.make_repository()
        item = self.app.library_store.register(repository)
        self.search_for("work.txt")
        key = next(k for k, h in self.app._library_search_results.items() if h.snapshot_id == first.snapshot_id)
        self.app.library_search_tree.selection_set(key)
        self.app._library_restore_prepare()
        destination = self.base / "direct-restored"
        self.app.library_restore_destination.set(str(destination))
        return item, first, destination

    def test_restore_confirmation_cancel_writes_nothing(self):
        _, first, destination = self.prepare_restore()
        before = self.app.library_store.timeline()
        self.app._library_restore_start()
        self.assertFalse(self.app.busy)
        self.assertFalse(destination.exists())
        self.assertEqual(before, self.app.library_store.timeline())
        self.assertIn(first.snapshot_id, self.dialogs["askyesno"].call_args.args[1])
        self.assertIn(str(destination), self.dialogs["askyesno"].call_args.args[1])
        self.assert_no_external_open()

    def test_restore_exact_old_file_receipt_and_explicit_reveal(self):
        _, first, destination = self.prepare_restore()
        self.dialogs["askyesno"].return_value = True
        self.app._library_restore_start()
        self.wait_idle()
        self.assertEqual((destination / "work.txt").read_bytes(), b"Generated first revision" + os.linesep.encode())
        self.assertIn(first.snapshot_id, self.app.library_restore_status.get())
        receipt = next(e for e in self.app.library_store.timeline() if e.title == "File restored")
        self.app.library_timeline_tree.selection_set(receipt.id)
        self.app._library_open_event()
        self.assertEqual(self.dialogs["showinfo"].call_args.args[0], "Restore receipt")
        self.assert_no_external_open()
        self.app._library_restore_show()
        self.reveal.assert_called_once_with(destination / "work.txt")
        self.startfile.assert_not_called()

    def test_restore_receipt_failure_reports_safe_file_not_failed_restore(self):
        _, _, destination = self.prepare_restore()
        self.dialogs["askyesno"].return_value = True
        with mock.patch.object(self.app.library_store, "record_restored", side_effect=library.LibraryError("locked")):
            self.app._library_restore_start()
            self.wait_idle()
        self.assertTrue((destination / "work.txt").is_file())
        self.assertIn("file is safe", self.app.library_restore_status.get())
        self.assertIn("Do not restore it again", self.app.library_restore_status.get())
        self.assertEqual(self.app._library_restored_path, destination / "work.txt")
        self.assert_no_external_open()

    def test_restore_existing_destination_refused_before_confirmation(self):
        _, _, destination = self.prepare_restore()
        destination.mkdir()
        self.app._library_restore_start()
        self.dialogs["askyesno"].assert_not_called()
        self.assertFalse(self.app.busy)
        self.assertEqual(list(destination.iterdir()), [])

    def test_restore_missing_snapshot_never_falls_back_to_latest(self):
        item, first, destination = self.prepare_restore()
        (Path(item.path) / "manifests" / (first.manifest_sha256 + ".rtsnap.json")).unlink()
        self.dialogs["askyesno"].return_value = True
        self.app._library_restore_start()
        self.wait_idle()
        self.assertFalse(destination.exists())
        self.assertIsNone(self.app._library_restored_path)
        self.assertIn("did not complete", self.app.library_restore_status.get())
        self.assert_no_external_open()

    def test_restore_plain_archive_guides_to_open_result(self):
        self.app.library_store.register(self.fixture())
        self.search_for(".txt")
        key = next(k for k, h in self.app._library_search_results.items() if h.kind == "File")
        self.app.library_search_tree.selection_set(key)
        self.app._library_restore_prepare()
        self.assertIsNone(self.app._library_restore_hit)
        self.assertIn("Open result", self.dialogs["showinfo"].call_args.args[1])
        self.assert_no_external_open()

    def test_restore_parent_picker_and_back_do_not_restore(self):
        self.dialogs["askdirectory"].return_value = str(self.base)
        self.app._library_restore_choose_destination()
        proposed = Path(self.app.library_restore_destination.get())
        self.assertEqual(proposed.parent, self.base)
        self.assertFalse(proposed.exists())
        self.app._library_restore_show()
        self.app._library_restore_back()
        self.assertEqual(self.app.library_modes.select(), str(self.app.library_search_form))
        self.assert_no_external_open()

    def test_health_confirmation_cancel_has_no_side_effects(self):
        self.app._library_health_start()
        self.assertFalse(self.catalog.exists())
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app._library_health_results, {})
        self.assert_no_external_open()

    def test_health_success_has_separate_columns_and_opens_receipt_not_storage(self):
        repository, _, _ = self.make_repository()
        item = self.app.library_store.register(repository)
        self.dialogs["askyesno"].return_value = True
        self.app._library_health_start()
        self.wait_idle()
        result = self.app._library_health_results[item.id]
        self.assertEqual(result.status, "Verified", result.detail)
        row = self.app.library_health_tree.item(item.id, "values")
        self.assertEqual(row[1:3], ("Located", "Verified"))
        receipt = next(e for e in self.app.library_store.timeline() if e.title == "Library health check")
        self.app.library_timeline_tree.selection_set(receipt.id)
        self.app._library_open_event()
        self.assertEqual(self.dialogs["showinfo"].call_args.args[0], "Health check receipt")
        self.assert_no_external_open()

    def test_health_failure_does_not_keep_previous_green_results(self):
        repository, _, _ = self.make_repository()
        item = self.app.library_store.register(repository)
        self.dialogs["askyesno"].return_value = True
        self.app._library_health_start()
        self.wait_idle()
        self.assertEqual(self.app._library_health_results[item.id].status, "Verified")
        with mock.patch.object(library_app.library_health, "check_library", side_effect=OSError("Generated failure")):
            self.app._library_health_start()
            self.wait_idle()
        self.assertEqual(self.app._library_health_results, {})
        self.assertIn("did not complete", self.app.library_health_status.get())

    def test_health_cancel_remains_available_while_busy(self):
        started = threading.Event()
        self.dialogs["askyesno"].return_value = True
        def work(store, **kwargs):
            started.set()
            if not kwargs["cancel"].wait(10):
                raise TimeoutError("Cancellation not requested")
            return library_app.library_health.HealthReport((), cancelled=True)
        with mock.patch.object(library_app.library_health, "check_library", work):
            self.app._library_health_start()
            self.assertTrue(started.wait(5))
            self.assertFalse(self.app.library_health_cancel_button.instate(["disabled"]))
            self.app._library_health_stop()
            self.wait_idle()
        self.assertIn("Cancelled", self.app.library_health_status.get())
        self.assertTrue(self.app.library_health_cancel_button.instate(["disabled"]))
        self.assertIsNone(self.app._library_health_cancel)

    def test_health_receipt_failure_is_visible_and_result_remains_available(self):
        repository, _, _ = self.make_repository()
        item = self.app.library_store.register(repository)
        self.dialogs["askyesno"].return_value = True
        with mock.patch.object(self.app.library_store, "record_health", side_effect=library.LibraryError("Locked")):
            self.app._library_health_start()
            self.wait_idle()
        self.assertEqual(self.app._library_health_results[item.id].status, "Verified")
        self.assertIn("could not be saved", self.app.library_health_status.get())
        self.app.library_health_tree.selection_set(item.id)
        self.app._library_health_selected()
        self.assertIn("NOT saved", self.app.library_health_details.get())

    def test_health_selected_scope_and_restore_navigation(self):
        repository, _, _ = self.make_repository()
        item = self.app.library_store.register(repository)
        ignored = self.app.library_store.register(self.fixture())
        self.app._refresh_library_view()
        self.app.library_health_tree.selection_set(item.id)
        self.dialogs["askyesno"].return_value = True
        self.app._library_health_selected_start()
        self.wait_idle()
        self.assertEqual(set(self.app._library_health_results), {item.id})
        self.assertEqual(self.app.library_health_tree.item(ignored.id, "values")[2], "Not checked")
        self.app._library_health_restore()
        self.assertEqual(self.app.library_modes.select(), str(self.app.library_search_form))
        self.assert_no_external_open()

    def test_busy_and_tutorial_direct_callbacks_never_bypass_the_guards(self):
        callbacks = (
            "_library_add_file", "_library_add_repository", "_library_new_project",
            "_library_add_note", "_library_open_selected", "_library_open_event",
            "_library_relink_selected", "_library_remove_selected", "_library_assign_project",
            "_library_rename_project", "_library_delete_project", "_library_note_for_project",
            "_library_refresh_selected",
            "_library_store_open", "_library_store_back", "_library_store_start",
            "_library_store_choose_source", "_library_store_choose_destination",
            "_library_store_selected_backup",
            "_library_search_start", "_library_search_open", "_library_search_clear",
            "_library_restore_prepare", "_library_restore_start", "_library_restore_show",
            "_library_restore_choose_destination", "_library_restore_back",
            "_library_health_start", "_library_health_selected_start", "_library_health_selected",
            "_library_health_locate", "_library_health_open", "_library_health_restore",
        )
        archive = self.fixture()
        item = self.app.library_store.register(archive)
        self.select_item(item)
        before = self.app.library_store.timeline()
        for guard in ("busy", "tutorial"):
            with self.subTest(guard=guard):
                for dialog in self.dialogs.values():
                    dialog.reset_mock()
                if guard == "busy":
                    self.app.busy = True
                else:
                    self.app.start_tutorial("vault-search")
                try:
                    for name in callbacks:
                        getattr(self.app, name)()
                    self.root.update_idletasks()
                    for name, dialog in self.dialogs.items():
                        self.assertEqual(dialog.call_count, 0, f"{guard}: unexpected {name}")
                    self.assertEqual(self.app.library_store.timeline(), before)
                finally:
                    if guard == "busy":
                        self.app.busy = False
                    else:
                        self.app.tutorial_exit()
        self.assert_no_external_open()

    def test_library_buttons_stay_disabled_during_real_worker_then_restore(self):
        self.app._go_to("Library")
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def work():
            started.set()
            if not release.wait(15):
                raise TimeoutError("Generated worker was not released")
            return "generated result"

        self.app._run_task("Checking generated Library test...", work, lambda _result: None)
        self.assertTrue(started.wait(5))
        self.assertTrue(self.app.busy)
        buttons = [button for button in self.app.action_buttons
                   if self.app._inside(button, self.app.pages["Library"])]
        self.assertGreater(len(buttons), 4)
        self.app._refresh_library_view()
        self.root.update_idletasks()
        for button in buttons:
            self.assertIn("disabled", button.state(), button.cget("text"))
        release.set()
        self.wait_idle()
        self.assertTrue(any("disabled" not in button.state() for button in buttons))
        self.dialogs["showerror"].assert_not_called()

    def test_all_five_tutorials_can_exit_back_to_library_without_registering_samples(self):
        self.app._go_to("Library")
        for lesson in tutorials.TUTORIALS:
            if not lesson.available:
                continue
            with self.subTest(lesson=lesson.id):
                self.assertTrue(self.app.start_tutorial(lesson.id))
                self.assertFalse(self.app._go_to("Library"))
                self.assertTrue(self.app._go_to(self.app._tutorial_workspace))
                self.app.tutorial_exit()
                self.root.update_idletasks()
                self.assertFalse(self.app.tutorial_active)
                self.assertEqual(self.app.tabs.select(), str(self.app.pages["Library"]))
                self.assertEqual(self.app.library_store.list_items(), [])
        self.assert_no_external_open()

    def test_library_scroll_region_covers_compact_and_large_viewports(self):
        scroller = self.app.page_scrollers["Library"]
        for width, height in ((420, 280), (850, 620)):
            with self.subTest(viewport=(width, height)), mock.patch.object(
                scroller.canvas, "winfo_width", return_value=width,
            ), mock.patch.object(scroller.canvas, "winfo_height", return_value=height):
                scroller._layout()
                self.root.update_idletasks()
                scroller._layout()
                bounds = scroller.canvas.bbox("all")
                self.assertIsNotNone(bounds)
                self.assertGreaterEqual(bounds[2], max(width, scroller.content.winfo_reqwidth()))
                self.assertGreaterEqual(bounds[3], max(height, scroller.content.winfo_reqheight()))
                for label, maximum in scroller._labels:
                    self.assertLessEqual(int(label.cget("wraplength")), maximum)

    @unittest.skipUnless(os.name == "nt", "Windows Tk high-DPI geometry check")
    def test_library_controls_remain_reachable_with_long_labels_and_high_dpi(self):
        for scaling in (1.333, 2.0, 2.667):
            with self.subTest(tk_scaling=scaling):
                window = tk.Tk()
                window.withdraw()
                log = diagnostics.LocalDiagnostics(self.base / f"geometry-log-{scaling}")
                try:
                    window.tk.call("tk", "scaling", scaling)
                    window.attributes("-alpha", 0.0)
                    app = library_app.LibraryRatTrapApp(
                        window, diagnostic_log=log,
                        library_path=self.base / f"geometry-library-{scaling}.sqlite3",
                    )
                    project = app.library_store.create_project("Long Unicode 日本 project " * 7)
                    item = app.library_store.register(
                        self.fixture(target=f"geometry-{scaling}.gmw"),
                        label="A deliberately long archive label " * 7,
                        project_id=project.id,
                    )
                    app._refresh_library_view()
                    app._go_to("Library")
                    app.library_tree.selection_set(item.id)
                    window.geometry("960x640+20000+20000")
                    window.deiconify()
                    window.update()
                    scroller = app.page_scrollers["Library"]
                    canvas = scroller.canvas
                    self.assertGreater(canvas.winfo_height(), 120)
                    self.assertGreater(canvas.winfo_width(), 280)
                    buttons = [button for button in app.action_buttons
                               if app._inside(button, scroller.content)]
                    self.assertGreater(len(buttons), 4)
                    for button in buttons:
                        for mode in app.library_modes.tabs():
                            if app._inside(button, window.nametowidget(mode)):
                                app.library_modes.select(mode)
                                window.update_idletasks()
                        region = canvas.bbox("all")
                        x = button.winfo_rootx() - scroller.content.winfo_rootx()
                        y = button.winfo_rooty() - scroller.content.winfo_rooty()
                        canvas.xview_moveto(x / max(1, region[2]))
                        canvas.yview_moveto(y / max(1, region[3]))
                        window.update_idletasks()
                        left = button.winfo_rootx() - canvas.winfo_rootx()
                        top = button.winfo_rooty() - canvas.winfo_rooty()
                        context = f"scale={scaling}, button={button.cget('text')}, {left=}, {top=}"
                        self.assertTrue(button.winfo_ismapped(), context)
                        self.assertGreaterEqual(left, -1, context)
                        self.assertGreaterEqual(top, -1, context)
                        self.assertLessEqual(left + button.winfo_width(), canvas.winfo_width() + 1, context)
                        self.assertLessEqual(top + button.winfo_height(), canvas.winfo_height() + 1, context)
                finally:
                    for timer in window.tk.call("after", "info"):
                        window.after_cancel(timer)
                    window.withdraw()
                    window.destroy()
                    log.close()


if __name__ == "__main__":
    unittest.main()
