"""Sample-only protection lessons on internal, hidden Tk controls."""

import hashlib
import json
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from rat_trap import desktop_preview2, diagnostics, guided_app, protection_tutorials, tutorials, windows_app


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProtectionGuidedTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-protection-guided-test-")
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
        create_practice = protection_tutorials.create_practice
        self.enterContext(mock.patch.object(
            protection_tutorials, "create_practice", side_effect=lambda parent=None: create_practice(self.base)
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
        self.assertFalse(self.app.busy, "Protection practice worker did not finish")

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
        self.assertTrue(self.app.start_tutorial("protect"))
        self.assertEqual(self.app.tutorial_step, "navigate")
        self.app.nav_buttons["Secure files"].invoke()
        self.assertEqual(self.app.tutorial_step, "load")
        self.app.protection_source_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "destination")
        self.retained_demos.append(self.app.tutorial_demo)
        return self.app.tutorial_demo

    def reach_seal(self):
        demo = self.load()
        self.app.protection_output_button.invoke()
        self.assertEqual(self.app.tutorial_step, "password")
        self.app.protection_password_check.invoke()
        self.assertTrue(self.app.protection_password_ack.get())
        self.assertTrue(self.app.tutorial_next())
        self.assertEqual(self.app.tutorial_step, "key")
        self.app.protection_key_button.invoke()
        self.assertEqual(self.app.tutorial_step, "seal")
        return demo

    def reach_open(self):
        demo = self.reach_seal()
        self.app.protection_seal_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "open")
        return demo

    def reach_password_restore(self):
        demo = self.reach_open()
        self.assertTrue(self.app.tutorial_next())
        self.assertEqual(self.app.tutorial_step, "restore-load")
        self.app.protection_restore_source_button.invoke()
        self.assertEqual(self.app.tutorial_step, "restore-destination")
        self.app.protection_restore_destination_button.invoke()
        self.assertEqual(self.app.tutorial_step, "password-restore")
        return demo

    def reach_recovery(self):
        demo = self.reach_password_restore()
        self.app.protection_restore_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "recovery")
        return demo

    def reach_verify(self):
        demo = self.reach_recovery()
        self.app.protection_recovery_button.invoke()
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

    def snapshot(self):
        names = ("seal_source", "seal_output", "unseal_source", "unseal_destination", "bulk_seal_source",
                 "bulk_seal_output", "bulk_recovery_output", "encrypt_created_archive", "protection_password_ack",
                 "status_text", "activity_title", "activity_elapsed", "activity_hint", "result_path", "result_summary")
        buttons = ("protection_source_button", "protection_output_button", "protection_restore_source_button",
                   "protection_restore_destination_button", "protection_restore_button")
        return {
            "variables": {name: getattr(self.app, name).get() for name in names},
            "page": self.app.tabs.select(), "mode": self.app.secure_modes.select(),
            "output": self.app.last_output, "picker": self.app._picker_directory,
            "buttons": {name: getattr(self.app, name).cget("text") for name in buttons},
            "completion": bool(self.app.completion_frame.winfo_manager()),
        }

    def seed_state(self):
        fixture = self.base / "unrelated generated fixture.txt"
        fixture.write_bytes(b"Generated unrelated file; leave unchanged")
        for index, name in enumerate(("seal_source", "seal_output", "unseal_source", "unseal_destination",
                                      "bulk_seal_source", "bulk_seal_output", "bulk_recovery_output")):
            getattr(self.app, name).set(f'"{self.base / ("prior chosen path " + str(index))}"')
        self.app.encrypt_created_archive.set(True)
        self.app.protection_password_ack.set(True)
        self.app.secure_modes.select(self.app.secure_bulk_mode)
        self.app._go_to("Inspect / export")
        self.app._picker_directory = self.base
        self.app._publish_completion(desktop_preview2.CompletedOutput(fixture, "file", "Prior result", "Keep this result"))
        self.app.status_text.set("Prior status")
        self.app.activity_title.set("Prior activity")
        self.app.activity_hint.set("Prior hint")
        return fixture, self.snapshot()

    def ui_text(self):
        pieces = []
        for widget in guided_app._descendants(self.root):
            if isinstance(widget, tk.Text):
                pieces.append(widget.get("1.0", "end-1c"))
            for option in ("text", "textvariable"):
                try:
                    value = widget.cget(option)
                    if option == "textvariable" and value:
                        value = self.root.getvar(value)
                    pieces.append(str(value))
                except tk.TclError:
                    pass
        return "\n".join(pieces)

    def test_real_seal_password_restore_and_key_only_recovery_verified_then_prior_state_restored(self):
        fixture, before = self.seed_state()
        original = digest(fixture)
        with mock.patch.object(windows_app.sealed_file, "seal_file", wraps=windows_app.sealed_file.seal_file) as seal:
            demo = self.reach_open()
        seal.assert_called_once()
        password = demo.practice_password
        self.assertGreaterEqual(len(password), 15)
        self.assertTrue(demo.source_is_intact())
        self.assertTrue(demo.sealed_is_intact())
        self.assertTrue(demo.key_is_intact())
        self.assertNotEqual(demo.sealed.parent, demo.recovery_key.parent)
        self.assertNotIn(password, self.ui_text())
        key_text = demo.recovery_key.read_text(encoding="utf-8")
        key_material = json.loads(key_text)["recovery_key"]
        self.assertNotIn(key_text.strip(), self.ui_text())
        self.assertNotIn(key_material, self.ui_text())
        self.app.tutorial_next()
        self.app.protection_restore_source_button.invoke()
        self.app.protection_restore_destination_button.invoke()
        with mock.patch.object(windows_app.sealed_file, "unseal_file", wraps=windows_app.sealed_file.unseal_file) as restore:
            self.app.protection_restore_button.invoke()
            self.wait_idle()
        restore.assert_called_once()
        self.assertEqual(restore.call_args.kwargs["password"], password)
        self.assertNotIn("recovery_key", restore.call_args.kwargs)
        self.assertEqual(self.app.tutorial_step, "recovery")
        with mock.patch.object(windows_app.sealed_file, "unseal_file", wraps=windows_app.sealed_file.unseal_file) as recovery:
            self.app.protection_recovery_button.invoke()
            self.wait_idle()
        recovery.assert_called_once()
        self.assertEqual(recovery.call_args.kwargs["recovery_key"], demo.recovery_key)
        self.assertNotIn("password", recovery.call_args.kwargs)
        self.assertEqual(self.app.tutorial_step, "verify")
        self.assertFalse(self.app.tutorial_next())
        for directory in (demo.password_output, demo.recovery_output):
            self.assertEqual((directory / protection_tutorials.PRACTICE_NAME).read_bytes(), protection_tutorials.PRACTICE_BYTES)
            self.assertNotEqual(directory, demo.source.parent)
        self.app.protection_verify_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "finish")
        self.assertIn("sha-256", self.app.protection_restore_result.get("1.0", "end-1c").lower())
        self.assert_no_external_actions()
        self.assertNotIn(password, self.ui_text())
        self.assertNotIn(key_text.strip(), self.ui_text())
        self.assertNotIn(key_material, self.ui_text())
        with mock.patch.object(self.root, "clipboard_clear"), mock.patch.object(self.root, "clipboard_append") as clipboard:
            self.app._copy_support_details()
        support = "\n".join(str(call.args[0]) for call in clipboard.call_args_list)
        self.assertNotIn(password, support)
        self.assertNotIn(key_text.strip(), support)
        self.assertNotIn(key_material, support)
        logged = "\n".join(path.read_text(encoding="utf-8") for path in (self.base / "diagnostics").rglob("*") if path.is_file())
        self.assertNotIn(password, logged)
        self.assertNotIn(key_text.strip(), logged)
        self.assertNotIn(key_material, logged)
        self.app.tutorial_next_button.invoke()
        self.assertFalse(self.app.tutorial_active)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(digest(fixture), original)
        self.assertFalse(demo.root.exists())
        self.assertEqual(demo.practice_password, "")

    def test_exit_restores_all_secure_paths_mode_checkbox_and_prior_acknowledgment(self):
        fixture, before = self.seed_state()
        demo = self.load()
        self.assertFalse(self.app.protection_password_ack.get())
        self.app.tutorial_exit_button.invoke()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(fixture.exists())
        self.assertFalse(demo.root.exists())
        self.assertEqual(demo.practice_password, "")

    def test_password_acknowledgement_is_explicit_and_cannot_skip_to_seal(self):
        self.load()
        self.app.protection_output_button.invoke()
        self.assertEqual(self.app.tutorial_step, "password")
        self.assertFalse(self.app.protection_password_ack.get())
        self.assertFalse(self.app.tutorial_next())
        self.app._start_seal_file()
        self.app._select_practice_key()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tutorial_step, "password")
        self.assertTrue(self.app.protection_seal_button.instate(["disabled"]))
        self.assert_no_external_actions()

    def test_nested_notebook_and_unrelated_callbacks_remain_gated(self):
        self.load()
        selected = self.app.secure_modes.select()
        self.app.secure_modes.select(self.app.secure_bulk_mode)
        self.app.secure_modes.select(self.app.secure_restore_mode)
        self.assertEqual(self.app.secure_modes.select(), selected)
        page = self.app.tabs.select()
        self.app._home_protect()
        self.app._home_restore()
        self.app._shortcut_page("Home")
        self.app.tabs.select(self.app.pages["Extract archive"])
        self.app.apply_launch_request(windows_app.LaunchRequest("open-sealed", self.base / "unrelated.rtsf"))
        for action in ("_choose_bulk_seal_source", "_choose_bulk_seal_output", "_choose_bulk_recovery_output",
                       "_start_seal_folder", "_start_verify_sealed", "_start_create", "_start_extract",
                       "_choose_source", "_choose_extract_archive", "_open_result", "_show_result_folder"):
            getattr(self.app, action)()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tabs.select(), page)
        self.assertEqual(self.app.tutorial_step, "destination")
        self.assert_no_external_actions()

    def test_every_step_enables_only_current_control_and_coach_actions(self):
        self.app.start_tutorial("protect")
        self.app._go_to("Secure files")
        for step in tutorials.STEPS_BY_ID["protect"]:
            with self.subTest(step=step.id):
                self.app._set_tutorial_step(step.id)
                for widget in guided_app._descendants(self.root):
                    if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Entry, ttk.Combobox)) and not widget.instate(["disabled"]):
                        self.assertIn(widget, (self.app.tutorial_target, self.app.tutorial_back_button,
                                               self.app.tutorial_next_button, self.app.tutorial_exit_button))
                for entry in self.app.path_entries.values():
                    before = entry.get()
                    entry.insert("end", "forbidden typed edit")
                    self.assertEqual(entry.get(), before)

    def test_seal_refuses_changed_source_or_output_selection_before_engine(self):
        demo = self.reach_seal()
        for field in ("seal_source", "seal_output"):
            with self.subTest(field=field):
                original = getattr(self.app, field).get()
                getattr(self.app, field).set(str(self.base / "never selected personal fixture"))
                with mock.patch.object(windows_app.sealed_file, "seal_file") as seal:
                    self.app.protection_seal_button.invoke()
                    self.wait_idle()
                seal.assert_not_called()
                self.assertEqual(self.app.tutorial_step, "seal")
                self.assertFalse(demo.sealed.exists())
                getattr(self.app, field).set(original)
        self.assert_no_external_actions()

    def test_seal_refuses_changed_sample_bytes_and_preserves_them_on_exit(self):
        demo = self.reach_seal()
        demo.source.write_bytes(b"User-added modification to generated fixture")
        with mock.patch.object(windows_app.sealed_file, "seal_file") as seal:
            self.app.protection_seal_button.invoke()
            self.wait_idle()
        seal.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "seal")
        self.app.tutorial_exit()
        self.assertTrue(demo.source.exists())
        self.assertEqual(demo.source.read_bytes(), b"User-added modification to generated fixture")

    def test_restore_refuses_changed_sealed_or_destination_selection_before_engine(self):
        demo = self.reach_password_restore()
        for field in ("unseal_source", "unseal_destination"):
            with self.subTest(field=field):
                original = getattr(self.app, field).get()
                getattr(self.app, field).set(str(self.base / "unrelated restore fixture"))
                with mock.patch.object(windows_app.sealed_file, "unseal_file") as restore:
                    self.app.protection_restore_button.invoke()
                    self.wait_idle()
                restore.assert_not_called()
                self.assertEqual(self.app.tutorial_step, "password-restore")
                self.assertFalse(demo.password_output.exists())
                getattr(self.app, field).set(original)
        self.assert_no_external_actions()

    def test_recovery_refuses_tampered_key_without_calling_decryption(self):
        demo = self.reach_recovery()
        demo.recovery_key.write_bytes(b"Modified generated key, not a real credential")
        with mock.patch.object(windows_app.sealed_file, "unseal_file") as restore:
            self.app.protection_recovery_button.invoke()
            self.wait_idle()
        restore.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "recovery")
        self.assertFalse(demo.recovery_output.exists())
        self.app.tutorial_exit()
        self.assertTrue(demo.recovery_key.exists())

    def test_explicit_comparison_rejects_modified_restored_copy_and_does_not_claim_success(self):
        demo = self.reach_verify()
        output = demo.recovery_output / protection_tutorials.PRACTICE_NAME
        output.write_bytes(b"Changed recovered sample")
        self.app.protection_verify_button.invoke()
        self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "verify")
        self.assertFalse(self.app.tutorial_next())
        self.assertIn("attention", self.app.protection_restore_result.get("1.0", "end-1c").lower())
        self.app.tutorial_exit()
        self.assertEqual(output.read_bytes(), b"Changed recovered sample")

    def test_seal_back_replay_reviews_existing_result_without_overwrite(self):
        demo = self.reach_open()
        before = {path: (digest(path), path.stat().st_mtime_ns) for path in (demo.sealed, demo.recovery_key)}
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "seal")
        with mock.patch.object(windows_app.sealed_file, "seal_file") as seal:
            self.app.protection_seal_button.invoke()
            self.wait_idle()
        seal.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "open")
        self.assertEqual({path: (digest(path), path.stat().st_mtime_ns) for path in before}, before)

    def test_password_and_recovery_back_replays_never_overwrite_restored_files(self):
        demo = self.reach_verify()
        outputs = tuple(directory / protection_tutorials.PRACTICE_NAME for directory in (demo.password_output, demo.recovery_output))
        before = {path: (digest(path), path.stat().st_mtime_ns) for path in outputs}
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "recovery")
        with mock.patch.object(windows_app.sealed_file, "unseal_file") as restore:
            self.app.protection_recovery_button.invoke()
            self.wait_idle()
        restore.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "verify")
        self.app.tutorial_back()
        self.app.tutorial_back()
        self.assertEqual(self.app.tutorial_step, "password-restore")
        with mock.patch.object(windows_app.sealed_file, "unseal_file") as restore:
            self.app.protection_restore_button.invoke()
            self.wait_idle()
        restore.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "recovery")
        self.assertEqual({path: (digest(path), path.stat().st_mtime_ns) for path in before}, before)

    def test_exit_while_sealing_waits_for_worker_then_cleans_and_restores(self):
        fixture, before = self.seed_state()
        demo = self.reach_seal()
        started, release, work = self.blocked(windows_app.sealed_file.seal_file)
        with mock.patch.object(windows_app.sealed_file, "seal_file", side_effect=work):
            self.app.protection_seal_button.invoke()
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
        self.assertEqual(demo.practice_password, "")

    def test_exit_during_each_unlock_keeps_inputs_until_worker_finishes(self):
        for kind in ("password", "recovery"):
            with self.subTest(kind=kind):
                demo = self.reach_password_restore() if kind == "password" else self.reach_recovery()
                button = self.app.protection_restore_button if kind == "password" else self.app.protection_recovery_button
                started, release, work = self.blocked(windows_app.sealed_file.unseal_file)
                with mock.patch.object(windows_app.sealed_file, "unseal_file", side_effect=work):
                    button.invoke()
                    self.assertTrue(started.wait(5))
                    self.app.tutorial_exit()
                    self.assertTrue(self.app.busy)
                    self.assertTrue(demo.sealed.exists())
                    self.assertTrue(demo.recovery_key.exists())
                    release.set()
                    self.wait_idle()
                self.assertFalse(self.app.tutorial_active)
                self.assertFalse(demo.root.exists())

    def test_back_during_seal_returns_one_step_and_later_replay_is_read_only(self):
        demo = self.reach_seal()
        started, release, work = self.blocked(windows_app.sealed_file.seal_file)
        with mock.patch.object(windows_app.sealed_file, "seal_file", side_effect=work):
            self.app.protection_seal_button.invoke()
            self.assertTrue(started.wait(5))
            self.app.tutorial_back()
            self.assertTrue(self.app.busy)
            self.assertTrue(demo.source.exists())
            release.set()
            self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "key")
        self.assertTrue(demo.sealed_is_intact())
        self.app.protection_key_button.invoke()
        with mock.patch.object(windows_app.sealed_file, "seal_file") as seal:
            self.app.protection_seal_button.invoke()
            self.wait_idle()
        seal.assert_not_called()
        self.assertEqual(self.app.tutorial_step, "open")

    def test_thread_setup_failure_retains_only_expected_retry_controls(self):
        demo = self.reach_seal()
        with mock.patch.object(windows_app.threading.Thread, "start", side_effect=RuntimeError("Generated setup failure")):
            self.app.protection_seal_button.invoke()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.tutorial_step, "seal")
        self.assertFalse(demo.sealed.exists())
        self.assertFalse(self.app.protection_seal_button.instate(["disabled"]))
        self.assertTrue(self.app.protection_output_button.instate(["disabled"]))
        self.assertTrue(self.app.nav_buttons["Home"].instate(["disabled"]))
        self.dialogs["showerror"].assert_called_once()

    def test_engine_failure_cannot_echo_practice_password_into_errors_or_logs(self):
        demo = self.reach_seal()
        password = demo.practice_password
        with mock.patch.object(windows_app.sealed_file, "seal_file", side_effect=RuntimeError(password)):
            self.app.protection_seal_button.invoke()
            self.wait_idle()
        self.assertEqual(self.app.tutorial_step, "seal")
        self.assertFalse(demo.sealed.exists())
        self.assertNotIn(password, self.ui_text())
        for dialog in self.dialogs.values():
            self.assertNotIn(password, str(dialog.call_args_list))
        logged = "\n".join(path.read_text(encoding="utf-8") for path in (self.base / "diagnostics").rglob("*") if path.is_file())
        self.assertNotIn(password, logged)

    def test_late_sample_load_cleans_credentials_without_overwriting_new_lesson(self):
        self.app.start_tutorial("protect")
        self.app._go_to("Secure files")
        with mock.patch.object(desktop_preview2.DesktopPreview2App, "_run_task") as run:
            self.app.protection_source_button.invoke()
        old_done = run.call_args.args[2]
        self.app.tutorial_exit()
        self.app.start_tutorial("restore")
        self.app._go_to("Extract archive")
        token = self.app.tutorial_session_token
        stale = protection_tutorials.create_practice()
        self.retained_demos.append(stale)
        old_done(stale)
        self.assertIs(self.app.tutorial_session_token, token)
        self.assertEqual(self.app.tutorial_id, "restore")
        self.assertEqual(self.app.tutorial_step, "load")
        self.assertIsNone(self.app.tutorial_demo)
        self.assertFalse(stale.root.exists())
        self.assertEqual(stale.practice_password, "")


class ProtectionLessonGeometryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Tk high-DPI geometry check")
    def test_each_protection_step_keeps_coach_actions_and_active_controls_visible(self):
        with tempfile.TemporaryDirectory(prefix="rat-trap-protection-geometry-") as temporary:
            for scaling in (1.333, 2.0, 2.667):
                with self.subTest(tk_scaling=scaling):
                    window = tk.Tk()
                    window.withdraw()
                    log = diagnostics.LocalDiagnostics(Path(temporary) / str(scaling))
                    try:
                        window.tk.call("tk", "scaling", scaling)
                        window.attributes("-alpha", 0.0)
                        app = guided_app.GuidedRatTrapApp(window, diagnostic_log=log)
                        window.geometry("960x640+20000+20000")
                        window.deiconify()
                        window.update()
                        self.assertTrue(app.start_tutorial("protect"))
                        app._go_to("Secure files")
                        for step in tutorials.STEPS_BY_ID["protect"]:
                            app._set_tutorial_step(step.id)
                            window.update()
                            for button in (app.tutorial_next_button, app.tutorial_back_button, app.tutorial_exit_button):
                                left = button.winfo_rootx() - window.winfo_rootx()
                                top = button.winfo_rooty() - window.winfo_rooty()
                                detail = f"protect/{step.id}, {scaling=}, {button.cget('text')}"
                                self.assertTrue(button.winfo_ismapped(), detail)
                                self.assertGreaterEqual(left, 0, detail)
                                self.assertGreaterEqual(top, 0, detail)
                                self.assertLessEqual(left + button.winfo_width(), window.winfo_width(), detail)
                                self.assertLessEqual(top + button.winfo_height(), window.winfo_height(), detail)
                            canvas = app.page_scrollers["Secure files"].canvas
                            self.assertGreaterEqual(canvas.winfo_height(), 80)
                            target = app.tutorial_target
                            self.assertIsNotNone(target)
                            self.assertTrue(target.winfo_ismapped(), f"protect/{step.id}: target hidden")
                            if step.id == "navigate":
                                continue
                            left = target.winfo_rootx() - canvas.winfo_rootx()
                            top = target.winfo_rooty() - canvas.winfo_rooty()
                            detail = f"protect/{step.id}, scale={scaling}, target={target}, {left=}, {top=}"
                            self.assertLess(left, canvas.winfo_width(), detail)
                            self.assertLess(top, canvas.winfo_height(), detail)
                            self.assertGreater(left + target.winfo_width(), 0, detail)
                            self.assertGreater(top + target.winfo_height(), 0, detail)
                            if isinstance(target, (ttk.Button, ttk.Checkbutton)):
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
