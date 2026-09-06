"""Sample-only backup-history lessons on internal, hidden Tk controls."""

import hashlib
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest import mock

from rat_trap import desktop_preview2, diagnostics, guided_app, history_tutorials, tutorials, windows_app


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_snapshot(path):
    return {item.relative_to(path).as_posix(): (digest(item), item.stat().st_mtime_ns)
            for item in path.rglob("*") if item.is_file()}


class HistoryGuidedTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-history-guided-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.log = diagnostics.LocalDiagnostics(self.base / "diagnostics")
        self.addCleanup(self.log.close)
        self.app = guided_app.GuidedRatTrapApp(self.root, diagnostic_log=self.log)
        self.root.update_idletasks()
        create_practice = history_tutorials.create_practice
        self.enterContext(mock.patch.object(
            history_tutorials, "create_practice", side_effect=lambda parent=None: create_practice(self.base)
        ))
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
        self.opened = self.enterContext(mock.patch.object(os, "startfile")) if hasattr(os, "startfile") else None
        self.releases = []
        self.retained_demos = []

    def tearDown(self):
        for release in self.releases:
            release.set()
        if self.app.busy:
            self.wait_idle()
        self.app.tutorial_exit()
        for demo in self.retained_demos:
            demo.cleanup()
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)

    def wait_idle(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.root.update()
        self.assertFalse(self.app.busy, "Backup-history practice worker did not finish")

    def blocked(self, operation):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def work(*args, **kwargs):
            started.set()
            if not release.wait(20):
                raise TimeoutError("Generated test worker was not released")
            return operation(*args, **kwargs)

        return started, release, work

    def load(self):
        self.assertTrue(self.app.start_tutorial("history"))
        self.assertEqual(self.app.tutorial_step, "navigate")
        self.app.nav_buttons["Backups & history"].invoke()
        self.assertEqual(self.app.tutorial_step, "load")
        self.app.history_source_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "repository")
        self.retained_demos.append(self.app.tutorial_demo)
        return self.app.tutorial_demo

    def reach_first(self):
        demo = self.load()
        self.app.history_repository_button.invoke()
        self.assertEqual(self.app.tutorial_step, "first")
        return demo

    def reach_change(self):
        demo = self.reach_first()
        self.app.history_backup_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "change")
        return demo

    def reach_second(self):
        demo = self.reach_change()
        self.app.history_change_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "second")
        return demo

    def reach_history(self):
        demo = self.reach_second()
        self.app.history_backup_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "history")
        return demo

    def reach_select(self):
        demo = self.reach_history()
        self.app.history_refresh_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "select")
        return demo

    def choose_older(self, demo):
        self.app.repository_snapshot_tree.selection_set(demo.first_snapshot.snapshot_id)
        self.app.repository_snapshot_tree.focus(demo.first_snapshot.snapshot_id)
        self.root.update()
        self.assertTrue(self.app.tutorial_next())
        self.assertEqual(self.app.tutorial_step, "destination")

    def reach_restore(self):
        demo = self.reach_select()
        self.choose_older(demo)
        self.app.history_destination_button.invoke()
        self.assertEqual(self.app.tutorial_step, "restore")
        return demo

    def reach_verify(self):
        demo = self.reach_restore()
        self.app.history_restore_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "verify")
        return demo

    def assert_no_external_actions(self):
        for name, dialog in self.dialogs.items():
            if name != "showerror":
                dialog.assert_not_called()
        self.reveal.assert_not_called()
        if self.opened is not None:
            self.opened.assert_not_called()

    def tree_snapshot(self, tree):
        return {
            "rows": [(iid, tree.item(iid)) for iid in tree.get_children()],
            "selection": tree.selection(), "focus": tree.focus(),
            "displaycolumns": tree.cget("displaycolumns"), "height": tree.cget("height"),
            "style": tree.cget("style"),
            "columns": {name: tree.column(name) for name in tree.cget("columns")},
            "xview": tree.xview(), "yview": tree.yview(),
        }

    def snapshot(self):
        names = ("repository_path", "repository_source", "repository_label", "repository_search",
                 "repository_status", "repository_keep_last", "repository_keep_daily", "repository_keep_weekly",
                 "repository_keep_monthly", "history_restore_destination", "status_text", "activity_title",
                 "activity_elapsed", "activity_hint", "result_path", "result_summary")
        buttons = ("history_source_button", "history_repository_button", "history_backup_button",
                   "history_refresh_button", "history_restore_button", "repository_pin_button")
        return {
            "variables": {name: getattr(self.app, name).get() for name in names},
            "page": self.app.tabs.select(), "mode": self.app.repository_result_tabs.select(),
            "loaded": self.app.repository_loaded_path,
            "snapshots": dict(self.app.repository_snapshots),
            "history_ids": dict(self.app.repository_history_snapshot_ids),
            "snapshot_tree": self.tree_snapshot(self.app.repository_snapshot_tree),
            "history_tree": self.tree_snapshot(self.app.repository_history_tree),
            "output": self.app.last_output, "picker": self.app._picker_directory,
            "buttons": {name: getattr(self.app, name).cget("text") for name in buttons},
            "completion": bool(self.app.completion_frame.winfo_manager()),
        }

    def seed_state(self):
        fixture = self.base / "unrelated generated fixture.txt"
        fixture.write_bytes(b"Generated unrelated file; leave unchanged")
        for index, name in enumerate(("repository_path", "repository_source", "history_restore_destination")):
            getattr(self.app, name).set(f'"{self.base / ("prior chosen path " + str(index))}"')
        self.app.repository_label.set("Prior backup label")
        self.app.repository_search.set("Prior searched path")
        for index, name in enumerate(("repository_keep_last", "repository_keep_daily", "repository_keep_weekly", "repository_keep_monthly")):
            getattr(self.app, name).set(str(21 + index))
        self.app.repository_loaded_path = self.base / "prior repository"
        self.app.repository_snapshots = {"prior-snapshot": SimpleNamespace(snapshot_id="prior-snapshot", pinned=True)}
        self.app.repository_history_snapshot_ids = {"prior-history": "prior-snapshot"}
        for tree, iid in ((self.app.repository_snapshot_tree, "prior-snapshot"), (self.app.repository_history_tree, "prior-history")):
            tree.insert("", "end", iid=iid, text="Prior row", values=("Prior date", "Prior label", "Prior source"), tags=("prior",))
            tree.selection_set(iid)
            tree.focus(iid)
        self.root.update()
        self.app.repository_status.set("Prior repository status")
        self.app._picker_directory = self.base
        self.app._publish_completion(desktop_preview2.CompletedOutput(fixture, "file", "Prior result", "Keep this result"))
        self.app.status_text.set("Prior status")
        self.app.activity_title.set("Prior activity")
        self.app.activity_hint.set("Prior hint")
        # Apply every seeded field and completion panel before mapping tables.
        # Even normal navigation stretches native columns after a late status
        # change; the baseline must represent the settled, user-visible layout.
        self.root.attributes("-alpha", 0.0)
        self.root.geometry("1100x760+20000+20000")
        self.app._go_to("Backups & history")
        self.root.deiconify()
        for mode in (0, 1):
            self.app.repository_result_tabs.select(mode)
            self.root.update()
        self.app._go_to("Inspect / export")
        self.root.update()
        return fixture, self.snapshot()

    def test_two_real_snapshots_and_older_restore_preserve_current_contents_and_prior_ui(self):
        fixture, before = self.seed_state()
        original = digest(fixture)
        engine = windows_app.repository_engine
        with mock.patch.object(engine, "create_snapshot", wraps=engine.create_snapshot) as backup:
            demo = self.reach_select()
        self.assertEqual(backup.call_count, 2)
        self.assertEqual(demo.source_version, 2)
        self.assertEqual(len(demo.history), 2)
        self.assertNotEqual(demo.first_snapshot.snapshot_id, demo.second_snapshot.snapshot_id)
        self.assertEqual(demo.second_snapshot.parent_snapshot_id, demo.first_snapshot.snapshot_id)
        self.assertEqual([item.snapshot_id for item in demo.history],
                         [demo.second_snapshot.snapshot_id, demo.first_snapshot.snapshot_id])
        self.assertEqual(self.app.repository_snapshot_tree.get_children(),
                         (demo.second_snapshot.snapshot_id, demo.first_snapshot.snapshot_id))
        self.choose_older(demo)
        self.app.history_destination_button.invoke()
        self.assertEqual(self.app.history_restore_destination.get(), str(demo.restored))
        self.assertFalse(demo.restored.exists())
        with mock.patch.object(engine, "restore_snapshot", wraps=engine.restore_snapshot) as restore:
            self.app.history_restore_button.invoke()
            self.wait_idle()
        restore.assert_called_once()
        self.assertEqual(restore.call_args.args[1], demo.first_snapshot.snapshot_id)
        self.assertNotEqual(demo.restored, demo.source)
        self.assertNotEqual(demo.restored, demo.repository)
        self.assertFalse(self.app.tutorial_next())
        for name, contents in history_tutorials.FIRST_FILES.items():
            self.assertEqual((demo.restored / name).read_bytes(), contents)
        for name, contents in history_tutorials.SECOND_FILES.items():
            self.assertEqual((demo.source / name).read_bytes(), contents)
        self.app.history_verify_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "finish")
        self.assertIn("sha-256", self.app.history_result.get("1.0", "end-1c").lower())
        self.assertTrue(demo.source_is_intact())
        self.assertTrue(demo.repository_is_intact())
        self.assert_no_external_actions()
        self.app.tutorial_next_button.invoke()
        self.root.update()
        self.assertFalse(self.app.tutorial_active)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(digest(fixture), original)
        self.assertFalse(demo.root.exists())

    def test_idle_exit_restores_both_repository_tables_and_all_path_and_retention_fields(self):
        fixture, before = self.seed_state()
        demo = self.reach_select()
        self.app.tutorial_exit_button.invoke()
        self.root.update()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(fixture.exists())
        self.assertFalse(demo.root.exists())

    def test_exit_returns_to_already_visible_history_search_tab_without_changing_columns(self):
        self.seed_state()
        self.root.attributes("-alpha", 0.0)
        self.root.geometry("1100x760+20000+20000")
        self.app._go_to("Backups & history")
        self.root.deiconify()
        self.root.update()
        self.assertTrue(self.app.repository_history_tree.winfo_ismapped())
        before = self.snapshot()
        demo = self.reach_select()
        self.app.tutorial_exit()
        self.root.update()
        self.assertTrue(self.app.repository_history_tree.winfo_ismapped())
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(demo.root.exists())

    def test_normal_pick_and_backup_callbacks_still_delegate_outside_tutorial(self):
        for method in ("_choose_repository_source", "_choose_repository", "_start_repository_snapshot",
                       "_start_repository_refresh", "_start_repository_restore"):
            with self.subTest(method=method), mock.patch.object(desktop_preview2.DesktopPreview2App, method) as original:
                getattr(self.app, method)()
                original.assert_called_once()

    def test_catalog_defines_complete_immutable_history_steps(self):
        self.assertEqual([step.id for step in tutorials.STEPS_BY_ID["history"]], [
            "navigate", "load", "repository", "first", "change", "second", "history", "select",
            "destination", "restore", "verify", "finish",
        ])
        for step in tutorials.STEPS_BY_ID["history"]:
            for field in ("title", "where", "action", "why", "expect"):
                self.assertTrue(getattr(step, field).strip(), (step.id, field))

    def test_every_step_enables_only_current_control_and_coach_actions(self):
        self.app.start_tutorial("history")
        self.app._go_to("Backups & history")
        for step in tutorials.STEPS_BY_ID["history"]:
            with self.subTest(step=step.id):
                self.app._set_tutorial_step(step.id)
                for widget in guided_app._descendants(self.root):
                    if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Entry, ttk.Combobox, ttk.Treeview)) and not widget.instate(["disabled"]):
                        self.assertIn(widget, (self.app.tutorial_target, self.app.tutorial_back_button,
                                               self.app.tutorial_next_button, self.app.tutorial_exit_button))
                for entry in self.app.path_entries.values():
                    before = entry.get()
                    entry.insert("end", "forbidden typed edit")
                    self.assertEqual(entry.get(), before)

    def test_nested_tabs_and_unrelated_normal_callbacks_cannot_escape_lesson(self):
        self.load()
        selected, page = self.app.repository_result_tabs.select(), self.app.tabs.select()
        self.app.repository_result_tabs.select(1)
        self.app._show_repository_snapshots()
        self.app._open_repository_search_snapshot()
        self.app._home_restore()
        self.app._shortcut_page("Home")
        self.app.tabs.select(self.app.pages["Extract archive"])
        self.app.apply_launch_request(windows_app.LaunchRequest("open-archive", self.base / "unrelated.gmw"))
        for action in ("_start_repository_initialize", "_start_repository_incomplete_jobs", "_start_repository_issues",
                       "_start_repository_search", "_start_repository_pin_toggle", "_start_repository_export",
                       "_start_repository_retention_preview", "_start_create", "_start_extract", "_choose_source",
                       "_choose_seal_source", "_start_seal_file", "_open_result", "_show_result_folder"):
            getattr(self.app, action)()
        self.app._start_repository_verify(full=True)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tabs.select(), page)
        self.assertEqual(self.app.repository_result_tabs.select(), selected)
        self.assertEqual(self.app.tutorial_step, "repository")
        self.assert_no_external_actions()

    def test_repository_nested_tabs_are_gated_in_other_tutorials_too(self):
        self.app.repository_result_tabs.select(1)
        self.app.start_tutorial("compress")
        selected = self.app.repository_result_tabs.select()
        self.app.repository_result_tabs.select(0)
        self.app._show_repository_snapshots()
        self.assertEqual(self.app.repository_result_tabs.select(), selected)
        self.assertEqual(self.app.tutorial_step, "navigate")

    def test_newest_or_no_snapshot_selection_cannot_advance_or_restore(self):
        demo = self.reach_select()
        tree = self.app.repository_snapshot_tree
        for selection in ((), (demo.second_snapshot.snapshot_id,)):
            with self.subTest(selection=selection):
                tree.selection_set(selection)
                self.root.update()
                self.assertFalse(self.app.tutorial_next())
                with mock.patch.object(windows_app.repository_engine, "restore_snapshot") as restore:
                    self.app._start_repository_restore()
                restore.assert_not_called()
                self.assertEqual(self.app.tutorial_step, "select")
                self.assertFalse(demo.restored.exists())
        self.choose_older(demo)

    def test_changed_repository_or_source_selection_refused_before_backup_engine(self):
        demo = self.reach_first()
        for field in ("repository_path", "repository_source"):
            with self.subTest(field=field):
                original = getattr(self.app, field).get()
                getattr(self.app, field).set(str(self.base / "never selected personal fixture"))
                with mock.patch.object(windows_app.repository_engine, "create_snapshot") as backup:
                    self.app.history_backup_button.invoke()
                    self.wait_idle()
                backup.assert_not_called()
                self.assertEqual(self.app.tutorial_step, "first")
                self.assertIsNone(demo.first_snapshot)
                getattr(self.app, field).set(original)
        self.assert_no_external_actions()

    def test_changed_source_bytes_refused_and_preserved_on_exit(self):
        demo = self.reach_first()
        source = demo.source / history_tutorials.CHANGED_NAME
        source.write_bytes(b"User-added modification to generated fixture")
        with mock.patch.object(windows_app.repository_engine, "create_snapshot") as backup:
            self.app.history_backup_button.invoke()
            self.wait_idle()
        backup.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "first")
        self.app.tutorial_exit()
        self.assertEqual(source.read_bytes(), b"User-added modification to generated fixture")

    def test_added_hard_link_to_source_cannot_be_backed_up(self):
        demo = self.reach_first()
        source = demo.source / history_tutorials.CHANGED_NAME
        link = self.base / "generated-hardlink.txt"
        os.link(source, link)
        try:
            with mock.patch.object(windows_app.repository_engine, "create_snapshot") as backup:
                self.app.history_backup_button.invoke()
                self.wait_idle()
            backup.assert_not_called()
            self.assertEqual(self.app.tutorial_step, "first")
        finally:
            link.unlink()

    def test_changed_restore_destination_or_snapshot_selection_cannot_restore(self):
        demo = self.reach_restore()
        original = self.app.history_restore_destination.get()
        self.app.history_restore_destination.set(str(self.base / "unrelated restore fixture"))
        with mock.patch.object(windows_app.repository_engine, "restore_snapshot") as restore:
            self.app.history_restore_button.invoke()
            self.wait_idle()
        restore.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "restore")
        self.app.history_restore_destination.set(original)
        self.app.repository_snapshot_tree.selection_set(demo.second_snapshot.snapshot_id)
        self.root.update()
        with mock.patch.object(windows_app.repository_engine, "restore_snapshot") as restore:
            self.app.history_restore_button.invoke()
            self.wait_idle()
        restore.assert_not_called()
        self.assertFalse(demo.restored.exists())
        self.assert_no_external_actions()

    def test_changed_repository_file_prevents_history_open_and_is_preserved(self):
        demo = self.reach_history()
        metadata = demo.repository / "repository.json"
        metadata.write_bytes(b"Modified generated repository metadata")
        with mock.patch.object(windows_app.repository_engine, "list_snapshots") as history:
            self.app.history_refresh_button.invoke()
            self.wait_idle()
        history.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "history")
        self.app.tutorial_exit()
        self.assertEqual(metadata.read_bytes(), b"Modified generated repository metadata")

    def test_verification_rejects_changed_restored_copy_without_claiming_completion(self):
        demo = self.reach_verify()
        restored = demo.restored / history_tutorials.CHANGED_NAME
        restored.write_bytes(b"Changed generated restored copy")
        self.app.history_verify_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "verify")
        self.assertFalse(self.app.tutorial_next())
        self.assertIn("attention", self.app.history_result.get("1.0", "end-1c").lower())
        self.app.tutorial_exit()
        self.assertEqual(restored.read_bytes(), b"Changed generated restored copy")

    def test_verification_also_checks_current_source_was_not_replaced_by_old_copy(self):
        demo = self.reach_verify()
        source = demo.source / history_tutorials.CHANGED_NAME
        source.write_bytes(history_tutorials.FIRST_FILES[history_tutorials.CHANGED_NAME])
        self.app.history_verify_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "verify")
        self.assertFalse(self.app.tutorial_next())
        self.assertIn("attention", self.app.history_result.get("1.0", "end-1c").lower())
        self.app.tutorial_exit()
        self.assertEqual(source.read_bytes(), history_tutorials.FIRST_FILES[history_tutorials.CHANGED_NAME])

    def test_first_backup_replay_does_not_create_another_snapshot(self):
        demo = self.reach_change()
        before = file_snapshot(demo.repository)
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "first")
        with mock.patch.object(windows_app.repository_engine, "create_snapshot") as backup:
            self.app.history_backup_button.invoke()
            self.wait_idle()
        backup.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "change")
        self.assertEqual(file_snapshot(demo.repository), before)

    def test_change_and_second_backup_replays_never_rewrite_source_or_add_snapshot(self):
        demo = self.reach_history()
        before_source, before_repository = file_snapshot(demo.source), file_snapshot(demo.repository)
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "second")
        with mock.patch.object(windows_app.repository_engine, "create_snapshot") as backup:
            self.app.history_backup_button.invoke()
            self.wait_idle()
        backup.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "history")
        self.app.tutorial_back()
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "change")
        with mock.patch.object(history_tutorials.HistoryPractice, "change_sample") as change:
            self.app.history_change_button.invoke()
            self.wait_idle()
        change.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "second")
        self.assertEqual(file_snapshot(demo.source), before_source)
        self.assertEqual(file_snapshot(demo.repository), before_repository)

    def test_restore_back_replay_never_overwrites_the_restored_files(self):
        demo = self.reach_verify()
        before = file_snapshot(demo.restored)
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "restore")
        with mock.patch.object(windows_app.repository_engine, "restore_snapshot") as restore:
            self.app.history_restore_button.invoke()
            self.wait_idle()
        restore.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "verify")
        self.assertEqual(file_snapshot(demo.restored), before)

    def test_busy_exit_waits_for_first_backup_then_cleans_and_restores_prior_state(self):
        fixture, before = self.seed_state()
        demo = self.reach_first()
        started, release, work = self.blocked(windows_app.repository_engine.create_snapshot)
        with mock.patch.object(windows_app.repository_engine, "create_snapshot", side_effect=work):
            self.app.history_backup_button.invoke()
            self.assertTrue(started.wait(5))
            self.app.tutorial_exit()
            self.assertTrue(self.app.busy)
            self.assertTrue(self.app.tutorial_active)
            self.assertTrue(demo.source.exists())
            self.assertFalse(self.app.tutorial_exit_button.instate(["disabled"]))
            self.assertFalse(self.app.start_tutorial("compress"))
            release.set()
            self.wait_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(fixture.exists())

    def test_busy_back_during_second_backup_returns_to_change_and_replays_read_only(self):
        demo = self.reach_second()
        started, release, work = self.blocked(windows_app.repository_engine.create_snapshot)
        with mock.patch.object(windows_app.repository_engine, "create_snapshot", side_effect=work):
            self.app.history_backup_button.invoke()
            self.assertTrue(started.wait(5))
            self.app.tutorial_back()
            self.assertTrue(self.app.busy)
            self.assertTrue(demo.source.exists())
            release.set()
            self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "change")
        self.assertIsNotNone(demo.second_snapshot)
        self.app.history_change_button.invoke()
        self.wait_idle()
        with mock.patch.object(windows_app.repository_engine, "create_snapshot") as backup:
            self.app.history_backup_button.invoke()
            self.wait_idle()
        backup.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "history")

    def test_busy_exit_during_restore_keeps_backup_until_worker_finishes(self):
        demo = self.reach_restore()
        started, release, work = self.blocked(windows_app.repository_engine.restore_snapshot)
        with mock.patch.object(windows_app.repository_engine, "restore_snapshot", side_effect=work):
            self.app.history_restore_button.invoke()
            self.assertTrue(started.wait(5))
            self.app.tutorial_exit()
            self.assertTrue(self.app.busy)
            self.assertTrue(demo.repository.exists())
            release.set()
            self.wait_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())

    def test_busy_exit_during_verification_cannot_publish_late_success(self):
        demo = self.reach_verify()
        started, release, work = self.blocked(history_tutorials.HistoryPractice.verify_restored)
        with mock.patch.object(history_tutorials.HistoryPractice, "verify_restored", autospec=True, side_effect=work):
            self.app.history_verify_button.invoke()
            self.assertTrue(started.wait(5))
            self.app.tutorial_exit()
            self.assertTrue(self.app.busy)
            self.assertTrue(demo.restored.exists())
            release.set()
            self.wait_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())

    def test_thread_setup_failure_leaves_only_retry_and_coach_actions(self):
        demo = self.reach_first()
        with mock.patch.object(windows_app.threading.Thread, "start", side_effect=RuntimeError("Generated setup failure")):
            self.app.history_backup_button.invoke()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tutorial_step, "first")
        self.assertIsNone(demo.first_snapshot)
        self.assertFalse(self.app.history_backup_button.instate(["disabled"]))
        self.assertTrue(self.app.history_source_button.instate(["disabled"]))
        self.assertTrue(self.app.nav_buttons["Home"].instate(["disabled"]))
        self.dialogs["showerror"].assert_called_once()

    def test_late_load_cleans_old_sample_without_overwriting_new_lesson(self):
        self.app.start_tutorial("history")
        self.app._go_to("Backups & history")
        with mock.patch.object(desktop_preview2.DesktopPreview2App, "_run_task") as run:
            self.app.history_source_button.invoke()
        old_done = run.call_args.args[2]
        self.app.tutorial_exit()
        self.app.start_tutorial("restore")
        self.app._go_to("Extract archive")
        token = self.app.tutorial_session_token
        stale = history_tutorials.create_practice()
        self.retained_demos.append(stale)
        old_done(stale)
        self.assertIs(self.app.tutorial_session_token, token)
        self.assertEqual(self.app.tutorial_id, "restore")
        self.assertEqual(self.app.tutorial_step, "load")
        self.assertIsNone(self.app.tutorial_demo)
        self.assertFalse(stale.root.exists())


class HistoryLessonGeometryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Tk high-DPI exact-state check")
    def test_exact_prior_state_returns_after_exit_and_finish_at_each_scale(self):
        native_tk = tk.Tk
        for scaling in (1.333, 2.0, 2.667):
            for finish in (False, True):
                with self.subTest(tk_scaling=scaling, finish=finish):
                    def scaled_root():
                        window = native_tk()
                        window.withdraw()
                        window.tk.call("tk", "scaling", scaling)
                        return window

                    case = HistoryGuidedTests("test_idle_exit_restores_both_repository_tables_and_all_path_and_retention_fields")
                    with mock.patch.object(tk, "Tk", side_effect=scaled_root):
                        case.setUp()
                    try:
                        fixture, before = case.seed_state()
                        contents = fixture.read_bytes()
                        if finish:
                            demo = case.reach_verify()
                            case.app.history_verify_button.invoke()
                            case.wait_idle()
                            self.assertEqual(case.app.tutorial_step, "finish")
                            case.app.tutorial_next_button.invoke()
                        else:
                            demo = case.reach_select()
                            case.app.tutorial_exit()
                        case.root.update()
                        self.assertEqual(case.snapshot(), before)
                        self.assertFalse(demo.root.exists())
                        self.assertEqual(fixture.read_bytes(), contents)
                        case.assert_no_external_actions()
                    finally:
                        case.tearDown()
                        case.doCleanups()

    @unittest.skipUnless(os.name == "nt", "Windows Tk high-DPI geometry check")
    def test_every_history_step_keeps_coach_actions_active_controls_and_snapshot_rows_visible(self):
        with tempfile.TemporaryDirectory(prefix="rat-trap-history-geometry-") as temporary:
            for scaling in (1.333, 2.0, 2.667):
                with self.subTest(tk_scaling=scaling):
                    window = tk.Tk()
                    window.withdraw()
                    log = diagnostics.LocalDiagnostics(Path(temporary) / str(scaling))
                    demo = None
                    try:
                        window.tk.call("tk", "scaling", scaling)
                        window.attributes("-alpha", 0.0)
                        app = guided_app.GuidedRatTrapApp(window, diagnostic_log=log)
                        window.geometry("960x640+20000+20000")
                        window.deiconify()
                        window.update()
                        self.assertTrue(app.start_tutorial("history"))
                        app._go_to("Backups & history")
                        demo = history_tutorials.create_practice(Path(temporary))
                        demo.create_first_backup()
                        demo.change_sample()
                        demo.create_second_backup()
                        demo.list_history()
                        app.tutorial_demo = demo
                        app.repository_source.set(str(demo.source))
                        app.repository_path.set(str(demo.repository))
                        app.repository_loaded_path = demo.repository
                        app._render_history_list(demo.history)
                        for step in tutorials.STEPS_BY_ID["history"]:
                            app._set_tutorial_step(step.id)
                            window.update()
                            for button in (app.tutorial_next_button, app.tutorial_back_button, app.tutorial_exit_button):
                                left = button.winfo_rootx() - window.winfo_rootx()
                                top = button.winfo_rooty() - window.winfo_rooty()
                                detail = f"history/{step.id}, {scaling=}, {button.cget('text')}"
                                self.assertTrue(button.winfo_ismapped(), detail)
                                self.assertGreaterEqual(left, 0, detail)
                                self.assertGreaterEqual(top, 0, detail)
                                self.assertLessEqual(left + button.winfo_width(), window.winfo_width(), detail)
                                self.assertLessEqual(top + button.winfo_height(), window.winfo_height(), detail)
                            canvas = app.page_scrollers["Backups & history"].canvas
                            self.assertGreaterEqual(canvas.winfo_height(), 80)
                            target = app.tutorial_target
                            self.assertIsNotNone(target)
                            self.assertTrue(target.winfo_ismapped(), f"history/{step.id}: target hidden")
                            if step.id == "navigate":
                                continue
                            left = target.winfo_rootx() - canvas.winfo_rootx()
                            top = target.winfo_rooty() - canvas.winfo_rooty()
                            detail = f"history/{step.id}, scale={scaling}, target={target}, {left=}, {top=}"
                            self.assertLess(left, canvas.winfo_width(), detail)
                            self.assertLess(top, canvas.winfo_height(), detail)
                            self.assertGreater(left + target.winfo_width(), 0, detail)
                            self.assertGreater(top + target.winfo_height(), 0, detail)
                            if isinstance(target, (ttk.Button, ttk.Checkbutton)):
                                self.assertGreaterEqual(left, 0, detail)
                                self.assertGreaterEqual(top, 0, detail)
                                self.assertLessEqual(left + target.winfo_width(), canvas.winfo_width(), detail)
                                self.assertLessEqual(top + target.winfo_height(), canvas.winfo_height(), detail)
                            if step.id == "select":
                                for item in (demo.second_snapshot.snapshot_id, demo.first_snapshot.snapshot_id):
                                    bounds = target.bbox(item)
                                    self.assertTrue(bounds, f"{detail}: {item} missing")
                                    x, y, width, height = bounds
                                    self.assertGreaterEqual(top + y, 0, detail)
                                    self.assertLessEqual(top + y + height, canvas.winfo_height(), detail)
                                    label = target.bbox(item, "label")
                                    self.assertTrue(label, f"{detail}: {item} label missing")
                                    self.assertGreaterEqual(left + label[0], 0, detail)
                                    self.assertLessEqual(left + label[0] + label[2], canvas.winfo_width(), detail)
                                    font = ttk.Style(window).lookup(target.cget("style") or "Treeview", "font")
                                    text_width = int(window.tk.call("font", "measure", font, target.set(item, "label")))
                                    self.assertLessEqual(text_width + 8, label[2], f"{detail}: row label clipped")
                        app.tutorial_exit()
                    finally:
                        if demo is not None:
                            demo.cleanup()
                        window.withdraw()
                        window.destroy()
                        log.close()


if __name__ == "__main__":
    unittest.main()
