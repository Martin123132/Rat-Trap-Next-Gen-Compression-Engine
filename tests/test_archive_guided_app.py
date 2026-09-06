"""Real compression/restore lessons exercised through internal, hidden Tk."""

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

from rat_trap import archive_tutorials, desktop_preview2, diagnostics, guided_app, windows_app


def hashes(folder):
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.rglob("*") if path.is_file()
    }


class ArchiveGuidedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-archive-guided-test-")
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
        make_practice = archive_tutorials.create_practice
        self.enterContext(mock.patch.object(
            archive_tutorials, "create_practice",
            side_effect=lambda parent=None, with_archive=False: make_practice(self.base, with_archive=with_archive),
        ))
        self.error = self.enterContext(mock.patch.object(windows_app.messagebox, "showerror"))
        self.info = self.enterContext(mock.patch.object(windows_app.messagebox, "showinfo"))
        self.warning = self.enterContext(mock.patch.object(windows_app.messagebox, "showwarning"))
        self.pickers = [self.enterContext(mock.patch.object(windows_app.filedialog, name, return_value=""))
                        for name in ("askopenfilename", "asksaveasfilename", "askdirectory")]
        self.enterContext(mock.patch.object(windows_app.simpledialog, "askstring", return_value=None))
        self.confirm = self.enterContext(mock.patch.object(windows_app.messagebox, "askyesno", return_value=False))
        self.enterContext(mock.patch.object(windows_app.messagebox, "askyesnocancel", return_value=None))
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

    def wait_idle(self, timeout=20):
        deadline = time.monotonic() + timeout
        while self.app.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.root.update()
        self.assertFalse(self.app.busy, "Practice worker did not finish")

    def blocked(self, operation):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def work(*args, **kwargs):
            started.set()
            if not release.wait(10):
                raise TimeoutError("Generated test worker was not released")
            return operation(*args, **kwargs)

        return started, release, work

    def load(self, tutorial_id):
        self.assertTrue(self.app.start_tutorial(tutorial_id))
        self.assertEqual(self.app.tutorial_id, tutorial_id)
        self.assertEqual(self.app.tutorial_step, "navigate")
        page = "Create archive" if tutorial_id == "compress" else "Extract archive"
        self.app.nav_buttons[page].invoke()
        self.assertEqual(self.app.tutorial_step, "load")
        button = self.app.lesson_source_button if tutorial_id == "compress" else self.app.lesson_archive_button
        button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "destination")
        self.assertIsInstance(self.app.tutorial_demo, archive_tutorials.ArchivePractice)
        self.retained_demos.append(self.app.tutorial_demo)
        return self.app.tutorial_demo

    def reach_create(self, profile="balanced"):
        demo = self.load("compress")
        self.app.lesson_output_button.invoke()
        self.assertEqual(self.app.tutorial_step, "profile")
        label = next(label for label, value in windows_app.PROFILE_OPTIONS.items() if value == profile)
        self.app.profile_label.set(label)
        self.app._profile_changed()
        self.assertTrue(self.app.tutorial_next())
        self.assertEqual(self.app.tutorial_step, "create")
        return demo

    def reach_extract(self):
        demo = self.load("restore")
        self.app.lesson_destination_button.invoke()
        self.assertEqual(self.app.tutorial_step, "extract")
        return demo

    def reach_verify(self):
        demo = self.reach_extract()
        self.app.lesson_extract_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "verify")
        return demo

    def seed_state(self):
        source = self.base / "original user folder"
        source.mkdir()
        (source / "never change.txt").write_bytes(b"Generated unrelated fixture only")
        for name, value in {
            "source_folder": f'"{source}"',
            "create_archive": f'"{self.base / "previous output.gmw"}"',
            "extract_archive": f'"{self.base / "previous restore.gmw"}"',
            "extract_folder": f'"{self.base / "previous destination"}"',
            "profile_label": next(label for label, value in windows_app.PROFILE_OPTIONS.items() if value == "vault"),
            "profile_note": "Existing custom profile explanation",
            "encrypt_created_archive": True,
            "vault_archive": str(self.base / "old vault.gmw"),
            "vault_query": "Previously typed query",
            "vault_extension": "csv",
        }.items():
            getattr(self.app, name).set(value)
        output = self.base / "previous result.gmw"
        output.write_bytes(b"Generated prior completion fixture")
        self.app._publish_completion(desktop_preview2.CompletedOutput(output, "archive", "Existing result", "Keep me"))
        self.app._picker_directory = source
        self.app._go_to("Inspect / export")
        self.app.status_text.set("Existing task status")
        self.app.activity_title.set("Existing activity title")
        self.app.activity_hint.set("Existing activity hint")
        return source, self.snapshot()

    def snapshot(self):
        names = ("source_folder", "create_archive", "extract_archive", "extract_folder", "profile_label",
                 "profile_note", "encrypt_created_archive", "vault_archive", "vault_query", "vault_extension",
                 "status_text", "activity_title", "activity_elapsed", "activity_hint", "result_path", "result_summary")
        return {
            "variables": {name: getattr(self.app, name).get() for name in names},
            "page": self.app.tabs.select(), "picker": self.app._picker_directory,
            "output": self.app.last_output,
            "profile_options": tuple(self.app.lesson_profile_box.cget("values")),
            "browse": [button.cget("text") for button in (self.app.lesson_source_button, self.app.lesson_output_button,
                        self.app.lesson_archive_button, self.app.lesson_destination_button)],
            "completion": bool(self.app.completion_frame.winfo_manager()),
        }

    def assert_no_external_actions(self):
        for picker in self.pickers:
            picker.assert_not_called()
        self.confirm.assert_not_called()
        self.reveal.assert_not_called()
        if self.opened is not None:
            self.opened.assert_not_called()

    def test_compress_real_engine_result_and_finish_restore_prior_state(self):
        source, before = self.seed_state()
        original = hashes(source)
        demo = self.reach_create()
        result_frame = self.app._lesson_frames["compress"]
        overlapping = [widget for widget in self.app.pages["Create archive"].grid_slaves(
            row=result_frame.grid_info()["row"], column=0) if widget != result_frame]
        self.assertEqual(overlapping, [], "Practice result overlaps an existing workspace control")
        archive = Path(self.app.create_archive.get())
        sample_hashes = hashes(demo.source)
        with mock.patch.object(windows_app.gmw_tool, "compress_folder", wraps=windows_app.gmw_tool.compress_folder) as compress:
            self.app.lesson_create_button.invoke()
            self.wait_idle()
        compress.assert_called_once()
        self.assertEqual(self.app.tutorial_step, "finish")
        self.assertTrue(archive.is_file())
        self.assertGreater(archive.stat().st_size, 0)
        self.assertEqual(hashes(demo.source), sample_hashes)
        text = self.app.create_lesson_result.get("1.0", "end-1c").lower()
        self.assertIn("original", text)
        self.assertIn("archive", text)
        self.assertIn("%", text)
        self.assertFalse(self.app.encrypt_created_archive.get())
        self.assert_no_external_actions()
        self.info.assert_not_called()
        self.app.tutorial_next_button.invoke()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(hashes(source), original)

    def test_restore_real_engine_and_explicit_hash_check_precede_finish(self):
        source, before = self.seed_state()
        original = hashes(source)
        demo = self.reach_extract()
        destination = Path(self.app.extract_folder.get())
        self.assertFalse(destination.exists())
        self.assertFalse(destination.is_relative_to(demo.source))
        with mock.patch.object(windows_app.gmw_tool, "extract_archive", wraps=windows_app.gmw_tool.extract_archive) as extract:
            self.app.lesson_extract_button.invoke()
            self.wait_idle()
        extract.assert_called_once()
        self.assertEqual(self.app.tutorial_step, "verify")
        self.assertEqual(hashes(destination), hashes(demo.source))
        self.assertFalse(self.app.tutorial_next())
        self.assertNotIn("verified", self.app.restore_lesson_result.get("1.0", "end-1c").lower())
        self.app.lesson_verify_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "finish")
        self.assertIn("sha-256", self.app.restore_lesson_result.get("1.0", "end-1c").lower())
        self.assert_no_external_actions()
        self.info.assert_not_called()
        self.app.tutorial_next_button.invoke()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(hashes(source), original)
        self.assertFalse(demo.root.exists())

    def test_navigation_home_shortcuts_picker_callbacks_and_normal_operations_cannot_skip(self):
        for tutorial_id in ("compress", "restore"):
            with self.subTest(tutorial=tutorial_id):
                self.assertTrue(self.app.start_tutorial(tutorial_id))
                page = self.app.tabs.select()
                self.app._home_compress()
                self.app._home_restore()
                self.app._shortcut_page("Home")
                self.app._open_shortcut()
                self.app.tabs.select(self.app.pages["Secure files"])
                self.app.apply_launch_request(windows_app.LaunchRequest("open-archive", self.base / "unrelated.gmw"))
                self.app._choose_source()
                self.app._choose_create_archive()
                self.app._choose_extract_archive()
                self.app._choose_extract_folder()
                with mock.patch.object(self.app, "_run_task") as run:
                    self.app._start_create()
                    self.app._start_extract()
                    self.app._verify_practice_restore()
                    self.app._start_vault_search()
                    run.assert_not_called()
                self.assertEqual(self.app.tutorial_step, "navigate")
                self.assertEqual(self.app.tabs.select(), page)
                self.assert_no_external_actions()
                self.app.tutorial_exit()

    def test_idle_exit_from_both_lessons_restores_exact_paths_and_settings(self):
        source, before = self.seed_state()
        original = hashes(source)
        for tutorial_id in ("compress", "restore"):
            with self.subTest(tutorial=tutorial_id):
                demo = self.load(tutorial_id)
                self.app._normalize_path_variable(self.app.source_folder)
                self.app._normalize_path_variable(self.app.extract_archive)
                self.app.tutorial_exit()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(hashes(source), original)
                self.assertFalse(demo.root.exists())

    def test_create_rejects_tampered_source_output_profile_or_encryption_before_engine(self):
        demo = self.reach_create()
        expected_source = self.app.source_folder.get()
        expected_output = self.app.create_archive.get()
        expected_profile = self.app.profile_label.get()
        unrelated = self.base / "unrelated.txt"
        unrelated.write_bytes(b"Generated fixture must remain unchanged")
        changes = (("source_folder", str(self.base)), ("create_archive", str(unrelated)),
                   ("profile_label", "Not a real profile"), ("encrypt_created_archive", True))
        with mock.patch.object(windows_app.gmw_tool, "compress_folder") as compress, \
                mock.patch.object(self.app, "_new_encryption_options") as encryption:
            for name, value in changes:
                with self.subTest(variable=name):
                    getattr(self.app, name).set(value)
                    self.app._start_create()
                    compress.assert_not_called()
                    encryption.assert_not_called()
                    self.assertFalse(self.app.busy)
                    self.assertEqual(self.app.tutorial_step, "create")
                    self.app.source_folder.set(expected_source)
                    self.app.create_archive.set(expected_output)
                    self.app.profile_label.set(expected_profile)
                    self.app.encrypt_created_archive.set(False)
        self.assertEqual(unrelated.read_bytes(), b"Generated fixture must remain unchanged")
        self.assertFalse(Path(expected_output).exists())
        self.assert_no_external_actions()

    def test_extract_rejects_tampered_archive_destination_before_access_or_engine(self):
        self.reach_extract()
        expected_archive = self.app.extract_archive.get()
        expected_destination = self.app.extract_folder.get()
        unrelated = self.base / "unrelated.gmw"
        unrelated.write_bytes(b"Generated unrelated bytes")
        with mock.patch.object(windows_app.gmw_tool, "extract_archive") as extract, \
                mock.patch.object(self.app, "_archive_access") as access:
            for name, value in (("extract_archive", str(unrelated)), ("extract_folder", str(self.base))):
                with self.subTest(variable=name):
                    getattr(self.app, name).set(value)
                    self.app._start_extract()
                    extract.assert_not_called()
                    access.assert_not_called()
                    self.assertFalse(self.app.busy)
                    self.assertEqual(self.app.tutorial_step, "extract")
                    self.app.extract_archive.set(expected_archive)
                    self.app.extract_folder.set(expected_destination)
        self.assertEqual(unrelated.read_bytes(), b"Generated unrelated bytes")
        self.assert_no_external_actions()

    def test_back_replay_create_reviews_without_overwriting_existing_archive(self):
        self.reach_create()
        self.app.lesson_create_button.invoke()
        self.wait_idle()
        archive = Path(self.app.create_archive.get())
        before = archive.read_bytes(), archive.stat().st_mtime_ns
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "create")
        with mock.patch.object(windows_app.gmw_tool, "compress_folder") as compress:
            self.app.lesson_create_button.invoke()
            self.wait_idle()
        compress.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "finish")
        self.assertEqual((archive.read_bytes(), archive.stat().st_mtime_ns), before)
        self.confirm.assert_not_called()

    def test_back_replay_extract_reviews_without_overwriting_recovered_files(self):
        self.reach_verify()
        destination = Path(self.app.extract_folder.get())
        before = hashes(destination)
        mtimes = {path: path.stat().st_mtime_ns for path in destination.rglob("*") if path.is_file()}
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "extract")
        with mock.patch.object(windows_app.gmw_tool, "extract_archive") as extract:
            self.app.lesson_extract_button.invoke()
            self.wait_idle()
        extract.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "verify")
        self.assertEqual(hashes(destination), before)
        self.assertEqual({path: path.stat().st_mtime_ns for path in mtimes}, mtimes)
        self.confirm.assert_not_called()

    def test_failed_restore_verification_stays_at_verify_without_success_claim(self):
        demo = self.reach_verify()
        destination = Path(self.app.extract_folder.get())
        target = next(path for path in destination.rglob("*") if path.is_file())
        original = target.read_bytes()
        try:
            target.write_bytes(b"Generated changed practice output")
            self.app.lesson_verify_button.invoke()
            self.wait_idle()
            self.assertEqual(self.app.tutorial_step, "verify")
            self.assertFalse(self.app.tutorial_next())
            self.assertNotIn("all files verified", self.app.restore_lesson_result.get("1.0", "end-1c").lower())
        finally:
            target.write_bytes(original)

    def test_changed_sample_source_cannot_be_compressed(self):
        demo = self.reach_create()
        target = next(path for path in demo.source.rglob("*") if path.is_file())
        target.write_bytes(b"Generated change to practice data")
        with mock.patch.object(windows_app.gmw_tool, "compress_folder") as compress:
            self.app.lesson_create_button.invoke()
            self.wait_idle()
        compress.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "create")
        self.assertFalse(demo.archive.exists())
        self.app.tutorial_exit()
        self.assertEqual(target.read_bytes(), b"Generated change to practice data")

    def test_replaced_sample_archive_cannot_be_restored(self):
        demo = self.reach_extract()
        replacement = self.base / "generated replacement.gmw"
        replacement.write_bytes(b"Not an archive; must never reach the restore engine")
        os.replace(replacement, demo.archive)
        with mock.patch.object(windows_app.gmw_tool, "extract_archive") as extract:
            self.app.lesson_extract_button.invoke()
            self.wait_idle()
        extract.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "extract")
        self.assertFalse(demo.restored.exists())
        self.app.tutorial_exit()
        self.assertEqual(demo.archive.read_bytes(), b"Not an archive; must never reach the restore engine")

    def test_changed_profile_after_completed_create_requires_fresh_sample(self):
        demo = self.reach_create()
        self.app.lesson_create_button.invoke()
        self.wait_idle()
        original = demo.archive.read_bytes(), demo.archive.stat().st_mtime_ns
        self.app.tutorial_back()
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "profile")
        self.app.profile_label.set(next(label for label, value in windows_app.PROFILE_OPTIONS.items() if value == "fast"))
        self.app._profile_changed()
        with mock.patch.object(windows_app.gmw_tool, "compress_folder") as compress:
            self.app.tutorial_next()
            self.app._start_create()
            self.wait_idle()
            compress.assert_not_called()
        self.assertEqual((demo.archive.read_bytes(), demo.archive.stat().st_mtime_ns), original)
        while self.app.tutorial_step != "load":
            self.app.tutorial_back()
        self.app.lesson_source_button.invoke()
        self.wait_idle()
        self.retained_demos.append(self.app.tutorial_demo)
        self.assertIsNot(self.app.tutorial_demo, demo)
        self.assertNotEqual(self.app.tutorial_demo.root, demo.root)
        self.assertEqual(self.app.tutorial_step, "destination")
        self.assertFalse(demo.root.exists())

    def test_exit_during_hash_verification_cannot_publish_late_success(self):
        _source, before = self.seed_state()
        demo = self.reach_verify()
        original = demo.verify_restored
        started, release, work = self.blocked(original)
        with mock.patch.object(demo, "verify_restored", side_effect=work):
            self.app.lesson_verify_button.invoke()
            self.assertTrue(started.wait(2))
            self.assertEqual(self.app.tutorial_step, "verify")
            self.assertFalse(self.app.tutorial_next())
            self.app.tutorial_exit()
            self.assertTrue(self.app.busy)
            self.assertTrue(demo.restored.exists())
            release.set()
            self.wait_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(demo.root.exists())

    def test_only_current_targets_and_coach_actions_are_enabled(self):
        for tutorial_id in ("compress", "restore"):
            self.app.start_tutorial(tutorial_id)
            for widget in guided_app._descendants(self.root):
                if isinstance(widget, ttk.Button) and not widget.instate(["disabled"]):
                    self.assertIn(widget, (self.app.tutorial_target, self.app.tutorial_back_button,
                                          self.app.tutorial_next_button, self.app.tutorial_exit_button))
            for entry in self.app.path_entries.values():
                before = entry.get()
                entry.insert("end", "forbidden edit")
                self.assertEqual(entry.get(), before)
            self.app.tutorial_exit()

    def test_exit_during_actual_create_keeps_inputs_until_finished_then_restores(self):
        _source, before = self.seed_state()
        demo = self.reach_create()
        started, release, work = self.blocked(windows_app.gmw_tool.compress_folder)
        with mock.patch.object(windows_app.gmw_tool, "compress_folder", side_effect=work):
            self.app.lesson_create_button.invoke()
            self.assertTrue(started.wait(2))
            token = self.app.tutorial_session_token
            self.app.tutorial_exit()
            self.assertTrue(self.app.busy)
            self.assertTrue(self.app.tutorial_active)
            self.assertIsNot(self.app.tutorial_session_token, token)
            self.assertTrue(demo.source.exists())
            self.assertFalse(self.app.start_tutorial("restore"))
            self.assertFalse(self.app.tutorial_exit_button.instate(["disabled"]))
            release.set()
            self.wait_idle()
        self.assertFalse(self.app.tutorial_active)
        self.assertFalse(demo.root.exists())
        self.assertEqual(self.snapshot(), before)

    def test_back_during_actual_extract_waits_then_returns_only_one_step(self):
        demo = self.reach_extract()
        started, release, work = self.blocked(windows_app.gmw_tool.extract_archive)
        with mock.patch.object(windows_app.gmw_tool, "extract_archive", side_effect=work):
            self.app.lesson_extract_button.invoke()
            self.assertTrue(started.wait(2))
            token = self.app.tutorial_session_token
            self.app.tutorial_back()
            self.assertTrue(self.app.busy)
            self.assertIsNot(self.app.tutorial_session_token, token)
            self.assertTrue(demo.archive.exists())
            release.set()
            self.wait_idle()
        self.assertTrue(self.app.tutorial_active)
        self.assertEqual(self.app.tutorial_step, "destination")
        self.assertFalse(self.app.tutorial_next())

    def test_back_during_actual_create_preserves_completed_profile_and_replays_read_only(self):
        demo = self.reach_create("fast")
        started, release, work = self.blocked(windows_app.gmw_tool.compress_folder)
        with mock.patch.object(windows_app.gmw_tool, "compress_folder", side_effect=work):
            self.app.lesson_create_button.invoke()
            self.assertTrue(started.wait(2))
            self.app.tutorial_back()
            release.set()
            self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "profile")
        self.assertEqual(demo.profile, "fast")
        before = demo.archive.read_bytes(), demo.archive.stat().st_mtime_ns
        self.app.tutorial_next()
        with mock.patch.object(windows_app.gmw_tool, "compress_folder") as compress:
            self.app.lesson_create_button.invoke()
            self.wait_idle()
            compress.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "finish")
        self.assertEqual((demo.archive.read_bytes(), demo.archive.stat().st_mtime_ns), before)

    def test_late_load_completion_cleans_old_sample_without_overwriting_new_lesson(self):
        self.app.start_tutorial("compress")
        self.app._go_to("Create archive")
        with mock.patch.object(desktop_preview2.DesktopPreview2App, "_run_task") as run:
            self.app.lesson_source_button.invoke()
        old_done = run.call_args.args[2]
        self.app.tutorial_exit()
        self.app.start_tutorial("restore")
        self.app._go_to("Extract archive")
        token, before = self.app.tutorial_session_token, self.snapshot()
        stale = archive_tutorials.create_practice()
        self.retained_demos.append(stale)
        old_done(stale)
        self.assertIs(self.app.tutorial_session_token, token)
        self.assertEqual(self.app.tutorial_id, "restore")
        self.assertEqual(self.app.tutorial_step, "load")
        self.assertIsNone(self.app.tutorial_demo)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(stale.root.exists())

    def test_create_thread_setup_failure_leaves_only_retry_and_coach_controls(self):
        demo = self.reach_create()
        with mock.patch.object(windows_app.threading.Thread, "start", side_effect=RuntimeError("Generated thread setup failure")):
            self.app.lesson_create_button.invoke()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tutorial_step, "create")
        self.assertFalse(demo.archive.exists())
        self.assertFalse(self.app.lesson_create_button.instate(["disabled"]))
        self.assertTrue(self.app.nav_buttons["Secure files"].instate(["disabled"]))
        self.assertTrue(self.app.lesson_output_button.instate(["disabled"]))
        self.error.assert_called_once()


class ArchiveLessonGeometryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Tk high-DPI geometry check")
    def test_each_archive_lesson_step_keeps_coach_actions_and_workspace_visible(self):
        with tempfile.TemporaryDirectory(prefix="rat-trap-archive-lesson-geometry-") as temporary:
            for scaling in (1.333, 2.0, 2.667):
                with self.subTest(tk_scaling=scaling):
                    window = tk.Tk()
                    window.withdraw()
                    log = diagnostics.LocalDiagnostics(Path(temporary) / str(scaling))
                    try:
                        window.tk.call("tk", "scaling", scaling)
                        window.attributes("-alpha", 0.0)
                        app = guided_app.GuidedRatTrapApp(window, diagnostic_log=log)
                        # Transparent off-screen mapping obtains actual Tk
                        # layout only; no native desktop input/capture is used.
                        window.geometry("960x640+20000+20000")
                        window.deiconify()
                        window.update()
                        for tutorial_id, page, steps in (
                            ("compress", "Create archive", ("navigate", "load", "destination", "profile", "create", "finish")),
                            ("restore", "Extract archive", ("navigate", "load", "destination", "extract", "verify", "finish")),
                        ):
                            app.start_tutorial(tutorial_id)
                            app._go_to(page)
                            for step in steps:
                                app._set_tutorial_step(step)
                                window.update()
                                for button in (app.tutorial_next_button, app.tutorial_back_button, app.tutorial_exit_button):
                                    left = button.winfo_rootx() - window.winfo_rootx()
                                    top = button.winfo_rooty() - window.winfo_rooty()
                                    detail = f"{tutorial_id}/{step}, {scaling=}, {button.cget('text')}"
                                    self.assertTrue(button.winfo_ismapped(), detail)
                                    self.assertGreaterEqual(left, 0, detail)
                                    self.assertGreaterEqual(top, 0, detail)
                                    self.assertLessEqual(left + button.winfo_width(), window.winfo_width(), detail)
                                    self.assertLessEqual(top + button.winfo_height(), window.winfo_height(), detail)
                                self.assertGreaterEqual(app.page_scrollers[page].canvas.winfo_height(), 80)
                                target = app.tutorial_target
                                self.assertIsNotNone(target)
                                self.assertTrue(target.winfo_ismapped(), f"{tutorial_id}/{step}: target hidden")
                                if step != "navigate":
                                    canvas = app.page_scrollers[page].canvas
                                    left = target.winfo_rootx() - canvas.winfo_rootx()
                                    top = target.winfo_rooty() - canvas.winfo_rooty()
                                    detail = f"{tutorial_id}/{step}, scale={scaling}, target={target}, {left=}, {top=}"
                                    self.assertLess(left, canvas.winfo_width(), detail)
                                    self.assertLess(top, canvas.winfo_height(), detail)
                                    self.assertGreater(left + target.winfo_width(), 0, detail)
                                    self.assertGreater(top + target.winfo_height(), 0, detail)
                                    if isinstance(target, (ttk.Button, ttk.Combobox)):
                                        self.assertGreaterEqual(left, 0, detail)
                                        self.assertGreaterEqual(top, 0, detail)
                                        self.assertLessEqual(left + target.winfo_width(), canvas.winfo_width(), detail)
                                        self.assertLessEqual(top + target.winfo_height(), canvas.winfo_height(), detail)
                            app.tutorial_exit()
                    finally:
                        window.withdraw()
                        window.destroy()
                        log.close()


if __name__ == "__main__":
    unittest.main()
