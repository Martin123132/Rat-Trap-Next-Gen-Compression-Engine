import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool, secure_engine, vault_engine


PASSWORD = "Rat-Trap integration password 2026!"


def _file_tree(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _directory_tree(folder: Path) -> set[str]:
    return {
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.is_dir()
    }


def _all_parsers(parser: argparse.ArgumentParser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                yield from _all_parsers(child)


class SecureGmwIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)

        cls.source = cls.root / "source"
        (cls.source / "documents").mkdir(parents=True)
        (cls.source / "empty-directory").mkdir()
        (cls.source / "documents" / "notes.txt").write_text(
            "Rat-Trap encrypted integration marker: silver-orbit.\n"
            "This sentence must be searchable inside a Vault.\n",
            encoding="utf-8",
        )
        (cls.source / "records.csv").write_text(
            "name,score,status\n"
            "alpha,10,ready\n"
            "beta,20,pending\n"
            "gamma,30,ready\n",
            encoding="utf-8",
        )
        (cls.source / "payload.bin").write_bytes(bytes(range(64)) * 4)

        cls.balanced_archive = cls.root / "balanced-secure.gmw"
        cls.balanced_recovery = cls.root / "balanced-recovery.rtrk"
        cls.balanced_created = gmw_tool.compress_folder(
            cls.source,
            cls.balanced_archive,
            profile="balanced",
            encryption_password=PASSWORD,
            recovery_key_output=cls.balanced_recovery,
            allow_plaintext_temp=True,
        )

        cls.vault_archive = cls.root / "vault-secure.gmw"
        cls.vault_recovery = cls.root / "vault-recovery.rtrk"
        cls.vault_created = gmw_tool.compress_folder(
            cls.source,
            cls.vault_archive,
            profile="vault",
            encryption_password=PASSWORD,
            recovery_key_output=cls.vault_recovery,
            allow_plaintext_temp=True,
        )

        cls.plain_archive = cls.root / "plain-balanced.gmw"
        cls.plain_created = gmw_tool.compress_folder(
            cls.source,
            cls.plain_archive,
            profile="balanced",
        )

    def assert_encrypted_metadata(self, metadata: gmw_tool.Metadata) -> None:
        self.assertTrue(metadata.encrypted)
        self.assertEqual(metadata.encryption_format, secure_engine.SECURE_FORMAT)
        self.assertEqual(metadata.encryption_cipher, "AES-256-GCM-SIV")

    def assert_source_restored(self, destination: Path) -> None:
        self.assertEqual(_file_tree(destination), _file_tree(self.source))
        self.assertEqual(_directory_tree(destination), _directory_tree(self.source))

    def test_encrypted_balanced_create_read_extract_and_export(self) -> None:
        self.assertEqual(self.balanced_created.format, "GMW-SOLID-2")
        self.assertEqual(self.balanced_created.profile, "balanced")
        self.assert_encrypted_metadata(self.balanced_created)
        self.assertTrue(self.balanced_archive.is_file())
        self.assertTrue(self.balanced_recovery.is_file())

        by_password = gmw_tool.read_metadata(
            self.balanced_archive,
            password=PASSWORD,
            allow_plaintext_temp=True,
        )
        by_recovery = gmw_tool.read_metadata(
            self.balanced_archive,
            recovery_key=self.balanced_recovery,
            allow_plaintext_temp=True,
        )
        self.assert_encrypted_metadata(by_password)
        self.assert_encrypted_metadata(by_recovery)
        self.assertEqual(by_password.file_count, len(_file_tree(self.source)))
        self.assertEqual(by_password.as_dict(), by_recovery.as_dict())

        password_restore = self.root / "balanced-password-restore"
        extracted = gmw_tool.extract_archive(
            self.balanced_archive,
            password_restore,
            password=PASSWORD,
            allow_plaintext_temp=True,
        )
        self.assert_encrypted_metadata(extracted)
        self.assert_source_restored(password_restore)

        recovery_restore = self.root / "balanced-recovery-restore"
        gmw_tool.extract_archive(
            self.balanced_archive,
            recovery_restore,
            recovery_key=self.balanced_recovery,
            allow_plaintext_temp=True,
        )
        self.assert_source_restored(recovery_restore)

        exported = self.root / "balanced-export.zip"
        exported_metadata = gmw_tool.export_zip(
            self.balanced_archive,
            exported,
            recovery_key=self.balanced_recovery,
            allow_plaintext_temp=True,
        )
        self.assert_encrypted_metadata(exported_metadata)
        with zipfile.ZipFile(exported) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(
                archive.read("documents/notes.txt"),
                (self.source / "documents" / "notes.txt").read_bytes(),
            )
            self.assertEqual(
                set(name.rstrip("/") for name in archive.namelist()),
                set(_file_tree(self.source)),
            )

    def test_encrypted_vault_create_search_tables_query_and_extract(self) -> None:
        self.assertEqual(self.vault_created.format, vault_engine.FORMAT)
        self.assertEqual(self.vault_created.profile, "vault")
        self.assertGreaterEqual(self.vault_created.structured_source_count, 1)
        self.assert_encrypted_metadata(self.vault_created)

        results = gmw_tool.search_vault(
            self.vault_archive,
            "silver-orbit",
            password=PASSWORD,
            allow_plaintext_temp=True,
        )
        self.assertEqual([result.path for result in results], ["documents/notes.txt"])

        tables = gmw_tool.list_structured_sources(
            self.vault_archive,
            recovery_key=self.vault_recovery,
            allow_plaintext_temp=True,
        )
        csv_table = next(table for table in tables if table.path == "records.csv")
        self.assertEqual(csv_table.row_count, 3)
        self.assertEqual(csv_table.column_count, 3)

        queried = gmw_tool.query_structured_source(
            self.vault_archive,
            csv_table.id,
            search="ready",
            column="status",
            sort_by="score",
            descending=True,
            password=PASSWORD,
            allow_plaintext_temp=True,
        )
        self.assertEqual(queried.columns, ("__row__", "name", "score", "status"))
        self.assertEqual(
            queried.rows,
            ((3, "gamma", 30, "ready"), (1, "alpha", 10, "ready")),
        )

        selected = self.root / "vault-selected-restore"
        extracted = gmw_tool.extract_vault_files(
            self.vault_archive,
            selected,
            ["records.csv"],
            recovery_key=self.vault_recovery,
            allow_plaintext_temp=True,
        )
        self.assert_encrypted_metadata(extracted)
        self.assertEqual(
            (selected / "records.csv").read_bytes(),
            (self.source / "records.csv").read_bytes(),
        )
        self.assertFalse((selected / "documents" / "notes.txt").exists())

        verified = gmw_tool.verify_vault(
            self.vault_archive,
            password=PASSWORD,
            allow_plaintext_temp=True,
        )
        self.assert_encrypted_metadata(verified)
        self.assertEqual(verified.file_count, len(_file_tree(self.source)))

        full_restore = self.root / "vault-full-restore"
        fully_extracted = gmw_tool.extract_archive(
            self.vault_archive,
            full_restore,
            recovery_key=self.vault_recovery,
            allow_plaintext_temp=True,
        )
        self.assert_encrypted_metadata(fully_extracted)
        self.assert_source_restored(full_restore)

    def test_vault_tables_cli_decrypts_encrypted_vault_once(self) -> None:
        stdout = io.StringIO()
        with mock.patch.object(
            secure_engine,
            "decrypt_file",
            wraps=secure_engine.decrypt_file,
        ) as decrypt:
            with contextlib.redirect_stdout(stdout):
                gmw_tool.main(
                    [
                        "vault-tables",
                        str(self.vault_archive),
                        "--recovery-key-file",
                        str(self.vault_recovery),
                        "--allow-plaintext-temp",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(decrypt.call_count, 1)
        self.assertEqual([item["path"] for item in payload], ["records.csv"])
        self.assertEqual(
            [column["source_name"] for column in payload[0]["columns"]],
            ["name", "score", "status"],
        )

    def test_encrypted_operations_refuse_unacknowledged_plaintext_staging(self) -> None:
        refused_archive = self.root / "refused-secure.gmw"
        refused_recovery = self.root / "refused-recovery.rtrk"
        with self.assertRaisesRegex(
            secure_engine.SecureArchiveError, "explicit acknowledgement"
        ):
            gmw_tool.compress_folder(
                self.source,
                refused_archive,
                profile="balanced",
                encryption_password=PASSWORD,
                recovery_key_output=refused_recovery,
            )
        self.assertFalse(refused_archive.exists())
        self.assertFalse(refused_recovery.exists())

        for operation in (
            lambda: gmw_tool.read_metadata(
                self.balanced_archive,
                password=PASSWORD,
            ),
            lambda: gmw_tool.extract_archive(
                self.balanced_archive,
                self.root / "refused-extract",
                recovery_key=self.balanced_recovery,
            ),
            lambda: gmw_tool.export_zip(
                self.balanced_archive,
                self.root / "refused.zip",
                password=PASSWORD,
            ),
            lambda: gmw_tool.search_vault(
                self.vault_archive,
                "silver-orbit",
                recovery_key=self.vault_recovery,
            ),
            lambda: gmw_tool.list_structured_sources(
                self.vault_archive,
                password=PASSWORD,
            ),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    secure_engine.SecureArchiveError, "explicit acknowledgement"
                ):
                    operation()

        self.assertFalse((self.root / "refused-extract").exists())
        self.assertFalse((self.root / "refused.zip").exists())

    def test_encrypted_outputs_cannot_destroy_their_source_archive(self) -> None:
        balanced_source = self.root / "alias-balanced-source"
        balanced_source.mkdir()
        (balanced_source / "protected.gmw").write_bytes(b"stored plaintext")
        balanced_destination = self.root / "alias-balanced-destination"
        balanced_destination.mkdir()
        balanced_archive = balanced_destination / "protected.gmw"
        balanced_recovery = self.root / "alias-balanced.rtrk"

        vault_source = self.root / "alias-vault-source"
        vault_source.mkdir()
        (vault_source / "protected.vault.gmw").write_bytes(
            b"stored Vault plaintext"
        )
        vault_destination = self.root / "alias-vault-destination"
        vault_destination.mkdir()
        vault_archive = vault_destination / "protected.vault.gmw"
        vault_recovery = self.root / "alias-vault.rtrk"

        with mock.patch.object(
            secure_engine,
            "_argon2_key",
            side_effect=lambda *_args: b"\x42" * 32,
        ):
            gmw_tool.compress_folder(
                balanced_source,
                balanced_archive,
                profile="balanced",
                encryption_password=PASSWORD,
                recovery_key_output=balanced_recovery,
                allow_plaintext_temp=True,
            )
            gmw_tool.compress_folder(
                vault_source,
                vault_archive,
                profile="vault",
                encryption_password=PASSWORD,
                recovery_key_output=vault_recovery,
                allow_plaintext_temp=True,
            )

        balanced_before = balanced_archive.read_bytes()
        with self.assertRaisesRegex(
            secure_engine.SecureArchiveError,
            "destination tree",
        ):
            gmw_tool.extract_archive(
                balanced_archive,
                balanced_destination,
                recovery_key=balanced_recovery,
                allow_plaintext_temp=True,
            )
        self.assertEqual(balanced_archive.read_bytes(), balanced_before)

        vault_before = vault_archive.read_bytes()
        with self.assertRaisesRegex(
            secure_engine.SecureArchiveError,
            "destination tree",
        ):
            gmw_tool.extract_vault_files(
                vault_archive,
                vault_destination,
                ["protected.vault.gmw"],
                recovery_key=vault_recovery,
                allow_plaintext_temp=True,
            )
        self.assertEqual(vault_archive.read_bytes(), vault_before)

        original_balanced = self.balanced_archive.read_bytes()
        with self.assertRaisesRegex(
            secure_engine.SecureArchiveError,
            "must not replace",
        ):
            gmw_tool.export_zip(
                self.balanced_archive,
                self.balanced_archive,
                recovery_key=self.balanced_recovery,
                allow_plaintext_temp=True,
            )
        self.assertEqual(self.balanced_archive.read_bytes(), original_balanced)

        original_vault = self.vault_archive.read_bytes()
        hardlink_output = self.root / "vault-hardlink-results.csv"
        os.link(self.vault_archive, hardlink_output)
        result = vault_engine.structured_data.StructuredQueryResult(
            columns=("private",),
            rows=(("do not overwrite the Vault",),),
        )
        with (
            mock.patch.object(
                vault_engine,
                "export_structured_result",
                side_effect=AssertionError(
                    "hard-link alias must be rejected before export"
                ),
            ) as export_result,
            self.assertRaisesRegex(
                secure_engine.SecureArchiveError,
                "must not replace",
            ),
        ):
            gmw_tool.export_structured_result(
                result,
                hardlink_output,
                source_archive=self.vault_archive,
            )
        export_result.assert_not_called()
        self.assertEqual(self.vault_archive.read_bytes(), original_vault)

        destructive_commands = (
            [
                "vault-query",
                str(self.vault_archive),
                "1",
                "--output",
                str(self.vault_archive),
                "--recovery-key-file",
                str(self.vault_recovery),
                "--allow-plaintext-output",
            ],
            [
                "vault-sql",
                str(self.vault_archive),
                "SELECT 1",
                "--output",
                str(self.vault_archive),
                "--recovery-key-file",
                str(self.vault_recovery),
                "--allow-plaintext-output",
            ],
        )
        for command in destructive_commands:
            with self.subTest(command=command[0]):
                with (
                    mock.patch.object(
                        secure_engine,
                        "decrypt_file",
                        side_effect=AssertionError(
                            "alias must be rejected before decryption"
                        ),
                    ),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as refused,
                ):
                    gmw_tool.main(command)
                self.assertEqual(refused.exception.code, 2)
                self.assertEqual(self.vault_archive.read_bytes(), original_vault)

    def test_plaintext_replacement_of_encrypted_archive_requires_named_consent(
        self,
    ) -> None:
        protected = self.root / "protected-against-downgrade.gmw"
        protected.write_bytes(self.balanced_archive.read_bytes())
        original = protected.read_bytes()

        with (
            mock.patch.object(
                gmw_tool.solid_engine,
                "compress_folder",
                side_effect=AssertionError(
                    "plaintext writer must not run before downgrade consent"
                ),
            ) as writer,
            self.assertRaisesRegex(
                secure_engine.SecureArchiveError,
                "encryption will be removed",
            ),
        ):
            gmw_tool.compress_folder(
                self.source,
                protected,
                profile="balanced",
            )
        writer.assert_not_called()
        self.assertEqual(protected.read_bytes(), original)

        with (
            mock.patch.object(
                gmw_tool.solid_engine,
                "compress_folder",
                side_effect=AssertionError(
                    "CLI writer must not run before downgrade consent"
                ),
            ) as cli_writer,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as refused,
        ):
            gmw_tool.main(
                [
                    "compress",
                    str(self.source),
                    str(protected),
                    "--profile",
                    "balanced",
                ]
            )
        self.assertEqual(refused.exception.code, 2)
        cli_writer.assert_not_called()
        self.assertEqual(protected.read_bytes(), original)

        allowed = self.root / "explicit-plaintext-downgrade.gmw"
        allowed.write_bytes(original)
        with contextlib.redirect_stdout(io.StringIO()):
            gmw_tool.main(
                [
                    "compress",
                    str(self.source),
                    str(allowed),
                    "--profile",
                    "balanced",
                    "--allow-remove-encryption",
                ]
            )
        self.assertFalse(secure_engine.is_encrypted_archive(allowed))
        self.assertFalse(gmw_tool.read_metadata(allowed).encrypted)

    def test_plain_unencrypted_operations_remain_prompt_and_acknowledgement_free(
        self,
    ) -> None:
        self.assertFalse(self.plain_created.encrypted)
        self.assertEqual(self.plain_created.encryption_format, "")
        self.assertEqual(self.plain_created.encryption_cipher, "")

        inspected = gmw_tool.read_metadata(self.plain_archive)
        self.assertFalse(inspected.encrypted)
        self.assertEqual(inspected.profile, "balanced")

        restored = self.root / "plain-restore"
        with mock.patch.object(
            gmw_tool,
            "_prompt_password",
            side_effect=AssertionError("plain archives must never prompt"),
        ):
            gmw_tool.extract_archive(self.plain_archive, restored)
        self.assert_source_restored(restored)

        exported = self.root / "plain-export.zip"
        gmw_tool.export_zip(self.plain_archive, exported)
        with zipfile.ZipFile(exported) as archive:
            self.assertIsNone(archive.testzip())

    def test_cli_parser_exposes_safe_controls_without_raw_password_arguments(
        self,
    ) -> None:
        parser = gmw_tool.build_parser()
        option_strings = {
            option
            for child in _all_parsers(parser)
            for action in child._actions
            for option in action.option_strings
        }
        self.assertNotIn("--password", option_strings)
        self.assertFalse(
            any(option.startswith("--password=") for option in option_strings)
        )

        compress = parser.parse_args(
            [
                "compress",
                "source",
                "archive.gmw",
                "--encrypt",
                "--recovery-key-out",
                "archive.rtrk",
                "--allow-plaintext-temp",
            ]
        )
        self.assertTrue(compress.encrypt)
        self.assertEqual(compress.recovery_key_out, "archive.rtrk")
        self.assertTrue(compress.allow_plaintext_temp)
        self.assertFalse(compress.allow_remove_encryption)
        self.assertFalse(hasattr(compress, "password"))

        downgrade = parser.parse_args(
            [
                "compress",
                "source",
                "archive.gmw",
                "--allow-remove-encryption",
            ]
        )
        self.assertTrue(downgrade.allow_remove_encryption)

        extract = parser.parse_args(
            [
                "extract",
                "archive.gmw",
                "restored",
                "--recovery-key-file",
                "archive.rtrk",
                "--allow-plaintext-output",
            ]
        )
        self.assertEqual(extract.recovery_key_file, "archive.rtrk")
        self.assertTrue(extract.allow_plaintext_output)
        self.assertFalse(hasattr(extract, "password"))

        search = parser.parse_args(
            [
                "vault-search",
                "vault.gmw",
                "needle",
                "--recovery-key-file",
                "vault.rtrk",
                "--allow-plaintext-temp",
            ]
        )
        self.assertEqual(search.recovery_key_file, "vault.rtrk")
        self.assertTrue(search.allow_plaintext_temp)

        query = parser.parse_args(
            [
                "vault-query",
                "vault.gmw",
                "1",
                "--output",
                "results.csv",
                "--allow-plaintext-output",
            ]
        )
        self.assertTrue(query.allow_plaintext_output)
        self.assertFalse(query.allow_plaintext_temp)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "extract",
                        "archive.gmw",
                        "restored",
                        "--password",
                        "secret-on-command-line",
                    ]
                )

    def test_cli_info_is_locked_by_default_and_does_not_prompt(self) -> None:
        stdout = io.StringIO()
        with mock.patch.object(
            gmw_tool,
            "_prompt_password",
            side_effect=AssertionError("locked info must never prompt"),
        ):
            with contextlib.redirect_stdout(stdout):
                gmw_tool.main(["info", str(self.balanced_archive)])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["format"], secure_engine.SECURE_FORMAT)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["password_slot_count"], 1)
        self.assertEqual(payload["recovery_slot_count"], 1)
        self.assertNotIn("file_count", payload)
        self.assertNotIn("profile", payload)
        self.assertNotIn("checksum", payload)

    def test_cli_requires_plaintext_acknowledgement_before_prompting(self) -> None:
        with mock.patch.object(
            gmw_tool,
            "_prompt_password",
            side_effect=AssertionError(
                "acknowledgement must be checked before collecting a password"
            ),
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    gmw_tool.main(
                        [
                            "extract",
                            str(self.balanced_archive),
                            str(self.root / "cli-refused-output"),
                        ]
                    )
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse((self.root / "cli-refused-output").exists())

        refused_commands = (
            [
                "vault-query",
                str(self.vault_archive),
                "1",
                "--output",
                str(self.root / "cli-refused-query.csv"),
                "--allow-plaintext-temp",
            ],
            [
                "vault-sql",
                str(self.vault_archive),
                "SELECT 1",
                "--output",
                str(self.root / "cli-refused-sql.csv"),
                "--allow-plaintext-temp",
            ],
        )
        for command in refused_commands:
            with self.subTest(command=command[0]):
                with mock.patch.object(
                    gmw_tool,
                    "_prompt_password",
                    side_effect=AssertionError(
                        "plaintext-output acknowledgement must precede "
                        "password collection"
                    ),
                ):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as refused:
                            gmw_tool.main(command)
                self.assertEqual(refused.exception.code, 2)
                self.assertFalse(Path(command[command.index("--output") + 1]).exists())

    def test_cli_structured_exports_accept_specific_plaintext_output_consent(
        self,
    ) -> None:
        table = gmw_tool.list_structured_sources(
            self.vault_archive,
            recovery_key=self.vault_recovery,
            allow_plaintext_temp=True,
        )[0]
        query_output = self.root / "cli-query-output.csv"
        sql_output = self.root / "cli-sql-output.csv"

        gmw_tool.main(
            [
                "vault-query",
                str(self.vault_archive),
                str(table.id),
                "--output",
                str(query_output),
                "--recovery-key-file",
                str(self.vault_recovery),
                "--allow-plaintext-output",
            ]
        )
        gmw_tool.main(
            [
                "vault-sql",
                str(self.vault_archive),
                f'SELECT * FROM "{table.table_name}" LIMIT 1',
                "--output",
                str(sql_output),
                "--recovery-key-file",
                str(self.vault_recovery),
                "--allow-plaintext-output",
            ]
        )

        self.assertIn("alpha", query_output.read_text(encoding="utf-8"))
        self.assertIn("alpha", sql_output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
