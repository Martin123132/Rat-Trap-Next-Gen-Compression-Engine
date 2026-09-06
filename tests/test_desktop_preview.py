"""Desktop preview checks, including generated-fixture round trips; no native UI automation."""

import contextlib
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import desktop_app, diagnostics, sealed_file, windows_app


WORKSPACES = {
    "Secure files",
    "Create archive",
    "Backups & history",
    "Search Vault",
    "Data Tables",
    "Extract archive",
    "Inspect / export",
    "About",
}


class ArchiveDestinationTests(unittest.TestCase):
    def test_suggested_archive_is_a_sibling_and_preserves_full_folder_name(self):
        source = Path("samples") / "Photos 2026.été 日本"
        for profile in ("fast", "balanced", "smallest", "vault"):
            with self.subTest(profile=profile):
                suffix = ".vault.gmw" if profile == "vault" else ".gmw"
                result = desktop_app.suggested_archive_path(source, profile)
                self.assertEqual(result, source.parent / (source.name + suffix))
                self.assertEqual(result.parent, source.parent)

    def test_blank_destination_gets_new_default(self):
        source = Path("samples") / "New folder"
        self.assertEqual(
            desktop_app.updated_archive_destination("", str(source), "", "balanced"),
            str(source.parent / "New folder.gmw"),
        )

    def test_previous_automatic_names_follow_source_and_selected_profile(self):
        previous = Path("samples") / "Previous folder"
        selected = Path("different samples") / "New 日本 folder"
        for old_suffix in (".gmw", ".vault.gmw"):
            for profile in ("balanced", "vault"):
                with self.subTest(old_suffix=old_suffix, profile=profile):
                    old_default = previous.parent / (previous.name + old_suffix)
                    result = desktop_app.updated_archive_destination(
                        str(previous), str(selected), str(old_default), profile
                    )
                    self.assertEqual(
                        result,
                        str(desktop_app.suggested_archive_path(selected, profile)),
                    )

    def test_custom_destination_is_never_replaced_by_source_selection(self):
        previous = Path("samples") / "Previous"
        selected = Path("samples") / "Selected"
        for custom in (
            str(Path("exports") / "my chosen archive.gmw"),
            str(Path("different parent") / "Previous.gmw"),
            str(Path("samples") / "Previous-personal.vault.gmw"),
        ):
            with self.subTest(custom=custom):
                self.assertEqual(
                    desktop_app.updated_archive_destination(
                        str(previous), str(selected), custom, "vault"
                    ),
                    custom,
                )

    def test_first_source_selection_preserves_preentered_custom_destination(self):
        custom = str(Path("exports") / "already chosen.gmw")
        self.assertEqual(
            desktop_app.updated_archive_destination("", "New source", custom, "vault"),
            custom,
        )

    @unittest.skipUnless(os.name == "nt", "Native Windows path semantics")
    def test_native_windows_paths_compare_case_and_separators(self):
        result = desktop_app.updated_archive_destination(
            r"C:\Sample Files\Old 日本",
            r"D:\Other Files\New été",
            "c:/sample files/OLD 日本.GMW",
            "vault",
        )
        self.assertEqual(result, str(Path(r"D:\Other Files\New été.vault.gmw")))


class DesktopPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rat-trap-preview-test-")
        self.addCleanup(self.temporary.cleanup)
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.log = diagnostics.LocalDiagnostics(Path(self.temporary.name) / "diagnostics")
        self.addCleanup(self.log.close)
        self.app = desktop_app.DesktopPreviewApp(self.root, diagnostic_log=self.log)
        self.root.update_idletasks()

    def assert_selected(self, title):
        self.assertEqual(self.app.tabs.select(), str(self.app.pages[title]))

    def selection_state(self):
        return (
            self.app.tabs.select(),
            self.app.source_folder.get(),
            self.app.create_archive.get(),
            self.app.inspect_archive.get(),
            self.app.unseal_source.get(),
            self.app.vault_archive.get(),
            self.app.data_archive.get(),
            self.app.status_text.get(),
        )

    @contextlib.contextmanager
    def no_automatic_work(self):
        with contextlib.ExitStack() as stack:
            spies = [
                stack.enter_context(mock.patch.object(self.app, name))
                for name in (
                    "_run_task", "_load_details", "_show_all_vault",
                    "_start_vault_search", "_start_load_data_sources",
                    "_start_unseal_file",
                )
            ]
            spies.extend(
                stack.enter_context(mock.patch.object(owner, name))
                for owner, name in (
                    (sealed_file, "unseal_file"),
                    (sealed_file, "verify_sealed_file"),
                    (windows_app.gmw_tool, "read_metadata"),
                    (windows_app.gmw_tool, "extract_archive"),
                    (windows_app.simpledialog, "askstring"),
                )
            )
            yield
            for spy in spies:
                spy.assert_not_called()

    def test_home_is_default_and_all_existing_workspaces_are_reachable(self):
        self.assertEqual(desktop_app.PREVIEW_LABEL, "Desktop Preview 1")
        self.assertIn(desktop_app.PREVIEW_LABEL, self.root.title())
        self.assertEqual(set(self.app.pages), WORKSPACES | {"Home"})
        self.assert_selected("Home")
        self.assertIsInstance(self.app.tabs.tabs(), tuple)
        self.assertEqual(
            set(self.app.tabs.tabs()), {str(page) for page in self.app.pages.values()}
        )
        with self.no_automatic_work():
            for title in sorted(WORKSPACES | {"Home"}):
                with self.subTest(title=title):
                    self.assertTrue(self.app._go_to(title))
                    self.assert_selected(title)

    def test_legacy_page_selection_adapter_supports_frames(self):
        self.app.tabs.select(self.app.inspect_tab)
        self.assert_selected("Inspect / export")
        self.app.tabs.select(self.app.secure_files_tab)
        self.assert_selected("Secure files")

    def test_navigation_preserves_inputs_across_every_workspace(self):
        variables = (
            self.app.source_folder, self.app.create_archive,
            self.app.repository_path, self.app.vault_archive,
            self.app.data_archive, self.app.extract_archive,
            self.app.inspect_archive, self.app.seal_source,
            self.app.vault_query,
        )
        expected = [f"sample value {index} 日本" for index in range(len(variables))]
        for variable, value in zip(variables, expected):
            variable.set(value)
        with self.no_automatic_work():
            for title in sorted(WORKSPACES):
                self.app._go_to(title)
            self.app._go_to("Home")
        self.assertEqual([variable.get() for variable in variables], expected)

    def test_every_page_has_a_scrollable_content_frame(self):
        self.assertEqual(set(self.app.page_scrollers), set(self.app.pages))
        for title, scroller in self.app.page_scrollers.items():
            with self.subTest(title=title):
                self.assertIsInstance(scroller.canvas, tk.Canvas)
                self.assertIs(scroller.content, self.app.pages[title])
                self.assertTrue(scroller.canvas.winfo_exists())
                self.assertGreater(scroller.content.winfo_reqwidth(), 0)
                self.assertGreater(scroller.content.winfo_reqheight(), 0)

    def test_scroll_regions_cover_content_at_compact_and_large_viewports(self):
        # Supply viewport dimensions internally: the Tk window stays withdrawn.
        for title, scroller in self.app.page_scrollers.items():
            for width, height in ((420, 280), (850, 620)):
                with self.subTest(title=title, viewport=(width, height)), mock.patch.object(
                    scroller.canvas, "winfo_width", return_value=width
                ), mock.patch.object(scroller.canvas, "winfo_height", return_value=height):
                    scroller._layout()
                    self.root.update_idletasks()
                    scroller._layout()
                    bounds = scroller.canvas.bbox("all")
                    self.assertIsNotNone(bounds)
                    self.assertEqual(bounds[:2], (0, 0))
                    self.assertGreaterEqual(bounds[2], max(width, scroller.content.winfo_reqwidth()))
                    self.assertGreaterEqual(bounds[3], max(height, scroller.content.winfo_reqheight()))
                    region = tuple(int(value) for value in scroller.canvas.cget("scrollregion").split())
                    self.assertEqual(region, bounds)
                    for label, maximum in scroller._labels:
                        self.assertLessEqual(int(label.cget("wraplength")), maximum)

    @unittest.skipUnless(os.name == "nt", "Windows Tk high-DPI geometry check")
    def test_sidebar_navigation_is_reachable_at_small_window_and_multiple_dpi_scales(self):
        for scaling in (1.333, 2.0, 2.667):
            with self.subTest(tk_scaling=scaling):
                window = tk.Tk()
                window.withdraw()
                log = diagnostics.LocalDiagnostics(
                    Path(self.temporary.name) / f"geometry-{scaling}"
                )
                try:
                    window.tk.call("tk", "scaling", scaling)
                    window.attributes("-alpha", 0.0)
                    app = desktop_app.DesktopPreviewApp(window, diagnostic_log=log)
                    # Mapping is required for actual pack geometry. This test
                    # window is transparent and off-screen, never user-visible.
                    window.geometry("960x640+20000+20000")
                    window.deiconify()
                    window.update()
                    canvas = app._sidebar_canvas
                    self.assertGreater(canvas.winfo_height(), 60)
                    for title, button in app.nav_buttons.items():
                        button.invoke()
                        window.update_idletasks()
                        self.assertEqual(app.tabs.select(), str(app.pages[title]))
                        top = button.winfo_rooty() - canvas.winfo_rooty()
                        bottom = top + button.winfo_height()
                        detail = f"{title}, scaling={scaling}, button={top}:{bottom}, viewport={canvas.winfo_height()}"
                        self.assertTrue(button.winfo_ismapped(), detail)
                        self.assertGreaterEqual(top, -1, detail)
                        self.assertLessEqual(bottom, canvas.winfo_height() + 1, detail)
                    app._go_to("Home")
                    window.update_idletasks()
                    self.assertEqual(
                        [int(button.master.grid_info()["column"]) for button in app.home_buttons.values()],
                        [0, 0, 0, 0],
                        "Home cards should stack at this compact viewport",
                    )
                    cards = next(iter(app.home_buttons.values())).master.master
                    self.assertFalse(cards.columnconfigure(1)["uniform"])
                finally:
                    window.withdraw()
                    window.destroy()
                    log.close()

    def test_path_entries_have_stable_variable_bindings_and_remain_editable(self):
        for variable in (
            self.app.source_folder, self.app.create_archive,
            self.app.inspect_archive, self.app.vault_archive,
            self.app.extract_archive, self.app.unseal_source,
        ):
            with self.subTest(variable=str(variable)):
                entry = self.app.path_entries[str(variable)]
                self.assertEqual(str(entry.cget("textvariable")), str(variable))
                entry.delete(0, tk.END)
                entry.insert(0, "editable path 日本")
                self.assertEqual(variable.get(), "editable path 日本")

    def test_open_existing_only_preselects_supported_files(self):
        cases = (
            ("backup with spaces 日本.GMW", "Inspect / export", "inspect_archive"),
            ("protected file été.RTSF", "Secure files", "unseal_source"),
            ("queryable vault 日本.DB", "Search Vault", "vault_archive"),
        )
        for name, title, variable_name in cases:
            selected = str(Path(self.temporary.name) / name)
            with self.subTest(name=name), self.no_automatic_work(), mock.patch.object(
                windows_app.filedialog, "askopenfilename", return_value=selected
            ):
                self.app._open_existing()
                self.assert_selected(title)
                self.assertEqual(getattr(self.app, variable_name).get(), selected)
                if title == "Secure files":
                    self.assertEqual(
                        self.app.secure_modes.select(), str(self.app.secure_restore_mode)
                    )

    def test_cancel_open_existing_leaves_all_selections_unchanged(self):
        self.app.inspect_archive.set("already selected.gmw")
        self.app._go_to("Create archive")
        before = self.selection_state()
        with self.no_automatic_work(), mock.patch.object(
            windows_app.filedialog, "askopenfilename", return_value=""
        ):
            self.app._open_existing()
        self.assertEqual(self.selection_state(), before)

    def test_home_restore_preselects_extraction_without_overwriting_destination(self):
        archive = Path(self.temporary.name) / "restore a copy 日本.gmw"
        destination = str(Path(self.temporary.name) / "custom restored files")
        self.app.extract_folder.set(destination)
        with self.no_automatic_work(), mock.patch.object(
            windows_app.filedialog, "askopenfilename", return_value=str(archive)
        ):
            self.app._home_restore()
        self.assert_selected("Extract archive")
        self.assertEqual(self.app.extract_archive.get(), str(archive))
        self.assertEqual(self.app.extract_folder.get(), destination)

    def test_home_protect_only_preselects_file_and_opaque_output(self):
        selected = Path(self.temporary.name) / "private sample 日本.txt"
        with self.no_automatic_work(), mock.patch.object(
            windows_app.filedialog, "askopenfilename", return_value=str(selected)
        ):
            self.app._home_protect()
        self.assert_selected("Secure files")
        self.assertEqual(self.app.secure_modes.select(), str(self.app.secure_protect_mode))
        self.assertEqual(self.app.seal_source.get(), str(selected))
        self.assertRegex(Path(self.app.seal_output.get()).name, r"^RT-[0-9a-f]{32}\.rtsf$")

    def test_unsupported_existing_file_warns_without_changing_selection(self):
        for suffix in (".txt", ".rtrk"):
            with self.subTest(suffix=suffix):
                before = self.selection_state()
                with self.no_automatic_work(), mock.patch.object(
                    windows_app.filedialog, "askopenfilename",
                    return_value=str(Path(self.temporary.name) / ("not an archive" + suffix)),
                ), mock.patch.object(windows_app.messagebox, "showwarning") as warning:
                    self.app._open_existing()
                warning.assert_called_once()
                self.assertEqual(self.selection_state(), before)

    def test_launch_activation_only_preselects_existing_secure_and_archive_screens(self):
        for action, suffix, title, variable_name in (
            ("open-archive", ".gmw", "Inspect / export", "inspect_archive"),
            ("open-sealed", ".rtsf", "Secure files", "unseal_source"),
            ("seal-file", ".txt", "Secure files", "seal_source"),
            ("seal-folder", "", "Secure files", "bulk_seal_source"),
        ):
            selected = Path(self.temporary.name) / ("sample with spaces 日本" + suffix)
            with self.subTest(action=action), self.no_automatic_work():
                self.app.apply_launch_request(windows_app.LaunchRequest(action, selected))
                self.assert_selected(title)
                self.assertEqual(getattr(self.app, variable_name).get(), str(selected))

    def test_choose_source_updates_previous_automatic_output(self):
        old_source = Path(self.temporary.name) / "Old folder"
        selected = Path(self.temporary.name) / "New 日本 folder"
        self.app.source_folder.set(str(old_source))
        self.app.create_archive.set(str(old_source.parent / "Old folder.gmw"))
        with self.no_automatic_work(), mock.patch.object(
            windows_app.filedialog, "askdirectory", return_value=str(selected)
        ):
            self.app._choose_source()
        self.assertEqual(self.app.source_folder.get(), str(selected))
        self.assertEqual(self.app.create_archive.get(), str(selected.parent / "New 日本 folder.gmw"))

    def test_choose_source_preserves_custom_output(self):
        custom = str(Path(self.temporary.name) / "custom archive.gmw")
        self.app.create_archive.set(custom)
        with self.no_automatic_work(), mock.patch.object(
            windows_app.filedialog, "askdirectory", return_value="New chosen source"
        ):
            self.app._choose_source()
        self.assertEqual(self.app.source_folder.get(), "New chosen source")
        self.assertEqual(self.app.create_archive.get(), custom)

    def test_cancel_source_picker_preserves_existing_source_and_output(self):
        self.app.source_folder.set("Existing source")
        self.app.create_archive.set("Existing custom output.gmw")
        before = self.selection_state()
        with mock.patch.object(windows_app.filedialog, "askdirectory", return_value=""):
            self.app._choose_source()
        self.assertEqual(self.selection_state(), before)

    def test_busy_blocks_navigation_and_file_pickers_without_changing_state(self):
        self.app.source_folder.set("active source")
        self.app.create_archive.set("active output.gmw")
        self.app.busy = True
        before = self.selection_state()
        with mock.patch.object(windows_app.filedialog, "askdirectory") as directory, mock.patch.object(
            windows_app.filedialog, "askopenfilename"
        ) as open_file:
            self.assertFalse(self.app._go_to("Create archive"))
            self.app._choose_source()
            self.app._open_existing()
            self.app._home_compress()
            self.app._home_protect()
            self.app._home_restore()
            self.app.apply_launch_request(
                windows_app.LaunchRequest("open-archive", Path("ignored while busy.gmw"))
            )
        directory.assert_not_called()
        open_file.assert_not_called()
        self.assertEqual(self.selection_state(), before)
        self.app.busy = False

    def test_support_details_identify_preview_without_user_paths(self):
        with mock.patch.object(self.root, "clipboard_clear"), mock.patch.object(
            self.root, "clipboard_append"
        ) as copied:
            self.app._copy_support_details()
        text = "".join(call.args[0] for call in copied.call_args_list)
        self.assertIn(desktop_app.PREVIEW_LABEL, text)
        self.assertIn("5.7.0-desktop-preview.1", text)
        self.assertNotIn(self.temporary.name, text)

    def test_preview_create_and_restore_use_real_engine_and_worker(self):
        root = Path(self.temporary.name)
        source = root / "Generated sample 日本"
        source.mkdir()
        (source / "nested space").mkdir()
        payloads = {
            "notes.txt": b"Rat-Trap preview round trip\n" * 1000,
            "nested space/data.csv": b"name,value\nalpha,1\nbeta,2\n" * 30,
            "empty.txt": b"",
            "résumé.bin": bytes(range(256)) * 20,
        }
        for name, payload in payloads.items():
            (source / name).write_bytes(payload)
        output = root / "preview.gmw"
        restored = root / "Restored files"
        self.app.source_folder.set(str(source))
        self.app.create_archive.set(str(output))

        def wait_for_worker():
            deadline = time.monotonic() + 20
            while self.app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
            self.assertFalse(self.app.busy, "Preview operation did not finish")

        with mock.patch.object(windows_app.messagebox, "showinfo") as info, mock.patch.object(
            windows_app.messagebox, "showerror"
        ) as error, mock.patch.object(windows_app.messagebox, "showwarning") as warning:
            self.app._start_create()
            wait_for_worker()
            self.assertTrue(output.is_file())
            self.app._go_to("Extract archive")
            self.app.extract_archive.set(str(output))
            self.app.extract_folder.set(str(restored))
            self.app._start_extract()
            wait_for_worker()
        error.assert_not_called()
        warning.assert_not_called()
        self.assertEqual(info.call_count, 2)
        self.assertEqual(
            {path.relative_to(restored).as_posix(): path.read_bytes()
             for path in restored.rglob("*") if path.is_file()}, payloads,
        )
        for name, payload in payloads.items():
            self.assertEqual((source / name).read_bytes(), payload)

    def test_frozen_ui_self_test_path_runs_without_visible_window(self):
        desktop_app._ui_self_test()

    def test_controlled_task_disables_and_restores_registered_actions(self):
        release = threading.Event()
        started = threading.Event()
        completed = mock.Mock()
        before = {button: str(button.cget("state")) for button in self.app.action_buttons}
        self.assertTrue(before)
        self.assertEqual(set(self.app.nav_buttons), set(self.app.pages))
        self.assertEqual(len(self.app.home_buttons), 4)
        for button in (*self.app.nav_buttons.values(), *self.app.home_buttons.values()):
            self.assertIn(button, before)

        def work():
            started.set()
            if not release.wait(3):
                raise RuntimeError("Test worker release timed out")
            return "preview task completed"

        try:
            self.app._run_task("Testing preview action states...", work, completed)
            self.assertTrue(started.wait(1))
            self.assertTrue(self.app.busy)
            for button in before:
                self.assertEqual(str(button.cget("state")), "disabled")
            self.assertFalse(self.app._go_to("About"))
            self.assert_selected("Home")
        finally:
            release.set()
            deadline = time.monotonic() + 3
            while self.app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
        self.assertFalse(self.app.busy)
        completed.assert_called_once_with("preview task completed")
        self.assertEqual(
            {button: str(button.cget("state")) for button in before}, before
        )


if __name__ == "__main__":
    unittest.main()
