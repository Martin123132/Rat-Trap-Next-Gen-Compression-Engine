import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rat_trap.diagnostics import (
    HARD_MAX_BACKUP_COUNT,
    HARD_MAX_BYTES,
    LocalDiagnostics,
    create_support_id,
    diagnostics_directory,
    sanitize_diagnostic_text,
)


class DiagnosticsTests(unittest.TestCase):
    def test_default_directory_is_inside_per_user_application_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            if os.name == "nt":
                selected = diagnostics_directory(
                    environ={"LOCALAPPDATA": str(root)},
                    home=root / "unused-home",
                )
            else:
                selected = diagnostics_directory(
                    environ={"XDG_STATE_HOME": str(root)},
                    home=root / "unused-home",
                )

        self.assertEqual(
            selected,
            root / "Two Hands Network Ltd" / "Rat-Trap" / "Diagnostics",
        )

    def test_support_ids_are_short_non_identifying_and_unique(self) -> None:
        identifiers = {create_support_id() for _ in range(100)}

        self.assertEqual(len(identifiers), 100)
        for identifier in identifiers:
            self.assertRegex(identifier, r"^RT-[A-F0-9]{10}$")

    def test_record_writes_bounded_json_with_allowlisted_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = LocalDiagnostics(Path(temporary))
            identifier = diagnostics.record(
                "archive.create.failed",
                details={
                    "operation": "create_archive",
                    "stage": "compression",
                    "item_count": 12,
                    "unrecognised": "must not be persisted",
                },
            )
            diagnostics.close()
            entry = json.loads(
                (Path(temporary) / "rat-trap.log").read_text(encoding="utf-8")
            )

        self.assertEqual(entry["support_id"], identifier)
        self.assertEqual(entry["event"], "archive.create.failed")
        self.assertEqual(
            entry["details"],
            {
                "operation": "create_archive",
                "stage": "compression",
                "item_count": 12,
            },
        )
        self.assertRegex(entry["timestamp"], r"^\d{4}-\d{2}-\d{2}T")

    def test_secrets_paths_contents_and_exception_text_are_not_written(self) -> None:
        password = "hunter2"
        recovery_key = "RECOVERY-KEY-MATERIAL-123456789"
        contents = "private-client.txt"
        private_path = r"C:\Users\Martin\Documents\private-client.txt"
        message = (
            f"Could not open {private_path}; password={password}; "
            f"recovery_key={recovery_key}; input was {contents}"
        )
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = LocalDiagnostics(Path(temporary))
            diagnostics.record_exception(
                "archive.open.failed",
                ValueError(message),
                details={
                    "password": password,
                    "recovery_key": recovery_key,
                    "file_contents": contents,
                    "source_path": private_path,
                    "status": password,
                    "result": contents,
                    "operation": "open_archive",
                },
            )
            diagnostics.close()
            persisted = (
                Path(temporary) / "rat-trap.log"
            ).read_text(encoding="utf-8")
            entry = json.loads(persisted)

        for forbidden in (
            password,
            recovery_key,
            contents,
            "Martin",
            "private-client.txt",
        ):
            self.assertNotIn(forbidden, persisted)
        self.assertEqual(entry["exception"]["type"], "ValueError")
        self.assertEqual(entry["exception"]["message"], "[redacted]")
        self.assertEqual(entry["details"]["status"], "[redacted]")
        self.assertEqual(entry["details"]["result"], "[redacted]")
        self.assertNotIn("password", entry["details"])
        self.assertNotIn("recovery_key", entry["details"])
        self.assertNotIn("file_contents", entry["details"])
        self.assertNotIn("source_path", entry["details"])

    def test_allowlisted_fields_reject_unrecognised_short_strings(self) -> None:
        suspicious = {
            "archive_format": "private.zip",
            "component": "Martin",
            "error_code": "RECOVERYKEY123",
            "operation": "hunter2",
            "profile": "client-name",
            "result": "private-client.txt",
            "stage": "secret",
            "status": "password1",
            "ui_action": "customer-folder",
        }
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = LocalDiagnostics(Path(temporary))
            diagnostics.record("privacy.enum.test", details=suspicious)
            diagnostics.close()
            entry = json.loads(
                (Path(temporary) / "rat-trap.log").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(
            entry["details"],
            {key: "[redacted]" for key in suspicious},
        )

    def test_numbers_are_only_kept_for_numeric_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = LocalDiagnostics(Path(temporary))
            diagnostics.record(
                "privacy.numeric.test",
                details={
                    "duration_ms": 125.5,
                    "item_count": 42,
                    "operation": 1234,
                    "result": 5678,
                    "stage": True,
                    "status": 9012,
                },
            )
            diagnostics.close()
            entry = json.loads(
                (Path(temporary) / "rat-trap.log").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(entry["details"]["duration_ms"], 125.5)
        self.assertEqual(entry["details"]["item_count"], 42)
        for field in ("operation", "result", "stage", "status"):
            self.assertEqual(entry["details"][field], "[redacted]")

    def test_text_sanitizer_removes_common_private_values(self) -> None:
        value = (
            r"File C:\Users\Person Name\Documents\secret.txt "
            "password=hunter2 email person@example.com "
            "token=ABCDEFGHIJKLMNOPQRSTUVWX123456"
        )
        sanitized = sanitize_diagnostic_text(value)

        self.assertNotIn("Person Name", sanitized)
        self.assertNotIn("secret.txt", sanitized)
        self.assertNotIn("hunter2", sanitized)
        self.assertNotIn("person@example.com", sanitized)
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWX123456", sanitized)
        self.assertIn("[path]", sanitized)
        self.assertEqual(
            sanitize_diagnostic_text("contact person@example.com"),
            "contact [email]",
        )

    def test_rotation_and_user_configuration_remain_hard_capped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = LocalDiagnostics(
                Path(temporary),
                max_bytes=1024,
                backup_count=2,
            )
            for sequence in range(100):
                diagnostics.record(
                    "rotation.test",
                    details={
                        "operation": "x" * 150,
                        "item_count": sequence,
                    },
                )
            diagnostics.close()
            log_files = list(Path(temporary).glob("rat-trap.log*"))

        self.assertLessEqual(len(log_files), 3)

        with tempfile.TemporaryDirectory() as temporary:
            capped = LocalDiagnostics(
                Path(temporary),
                max_bytes=HARD_MAX_BYTES * 10,
                backup_count=HARD_MAX_BACKUP_COUNT * 10,
            )
            self.assertEqual(capped.max_bytes, HARD_MAX_BYTES)
            self.assertEqual(capped.backup_count, HARD_MAX_BACKUP_COUNT)
            capped.close()

    def test_unavailable_storage_fails_closed_and_still_returns_id(self) -> None:
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
            diagnostics = LocalDiagnostics(Path("unavailable"))

        identifier = diagnostics.record(
            "startup.failed",
            exception=RuntimeError("private message"),
        )
        diagnostics.close()
        diagnostics.close()

        self.assertFalse(diagnostics.available)
        self.assertTrue(re.fullmatch(r"RT-[A-F0-9]{10}", identifier))

    def test_invalid_configuration_cannot_crash_application_startup(self) -> None:
        diagnostics = LocalDiagnostics(
            object(),  # type: ignore[arg-type]
            max_bytes=None,  # type: ignore[arg-type]
            backup_count="invalid",  # type: ignore[arg-type]
        )

        identifier = diagnostics.record("startup.failed")
        diagnostics.close()

        self.assertFalse(diagnostics.available)
        self.assertRegex(identifier, r"^RT-[A-F0-9]{10}$")

    def test_write_failure_never_escapes_to_the_application(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = LocalDiagnostics(Path(temporary))
            with mock.patch.object(
                diagnostics._logger,
                "info",
                side_effect=OSError("disk full"),
            ):
                identifier = diagnostics.record("archive.failed")
            diagnostics.close()

        self.assertRegex(identifier, r"^RT-[A-F0-9]{10}$")


if __name__ == "__main__":
    unittest.main()
