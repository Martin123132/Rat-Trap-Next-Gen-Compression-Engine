"""Guided tutorial isolation and interaction tests using internal, hidden Tk."""

import hashlib
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from rat_trap import desktop_preview2, diagnostics, guided_app, tutorials, windows_app


def file_snapshot(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class GuidedAppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-guided-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.log = diagnostics.LocalDiagnostics(self.base / "diagnostics")
        self.addCleanup(self.log.close)
        self.app = guided_app.GuidedRatTrapApp(self.root, diagnostic_log=self.log)
        self.root.update_idletasks()
        self.error = self.enterContext(mock.patch.object(windows_app.messagebox, "showerror"))
        self.warning = self.enterContext(mock.patch.object(windows_app.messagebox, "showwarning"))
        self.info = self.enterContext(mock.patch.object(windows_app.messagebox, "showinfo"))
        self.pickers = {}
        for name in ("askopenfilename", "asksaveasfilename", "askdirectory"):
            self.pickers[name] = self.enterContext(mock.patch.object(
                windows_app.filedialog, name, return_value=""
            ))
        self.enterContext(mock.patch.object(windows_app.simpledialog, "askstring", return_value=None))
        self.enterContext(mock.patch.object(windows_app.messagebox, "askyesno", return_value=False))
        self.enterContext(mock.patch.object(windows_app.messagebox, "askyesnocancel", return_value=None))
        self.reveal = self.enterContext(mock.patch.object(desktop_preview2, "reveal_in_folder"))
        if hasattr(os, "startfile"):
            self.startfile = self.enterContext(mock.patch.object(os, "startfile"))
        self.release_events = []

    def tearDown(self):
        for release in getattr(self, "release_events", ()):
            release.set()
        if hasattr(self, "app") and self.app.busy:
            self.wait_until_idle()
        if hasattr(self, "app"):
            self.app.tutorial_exit()
        if hasattr(self, "root"):
            for timer in self.root.tk.call("after", "info"):
                self.root.after_cancel(timer)

    def wait_until_idle(self, timeout=15):
        deadline = time.perf_counter() + timeout
        while self.app.busy and time.perf_counter() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.root.update()
        self.assertFalse(self.app.busy, "Tutorial task did not become idle")

    def blocking_work(self, result=None, error=None):
        started = threading.Event()
        release = threading.Event()
        self.release_events.append(release)

        def work(*_args, **_kwargs):
            started.set()
            if not release.wait(10):
                raise TimeoutError("The generated test worker was not released")
            if error is not None:
                raise error
            return result

        return started, release, work

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from GuidedAppTests.descendants(child)

    def load_demo(self):
        self.assertTrue(self.app.start_tutorial("vault-search"))
        self.assertEqual(self.app.tutorial_step, "navigate")
        self.app._go_to("Search Vault")
        self.assertEqual(self.app.tutorial_step, "load")
        self.app._choose_vault_archive()
        self.wait_until_idle()
        self.assertEqual(self.app.tutorial_step, "query")
        self.assertIsNotNone(self.app.tutorial_demo)
        return self.app.tutorial_demo

    def reach_search(self):
        demo = self.load_demo()
        self.app.vault_query.set(tutorials.DEMO_QUERY)
        self.app.tutorial_next()
        self.assertEqual(self.app.tutorial_step, "search")
        return demo

    def reach_select(self):
        demo = self.reach_search()
        self.app._start_vault_search()
        self.wait_until_idle()
        self.assertEqual(self.app.tutorial_step, "select")
        return demo

    def select_sample_result(self):
        matches = [item for item in self.app.vault_results.get_children()
                   if self.app.vault_results.item(item, "values")[0] == tutorials.DEMO_PATH]
        self.assertEqual(len(matches), 1)
        self.app.vault_results.selection_set(matches[0])
        self.app.vault_results.focus(matches[0])
        return matches[0]

    def call_bound_callback(self, widget, sequence):
        # Exercise the actual registered Tcl callback while the Tk window stays
        # hidden. This does not send input to a native desktop surface.
        binding = widget.bind(sequence)
        self.assertTrue(binding, sequence)
        command = binding.split("[", 1)[1].split()[0]
        self.root.tk.call(command, "generated-test-event")
        self.root.update_idletasks()

    def seed_user_state(self):
        source = self.base / "generated-user-source"
        source.mkdir()
        (source / "unchanged.txt").write_text("Generated user data stand-in", encoding="utf-8")
        self.app.source_folder.set(str(source))
        self.app.create_archive.set(str(self.base / "custom output.gmw"))
        self.app.vault_archive.set(str(self.base / "previous vault.gmw"))
        self.app.vault_query.set("previous query")
        self.app.vault_extension.set("txt")
        self.app.vault_results_archive = Path(self.app.vault_archive.get())
        item = self.app.vault_results.insert("", "end", iid="old-result", values=(
            "previous.txt", "text/plain", "42 B", "Yes"
        ))
        self.app.vault_results.selection_set(item)
        self.app.vault_results.focus(item)
        self.app.vault_result_count.set("One existing result")
        self.app.vault_preview.configure(state="normal")
        self.app.vault_preview.insert("1.0", "Existing preview content")
        self.app.vault_preview.configure(state="disabled")
        self.app._picker_directory = source
        output_path = self.base / "previous output.gmw"
        output_path.write_bytes(b"Generated completion fixture")
        self.app._publish_completion(desktop_preview2.CompletedOutput(
            output_path, "archive", "Previous output", "Preserve this result"
        ))
        self.app.activity_title.set("Previous output")
        self.app.activity_elapsed.set("Elapsed 01:05")
        self.app.activity_hint.set("Previous activity hint")
        self.app.status_text.set("Previous task status")
        self.app._go_to("Inspect / export")
        return source, self.state_snapshot()

    def state_snapshot(self):
        names = ("source_folder", "create_archive", "vault_archive", "vault_query",
                 "vault_extension", "vault_result_count", "status_text", "activity_title",
                 "activity_elapsed", "activity_hint", "result_path", "result_summary")
        return {
            "variables": {name: getattr(self.app, name).get() for name in names},
            "page": self.app.tabs.select(),
            "rows": [(item, tuple(self.app.vault_results.item(item, "values")))
                     for item in self.app.vault_results.get_children()],
            "selection": self.app.vault_results.selection(),
            "focus": self.app.vault_results.focus(),
            "preview": self.app.vault_preview.get("1.0", "end-1c"),
            "results_archive": self.app.vault_results_archive,
            "output": self.app.last_output,
            "completion": bool(self.app.completion_frame.winfo_manager()),
            "picker_directory": self.app._picker_directory,
        }

    def test_normal_application_remains_available_before_start(self):
        self.assertIsInstance(self.app, desktop_preview2.DesktopPreview2App)
        self.assertFalse(self.app.tutorial_active)
        for title in ("Create archive", "Secure files", "Search Vault", "Home"):
            self.assertTrue(self.app._go_to(title))
            self.assertEqual(self.app.tabs.select(), str(self.app.pages[title]))

    def test_unknown_and_unavailable_tutorials_do_not_mutate_state(self):
        before = self.state_snapshot()
        for tutorial_id in ["unknown-journey"] + [
            item.id for item in tutorials.TUTORIALS if not item.available
        ]:
            with self.subTest(tutorial=tutorial_id):
                self.assertFalse(self.app.start_tutorial(tutorial_id))
                self.assertFalse(self.app.tutorial_active)
                self.assertEqual(self.state_snapshot(), before)

    def test_no_autostart_on_catalog_and_no_sample_created_at_first_step(self):
        with mock.patch.object(tutorials, "create_demo", wraps=tutorials.create_demo) as create:
            self.app.show_tutorials()
            self.assertFalse(self.app.tutorial_active)
            self.assertTrue(self.app.start_tutorial("vault-search"))
            self.assertEqual(self.app.tutorial_step, "navigate")
            self.assertFalse(self.app.busy)
            self.assertIsNone(self.app.tutorial_demo)
            create.assert_not_called()

    def test_navigation_keyboard_picker_and_launch_escape_routes_are_gated(self):
        self.app.start_tutorial("vault-search")
        current = self.app.tabs.select()
        self.assertFalse(self.app._go_to("Secure files"))
        self.app._shortcut_page("Home")
        self.assertEqual(self.app.tabs.select(), current)
        self.app._open_shortcut()
        self.app._choose_source()
        self.app.apply_launch_request(windows_app.LaunchRequest(
            "open-archive", self.base / "not-a-real-archive.gmw"
        ))
        self.assertEqual(self.app.tabs.select(), current)
        self.assertEqual(self.app.tutorial_step, "navigate")
        for picker in self.pickers.values():
            picker.assert_not_called()
        self.reveal.assert_not_called()

    def test_return_and_double_click_do_not_skip_steps_or_start_workers(self):
        self.app.start_tutorial("vault-search")
        with mock.patch.object(self.app, "_run_task") as run:
            self.call_bound_callback(self.app.vault_search_entry, "<Return>")
            self.call_bound_callback(self.app.vault_results, "<Double-1>")
            self.app._start_vault_search()
            self.app._start_vault_preview()
            self.app._start_vault_extract_selected()
            self.app._show_all_vault()
            run.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "navigate")
        self.warning.assert_not_called()
        for picker in self.pickers.values():
            picker.assert_not_called()

    def test_only_step_actions_are_enabled_and_other_path_fields_cannot_be_edited(self):
        self.app.start_tutorial("vault-search")
        allowed = {self.app.nav_buttons["Search Vault"], self.app.tutorial_next_button,
                   self.app.tutorial_back_button, self.app.tutorial_exit_button}
        enabled = {widget for widget in self.descendants(self.root)
                   if isinstance(widget, ttk.Button) and not widget.instate(["disabled"])}
        self.assertFalse(enabled - allowed, [str(widget.cget("text")) for widget in enabled - allowed])
        for entry in self.app.path_entries.values():
            with self.subTest(entry=str(entry)):
                before = entry.get()
                entry.insert("end", "generated forbidden edit")
                self.assertEqual(entry.get(), before)
        self.app._go_to("Search Vault")
        self.app._choose_vault_archive()
        self.wait_until_idle()
        self.assertFalse(self.app.vault_search_entry.instate(["disabled"]))
        self.assertTrue(self.app.vault_search_button.instate(["disabled"]))
        self.assertTrue(self.app.vault_preview_button.instate(["disabled"]))

    def test_direct_page_selection_cannot_escape_an_active_tutorial(self):
        self.app.start_tutorial("vault-search")
        selected = self.app.tabs.select()
        self.app.tabs.select(self.app.pages["Secure files"])
        self.assertEqual(self.app.tabs.select(), selected)
        self.assertEqual(self.app.tutorial_step, "navigate")

    def test_query_and_selection_require_the_expected_sample_values(self):
        self.load_demo()
        self.app.vault_query.set("wrong search")
        self.app.tutorial_next()
        self.assertEqual(self.app.tutorial_step, "query")
        self.app.vault_query.set(tutorials.DEMO_QUERY)
        self.app.tutorial_next()
        self.app._start_vault_search()
        self.wait_until_idle()
        self.app.vault_results.selection_remove(self.app.vault_results.selection())
        self.app.tutorial_next()
        self.assertEqual(self.app.tutorial_step, "select")
        self.select_sample_result()
        self.app.tutorial_next()
        self.assertEqual(self.app.tutorial_step, "preview")

    def test_real_sample_search_preview_finish_restores_prior_state_and_sources(self):
        source, before = self.seed_user_state()
        original = file_snapshot(source)
        demo = self.reach_select()
        demo_before = file_snapshot(demo.root)
        self.select_sample_result()
        self.app.tutorial_next()
        self.app._start_vault_preview()
        self.wait_until_idle()
        self.assertEqual(self.app.tutorial_step, "finish")
        self.assertIn(tutorials.DEMO_MARKER, self.app.vault_preview.get("1.0", "end-1c"))
        self.assertEqual(file_snapshot(demo.root), demo_before)
        self.assertEqual(file_snapshot(source), original)
        self.reveal.assert_not_called()
        self.app.tutorial_next()
        self.assertFalse(self.app.tutorial_active)
        self.assertEqual(self.state_snapshot(), before)
        self.assertFalse(demo.root.exists())
        self.assertEqual(file_snapshot(source), original)

    def test_idle_exit_restores_existing_results_and_completion(self):
        source, before = self.seed_user_state()
        original = file_snapshot(source)
        demo = self.load_demo()
        self.app.tutorial_exit()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())
        self.assertEqual(self.state_snapshot(), before)
        self.assertEqual(file_snapshot(source), original)

    def test_back_moves_only_one_completed_step_without_executing_search(self):
        self.reach_search()
        with mock.patch.object(self.app, "_run_task") as run:
            self.app.tutorial_back()
            self.assertEqual(self.app.tutorial_step, "query")
            run.assert_not_called()
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "load")

    def test_search_failure_keeps_current_step_and_does_not_show_completion(self):
        self.reach_search()
        with mock.patch.object(windows_app.gmw_tool, "search_vault", side_effect=RuntimeError("Generated failure")):
            self.app._start_vault_search()
            self.wait_until_idle()
        self.assertEqual(self.app.tutorial_step, "search")
        self.assertTrue(self.app.tutorial_active)
        self.error.assert_called_once()
        self.assertIsNone(self.app.last_output)
        self.assertTrue(self.app.nav_buttons["Secure files"].instate(["disabled"]))
        self.assertFalse(self.app.vault_search_button.instate(["disabled"]))

    def test_busy_next_does_not_advance_or_start_another_tutorial(self):
        self.reach_search()
        started, release, work = self.blocking_work(result=[])
        with mock.patch.object(windows_app.gmw_tool, "search_vault", side_effect=work):
            self.app._start_vault_search()
            self.assertTrue(started.wait(2))
            self.app.tutorial_next()
            self.assertEqual(self.app.tutorial_step, "search")
            self.assertFalse(self.app.start_tutorial("vault-search"))
            self.assertFalse(self.app.tutorial_back_button.instate(["disabled"]))
            self.assertFalse(self.app.tutorial_exit_button.instate(["disabled"]))
            release.set()
            self.wait_until_idle()

    def test_success_without_expected_result_does_not_advance(self):
        self.reach_search()
        with mock.patch.object(windows_app.gmw_tool, "search_vault", return_value=[]):
            self.app._start_vault_search()
            self.wait_until_idle()
        self.assertEqual(self.app.tutorial_step, "search")
        self.assertEqual(self.app.vault_results.get_children(), ())
        self.assertFalse(self.app.tutorial_next_button.instate(["!disabled"]))

    def test_changed_sample_path_or_extension_cannot_read_another_vault(self):
        demo = self.reach_search()
        with mock.patch.object(windows_app.gmw_tool, "search_vault") as search:
            self.app.vault_extension.set("txt")
            self.app._start_vault_search()
            search.assert_not_called()
            self.app.vault_extension.set("")
            other = self.base / "generated-not-the-demo.gmw"
            other.write_bytes(b"Generated unrelated bytes, never a real user file")
            self.app.vault_archive.set(str(other))
            self.app._start_vault_search()
            search.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "search")
        self.assertTrue(demo.archive.exists())
        self.assertEqual(other.read_bytes(), b"Generated unrelated bytes, never a real user file")

    def test_replaced_valid_sample_archive_is_rejected_before_search(self):
        demo = self.reach_search()
        outside = self.base / "generated-unrelated-source"
        outside.mkdir()
        (outside / "unrelated.txt").write_text("Different generated data; never user content", encoding="utf-8")
        replacement = self.base / "generated-unrelated.vault.gmw"
        windows_app.gmw_tool.compress_folder(outside, replacement, profile="vault")
        before = file_snapshot(outside)
        replacement_bytes = replacement.read_bytes()
        demo.archive.write_bytes(replacement_bytes)
        with mock.patch.object(windows_app.gmw_tool, "search_vault") as search:
            self.app._start_vault_search()
            search.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "search")
        self.assertEqual(file_snapshot(outside), before)
        self.app.tutorial_exit()
        self.assertEqual(demo.archive.read_bytes(), replacement_bytes)
        # This is an explicitly generated replacement fixture retained safely
        # by the tutorial, not a real user archive.
        demo.archive.unlink()
        demo.cleanup()

    def test_completion_callback_failure_does_not_advance(self):
        self.reach_search()
        with mock.patch.object(self.app.vault_results, "insert", side_effect=RuntimeError("Generated render failure")):
            self.app._start_vault_search()
            self.wait_until_idle()
        self.assertEqual(self.app.tutorial_step, "search")
        self.error.assert_called_once()
        self.assertTrue(self.app.nav_buttons["Secure files"].instate(["disabled"]))

    def test_first_back_restores_state_and_returns_to_catalog(self):
        _source, before = self.seed_user_state()
        self.app.start_tutorial("vault-search")
        with mock.patch.object(self.app, "show_tutorials") as catalog:
            self.app.tutorial_back()
        self.assertFalse(self.app.tutorial_active)
        self.assertEqual(self.state_snapshot(), before)
        catalog.assert_called_once()

    def test_stale_load_callback_cannot_overwrite_a_new_session(self):
        self.app.start_tutorial("vault-search")
        self.app._go_to("Search Vault")
        with mock.patch.object(desktop_preview2.DesktopPreview2App, "_run_task") as run:
            self.app._choose_vault_archive()
        old_done = run.call_args.args[2]
        self.app.tutorial_exit()
        self.app.start_tutorial("vault-search")
        self.app._go_to("Search Vault")
        token = self.app.tutorial_session_token
        state = self.state_snapshot()
        stale_demo = tutorials.create_demo(self.base)
        self.addCleanup(stale_demo.cleanup)
        old_done(stale_demo)
        self.assertIs(self.app.tutorial_session_token, token)
        self.assertEqual(self.app.tutorial_step, "load")
        self.assertIsNone(self.app.tutorial_demo)
        self.assertEqual(self.state_snapshot(), state)
        self.assertFalse(stale_demo.root.exists())

    def test_exit_during_demo_creation_cleans_late_sample_result(self):
        _source, before = self.seed_user_state()
        self.app.start_tutorial("vault-search")
        self.app._go_to("Search Vault")
        demo = tutorials.create_demo(self.base)
        self.addCleanup(demo.cleanup)
        started, release, work = self.blocking_work(result=demo)
        with mock.patch.object(tutorials, "create_demo", side_effect=work):
            self.app._choose_vault_archive()
            self.assertTrue(started.wait(2))
            self.app.tutorial_exit()
            self.assertTrue(demo.archive.exists())
            release.set()
            self.wait_until_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())
        self.assertEqual(self.state_snapshot(), before)

    def test_live_exit_invalidates_session_and_restores_only_after_worker_finishes(self):
        source, before = self.seed_user_state()
        original = file_snapshot(source)
        demo = self.reach_search()
        started, release, work = self.blocking_work(result=[])
        with mock.patch.object(windows_app.gmw_tool, "search_vault", side_effect=work):
            self.app._start_vault_search()
            self.assertTrue(started.wait(2))
            token = self.app.tutorial_session_token
            self.app.tutorial_exit()
            self.assertIsNot(self.app.tutorial_session_token, token)
            self.assertTrue(self.app.tutorial_active)
            self.assertEqual(self.app._tutorial_pending_action, "exit")
            self.assertTrue(demo.archive.exists(), "Live workers must retain their sample inputs")
            self.assertFalse(self.app.start_tutorial("vault-search"))
            release.set()
            self.wait_until_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())
        self.assertEqual(self.state_snapshot(), before)
        self.assertEqual(file_snapshot(source), original)

    def test_live_back_ignores_old_completion_and_returns_to_query(self):
        self.reach_search()
        started, release, work = self.blocking_work(result=[])
        with mock.patch.object(windows_app.gmw_tool, "search_vault", side_effect=work):
            self.app._start_vault_search()
            self.assertTrue(started.wait(2))
            token = self.app.tutorial_session_token
            self.app.tutorial_back()
            self.assertIsNot(self.app.tutorial_session_token, token)
            self.assertEqual(self.app._tutorial_pending_action, "back")
            release.set()
            self.wait_until_idle()
        self.assertTrue(self.app.tutorial_active)
        self.assertEqual(self.app.tutorial_step, "query")
        self.assertEqual(self.app.vault_results.get_children(), ())

    def test_worker_setup_failure_reenables_only_the_step_controls(self):
        self.reach_search()
        with mock.patch.object(windows_app.threading.Thread, "start", side_effect=RuntimeError("Generated start failure")):
            self.app._start_vault_search()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tutorial_step, "search")
        self.assertTrue(self.app.nav_buttons["Secure files"].instate(["disabled"]))
        self.assertFalse(self.app.vault_search_button.instate(["disabled"]))
        self.error.assert_called_once()

    def test_live_exit_after_failed_worker_restores_state_without_error_dialog(self):
        _source, before = self.seed_user_state()
        demo = self.reach_search()
        started, release, work = self.blocking_work(error=RuntimeError("Generated exited failure"))
        with mock.patch.object(windows_app.gmw_tool, "search_vault", side_effect=work):
            self.app._start_vault_search()
            self.assertTrue(started.wait(2))
            self.app.tutorial_exit()
            release.set()
            self.wait_until_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertEqual(self.state_snapshot(), before)
        self.assertFalse(demo.root.exists())
        self.error.assert_not_called()

    def test_monitor_failure_exit_waits_for_worker_then_recovers_without_closing(self):
        _source, before = self.seed_user_state()
        demo = self.reach_search()
        started, release, work = self.blocking_work(result=[])
        with mock.patch.object(windows_app.gmw_tool, "search_vault", side_effect=work):
            self.app._start_vault_search()
            self.assertTrue(started.wait(2))
            events = self.app._task_events
            # Break the actual scheduled polling callback once, allowing it to
            # enter its monitor-failed branch and stop normal rescheduling.
            with mock.patch.object(events, "get_nowait", side_effect=RuntimeError("Generated queue monitor failure")):
                deadline = time.perf_counter() + 2
                while not self.app._task_monitor_failed and time.perf_counter() < deadline:
                    self.root.update()
                    time.sleep(0.005)
            self.assertTrue(self.app._task_monitor_failed)
            self.app.tutorial_exit()
            self.assertTrue(self.app.busy)
            self.assertTrue(self.app.tutorial_active)
            self.assertTrue(demo.archive.exists())
            self.assertFalse(self.app.start_tutorial("vault-search"))
            release.set()
            deadline = time.perf_counter() + 5
            while self.app.busy and time.perf_counter() < deadline:
                self.root.update()
                time.sleep(0.005)
            recovered = not self.app.busy
            if not recovered:
                # Exact test-worker fallback allows fixture cleanup even when
                # this assertion exposes a missing UI recovery path.
                self.app._worker_thread.join(2)
                self.app._poll_task_events(self.app._task_token)
            self.assertTrue(recovered, "Exit stayed pending after the unmonitored tutorial worker ended")
        self.assertFalse(self.app.tutorial_active)
        self.assertEqual(self.state_snapshot(), before)
        self.assertFalse(demo.root.exists())
        self.assertTrue(self.root.winfo_exists())

class GuidedGeometryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-guided-geometry-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    @unittest.skipUnless(os.name == "nt", "Windows Tk high-DPI geometry check")
    def test_bubble_and_back_exit_remain_reachable_at_compact_high_dpi(self):
        for scaling in (1.333, 2.0, 2.667):
            with self.subTest(tk_scaling=scaling):
                window = tk.Tk()
                window.withdraw()
                log = diagnostics.LocalDiagnostics(self.base / f"geometry-{scaling}")
                try:
                    window.tk.call("tk", "scaling", scaling)
                    window.attributes("-alpha", 0.0)
                    app = guided_app.GuidedRatTrapApp(window, diagnostic_log=log)
                    # Native desktop interaction is not used: transparent,
                    # off-screen mapping supplies Tk's actual layout metrics.
                    window.geometry("960x640+20000+20000")
                    window.deiconify()
                    window.update()
                    self.assertEqual((window.winfo_width(), window.winfo_height()), (960, 640))
                    app.start_tutorial("vault-search")
                    window.update()
                    app._go_to("Search Vault")
                    # Geometry only: direct step selection avoids doing file
                    # operations in this layout test. Real transitions have a
                    # separate end-to-end sample search/preview test above.
                    for step in tutorials.VAULT_SEARCH_STEPS:
                        app._set_tutorial_step(step.id)
                        window.update()
                        for button in (app.tutorial_next_button, app.tutorial_back_button,
                                       app.tutorial_exit_button):
                            left = button.winfo_rootx() - window.winfo_rootx()
                            top = button.winfo_rooty() - window.winfo_rooty()
                            detail = f"{step.id}: {button.cget('text')}, scale={scaling}, {left=}, {top=}"
                            self.assertTrue(button.winfo_ismapped(), detail)
                            self.assertGreaterEqual(left, 0, detail)
                            self.assertGreaterEqual(top, 0, detail)
                            self.assertLessEqual(left + button.winfo_width(), window.winfo_width(), detail)
                            self.assertLessEqual(top + button.winfo_height(), window.winfo_height(), detail)
                        canvas = app.page_scrollers["Search Vault"].canvas
                        self.assertGreaterEqual(canvas.winfo_height(), 80,
                                                f"{step.id}: scale={scaling}, workspace became unusably short")
                        self.assertTrue(app.tutorial_bubble.winfo_ismapped())
                    app.tutorial_exit()
                finally:
                    window.withdraw()
                    window.destroy()
                    log.close()


if __name__ == "__main__":
    unittest.main()
