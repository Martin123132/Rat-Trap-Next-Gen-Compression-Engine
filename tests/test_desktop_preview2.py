"""Preview 2 lifecycle and safe completion-action tests using hidden Tk windows."""

import dataclasses
import hashlib
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import desktop_preview2, diagnostics, gmw_tool, sealed_file, windows_app


def metadata(*, profile="balanced"):
    return gmw_tool.Metadata(
        format="GMW-VAULT-1" if profile == "vault" else "GMW-SOLID-2",
        chunk_size=0,
        compressor="zstd",
        checksum=None,
        checksum_algorithm="sha256",
        created_at=0,
        elapsed_seconds=0.1,
        file_count=4,
        total_bytes=128,
        profile=profile,
    )


class Preview2ValueTests(unittest.TestCase):
    def test_normalize_path_trims_one_double_quote_pair_without_expansion(self):
        cases = {
            "": "",
            " \t\n ": "",
            '  "C:\\Folder with spaces\\日本.gmw"  ': r"C:\Folder with spaces\日本.gmw",
            "  relative file.gmw  ": "relative file.gmw",
            '"%USERPROFILE%\\archive.gmw"': r"%USERPROFILE%\archive.gmw",
            '"~/archive.gmw"': "~/archive.gmw",
            "'single quoted.gmw'": "'single quoted.gmw'",
            '"unbalanced.gmw': '"unbalanced.gmw',
            'unbalanced.gmw"': 'unbalanced.gmw"',
            '""nested.gmw""': '"nested.gmw"',
        }
        for given, expected in cases.items():
            with self.subTest(given=given):
                self.assertEqual(desktop_preview2.normalize_path_text(given), expected)

    def test_elapsed_format_handles_minutes_and_hours(self):
        for seconds, expected in ((0, "00:00"), (0.9, "00:00"), (59, "00:59"),
                                  (65, "01:05"), (3599, "59:59"),
                                  (3600, "1:00:00"), (3665, "1:01:05")):
            with self.subTest(seconds=seconds):
                self.assertEqual(desktop_preview2.format_elapsed(seconds), expected)

    def test_completed_output_is_a_frozen_dataclass(self):
        output = desktop_preview2.CompletedOutput(
            Path("result.gmw"), "archive", "Archive ready", "Four files"
        )
        self.assertTrue(dataclasses.is_dataclass(output))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            output.path = Path("replaced.gmw")

    @unittest.skipUnless(os.name == "nt", "Windows folder reveal implementation")
    def test_reveal_helper_opens_parent_directory_never_plaintext_executable(self):
        with tempfile.TemporaryDirectory(prefix="preview2-reveal-") as temporary:
            folder = Path(temporary)
            restored = folder / "restored-program.exe"
            restored.write_bytes(b"Inert generated test bytes, not a program")
            with mock.patch.object(os, "startfile") as startfile:
                desktop_preview2.reveal_in_folder(restored)
            startfile.assert_called_once()
            self.assertEqual(Path(startfile.call_args.args[0]), folder)
            self.assertNotEqual(Path(startfile.call_args.args[0]), restored)
            self.assertEqual(startfile.call_args.args[1], "explore")
            with mock.patch.object(os, "startfile") as startfile:
                desktop_preview2.reveal_in_folder(folder)
            self.assertEqual(Path(startfile.call_args.args[0]), folder)


class DesktopPreview2Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-preview2-test-")
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
        self.app = desktop_preview2.DesktopPreview2App(self.root, diagnostic_log=self.log)
        self.root.update_idletasks()
        self.error = self.enterContext(mock.patch.object(windows_app.messagebox, "showerror"))
        self.warning = self.enterContext(mock.patch.object(windows_app.messagebox, "showwarning"))
        self.info = self.enterContext(mock.patch.object(windows_app.messagebox, "showinfo"))
        for name in ("askopenfilename", "asksaveasfilename", "askdirectory"):
            self.enterContext(mock.patch.object(windows_app.filedialog, name, return_value=""))
        self.enterContext(mock.patch.object(windows_app.simpledialog, "askstring", return_value=None))
        self.enterContext(mock.patch.object(windows_app.messagebox, "askyesno", return_value=False))
        self.enterContext(mock.patch.object(windows_app.messagebox, "askyesnocancel", return_value=None))
        self.recorded_errors = self.enterContext(mock.patch.object(
            self.app, "_record_ui_exception", wraps=self.app._record_ui_exception
        ))
        self.reveal = self.enterContext(mock.patch.object(desktop_preview2, "reveal_in_folder"))
        if hasattr(os, "startfile"):
            self.startfile = self.enterContext(mock.patch.object(os, "startfile"))

    def tearDown(self):
        if hasattr(self, "app") and self.app.busy:
            self.wait_until_idle(timeout=5)
        if hasattr(self, "root"):
            for timer in self.root.tk.call("after", "info"):
                self.root.after_cancel(timer)

    def wait_until_idle(self, timeout=15):
        deadline = time.perf_counter() + timeout
        while self.app.busy and time.perf_counter() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.root.update_idletasks()
        self.assertFalse(self.app.busy, "Preview task did not become idle")

    def create_fake_archive_result(self, name="result.gmw", *, done=None, profile="balanced"):
        output = self.base / name
        output.write_bytes(b"Generated result-card fixture; not a real archive")
        self.app.create_archive.set(str(output))
        result = metadata(profile=profile)
        callback = mock.Mock() if done is None else done
        self.app._run_task("Creating archive...", lambda: result, callback)
        self.wait_until_idle()
        return output, result, callback

    def assert_no_completion(self):
        self.assertIsNone(self.app.last_output)
        self.assertFalse(self.app.completion_frame.winfo_manager())

    def test_preview_label_and_initial_completion_card_state(self):
        self.assertEqual(desktop_preview2.PREVIEW_LABEL, "Desktop Preview 2")
        self.assertIn(desktop_preview2.PREVIEW_LABEL, self.root.title())
        self.assert_no_completion()
        self.assertIn(self.app.activity_elapsed.get(), ("", "00:00", "Elapsed 00:00"))

    def test_archive_success_calls_original_done_before_publishing_without_auto_open(self):
        observed = []

        def done(result):
            observed.append((self.app.last_output, self.app.busy, result))

        path, result, _ = self.create_fake_archive_result(done=done)
        self.assertEqual(observed, [(None, False, result)])
        self.assertEqual(self.app.last_output.path, path.resolve())
        self.assertEqual(self.app.last_output.kind, "archive")
        self.assertEqual(self.app.result_path.get(), str(path.resolve()))
        self.assertTrue(self.app.result_summary.get())
        self.assertTrue(self.app.completion_frame.winfo_manager())
        self.assertNotEqual(str(self.app.open_result_button.cget("state")), "disabled")
        self.reveal.assert_not_called()
        if hasattr(self, "startfile"):
            self.startfile.assert_not_called()

    def test_task_context_captures_absolute_destination_not_later_entry_edits(self):
        original = self.base / "original destination.gmw"
        changed = self.base / "edited destination.gmw"
        original.write_bytes(b"generated")
        self.app.create_archive.set(f'  "{original}"  ')
        context = self.app._capture_task_context("Creating archive...")
        self.assertEqual(context.operation, "archive_create")
        self.assertEqual(context.path, original.resolve())
        release = threading.Event()
        started = threading.Event()

        def work():
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test release timed out")
            return metadata()

        try:
            self.app._run_task("Creating archive...", work, lambda _result: None)
            self.assertTrue(started.wait(1))
            self.app.create_archive.set(str(changed))
        finally:
            release.set()
            self.wait_until_idle()
        self.assertEqual(context.path, original.resolve())
        self.assertEqual(self.app.last_output.path, original.resolve())

    def test_capture_context_maps_only_known_output_operations(self):
        pairs = (
            ("Creating archive...", "archive_create", self.app.create_archive),
            ("Extracting files...", "archive_extract", self.app.extract_folder),
            ("Protecting and verifying file...", "sealed_create", self.app.seal_output),
            ("Restoring and verifying plaintext copy...", "sealed_restore", self.app.unseal_destination),
        )
        for label, operation, variable in pairs:
            with self.subTest(operation=operation):
                path = self.base / operation
                variable.set(str(path))
                captured = self.app._capture_task_context(label)
                self.assertEqual(captured.operation, operation)
                self.assertEqual(captured.path, path.resolve())
        self.assertIsNone(self.app._capture_task_context("Unknown background operation...").path)

    def test_failed_worker_does_not_call_done_or_publish_completion(self):
        self.create_fake_archive_result()
        done = mock.Mock()

        def fail():
            raise ValueError("Generated worker failure")

        self.app._run_task("Creating archive...", fail, done)
        self.assert_no_completion()
        self.wait_until_idle()
        done.assert_not_called()
        self.assert_no_completion()
        self.error.assert_called_once()

    def test_failed_done_callback_cannot_publish_a_success_card(self):
        def fail_done(_result):
            raise RuntimeError("Generated completion callback failure")

        self.create_fake_archive_result(done=fail_done)
        self.assert_no_completion()
        self.error.assert_called_once()

    def test_unknown_result_types_and_exception_values_never_publish_cards(self):
        path = self.base / "exists.gmw"
        path.write_bytes(b"generated")
        self.app.create_archive.set(str(path))
        for result in (None, object(), ValueError("exception as a value"), {"path": str(path)}):
            with self.subTest(result_type=type(result).__name__):
                done = mock.Mock()
                self.app._run_task("Creating archive...", lambda current=result: current, done)
                self.wait_until_idle()
                done.assert_called_once_with(result)
                self.assert_no_completion()

    def test_unrelated_operations_never_publish_even_if_result_is_metadata(self):
        for label in ("Searching Vault...", "Creating repository snapshot...", "Protecting folder...", "Unknown task..."):
            with self.subTest(label=label):
                self.app._run_task(label, metadata, lambda _result: None)
                self.wait_until_idle()
                self.assert_no_completion()

    def test_chained_task_does_not_receive_previous_completion_card(self):
        first = self.base / "first.gmw"
        second = self.base / "second.gmw"
        first.write_bytes(b"first generated fixture")
        second.write_bytes(b"second generated fixture")
        self.app.create_archive.set(str(first))
        release = threading.Event()
        second_started = threading.Event()

        def second_work():
            second_started.set()
            if not release.wait(5):
                raise RuntimeError("Chained test release timed out")
            return metadata()

        def first_done(_result):
            self.app.create_archive.set(str(second))
            self.app._run_task("Creating archive...", second_work, lambda _value: None)

        try:
            self.app._run_task("Creating archive...", metadata, first_done)
            deadline = time.perf_counter() + 3
            while not second_started.is_set() and time.perf_counter() < deadline:
                self.root.update()
                time.sleep(0.005)
            self.assertTrue(second_started.is_set())
            self.assertTrue(self.app.busy)
            self.assert_no_completion()
        finally:
            release.set()
            self.wait_until_idle()
        self.assertEqual(self.app.last_output.path, second.resolve())

    def test_open_result_preselects_archive_in_app_without_reading_or_extracting(self):
        path, _, _ = self.create_fake_archive_result()
        with mock.patch.object(self.app, "_load_details") as load, mock.patch.object(
            self.app, "_run_task"
        ) as run_task:
            self.app._open_result()
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Inspect / export"]))
        self.assertEqual(self.app.inspect_archive.get(), str(path.resolve()))
        load.assert_not_called()
        run_task.assert_not_called()
        self.reveal.assert_not_called()

    def test_reveal_result_is_explicit_and_missing_result_is_rechecked(self):
        path, _, _ = self.create_fake_archive_result()
        self.app._show_result_folder()
        self.reveal.assert_called_once_with(path.resolve())
        self.reveal.reset_mock()
        path.unlink()
        with mock.patch.object(self.app, "apply_launch_request") as launch:
            self.app._open_result()
            self.app._show_result_folder()
        self.assertGreaterEqual(self.warning.call_count, 1)
        launch.assert_not_called()
        self.reveal.assert_not_called()

    def test_vault_output_only_preselects_search_and_never_starts_a_query(self):
        path, _, _ = self.create_fake_archive_result("queryable.vault.gmw", profile="vault")
        self.assertEqual(self.app.last_output.kind, "vault")
        with mock.patch.object(self.app, "_start_vault_search") as search, mock.patch.object(
            self.app, "_show_all_vault"
        ) as show_all, mock.patch.object(self.app, "_run_task") as run_task:
            self.app._open_result()
        self.assertEqual(self.app.tabs.select(), str(self.app.pages["Search Vault"]))
        self.assertEqual(self.app.vault_archive.get(), str(path.resolve()))
        self.assertEqual(self.app.data_archive.get(), str(path.resolve()))
        search.assert_not_called()
        show_all.assert_not_called()
        run_task.assert_not_called()
        self.reveal.assert_not_called()

    def test_busy_result_actions_never_launch_or_reveal(self):
        self.create_fake_archive_result()
        self.app.busy = True
        try:
            with mock.patch.object(self.app, "apply_launch_request") as launch:
                self.app._open_result()
                self.app._show_result_folder()
            launch.assert_not_called()
            self.reveal.assert_not_called()
        finally:
            self.app.busy = False

    def test_real_four_file_archive_round_trip_updates_cards_and_preserves_bytes(self):
        source = self.base / "four files 日本"
        source.mkdir()
        expected = {
            "hello.txt": b"hello preview two\n" * 128,
            "notes été.txt": "Unicode sample 日本".encode("utf-8"),
            "nested/data.csv": b"name,value\nalpha,1\nbeta,2\n",
            "nested/sample.bin": bytes(range(256)),
        }
        for relative, data in expected.items():
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        archive = self.base / "four files.gmw"
        restored = self.base / "restored folder"
        self.app.source_folder.set(f'  "{source}"  ')
        self.app.create_archive.set(f'  "{archive}"  ')
        self.app._start_create()
        self.wait_until_idle()
        self.error.assert_not_called()
        self.assertEqual(self.app.last_output.path, archive.resolve())
        self.assertEqual(self.app.last_output.kind, "archive")
        self.app.extract_archive.set(f'  "{archive}"  ')
        self.app.extract_folder.set(f'  "{restored}"  ')
        self.app._start_extract()
        self.wait_until_idle()
        self.error.assert_not_called()
        self.assertEqual(self.app.last_output.path, restored.resolve())
        self.assertEqual(self.app.last_output.kind, "folder")
        self.assertEqual(str(self.app.open_result_button.cget("state")), "disabled")
        for relative, data in expected.items():
            self.assertEqual(hashlib.sha256((restored / relative).read_bytes()).digest(), hashlib.sha256(data).digest())
        self.reveal.assert_not_called()

    def test_real_sealed_round_trip_never_opens_restored_executable(self):
        source = self.base / "plaintext" / "inert restored example.exe"
        source.parent.mkdir()
        contents = b"Generated inert text fixture. This is not executable code.\n" * 16
        source.write_bytes(contents)
        output = self.base / "sealed" / sealed_file.default_sealed_name()
        output.parent.mkdir()
        key = self.base / "independent keys" / "sample.rtrk"
        key.parent.mkdir()
        password = "Generated preview test password 2026!"
        self.app.seal_source.set(f'  "{source}"  ')
        self.app.seal_output.set(f'  "{output}"  ')
        with mock.patch.object(self.app, "_new_sealed_credentials", return_value={
            "password": password, "recovery_key_output": key,
            "allow_plaintext_temp": True,
        }):
            self.app._start_seal_file()
            self.wait_until_idle()
        self.assertFalse(self.error.called, [str(call.args[1]) for call in self.recorded_errors.call_args_list])
        self.assertEqual(self.app.last_output.path, output.resolve())
        self.assertEqual(self.app.last_output.kind, "sealed")
        with mock.patch.object(self.app, "_run_task") as run_task:
            self.app._open_result()
        run_task.assert_not_called()
        self.assertEqual(self.app.unseal_source.get(), str(output.resolve()))
        self.app.unseal_destination.set(str(self.base / "restored plaintext"))
        with mock.patch.object(self.app, "_sealed_access", return_value={
            "password": password, "allow_plaintext_temp": True, "allow_plaintext_output": True,
        }):
            self.app._start_unseal_file()
            self.wait_until_idle()
        self.error.assert_not_called()
        restored = self.base / "restored plaintext" / source.name
        self.assertEqual(restored.read_bytes(), contents)
        self.assertEqual(self.app.last_output.path, restored.resolve())
        self.assertEqual(str(self.app.open_result_button.cget("state")), "disabled")
        self.app._open_result()
        self.reveal.assert_not_called()
        if hasattr(self, "startfile"):
            self.startfile.assert_not_called()
        self.app._show_result_folder()
        self.reveal.assert_called_once_with(restored.resolve())

    def test_restored_executable_output_is_reveal_only(self):
        restored = self.base / "generated restored program.exe"
        restored.write_bytes(b"Inert generated fixture, not executable code")
        self.app._publish_completion(desktop_preview2.CompletedOutput(
            restored, "file", "File restored", "Generated restored plaintext fixture"
        ))
        self.assertEqual(str(self.app.open_result_button.cget("state")), "disabled")
        with mock.patch.object(self.app, "_preselect_output_path") as select:
            self.app._open_result()
        select.assert_not_called()
        self.reveal.assert_not_called()
        if hasattr(self, "startfile"):
            self.startfile.assert_not_called()
        self.app._show_result_folder()
        self.reveal.assert_called_once_with(restored)

    def test_elapsed_clock_is_frozen_before_original_completion_dialog(self):
        path = self.base / "clock result.gmw"
        path.write_bytes(b"generated")
        self.app.create_archive.set(str(path))
        clock = [100.0]
        observed = []

        def done(_result):
            observed.append(self.app.activity_elapsed.get())
            clock[0] = 999.0  # Time spent reading a completion dialog is excluded.

        with mock.patch.object(desktop_preview2.time, "monotonic", side_effect=lambda: clock[0]):
            self.app._run_task("Creating archive...", metadata, done)
            self.assertEqual(self.app.activity_elapsed.get(), "Elapsed 00:00")
            self.assertIn("percentage", self.app.activity_hint.get().lower())
            clock[0] = 165.0
            self.wait_until_idle()
            self.assertEqual(observed, ["Elapsed 01:05"])
            self.assertEqual(self.app.activity_elapsed.get(), "Elapsed 01:05")
            self.assertIsNone(self.app._activity_after_id)

    def test_old_timer_and_stop_callbacks_cannot_mutate_new_activity(self):
        self.create_fake_archive_result("older.gmw")
        old_token = self.app._activity_token
        release = threading.Event()
        started = threading.Event()

        def work():
            started.set()
            if not release.wait(5):
                raise RuntimeError("Stale timer test release timed out")
            return metadata()

        self.app.create_archive.set(str(self.base / "current.gmw"))
        try:
            self.app._run_task("Creating archive...", work, lambda _result: None)
            self.assertTrue(started.wait(1))
            current_token = self.app._activity_token
            self.assertIsNot(current_token, old_token)
            before = (
                self.app.activity_title.get(), self.app.activity_elapsed.get(),
                self.app.activity_hint.get(), self.app._activity_after_id,
            )
            self.app._tick_activity(old_token)
            self.app._stop_activity_clock(old_token)
            self.assertEqual((
                self.app.activity_title.get(), self.app.activity_elapsed.get(),
                self.app.activity_hint.get(), self.app._activity_after_id,
            ), before)
            self.assertIs(self.app._activity_token, current_token)
        finally:
            release.set()
            self.wait_until_idle()

    def test_failed_task_clock_excludes_time_spent_reading_error_dialog(self):
        clock = [100.0]

        def fail():
            raise ValueError("Generated failure for elapsed-clock test")

        def show_error(*_args, **_kwargs):
            clock[0] = 999.0

        with mock.patch.object(desktop_preview2.time, "monotonic", side_effect=lambda: clock[0]):
            self.error.side_effect = show_error
            self.app._run_task("Creating archive...", fail, lambda _result: None)
            clock[0] = 165.0
            self.wait_until_idle()
            self.assertEqual(self.app.activity_elapsed.get(), "Elapsed 01:05")
            self.assertIsNone(self.app._activity_after_id)
        self.assert_no_completion()

    def test_root_destroy_handler_cancels_only_current_timer(self):
        token = object()
        timer = self.root.after(60000, lambda: None)
        self.app._activity_token = token
        self.app._activity_after_id = timer
        with mock.patch.object(self.root, "after_cancel", wraps=self.root.after_cancel) as cancel:
            self.app._root_destroyed(mock.Mock(widget=self.app.pages["Home"]))
            cancel.assert_not_called()
            self.app._root_destroyed(mock.Mock(widget=self.root))
            cancel.assert_called_once_with(timer)
        self.assertIsNone(self.app._activity_after_id)
        self.assertIsNone(self.app._activity_token)

    def test_worker_exit_without_queued_result_clears_working_activity(self):
        done = mock.Mock()
        self.app._run_task("Creating archive...", metadata, done)
        token = self.app._task_token
        self.app._worker_thread.join(timeout=2)
        self.assertFalse(self.app._worker_thread.is_alive())
        self.app._task_events.get_nowait()  # Simulate a lost completion event.
        self.app._poll_task_events(token)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.activity_title.get(), "Needs attention")
        self.assertNotEqual(self.app._activity_outcome, "working")
        self.assertIsNone(self.app._activity_after_id)
        self.assert_no_completion()
        done.assert_not_called()
        self.error.assert_called_once()

    def test_live_monitor_failure_remains_busy_with_an_honest_hint(self):
        release = threading.Event()
        started = threading.Event()

        def work():
            started.set()
            if not release.wait(5):
                raise RuntimeError("Monitor test release timed out")
            return metadata()

        try:
            self.app._run_task("Creating archive...", work, lambda _result: None)
            self.assertTrue(started.wait(1))
            self.app._task_monitor_failed = True
            timer = self.app._activity_after_id
            if timer is not None:
                self.root.after_cancel(timer)
                self.app._activity_after_id = None
            self.app._tick_activity(self.app._activity_token)
            self.assertTrue(self.app.busy)
            self.assertIn("interrupted", self.app.activity_hint.get())
            self.assertIn("keep Rat-Trap open", self.app.activity_hint.get())
            self.assert_no_completion()
        finally:
            release.set()
            self.wait_until_idle()

    def test_idle_timer_fallback_cannot_leave_a_working_status(self):
        self.app._activity_token = object()
        self.app._activity_outcome = "working"
        self.app.activity_title.set("Working")
        self.app._tick_activity(self.app._activity_token)
        self.assertEqual(self.app.activity_title.get(), "Needs attention")
        self.assertNotEqual(self.app._activity_outcome, "working")
        self.assertIsNone(self.app._activity_after_id)

    @unittest.skipUnless(os.name == "nt", "Windows hidden Tk footer geometry")
    def test_completion_actions_remain_reachable_in_small_windows(self):
        for scaling in (1.333, 2.0, 2.667):
            with self.subTest(tk_scaling=scaling):
                window = tk.Tk()
                window.withdraw()
                log = diagnostics.LocalDiagnostics(self.base / f"footer-{scaling}")
                try:
                    window.tk.call("tk", "scaling", scaling)
                    window.attributes("-alpha", 0.0)
                    app = desktop_preview2.DesktopPreview2App(window, diagnostic_log=log)
                    window.geometry("960x640+20000+20000")
                    window.deiconify()
                    app._publish_completion(desktop_preview2.CompletedOutput(
                        self.base / "example.gmw", "archive", "Archive ready",
                        "4 files. Generated output is ready for the next action.",
                    ))
                    window.update()
                    for widget in (app.result_path_entry, app.open_result_button, app.reveal_result_button):
                        top = widget.winfo_rooty() - window.winfo_rooty()
                        bottom = top + widget.winfo_height()
                        left = widget.winfo_rootx() - window.winfo_rootx()
                        right = left + widget.winfo_width()
                        detail = f"scaling={scaling}, widget={widget}, bounds={left},{top},{right},{bottom}"
                        self.assertTrue(widget.winfo_ismapped(), detail)
                        self.assertGreaterEqual(top, 0, detail)
                        self.assertLessEqual(bottom, window.winfo_height(), detail)
                        self.assertGreaterEqual(left, 0, detail)
                        self.assertLessEqual(right, window.winfo_width(), detail)
                finally:
                    window.withdraw()
                    window.destroy()
                    log.close()

    def test_focus_out_normalizes_quoted_paths_without_expansion(self):
        for variable in (self.app.source_folder, self.app.create_archive):
            with self.subTest(variable=str(variable)):
                variable.set('  "%USERPROFILE%\\sample 日本"  ')
                entry = self.app.path_entries[str(variable)]
                self.assertTrue(entry.bind("<FocusOut>"))
                entry.event_generate("<FocusOut>")
                self.root.update_idletasks()
                self.assertEqual(variable.get(), r"%USERPROFILE%\sample 日本")
        self.app.busy = True
        self.app.source_folder.set('  "active source"  ')
        self.app._normalize_path_variable(self.app.source_folder)
        self.assertEqual(self.app.source_folder.get(), '  "active source"  ')
        self.app.busy = False

    def test_cancelled_source_and_output_pickers_preserve_values_and_session_memory(self):
        remembered = self.base / "remembered"
        remembered.mkdir()
        self.app._remember_selection(str(remembered), directory=True)
        self.app.source_folder.set('  "existing source"  ')
        self.app.create_archive.set('  "custom output.gmw"  ')
        before = (self.app.source_folder.get(), self.app.create_archive.get(), self.app._picker_directory)
        with mock.patch.object(windows_app.filedialog, "askdirectory", return_value=""), mock.patch.object(
            windows_app.filedialog, "asksaveasfilename", return_value=""
        ):
            self.app._choose_source()
            self.app._choose_create_archive()
        self.assertEqual((self.app.source_folder.get(), self.app.create_archive.get(), self.app._picker_directory), before)

    def test_source_selection_follows_quoted_auto_output_but_preserves_quoted_custom(self):
        previous = self.base / "previous source"
        selected = self.base / "new source 日本"
        selected.mkdir()
        for current, expected in (
            (previous.parent / (previous.name + ".gmw"), selected.parent / (selected.name + ".gmw")),
            (self.base / "custom output.gmw", self.base / "custom output.gmw"),
        ):
            with self.subTest(current=current):
                self.app.source_folder.set(f'  "{previous}"  ')
                self.app.create_archive.set(f'  "{current}"  ')
                with mock.patch.object(windows_app.filedialog, "askdirectory", return_value=str(selected)):
                    self.app._choose_source()
                self.assertEqual(self.app.source_folder.get(), str(selected))
                self.assertEqual(self.app.create_archive.get(), str(expected))

    def test_ordinary_picker_memory_is_reused_without_becoming_persistent(self):
        directory = self.base / "ordinary files"
        directory.mkdir()
        selected = directory / "selected.gmw"
        with mock.patch.object(windows_app.filedialog, "askopenfilename", return_value=str(selected)):
            self.app._open_existing()
        self.assertEqual(self.app._picker_directory, directory)
        with mock.patch.object(windows_app.filedialog, "askopenfilename", return_value="") as picker:
            self.app._open_existing()
        self.assertEqual(Path(picker.call_args.kwargs["initialdir"]), directory)
        self.assertEqual(self.app._picker_initial_directory(), str(directory))
        fresh = desktop_preview2.DesktopPreview2App.__new__(desktop_preview2.DesktopPreview2App)
        fresh._picker_directory = None
        self.assertIsNone(fresh._picker_initial_directory())

    def test_recovery_dialogs_do_not_consult_or_change_ordinary_picker_memory(self):
        remembered = self.base / "ordinary files"
        remembered.mkdir()
        self.app._remember_selection(str(remembered), directory=True)
        output = self.base / "sealed" / sealed_file.default_sealed_name()
        with mock.patch.object(self.app, "_picker_initial_directory") as initial, mock.patch.object(
            self.app, "_remember_selection"
        ) as remember, mock.patch.object(windows_app.filedialog, "asksaveasfilename", return_value="") as picker:
            self.assertIsNone(self.app._new_sealed_credentials(output))
        initial.assert_not_called()
        remember.assert_not_called()
        self.assertEqual(self.app._picker_directory, remembered)
        self.assertNotEqual(picker.call_args.kwargs.get("initialdir"), str(remembered))


if __name__ == "__main__":
    unittest.main()
