import json
import re
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import sealed_file, windows_app


class SealedLaunchArgumentTests(unittest.TestCase):
    def test_supported_launch_forms_are_pure_preselection_requests(self) -> None:
        self.assertIsNone(windows_app._parse_launch_request([]))
        cases = (
            (["C:/Protected/RT-01.RTSF"], "open-sealed"),
            (["C:/Archives/backup.GMW"], "open-archive"),
            (["--open-sealed", "C:/Protected/file.rtsf"], "open-sealed"),
            (["--open-archive", "C:/Archives/backup.gmw"], "open-archive"),
            (["--seal-file", "C:/Private/report.txt"], "seal-file"),
            (["--seal-folder", "C:/Private"], "seal-folder"),
        )
        for arguments, expected_action in cases:
            with self.subTest(arguments=arguments):
                request = windows_app._parse_launch_request(arguments)
                self.assertIsNotNone(request)
                self.assertEqual(request.action, expected_action)
                self.assertEqual(request.path, Path(arguments[-1]))

    def test_invalid_or_ambiguous_launch_forms_are_rejected(self) -> None:
        invalid = (
            ["C:/Private/report.txt"],
            ["--open-sealed"],
            ["--open-sealed", "report.gmw"],
            ["--open-archive", "file.rtsf"],
            ["--seal-file", "one.txt", "two.txt"],
            ["--unknown", "file.rtsf"],
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    windows_app._parse_launch_request(arguments)

    def test_recovery_default_avoids_plaintext_and_sealed_trees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            documents = home / "Documents"
            desktop = home / "Desktop"
            documents.mkdir()
            desktop.mkdir()
            source = documents / "project"
            output = documents / "project-sealed"

            preferred = windows_app._preferred_sealed_recovery_directory(
                source_directory=source,
                output_directory=output,
                home=home,
            )
            impossible = windows_app._preferred_sealed_recovery_directory(
                source_directory=home,
                output_directory=home / "sealed",
                home=home,
            )

        self.assertEqual(preferred, desktop.resolve())
        self.assertIsNone(impossible)


class WindowsSealedUiTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()
        self.app = windows_app.RatTrapApp(self.root)
        self.addCleanup(self.root.destroy)

    def test_secure_files_is_first_tab_and_launch_never_auto_decrypts(self) -> None:
        selected = Path("C:/Protected/RT-0123456789abcdef.rtsf")
        with (
            mock.patch.object(sealed_file, "verify_sealed_file") as verify,
            mock.patch.object(sealed_file, "unseal_file") as unseal,
            mock.patch.object(windows_app.simpledialog, "askstring") as secret,
            mock.patch.object(windows_app.messagebox, "askyesnocancel") as unlock,
        ):
            self.app.apply_launch_request(
                windows_app.LaunchRequest("open-sealed", selected)
            )

        self.assertEqual(self.app.tabs.index("end"), 8)
        self.assertEqual(self.app.tabs.tab(0, "text"), "Secure files")
        self.assertEqual(self.app.tabs.index(self.app.tabs.select()), 0)
        self.assertEqual(
            self.app.secure_modes.index(self.app.secure_modes.select()),
            1,
        )
        self.assertEqual(self.app.unseal_source.get(), str(selected))
        verify.assert_not_called()
        unseal.assert_not_called()
        secret.assert_not_called()
        unlock.assert_not_called()

    def test_seal_file_selection_gets_an_opaque_default_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "identifying-name.txt"
            source.write_text("private", encoding="utf-8")
            with mock.patch.object(
                windows_app.filedialog,
                "askopenfilename",
                return_value=str(source),
            ):
                self.app._choose_seal_source()

            output = Path(self.app.seal_output.get())

        self.assertEqual(output.parent, source.parent)
        self.assertNotIn(source.stem.lower(), output.name.lower())
        self.assertRegex(
            output.name,
            re.compile(r"^RT-[0-9a-f]{32}\.rtsf$"),
        )

    def test_archive_launch_only_preselects_inspection(self) -> None:
        selected = Path("C:/Archives/backup.gmw")
        with (
            mock.patch.object(windows_app.gmw_tool, "read_metadata") as inspect,
            mock.patch.object(windows_app.gmw_tool, "extract_archive") as extract,
        ):
            self.app.apply_launch_request(
                windows_app.LaunchRequest("open-archive", selected)
            )

        self.assertEqual(
            self.app.tabs.index(self.app.tabs.select()),
            self.app.tabs.index(self.app.inspect_tab),
        )
        self.assertEqual(self.app.inspect_archive.get(), str(selected))
        inspect.assert_not_called()
        extract.assert_not_called()

    def test_temp_warning_is_acknowledged_before_new_password_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sealed" / "RT-test.rtsf"
            recovery = Path(temporary) / "recovery" / "RT-test.rtrk"
            password = "Rat-Trap sealed UI password 2026"
            password_prompt = mock.Mock(
                side_effect=(password, password),
            )

            def acknowledge(*_args, **_kwargs):
                self.assertEqual(password_prompt.call_count, 0)
                return True

            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    side_effect=acknowledge,
                ) as warning,
                mock.patch.object(
                    windows_app.simpledialog,
                    "askstring",
                    password_prompt,
                ),
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(recovery),
                ),
            ):
                credentials = self.app._new_sealed_credentials(output)

        self.assertIsNotNone(credentials)
        self.assertIn(
            sealed_file.PLAINTEXT_TEMP_WARNING,
            warning.call_args_list[0].args[1],
        )
        self.assertTrue(credentials["allow_plaintext_temp"])
        self.assertFalse(credentials["allow_recovery_same_directory"])
        self.assertEqual(credentials["recovery_key_output"], recovery.resolve())

    def test_declining_seal_warning_prevents_password_and_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private.txt"
            source.write_text("private", encoding="utf-8")
            output = Path(temporary) / sealed_file.default_sealed_name()
            self.app.seal_source.set(str(source))
            self.app.seal_output.set(str(output))
            recovery = Path(temporary).parent / "independent" / "key.rtrk"
            with (
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(recovery),
                ),
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    return_value=False,
                ) as warning,
                mock.patch.object(
                    windows_app.simpledialog,
                    "askstring",
                ) as secret,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_seal_file()

        self.assertIn(
            sealed_file.PLAINTEXT_TEMP_WARNING,
            warning.call_args.args[1],
        )
        secret.assert_not_called()
        run_task.assert_not_called()

    def test_custom_visible_name_requires_confirmation_before_credentials(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private.txt"
            source.write_text("private", encoding="utf-8")
            self.app.seal_source.set(str(source))
            self.app.seal_output.set(str(source.parent / "medical-results.rtsf"))
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    return_value=False,
                ) as warning,
                mock.patch.object(
                    self.app,
                    "_new_sealed_credentials",
                ) as credentials,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_seal_file()

        self.assertIn("exterior filename will remain visible", warning.call_args.args[1])
        credentials.assert_not_called()
        run_task.assert_not_called()

    def test_nested_recovery_folder_is_rejected_before_password(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            output = base / "sealed" / sealed_file.default_sealed_name()
            recovery = base / "sealed" / "keys" / "recovery.rtrk"
            with (
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(recovery),
                ),
                mock.patch.object(
                    windows_app.messagebox,
                    "showwarning",
                ) as warning,
                mock.patch.object(
                    windows_app.simpledialog,
                    "askstring",
                ) as secret,
            ):
                credentials = self.app._new_sealed_credentials(output)

        self.assertIsNone(credentials)
        self.assertIn("must not be inside", warning.call_args.args[1])
        secret.assert_not_called()

    def test_seal_action_retains_source_and_passes_explicit_acknowledgement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "private.txt"
            source.write_text("private", encoding="utf-8")
            output = base / sealed_file.default_sealed_name()
            recovery = base / "keys" / "independent.rtrk"
            self.app.seal_source.set(str(source))
            self.app.seal_output.set(str(output))
            credentials = {
                "password": "Rat-Trap sealed UI password 2026",
                "recovery_key_output": recovery,
                "allow_plaintext_temp": True,
                "allow_recovery_same_directory": False,
            }
            with (
                mock.patch.object(
                    self.app,
                    "_new_sealed_credentials",
                    return_value=credentials,
                ),
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_seal_file()
            work = run_task.call_args.args[1]
            with mock.patch.object(
                sealed_file,
                "seal_file",
                return_value=mock.sentinel.result,
            ) as seal:
                result = work()
            source_was_retained = source.exists()

        self.assertIs(result, mock.sentinel.result)
        seal.assert_called_once_with(source, output, **credentials)
        self.assertTrue(source_was_retained)

    def test_restore_warnings_are_required_before_unlock_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "sealed.rtsf"
            source.write_bytes(b"ciphertext placeholder")
            self.app.unseal_source.set(str(source))
            self.app.unseal_destination.set(str(base / "restored"))
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    return_value=False,
                ) as warning,
                mock.patch.object(
                    self.app,
                    "_sealed_unlock_credential",
                ) as unlock,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_unseal_file()

        self.assertIn(
            sealed_file.PLAINTEXT_OUTPUT_WARNING,
            warning.call_args.args[1],
        )
        self.assertIn(str((base / "restored").resolve()), warning.call_args.args[1])
        unlock.assert_not_called()
        run_task.assert_not_called()

    def test_verify_requires_temp_warning_but_never_plaintext_output_ack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sealed.rtsf"
            source.write_bytes(b"ciphertext placeholder")
            self.app.unseal_source.set(str(source))
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    return_value=False,
                ) as warning,
                mock.patch.object(
                    self.app,
                    "_sealed_unlock_credential",
                ) as unlock,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_verify_sealed()

        prompt = warning.call_args.args[1]
        self.assertIn(sealed_file.PLAINTEXT_TEMP_WARNING, prompt)
        self.assertNotIn(sealed_file.PLAINTEXT_OUTPUT_WARNING, prompt)
        unlock.assert_not_called()
        run_task.assert_not_called()

    def test_bulk_action_uses_new_separate_folders_and_keeps_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            private = source / "private.txt"
            private.write_text("private", encoding="utf-8")
            output = base / "sealed-location" / "new-sealed"
            recovery = base / "key-location" / "new-keys"
            self.app.bulk_seal_source.set(str(source))
            self.app.bulk_seal_output.set(str(output))
            self.app.bulk_recovery_output.set(str(recovery))
            password = "Rat-Trap bulk sealed password 2026"
            with (
                mock.patch.object(
                    self.app,
                    "_prompt_new_sealed_password",
                    return_value=password,
                ),
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_seal_folder()
            work = run_task.call_args.args[1]
            with mock.patch.object(
                sealed_file,
                "seal_folder",
                return_value=mock.sentinel.result,
            ) as bulk:
                result = work()
            source_was_retained = private.exists()

        self.assertIs(result, mock.sentinel.result)
        bulk.assert_called_once_with(
            source,
            output,
            recovery,
            password=password,
            allow_plaintext_temp=True,
            continue_on_error=True,
        )
        self.assertTrue(source_was_retained)

    def test_bulk_nested_output_and_recovery_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            (source / "private.txt").write_text("private", encoding="utf-8")
            output = base / "sealed"
            recovery = output / "keys"
            self.app.bulk_seal_source.set(str(source))
            self.app.bulk_seal_output.set(str(output))
            self.app.bulk_recovery_output.set(str(recovery))
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "showwarning",
                ) as warning,
                mock.patch.object(
                    self.app,
                    "_prompt_new_sealed_password",
                ) as password,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_seal_folder()

        self.assertIn("must not contain one another", warning.call_args.args[1])
        password.assert_not_called()
        run_task.assert_not_called()

    def test_bulk_destinations_inside_plaintext_tree_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "private.txt").write_text("private", encoding="utf-8")
            self.app.bulk_seal_source.set(str(source))
            self.app.bulk_seal_output.set(str(source / "sealed"))
            self.app.bulk_recovery_output.set(
                str(Path(temporary) / "separate-keys")
            )
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "showwarning",
                ) as warning,
                mock.patch.object(
                    self.app,
                    "_prompt_new_sealed_password",
                ) as password,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_seal_folder()

        self.assertIn("outside the plaintext source tree", warning.call_args.args[1])
        password.assert_not_called()
        run_task.assert_not_called()

    def test_bulk_partial_result_reports_all_states_and_reconciliation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            (source / "private.txt").write_text("private", encoding="utf-8")
            output = base / "sealed-location" / "new-sealed"
            recovery = base / "key-location" / "new-keys"
            self.app.bulk_seal_source.set(str(source))
            self.app.bulk_seal_output.set(str(output))
            self.app.bulk_recovery_output.set(str(recovery))
            with (
                mock.patch.object(
                    self.app,
                    "_prompt_new_sealed_password",
                    return_value="Rat-Trap bulk sealed password 2026",
                ),
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_seal_folder()
            done = run_task.call_args.args[2]
            result = sealed_file.BulkSealResult(
                source_directory=str(source),
                output_directory=str(output),
                recovery_directory=str(recovery),
                items=(
                    sealed_file.BulkSealItem(
                        source=str(source / "one.txt"),
                        relative_source="one.txt",
                        output=str(output / "one.rtsf"),
                        recovery_key_path=str(recovery / "one.rtrk"),
                        status="sealed",
                    ),
                    sealed_file.BulkSealItem(
                        source=str(source / "two.txt"),
                        relative_source="two.txt",
                        output=None,
                        recovery_key_path=None,
                        status="failed",
                        error="failed",
                    ),
                    sealed_file.BulkSealItem(
                        source=str(source / "three.txt"),
                        relative_source="three.txt",
                        output=None,
                        recovery_key_path=None,
                        status="unprocessed",
                        error="stopped",
                    ),
                    sealed_file.BulkSealItem(
                        source=str(source / "four.txt"),
                        relative_source="four.txt",
                        output=None,
                        recovery_key_path=str(recovery / "four.rtrk"),
                        status="orphan-recovery",
                        error="publication failed",
                    ),
                ),
                completed=False,
                reconciliation_error="source changed",
            )
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "showwarning",
                ) as warning,
                mock.patch.object(
                    self.app,
                    "_offer_bulk_seal_report",
                ) as offer_report,
            ):
                done(result)

        text = warning.call_args.args[1]
        self.assertIn("Protected: 1", text)
        self.assertIn("Failed: 1", text)
        self.assertIn("Unprocessed: 1", text)
        self.assertIn("Recovery-only incidents: 1", text)
        self.assertIn("Final source reconciliation failed: source changed", text)
        offer_report.assert_called_once_with(result)

    def test_bulk_report_export_contains_every_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            output = base / "sealed"
            recovery = base / "recovery"
            reports = base / "reports"
            for directory in (source, output, recovery, reports):
                directory.mkdir()
            result = sealed_file.BulkSealResult(
                source_directory=str(source),
                output_directory=str(output),
                recovery_directory=str(recovery),
                items=(
                    sealed_file.BulkSealItem(
                        source=str(source / "one.txt"),
                        relative_source="one.txt",
                        output=str(output / "RT-one.rtsf"),
                        recovery_key_path=str(recovery / "RT-one.rtrk"),
                        status="sealed",
                    ),
                    sealed_file.BulkSealItem(
                        source=str(source / "two.txt"),
                        relative_source="two.txt",
                        output=None,
                        recovery_key_path=None,
                        status="failed",
                        error="injected failure",
                    ),
                ),
                completed=False,
            )
            report = reports / "batch.json"
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    return_value=True,
                ),
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(report),
                ),
                mock.patch.object(
                    windows_app.messagebox,
                    "showinfo",
                ) as information,
            ):
                self.app._offer_bulk_seal_report(result)

            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(payload["items"], result.as_dict()["items"])
        self.assertFalse(payload["completed"])
        self.assertEqual(payload["sealed_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertIn("plaintext batch report saved", information.call_args.args[1])

    def test_bulk_report_is_refused_inside_protected_trees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            output = base / "sealed"
            recovery = base / "recovery"
            for directory in (source, output, recovery):
                directory.mkdir()
            result = sealed_file.BulkSealResult(
                source_directory=str(source),
                output_directory=str(output),
                recovery_directory=str(recovery),
                items=(),
                completed=False,
            )
            report = output / "mapping.json"
            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    return_value=True,
                ),
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(report),
                ),
                mock.patch.object(
                    windows_app.messagebox,
                    "showwarning",
                ) as warning,
                mock.patch.object(
                    windows_app,
                    "_write_new_json",
                ) as write_report,
            ):
                self.app._offer_bulk_seal_report(result)

        self.assertIn("outside", warning.call_args.args[1])
        write_report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
