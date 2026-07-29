import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rat_trap import windows_app


class WindowsSecurityUiTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()
        self.app = windows_app.RatTrapApp(self.root)
        self.addCleanup(self.root.destroy)

    def test_archive_path_changes_clear_bound_vault_and_query_state(self) -> None:
        old_archive = Path("old-vault.gmw").resolve()
        new_archive = Path("new-vault.gmw").resolve()

        self.app.vault_archive.set(str(old_archive))
        self.app.vault_results_archive = old_archive
        self.app.vault_results.insert(
            "",
            tk.END,
            iid="1",
            values=("private.txt", "text/plain", "10 B", "Yes"),
        )
        self.app.vault_preview.config(state=tk.NORMAL)
        self.app.vault_preview.insert("1.0", "private preview")
        self.app.vault_preview.config(state=tk.DISABLED)

        self.app.vault_archive.set(str(new_archive))

        self.assertIsNone(self.app.vault_results_archive)
        self.assertEqual(self.app.vault_results.get_children(), ())
        self.assertEqual(self.app.vault_preview.get("1.0", tk.END).strip(), "")

        self.app.data_archive.set(str(old_archive))
        self.app.data_loaded_archive = old_archive
        self.app.data_source_map["old table"] = object()
        self.app.data_source_box.configure(values=("old table",))
        self.app.data_source_label.set("old table")
        self.app._render_data_result(
            SimpleNamespace(
                columns=("secret",),
                rows=(("private row",),),
                truncated=False,
            ),
            archive=old_archive,
        )

        self.app.data_archive.set(str(new_archive))

        self.assertIsNone(self.app.data_loaded_archive)
        self.assertIsNone(self.app.data_result_archive)
        self.assertIsNone(self.app.data_current_result)
        self.assertEqual(self.app.data_source_map, {})
        self.assertEqual(self.app.data_results.get_children(), ())

    def test_archive_details_are_not_rendered_under_a_different_selection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.gmw"
            second = Path(temporary) / "second.gmw"
            first.write_bytes(b"first archive")
            second.write_bytes(b"second archive")
            self.app.inspect_archive.set(str(first))
            self.app.details.config(state=tk.NORMAL)
            self.app.details.insert("1.0", "stale details")
            self.app.details.config(state=tk.DISABLED)

            with (
                mock.patch.object(
                    self.app,
                    "_archive_access",
                    return_value={},
                ),
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._load_details()
            self.assertEqual(
                self.app.details.get("1.0", tk.END).strip(),
                "",
            )

            done = run_task.call_args.args[2]
            self.app.inspect_archive.set(str(second))
            done(SimpleNamespace())
            rendered = self.app.details.get("1.0", tk.END).strip()

        self.assertEqual(rendered, "")

    def test_encrypted_query_export_requires_plaintext_confirmation(self) -> None:
        archive = Path("encrypted-vault.gmw").resolve()
        self.app.data_archive.set(str(archive))
        self.app.data_current_result = SimpleNamespace(rows=(("private",),))
        self.app.data_result_archive = archive
        self.app.data_result_encrypted = True

        with (
            mock.patch.object(
                windows_app.messagebox,
                "askyesno",
                return_value=False,
            ) as confirm,
            mock.patch.object(
                windows_app.filedialog,
                "asksaveasfilename",
            ) as save_dialog,
        ):
            self.app._start_data_export()

        self.assertIn("ordinary unencrypted plaintext", confirm.call_args.args[1])
        save_dialog.assert_not_called()

    def test_query_export_cannot_replace_its_source_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "encrypted-vault.gmw"
            original = b"protected encrypted Vault"
            archive.write_bytes(original)
            resolved = archive.resolve()
            self.app.data_archive.set(str(resolved))
            self.app.data_current_result = SimpleNamespace(rows=(("private",),))
            self.app.data_result_archive = resolved
            self.app.data_result_encrypted = False
            output = Path(temporary) / "results.csv"
            os.link(archive, output)

            with (
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(output),
                ),
                mock.patch.object(
                    windows_app.messagebox,
                    "showwarning",
                ) as warning,
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                ) as replace_confirmation,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_data_export()
            preserved = archive.read_bytes()

        self.assertIn("cannot replace", warning.call_args.args[1])
        replace_confirmation.assert_not_called()
        run_task.assert_not_called()
        self.assertEqual(preserved, original)

    def test_zip_export_cannot_replace_its_source_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "encrypted.gmw"
            original = b"protected encrypted archive"
            archive.write_bytes(original)
            resolved = archive.resolve()
            self.app.inspect_archive.set(str(resolved))
            output = Path(temporary) / "export.zip"
            os.link(archive, output)

            with (
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(output),
                ),
                mock.patch.object(
                    windows_app.messagebox,
                    "showwarning",
                ) as warning,
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                ) as replace_confirmation,
                mock.patch.object(self.app, "_archive_access") as archive_access,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_export()
            preserved = archive.read_bytes()

        self.assertIn("cannot replace", warning.call_args.args[1])
        replace_confirmation.assert_not_called()
        archive_access.assert_not_called()
        run_task.assert_not_called()
        self.assertEqual(preserved, original)

    def test_same_folder_recovery_key_requires_separate_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            output = parent / "archive.gmw"
            recovery = parent / "archive.rtrk"
            password = "Rat-Trap UI security test password"

            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    side_effect=(True, False),
                ) as confirm,
                mock.patch.object(
                    windows_app.simpledialog,
                    "askstring",
                    side_effect=(password, password),
                ),
                mock.patch.object(
                    windows_app.filedialog,
                    "asksaveasfilename",
                    return_value=str(recovery),
                ),
            ):
                options = self.app._new_encryption_options(
                    output,
                    action="Creating this encrypted archive",
                )

        self.assertIsNone(options)
        self.assertEqual(confirm.call_count, 2)
        self.assertIn(
            "same folder as the archive",
            confirm.call_args_list[1].args[1],
        )

    def test_replacing_encrypted_archive_with_plaintext_requires_confirmation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source = parent / "source"
            source.mkdir()
            (source / "private.txt").write_text("private", encoding="utf-8")
            output = parent / "archive.gmw"
            original = windows_app.secure_engine.SECURE_MAGIC + b"existing"
            output.write_bytes(original)

            self.app.source_folder.set(str(source))
            self.app.create_archive.set(str(output))
            self.app.encrypt_created_archive.set(False)

            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    side_effect=(True, False),
                ) as confirm,
                mock.patch.object(
                    windows_app.simpledialog,
                    "askstring",
                ) as password_prompt,
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_create()
            preserved = output.read_bytes()

        self.assertEqual(confirm.call_count, 2)
        downgrade_message = confirm.call_args_list[1].args[1]
        self.assertIn("plaintext, unencrypted .gmw archive", downgrade_message)
        self.assertIn("Continue and remove encryption?", downgrade_message)
        password_prompt.assert_not_called()
        run_task.assert_not_called()
        self.assertEqual(preserved, original)

    def test_confirmed_plaintext_replacement_passes_downgrade_consent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source = parent / "source"
            source.mkdir()
            (source / "private.txt").write_text(
                "private",
                encoding="utf-8",
            )
            output = parent / "archive.gmw"
            output.write_bytes(
                windows_app.secure_engine.SECURE_MAGIC + b"existing"
            )
            self.app.source_folder.set(str(source))
            self.app.create_archive.set(str(output))
            self.app.encrypt_created_archive.set(False)

            with (
                mock.patch.object(
                    windows_app.messagebox,
                    "askyesno",
                    side_effect=(True, True),
                ),
                mock.patch.object(self.app, "_run_task") as run_task,
            ):
                self.app._start_create()
            work = run_task.call_args.args[1]
            with mock.patch.object(
                windows_app.gmw_tool,
                "compress_folder",
            ) as compress:
                work()

        self.assertTrue(
            compress.call_args.kwargs["allow_remove_encryption"]
        )

    def test_recovery_dialog_prefers_an_existing_different_user_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            documents = home / "Documents"
            desktop = home / "Desktop"
            documents.mkdir()
            desktop.mkdir()

            archive_in_documents = documents / "archive.gmw"
            self.assertEqual(
                windows_app._preferred_recovery_directory(
                    archive_in_documents,
                    home=home,
                ),
                desktop.resolve(),
            )
            archive_elsewhere = home / "Archives" / "archive.gmw"
            self.assertEqual(
                windows_app._preferred_recovery_directory(
                    archive_elsewhere,
                    home=home,
                ),
                documents.resolve(),
            )

    def test_structured_workspace_uses_one_secure_materialization(self) -> None:
        source = SimpleNamespace(id=7)
        columns = [SimpleNamespace(column_name="name")]
        result = SimpleNamespace(rows=(("Alice",),))
        materialized = mock.MagicMock()
        materialized.return_value.__enter__.return_value = (
            Path("inner-vault.gmw"),
            True,
        )

        with (
            mock.patch.object(
                windows_app.gmw_tool,
                "_materialized_archive",
                materialized,
            ),
            mock.patch.object(
                windows_app.vault_engine,
                "list_structured_sources",
                return_value=[source],
            ),
            mock.patch.object(
                windows_app.vault_engine,
                "list_structured_columns",
                return_value=columns,
            ),
            mock.patch.object(
                windows_app.vault_engine,
                "query_structured_source",
                return_value=result,
            ),
        ):
            bundle = windows_app._load_structured_workspace(
                Path("encrypted-vault.gmw"),
                access={
                    "recovery_key": Path("key.rtrk"),
                    "allow_plaintext_temp": True,
                },
            )

        materialized.assert_called_once()
        self.assertEqual(bundle, ([source], source, columns, result))


if __name__ == "__main__":
    unittest.main()
