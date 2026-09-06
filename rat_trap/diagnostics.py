"""Privacy-safe, local diagnostics for the Rat-Trap Windows application.

This module deliberately has no upload or networking code.  It records a small
set of allowlisted operational fields in rotating JSON-lines files under the
current user's local application-data directory.  Callers should use stable
event names and must never pass file contents or credentials as diagnostics.

Exception messages are not persisted because they routinely contain paths,
filenames, input data, or values supplied by a user.  The exception type and a
short support ID are enough to correlate a visible error with a local record.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import math
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_BACKUP_COUNT = 3
HARD_MAX_BYTES = 5 * 1024 * 1024
HARD_MAX_BACKUP_COUNT = 5

_REDACTED = "[redacted]"
_MAX_TEXT_LENGTH = 160
_EVENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]|\\\\)[^\r\n]*"
)
_HOME_PATH_RE = re.compile(r"(?<![A-Za-z0-9])~[\\/][^\r\n]*")
_POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9:])/[^\r\n]*")
_EMAIL_RE = re.compile(
    r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+\b"
)
_LABELLED_SECRET_RE = re.compile(
    r"(?i)\b("
    r"password|passphrase|secret|token|credential|authorization|"
    r"recovery(?:[\s_-]*(?:key|code|material))?|private[\s_-]*key"
    r")\b\s*[:=]\s*[^\s,;]+"
)
_LONG_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_+/=-]{24,}(?![A-Za-z0-9])")

# Values are written only for these fields.  Unknown fields are silently
# omitted, which is safer than attempting to recognise every kind of secret.
_SAFE_DETAIL_FIELDS = frozenset(
    {
        "archive_format",
        "component",
        "duration_ms",
        "error_code",
        "item_count",
        "operation",
        "profile",
        "result",
        "stage",
        "status",
        "ui_action",
    }
)

_SAFE_DETAIL_TEXT_VALUES = {
    "archive_format": frozenset(
        {
            "gmw",
            "gmw_solid",
            "gmw_vault",
            "sealed_file",
        }
    ),
    "component": frozenset(
        {
            "diagnostics",
            "windows_ui",
        }
    ),
    "error_code": frozenset(),
    "operation": frozenset(
        {
            "archive_change_password",
            "archive_create",
            "archive_export_zip",
            "archive_extract",
            "archive_inspect",
            "archive_rotate_recovery",
            "background_task",
            "create_archive",
            "data_catalog",
            "data_export",
            "data_load",
            "data_query",
            "data_sql",
            "open_archive",
            "repository_abandon_job",
            "repository_check_jobs",
            "repository_export",
            "repository_initialize",
            "repository_issues",
            "repository_open",
            "repository_pin",
            "repository_restore",
            "repository_retention_apply",
            "repository_retention_preview",
            "repository_search",
            "repository_snapshot",
            "repository_unpin",
            "repository_verify_full",
            "repository_verify_quick",
            "sealed_create",
            "sealed_folder",
            "sealed_restore",
            "sealed_verify",
            "vault_export",
            "vault_preview",
            "vault_search",
        }
    ),
    "profile": frozenset(
        {
            "balanced",
            "fast",
            "smallest",
            "vault",
        }
    ),
    "result": frozenset(
        {
            "failure",
            "success",
            "unverified",
            "verified",
        }
    ),
    "stage": frozenset(
        {
            "callback",
            "completion",
            "compression",
            "polling",
            "scheduling",
            "setup",
            "shutdown",
            "startup",
            "worker",
        }
    ),
    "status": frozenset(
        {
            "blocked",
            "busy",
            "cancelled",
            "complete",
            "failed",
            "unavailable",
        }
    ),
    "ui_action": frozenset(
        {
            "close",
            "open_about",
            "open_archive",
            "open_sealed",
        }
    ),
}


def diagnostics_directory(
    *,
    environ: Optional[Mapping[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    """Return the per-user directory used for local diagnostic logs.

    ``LOCALAPPDATA`` is preferred on Windows so logs do not roam between
    machines.  The optional arguments make path selection deterministic in
    tests without changing process-global state.
    """

    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else Path(home)
    if os.name == "nt":
        base_value = environment.get("LOCALAPPDATA")
        base = Path(base_value) if base_value else user_home / "AppData" / "Local"
    else:
        base_value = environment.get("XDG_STATE_HOME")
        base = Path(base_value) if base_value else user_home / ".local" / "state"
    return base / "Two Hands Network Ltd" / "Rat-Trap" / "Diagnostics"


def create_support_id() -> str:
    """Create a short, non-identifying ID suitable for a support dialog."""

    return f"RT-{secrets.token_hex(5).upper()}"


def sanitize_diagnostic_text(value: Any) -> str:
    """Remove common personal-data and secret shapes from a short text value."""

    if isinstance(value, Path):
        return "[path]"
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return _REDACTED
    text = " ".join(value.replace("\x00", " ").split())
    text = _LABELLED_SECRET_RE.sub(lambda match: f"{match.group(1)}={_REDACTED}", text)
    text = _EMAIL_RE.sub("[email]", text)
    text = _WINDOWS_PATH_RE.sub("[path]", text)
    text = _HOME_PATH_RE.sub("[path]", text)
    text = _POSIX_PATH_RE.sub("[path]", text)
    text = _LONG_TOKEN_RE.sub("[token]", text)
    if len(text) > _MAX_TEXT_LENGTH:
        text = text[: _MAX_TEXT_LENGTH - 3] + "..."
    return text


def _safe_event_name(event: Any) -> str:
    candidate = str(event).strip()
    if _EVENT_RE.fullmatch(candidate):
        return candidate
    candidate = _IDENTIFIER_RE.sub("_", candidate).strip("_.-")[:64]
    if not candidate or not candidate[0].isalpha():
        return "diagnostic_event"
    return candidate


def _safe_detail_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    numeric_field = key in {"duration_ms", "item_count"}
    if isinstance(value, bool):
        return _REDACTED
    if isinstance(value, int):
        return (
            value
            if numeric_field and abs(value) <= 10**15
            else _REDACTED
        )
    if isinstance(value, float):
        return (
            value
            if numeric_field
            and math.isfinite(value)
            and abs(value) <= 10**15
            else _REDACTED
        )
    if isinstance(value, str):
        allowed = _SAFE_DETAIL_TEXT_VALUES.get(key, frozenset())
        return value if value in allowed else _REDACTED
    if isinstance(value, Path):
        return _REDACTED
    return _REDACTED


def _safe_details(details: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(details, Mapping):
        return {}
    safe: dict[str, Any] = {}
    try:
        items = details.items()
        for raw_key, value in items:
            key = str(raw_key).strip().lower()
            if key in _SAFE_DETAIL_FIELDS:
                safe[key] = _safe_detail_value(key, value)
    except Exception:
        return {}
    return safe


def _bounded_integer(value: Any, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(lower, min(parsed, upper))


class _SilentRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating handler that never emits internal failures to stderr."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        return


class LocalDiagnostics:
    """Bounded local diagnostics that fail closed if storage is unavailable."""

    def __init__(
        self,
        directory: Optional[Path] = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
        filename: str = "rat-trap.log",
    ) -> None:
        self._logger: Optional[logging.Logger] = None
        self._handler: Optional[_SilentRotatingFileHandler] = None
        self.max_bytes = _bounded_integer(
            max_bytes, DEFAULT_MAX_BYTES, 1024, HARD_MAX_BYTES
        )
        self.backup_count = _bounded_integer(
            backup_count, DEFAULT_BACKUP_COUNT, 1, HARD_MAX_BACKUP_COUNT
        )
        try:
            self.directory = (
                diagnostics_directory() if directory is None else Path(directory)
            )
        except Exception:
            # Keep predictable attributes without falling back to an
            # unintended writable location.
            self.directory = Path()
            self.log_path = self.directory / "rat-trap.log"
            return
        try:
            safe_filename = Path(filename).name
        except Exception:
            safe_filename = "rat-trap.log"
        if safe_filename in {"", ".", ".."}:
            safe_filename = "rat-trap.log"
        self.log_path = self.directory / safe_filename

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            handler = _SilentRotatingFileHandler(
                self.log_path,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding="utf-8",
                delay=True,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger = logging.getLogger(
                f"rat_trap.local_diagnostics.{secrets.token_hex(8)}"
            )
            logger.setLevel(logging.INFO)
            logger.propagate = False
            logger.addHandler(handler)
            self._handler = handler
            self._logger = logger
        except Exception:
            # Diagnostics must never prevent the application from starting.
            self._logger = None
            self._handler = None

    @property
    def available(self) -> bool:
        """Whether a local handler was initialised successfully."""

        return self._logger is not None

    def record(
        self,
        event: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        exception: Optional[BaseException] = None,
        support_id: Optional[str] = None,
    ) -> str:
        """Record one privacy-safe event and return its support ID.

        The ID is returned even if local storage fails, so the UI can always
        show a stable-shaped error reference without exposing exception text.
        """

        identifier = (
            support_id
            if isinstance(support_id, str)
            and re.fullmatch(r"RT-[A-F0-9]{10}", support_id)
            else create_support_id()
        )
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "support_id": identifier,
            "event": _safe_event_name(event),
        }
        safe_details = _safe_details(details)
        if safe_details:
            entry["details"] = safe_details
        if exception is not None:
            entry["exception"] = {
                "type": _safe_event_name(type(exception).__name__),
                "message": _REDACTED,
            }

        try:
            if self._logger is not None:
                payload = json.dumps(
                    entry,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                self._logger.info(payload)
        except Exception:
            # Disk-full, permission, encoding, rollover, and shutdown failures
            # are deliberately non-fatal.
            pass
        return identifier

    def record_exception(
        self,
        event: str,
        exception: BaseException,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Convenience wrapper for recording an exception without its message."""

        return self.record(event, details=details, exception=exception)

    def close(self) -> None:
        """Flush and close the local log, ignoring shutdown-time failures."""

        logger, handler = self._logger, self._handler
        self._logger = None
        self._handler = None
        if logger is None or handler is None:
            return
        try:
            logger.removeHandler(handler)
            handler.close()
        except Exception:
            pass

    def __enter__(self) -> "LocalDiagnostics":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
