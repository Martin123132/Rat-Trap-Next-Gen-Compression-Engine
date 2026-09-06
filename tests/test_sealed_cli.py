import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rat_trap import gmw_tool


def _all_parsers(parser: argparse.ArgumentParser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                yield from _all_parsers(child)


class _JsonResult:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def as_dict(self) -> dict[str, object]:
        return self.payload


class SealedCliTests(unittest.TestCase):
    def test_parser_exposes_sealed_commands_without_raw_passwords(self) -> None:
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

        seal = parser.parse_args(
            [
                "seal-file",
                "source.txt",
                "opaque.rtsf",
                "--recovery-key-out",
                "separate/key.rtrk",
                "--allow-plaintext-temp",
                "--allow-recovery-beside-sealed",
            ]
        )
        self.assertEqual(seal.source, "source.txt")
        self.assertEqual(seal.output, "opaque.rtsf")
        self.assertEqual(seal.recovery_key_out, "separate/key.rtrk")
        self.assertTrue(seal.allow_plaintext_temp)
        self.assertTrue(seal.allow_recovery_beside_sealed)
        self.assertFalse(hasattr(seal, "password"))

        unseal = parser.parse_args(
            [
                "unseal-file",
                "opaque.rtsf",
                "restored",
                "--allow-plaintext-output",
                "--allow-plaintext-temp",
                "--recovery-key-file",
                "key.rtrk",
            ]
        )
        self.assertEqual(unseal.sealed, "opaque.rtsf")
        self.assertEqual(unseal.output_directory, "restored")
        self.assertTrue(unseal.allow_plaintext_output)
        self.assertTrue(unseal.allow_plaintext_temp)
        self.assertEqual(unseal.recovery_key_file, "key.rtrk")
        self.assertFalse(hasattr(unseal, "replace"))

        folder = parser.parse_args(
            [
                "seal-folder",
                "source",
                "sealed",
                "recovery",
                "--allow-plaintext-temp",
                "--stop-on-error",
            ]
        )
        self.assertEqual(folder.source_directory, "source")
        self.assertEqual(folder.output_directory, "sealed")
        self.assertEqual(folder.recovery_directory, "recovery")
        self.assertTrue(folder.allow_plaintext_temp)
        self.assertTrue(folder.stop_on_error)

        info = parser.parse_args(
            [
                "sealed-info",
                "opaque.rtsf",
                "--unlock",
                "--recovery-key-file",
                "key.rtrk",
                "--allow-plaintext-temp",
            ]
        )
        self.assertTrue(info.unlock)
        self.assertEqual(info.recovery_key_file, "key.rtrk")
        self.assertTrue(info.allow_plaintext_temp)

        verify = parser.parse_args(
            [
                "sealed-verify",
                "opaque.rtsf",
                "--recovery-key-file",
                "key.rtrk",
                "--allow-plaintext-temp",
            ]
        )
        self.assertEqual(verify.recovery_key_file, "key.rtrk")
        self.assertTrue(verify.allow_plaintext_temp)

    def test_sealed_handlers_check_acknowledgements_before_prompting(self) -> None:
        commands = (
            [
                "seal-file",
                "source.txt",
                "opaque.rtsf",
                "--recovery-key-out",
                "key.rtrk",
            ],
            [
                "unseal-file",
                "opaque.rtsf",
                "restored",
                "--allow-plaintext-temp",
            ],
            [
                "unseal-file",
                "opaque.rtsf",
                "restored",
                "--allow-plaintext-output",
            ],
            ["seal-folder", "source", "sealed", "recovery"],
            ["sealed-info", "opaque.rtsf", "--unlock"],
            ["sealed-verify", "opaque.rtsf"],
        )
        with mock.patch.object(
            gmw_tool,
            "_prompt_password",
            side_effect=AssertionError(
                "acknowledgement must precede password collection"
            ),
        ) as password_prompt:
            for command in commands:
                with self.subTest(command=command[0:2]):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as raised:
                            gmw_tool.main(command)
                    self.assertEqual(raised.exception.code, 2)
        password_prompt.assert_not_called()

    def test_seal_file_preflights_collision_before_password_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("plaintext", encoding="utf-8")
            output = root / "existing.rtsf"
            output.write_bytes(b"existing")
            recovery_folder = root / "recovery"
            recovery_folder.mkdir()
            recovery = recovery_folder / "key.rtrk"

            with (
                mock.patch.object(
                    gmw_tool.sealed_file,
                    "_validate_source",
                    return_value=source.resolve(),
                ),
                mock.patch.object(
                    gmw_tool,
                    "_prompt_password",
                    side_effect=AssertionError(
                        "collision must precede password collection"
                    ),
                ) as password_prompt,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    gmw_tool.main(
                        [
                            "seal-file",
                            str(source),
                            str(output),
                            "--recovery-key-out",
                            str(recovery),
                            "--allow-plaintext-temp",
                        ]
                    )

        self.assertEqual(raised.exception.code, 2)
        password_prompt.assert_not_called()

    def test_bulk_path_collision_precedes_password_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            output = root / "sealed"
            output.mkdir()
            recovery = root / "recovery"

            with (
                mock.patch.object(
                    gmw_tool,
                    "_prompt_password",
                    side_effect=AssertionError(
                        "collision must precede password collection"
                    ),
                ) as password_prompt,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    gmw_tool.main(
                        [
                            "seal-folder",
                            str(source),
                            str(output),
                            str(recovery),
                            "--allow-plaintext-temp",
                        ]
                    )

        self.assertEqual(raised.exception.code, 2)
        password_prompt.assert_not_called()

    def test_seal_file_handler_passes_hidden_password_and_safe_controls(self) -> None:
        result = _JsonResult({"operation": "seal-file", "ok": True})
        stdout = io.StringIO()
        with (
            mock.patch.object(gmw_tool, "_preflight_seal_file") as preflight,
            mock.patch.object(
                gmw_tool,
                "_prompt_password",
                return_value="hidden test password",
            ) as password_prompt,
            mock.patch.object(
                gmw_tool.sealed_file,
                "seal_file",
                return_value=result,
            ) as seal_file,
            contextlib.redirect_stdout(stdout),
        ):
            gmw_tool.main(
                [
                    "seal-file",
                    "source.txt",
                    "opaque.rtsf",
                    "--recovery-key-out",
                    "key.rtrk",
                    "--allow-plaintext-temp",
                    "--allow-recovery-beside-sealed",
                ]
            )

        preflight.assert_called_once()
        password_prompt.assert_called_once_with(
            "New Sealed File password: ",
            confirm=True,
        )
        self.assertEqual(
            seal_file.call_args.kwargs["password"],
            "hidden test password",
        )
        self.assertTrue(seal_file.call_args.kwargs["allow_plaintext_temp"])
        self.assertTrue(
            seal_file.call_args.kwargs["allow_recovery_same_directory"]
        )
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"operation": "seal-file", "ok": True},
        )

    def test_unseal_handler_can_use_recovery_without_prompting(self) -> None:
        result = _JsonResult({"operation": "unseal-file", "ok": True})
        stdout = io.StringIO()
        with (
            mock.patch.object(gmw_tool, "_preflight_unseal_file") as preflight,
            mock.patch.object(
                gmw_tool,
                "_prompt_password",
                side_effect=AssertionError(
                    "a supplied recovery key must avoid password prompting"
                ),
            ) as password_prompt,
            mock.patch.object(
                gmw_tool.sealed_file,
                "unseal_file",
                return_value=result,
            ) as unseal_file,
            contextlib.redirect_stdout(stdout),
        ):
            gmw_tool.main(
                [
                    "unseal-file",
                    "opaque.rtsf",
                    "restored",
                    "--allow-plaintext-output",
                    "--allow-plaintext-temp",
                    "--recovery-key-file",
                    "key.rtrk",
                ]
            )

        preflight.assert_called_once()
        password_prompt.assert_not_called()
        self.assertEqual(
            unseal_file.call_args.kwargs["recovery_key"],
            Path("key.rtrk"),
        )
        self.assertNotIn("replace", unseal_file.call_args.kwargs)
        self.assertTrue(
            unseal_file.call_args.kwargs["allow_plaintext_output"]
        )
        self.assertTrue(
            unseal_file.call_args.kwargs["allow_plaintext_temp"]
        )
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"operation": "unseal-file", "ok": True},
        )

    def test_locked_sealed_info_never_prompts(self) -> None:
        locked = _JsonResult(
            {
                "profile_format": "RAT-TRAP-SEALED-FILE-PROFILE-1",
                "profile_verified": False,
            }
        )
        stdout = io.StringIO()
        with (
            mock.patch.object(
                gmw_tool.sealed_file,
                "read_locked_info",
                return_value=locked,
            ) as read_locked,
            mock.patch.object(
                gmw_tool,
                "_prompt_password",
                side_effect=AssertionError("locked info must never prompt"),
            ) as password_prompt,
            contextlib.redirect_stdout(stdout),
        ):
            gmw_tool.main(["sealed-info", "opaque.rtsf"])

        read_locked.assert_called_once_with(Path("opaque.rtsf"))
        password_prompt.assert_not_called()
        self.assertFalse(json.loads(stdout.getvalue())["profile_verified"])

    def test_unlocked_info_and_verify_accept_recovery_credentials(self) -> None:
        unlocked = _JsonResult({"profile_verified": True})
        for command, method_name in (
            ("sealed-info", "inspect_sealed_file"),
            ("sealed-verify", "verify_sealed_file"),
        ):
            arguments = [
                command,
                "opaque.rtsf",
                "--recovery-key-file",
                "key.rtrk",
                "--allow-plaintext-temp",
            ]
            if command == "sealed-info":
                arguments.insert(2, "--unlock")
            stdout = io.StringIO()
            with (
                mock.patch.object(
                    gmw_tool.sealed_file,
                    "read_locked_info",
                ) as read_locked,
                mock.patch.object(
                    gmw_tool.sealed_file,
                    method_name,
                    return_value=unlocked,
                ) as operation,
                mock.patch.object(
                    gmw_tool,
                    "_prompt_password",
                    side_effect=AssertionError(
                        "recovery-key access must not prompt"
                    ),
                ) as password_prompt,
                contextlib.redirect_stdout(stdout),
            ):
                gmw_tool.main(arguments)

            read_locked.assert_called_once_with(Path("opaque.rtsf"))
            password_prompt.assert_not_called()
            self.assertEqual(
                operation.call_args.kwargs["recovery_key"],
                Path("key.rtrk"),
            )
            self.assertTrue(
                operation.call_args.kwargs["allow_plaintext_temp"]
            )
            self.assertTrue(json.loads(stdout.getvalue())["profile_verified"])

    def test_bulk_handler_prompts_once_and_prints_json(self) -> None:
        result = _JsonResult(
            {
                "completed": True,
                "sealed_count": 2,
                "failed_count": 0,
            }
        )
        stdout = io.StringIO()
        with (
            mock.patch.object(gmw_tool, "_preflight_seal_folder") as preflight,
            mock.patch.object(
                gmw_tool,
                "_prompt_password",
                return_value="hidden folder password",
            ) as password_prompt,
            mock.patch.object(
                gmw_tool.sealed_file,
                "seal_folder",
                return_value=result,
            ) as seal_folder,
            contextlib.redirect_stdout(stdout),
        ):
            gmw_tool.main(
                [
                    "seal-folder",
                    "source",
                    "sealed",
                    "recovery",
                    "--allow-plaintext-temp",
                ]
            )

        preflight.assert_called_once()
        password_prompt.assert_called_once_with(
            "New Sealed File password: ",
            confirm=True,
        )
        self.assertEqual(
            seal_folder.call_args.kwargs["password"],
            "hidden folder password",
        )
        self.assertTrue(
            seal_folder.call_args.kwargs["allow_plaintext_temp"]
        )
        self.assertTrue(
            seal_folder.call_args.kwargs["continue_on_error"]
        )
        self.assertEqual(json.loads(stdout.getvalue())["sealed_count"], 2)

    def test_partial_bulk_result_prints_json_and_exits_nonzero(self) -> None:
        result = _JsonResult(
            {
                "completed": False,
                "sealed_count": 1,
                "failed_count": 1,
                "unprocessed_count": 0,
                "orphan_recovery_count": 0,
                "reconciliation_error": None,
            }
        )
        stdout = io.StringIO()
        with (
            mock.patch.object(gmw_tool, "_preflight_seal_folder"),
            mock.patch.object(
                gmw_tool,
                "_prompt_password",
                return_value="hidden folder password",
            ),
            mock.patch.object(
                gmw_tool.sealed_file,
                "seal_folder",
                return_value=result,
            ),
            contextlib.redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            gmw_tool.main(
                [
                    "seal-folder",
                    "source",
                    "sealed",
                    "recovery",
                    "--allow-plaintext-temp",
                ]
            )

        self.assertEqual(raised.exception.code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["completed"])
        self.assertEqual(payload["failed_count"], 1)

    def test_locked_info_rejects_recovery_option_without_unlock(self) -> None:
        with (
            mock.patch.object(
                gmw_tool.sealed_file,
                "read_locked_info",
            ) as read_locked,
            mock.patch.object(
                gmw_tool,
                "_prompt_password",
            ) as password_prompt,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as raised:
                gmw_tool.main(
                    [
                        "sealed-info",
                        "opaque.rtsf",
                        "--recovery-key-file",
                        "key.rtrk",
                    ]
                )

        self.assertEqual(raised.exception.code, 2)
        read_locked.assert_not_called()
        password_prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
