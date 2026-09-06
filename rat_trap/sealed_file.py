"""Authenticated, compressed one-file containers for Rat-Trap.

``.rtsf`` is an application profile rather than a second cryptographic
format.  The outer bytes are the audited ``RAT-TRAP-ENCRYPTED-1`` schema-1
envelope and the encrypted inner payload is a ``GMW-SOLID-2`` archive with
exactly one regular file.  The original basename and file metadata therefore
remain inside authenticated ciphertext.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

from . import repository_engine, secure_engine, solid_engine


SEALED_EXTENSION = ".rtsf"
SEALED_PROFILE = "sealed-file"
SEALED_PROFILE_FORMAT = "RAT-TRAP-SEALED-FILE-PROFILE-1"
SEALED_PROFILE_SCHEMA_VERSION = 1
WRITER_VERSION = "5.7.0"
DEFAULT_MAX_INNER_BYTES = 1024**4
DEFAULT_MAX_ORIGINAL_BYTES = 8 * 1024**4

PLAINTEXT_TEMP_WARNING = (
    "Rat-Trap Sealed File operations create an isolated plaintext inner GMW "
    "working file in operating-system temporary storage and remove it on a "
    "best-effort basis. Windows, SSDs, sync or backup software, and malware "
    "may retain traces; Rat-Trap does not claim secure deletion."
)
PLAINTEXT_OUTPUT_WARNING = (
    "Unsealing publishes an ordinary plaintext file at the selected "
    "destination. Other applications and the signed-in Windows account can "
    "read or copy it."
)

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CLOCK$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
    "COM¹",
    "COM²",
    "COM³",
    "LPT¹",
    "LPT²",
    "LPT³",
}
_WINDOWS_FORBIDDEN = frozenset('<>:"/\\|?*')
_MAX_BASENAME_UTF16_UNITS = 255


class SealedFileError(secure_engine.SecureArchiveError):
    """Base error for an invalid or unsafe Rat-Trap Sealed File operation."""


@dataclass(frozen=True)
class SealedFileInfo:
    path: str
    profile_format: Optional[str]
    profile_schema_version: Optional[int]
    writer_version: str
    encryption_format: str
    encryption_schema_version: int
    cipher: str
    file_id: str
    created_at_ns: int
    encrypted_size: int
    inner_size: int
    original_name: Optional[str] = None
    original_size: Optional[int] = None
    original_sha256: Optional[str] = None
    modified_at_ns: Optional[int] = None
    mode: Optional[int] = None
    compressor: Optional[str] = None
    compression_level: Optional[int] = None
    profile_verified: bool = False
    content_verified: bool = False

    @property
    def locked(self) -> bool:
        return not self.profile_verified

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class SealResult:
    sealed_file: SealedFileInfo
    source: str
    recovery_key_path: str
    source_retained: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "sealed_file": self.sealed_file.as_dict(),
            "source": self.source,
            "recovery_key_path": self.recovery_key_path,
            "source_retained": self.source_retained,
        }


@dataclass(frozen=True)
class UnsealResult:
    sealed_file: SealedFileInfo
    output: str
    plaintext_sha256: str
    sealed_source_retained: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "sealed_file": self.sealed_file.as_dict(),
            "output": self.output,
            "plaintext_sha256": self.plaintext_sha256,
            "sealed_source_retained": self.sealed_source_retained,
        }


@dataclass(frozen=True)
class BulkSealItem:
    source: str
    relative_source: str
    output: Optional[str]
    recovery_key_path: Optional[str]
    status: str
    error: Optional[str] = None

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class BulkSealResult:
    source_directory: str
    output_directory: str
    recovery_directory: str
    items: tuple[BulkSealItem, ...]
    completed: bool
    source_retained: bool = True
    reconciliation_error: Optional[str] = None

    @property
    def sealed_count(self) -> int:
        return sum(item.status == "sealed" for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.items)

    @property
    def unprocessed_count(self) -> int:
        return sum(item.status == "unprocessed" for item in self.items)

    @property
    def orphan_recovery_count(self) -> int:
        return sum(
            item.status == "orphan-recovery" for item in self.items
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "source_directory": self.source_directory,
            "output_directory": self.output_directory,
            "recovery_directory": self.recovery_directory,
            "items": [item.as_dict() for item in self.items],
            "completed": self.completed,
            "source_retained": self.source_retained,
            "sealed_count": self.sealed_count,
            "failed_count": self.failed_count,
            "unprocessed_count": self.unprocessed_count,
            "orphan_recovery_count": self.orphan_recovery_count,
            "reconciliation_error": self.reconciliation_error,
        }


@dataclass(frozen=True)
class _SourceIdentity:
    device: int
    inode: int
    size: int
    modified_at_ns: int
    mode: int
    link_count: int

    @classmethod
    def read(cls, path: Path) -> "_SourceIdentity":
        value = Path(path).lstat()
        return cls(
            device=int(value.st_dev),
            inode=int(value.st_ino),
            size=int(value.st_size),
            modified_at_ns=int(value.st_mtime_ns),
            mode=int(value.st_mode),
            link_count=int(value.st_nlink),
        )


@dataclass(frozen=True)
class _BulkCandidate:
    path: Path
    relative_source: str
    identity: _SourceIdentity


def default_sealed_name() -> str:
    """Return a non-identifying exterior filename."""

    return f"RT-{uuid.uuid4().hex}{SEALED_EXTENSION}"


def _require_plaintext_temp(allowed: bool) -> None:
    if not allowed:
        raise SealedFileError(
            f"{PLAINTEXT_TEMP_WARNING} Re-run with explicit acknowledgement."
        )


def _require_plaintext_output(allowed: bool) -> None:
    if not allowed:
        raise SealedFileError(
            f"{PLAINTEXT_OUTPUT_WARNING} Re-run with explicit acknowledgement."
        )


def _validate_new_password(password: str) -> None:
    try:
        secure_engine.validate_new_password(password)
    except secure_engine.SecureArchiveError as exc:
        raise SealedFileError(str(exc)) from exc


def _paths_alias(first: Path, second: Path) -> bool:
    first = Path(first)
    second = Path(second)
    if first.resolve() == second.resolve():
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _directory_identity(path: Path) -> tuple[int, int, int]:
    value = Path(path).lstat()
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
    )


def _require_source_unchanged(
    source: Path,
    expected_identity: _SourceIdentity,
    expected_sha256: str,
) -> None:
    current = _validate_source(source)
    if (
        _SourceIdentity.read(current) != expected_identity
        or _sha256_file(current) != expected_sha256
    ):
        raise SealedFileError(
            "Input file changed while the Sealed File was being built"
        )


def _reject_reparse(path: Path, *, label: str) -> None:
    absolute = Path(os.path.abspath(path))
    for candidate in (absolute, *absolute.parents):
        if repository_engine._is_link_or_junction(candidate):
            raise SealedFileError(
                f"{label} cannot use a symbolic link, junction, or reparse "
                f"point: {candidate}"
            )


def _validate_basename(value: str) -> str:
    if not isinstance(value, str):
        raise SealedFileError("The encrypted original filename is invalid")
    try:
        encoded = value.encode("utf-8")
        utf16_units = len(value.encode("utf-16-le")) // 2
    except UnicodeError as exc:
        raise SealedFileError(
            "The encrypted original filename contains invalid Unicode"
        ) from exc
    if (
        not value
        or not encoded
        or utf16_units > _MAX_BASENAME_UTF16_UNITS
        or unicodedata.normalize("NFC", value) != value
        or value in {".", ".."}
        or "\0" in value
        or value.endswith((" ", "."))
        or any(character in _WINDOWS_FORBIDDEN for character in value)
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise SealedFileError(
            "The encrypted original filename is not a safe Windows basename"
        )
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise SealedFileError(
            "The encrypted original filename is reserved by Windows"
        )
    return value


def _validate_source(source_argument: Path) -> Path:
    source_argument = Path(source_argument)
    _reject_reparse(source_argument, label="Sealed File input")
    source = source_argument.resolve()
    if not source.is_file():
        raise SealedFileError(f"Input file not found: {source}")
    _validate_basename(source.name)
    source_stat = source.stat()
    if int(source_stat.st_size) > DEFAULT_MAX_ORIGINAL_BYTES:
        raise SealedFileError(
            "Rat-Trap Sealed Files Beta supports original files up to "
            f"{DEFAULT_MAX_ORIGINAL_BYTES:,} bytes"
        )
    if int(source_stat.st_nlink) != 1:
        raise SealedFileError(
            "Rat-Trap Sealed Files 5.4 refuse files with multiple hard-link "
            "names because sealing one name cannot protect the other "
            f"plaintext names: {source}"
        )
    try:
        streams = repository_engine._alternate_data_streams(source)
    except OSError as exc:
        raise SealedFileError(
            f"Could not verify NTFS data streams for input: {source}"
        ) from exc
    if streams:
        raise SealedFileError(
            "Rat-Trap Sealed Files 5.4 support only the unnamed data stream; "
            f"alternate data streams were found on {source}"
        )
    return source


def _validate_creation_paths(
    source: Path,
    output_argument: Path,
    recovery_argument: Path,
    *,
    allow_recovery_same_directory: bool,
) -> tuple[Path, Path]:
    output_argument = Path(output_argument)
    recovery_argument = Path(recovery_argument)
    _reject_reparse(output_argument, label="Sealed output")
    _reject_reparse(recovery_argument, label="Recovery-key output")
    output = output_argument.resolve()
    recovery = recovery_argument.resolve()
    if output.suffix.lower() != SEALED_EXTENSION:
        raise SealedFileError(
            f"Rat-Trap Sealed Files must use the {SEALED_EXTENSION} extension"
        )
    if any(
        _paths_alias(first, second)
        for first, second in (
            (source, output),
            (source, recovery),
            (output, recovery),
        )
    ):
        raise SealedFileError(
            "Input, sealed output, and recovery-key paths must be different"
        )
    if output.exists():
        raise SealedFileError(f"Sealed destination already exists: {output}")
    if recovery.exists():
        raise SealedFileError(
            f"Recovery-key destination already exists: {recovery}"
        )
    source_directory = source.parent
    output_directory = output.parent
    recovery_directory = recovery.parent
    if (
        recovery_directory == source_directory
        or _path_within(recovery_directory, source_directory)
        or _path_within(source_directory, recovery_directory)
    ):
        raise SealedFileError(
            "Store the recovery key outside the plaintext file's directory "
            "tree. Anyone who obtains the recovery key can unlock its "
            "matching Sealed File."
        )
    if (
        output_directory != recovery_directory
        and (
            _path_within(output_directory, recovery_directory)
            or _path_within(recovery_directory, output_directory)
        )
    ):
        raise SealedFileError(
            "The sealed-output and recovery-key directories must not contain "
            "one another"
        )
    if (
        output_directory == recovery_directory
        and not allow_recovery_same_directory
    ):
        raise SealedFileError(
            "Store the recovery key separately from the sealed file. "
            "Set allow_recovery_same_directory=True only after a separate "
            "same-folder warning and confirmation."
        )
    return output, recovery


def _locked_info(
    path: Path,
    outer: secure_engine.SecureFileInfo,
) -> SealedFileInfo:
    return SealedFileInfo(
        path=str(Path(path).resolve()),
        profile_format=None,
        profile_schema_version=None,
        writer_version=outer.writer_version,
        encryption_format=outer.format,
        encryption_schema_version=outer.schema_version,
        cipher=outer.cipher,
        file_id=outer.file_id,
        created_at_ns=outer.created_at_ns,
        encrypted_size=outer.encrypted_size,
        inner_size=outer.plaintext_size,
    )


def read_locked_info(path: Path) -> SealedFileInfo:
    """Read public envelope fields without claiming the inner profile is valid."""

    path = Path(path).resolve()
    if not secure_engine.is_encrypted_archive(path):
        raise SealedFileError(f"Not a Rat-Trap encrypted file: {path}")
    return _locked_info(path, secure_engine.read_secure_info(path))


def _validate_inner_metadata(
    path: Path,
    metadata: "solid_engine.SolidMetadata",
) -> None:
    if (
        type(metadata.format) is not str
        or metadata.format != "GMW-SOLID-2"
        or type(metadata.profile) is not str
        or metadata.profile != SEALED_PROFILE
        or type(metadata.compressor) is not str
        or metadata.compressor != "zstd"
        or type(metadata.compression_level) is not int
        or metadata.compression_level != 6
        or type(metadata.file_count) is not int
        or metadata.file_count != 1
        or type(metadata.directory_count) is not int
        or metadata.directory_count != 0
        or type(metadata.whole_file_dedup) is not bool
        or metadata.whole_file_dedup is not False
        or type(metadata.duplicate_file_count) is not int
        or metadata.duplicate_file_count != 0
        or type(metadata.entry_order) is not str
        or metadata.entry_order != "path"
        or metadata.zstd_window_log is not None
        or type(metadata.zstd_long_distance) is not bool
        or metadata.zstd_long_distance is not False
        or type(metadata.total_bytes) is not int
        or metadata.total_bytes < 0
        or metadata.total_bytes > DEFAULT_MAX_ORIGINAL_BYTES
        or type(metadata.payload_bytes) is not int
        or metadata.payload_bytes < 0
    ):
        raise SealedFileError(
            f"Encrypted payload is not a valid Rat-Trap Sealed File: {path}"
        )


def _validate_inner(
    path: Path,
    entry: "solid_engine.SolidSingleFileInfo",
) -> None:
    _validate_inner_metadata(path, entry.metadata)
    if entry.metadata.total_bytes != entry.size:
        raise SealedFileError(
            f"Encrypted payload is not a valid Rat-Trap Sealed File: {path}"
        )
    _validate_basename(entry.name)


@contextmanager
def _materialized_inner(
    path: Path,
    *,
    password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
    allow_plaintext_temp: bool,
) -> Iterator[tuple[Path, secure_engine.DecryptResult]]:
    _require_plaintext_temp(allow_plaintext_temp)
    path = Path(path).resolve()
    outer = secure_engine.read_secure_info(path)
    if outer.plaintext_size > DEFAULT_MAX_INNER_BYTES:
        raise SealedFileError(
            "Sealed inner archive exceeds this Rat-Trap beta's configured "
            f"limit of {DEFAULT_MAX_INNER_BYTES:,} bytes"
        )
    with tempfile.TemporaryDirectory(
        prefix="rat-trap-sealed-unlock-"
    ) as temporary:
        inner = Path(temporary) / "sealed-inner.gmw"
        result = secure_engine.decrypt_file(
            path,
            inner,
            password=password,
            recovery_key=recovery_key,
        )
        try:
            yield inner, result
        finally:
            try:
                inner.unlink()
            except OSError:
                pass


def inspect_sealed_file(
    path: Path,
    *,
    password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
    allow_plaintext_temp: bool = False,
) -> SealedFileInfo:
    """Authenticate the envelope and the exact one-file inner profile."""

    path = Path(path).resolve()
    with _materialized_inner(
        path,
        password=password,
        recovery_key=recovery_key,
        allow_plaintext_temp=allow_plaintext_temp,
    ) as (inner, decrypted):
        try:
            _validate_inner_metadata(
                path,
                solid_engine.read_metadata(inner),
            )
            entry = solid_engine.inspect_single_file(inner)
        except (OSError, ValueError) as exc:
            raise SealedFileError(
                "Encrypted payload is not a valid Rat-Trap Sealed File"
            ) from exc
        _validate_inner(path, entry)
    outer = dataclasses.replace(
        decrypted.secure_file,
        path=str(path),
        verified=True,
    )
    return dataclasses.replace(
        _locked_info(path, outer),
        profile_format=SEALED_PROFILE_FORMAT,
        profile_schema_version=SEALED_PROFILE_SCHEMA_VERSION,
        original_name=entry.name,
        original_size=entry.size,
        original_sha256=entry.sha256,
        modified_at_ns=int(entry.mtime * 1_000_000_000),
        mode=entry.mode,
        compressor=entry.metadata.compressor,
        compression_level=entry.metadata.compression_level,
        profile_verified=True,
        content_verified=True,
    )


def verify_sealed_file(
    path: Path,
    *,
    password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
    allow_plaintext_temp: bool = False,
) -> SealedFileInfo:
    return inspect_sealed_file(
        path,
        password=password,
        recovery_key=recovery_key,
        allow_plaintext_temp=allow_plaintext_temp,
    )


def seal_file(
    source: Path,
    output: Path,
    *,
    password: str,
    recovery_key_output: Path,
    allow_plaintext_temp: bool = False,
    allow_recovery_same_directory: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
) -> SealResult:
    """Compress, encrypt, and verify one file without modifying the source."""

    _require_plaintext_temp(allow_plaintext_temp)
    _validate_new_password(password)
    source = _validate_source(Path(source))
    source_identity = _SourceIdentity.read(source)
    output, recovery = _validate_creation_paths(
        source,
        Path(output),
        Path(recovery_key_output),
        allow_recovery_same_directory=allow_recovery_same_directory,
    )
    with tempfile.TemporaryDirectory(
        prefix="rat-trap-sealed-build-"
    ) as temporary:
        inner = Path(temporary) / "sealed-inner.gmw"
        try:
            solid_engine.compress_file(
                source,
                inner,
                compressor="zstd",
                level=6,
                profile=SEALED_PROFILE,
                stored_name=source.name,
            )
            inner_entry = solid_engine.inspect_single_file(inner)
        except (OSError, ValueError) as exc:
            raise SealedFileError(
                f"Could not prepare the one-file compressed payload: {exc}"
            ) from exc
        _validate_inner(inner, inner_entry)
        if inner.stat().st_size > DEFAULT_MAX_INNER_BYTES:
            raise SealedFileError(
                "Compressed Sealed File payload exceeds this beta's "
                f"{DEFAULT_MAX_INNER_BYTES:,}-byte inner limit"
            )
        _require_source_unchanged(
            source,
            source_identity,
            inner_entry.sha256,
        )

        staged_results: dict[str, SealedFileInfo] = {}

        def validate_staged(
            staged: Path,
            staged_recovery: Path,
        ) -> None:
            _require_source_unchanged(
                source,
                source_identity,
                inner_entry.sha256,
            )
            password_verified = inspect_sealed_file(
                staged,
                password=password,
                allow_plaintext_temp=True,
            )
            recovery_verified = inspect_sealed_file(
                staged,
                recovery_key=staged_recovery,
                allow_plaintext_temp=True,
            )
            if (
                password_verified.original_name != inner_entry.name
                or password_verified.original_size != inner_entry.size
                or password_verified.original_sha256 != inner_entry.sha256
                or recovery_verified.original_name
                != password_verified.original_name
                or recovery_verified.original_size
                != password_verified.original_size
                or recovery_verified.original_sha256
                != password_verified.original_sha256
            ):
                raise SealedFileError(
                    "Staged Sealed File does not match the verified source"
                )
            staged_results["password"] = password_verified
            staged_results["recovery"] = recovery_verified

        try:
            encrypted = secure_engine.encrypt_file(
                inner,
                output,
                password=password,
                recovery_key_output=recovery,
                progress=progress,
                pre_publish_validator=validate_staged,
            )
        except Exception as exc:
            if recovery.is_file() and not output.exists():
                raise SealedFileError(
                    f"{exc} No Sealed File was published. A verified orphan "
                    f"recovery key remains at {recovery}; retain it until "
                    "the failed operation has been reviewed."
                ) from exc
            raise
    verified = dataclasses.replace(
        staged_results["password"],
        path=str(output),
        encrypted_size=encrypted.secure_file.encrypted_size,
    )
    file_id, _ = secure_engine.read_recovery_key_file(recovery)
    if (
        file_id != encrypted.secure_file.file_id
        or file_id != verified.file_id
    ):
        raise SealedFileError(
            "Published recovery key does not belong to the Sealed File"
        )
    return SealResult(
        sealed_file=verified,
        source=str(source),
        recovery_key_path=str(recovery),
        source_retained=True,
    )


def unseal_file(
    path: Path,
    output_directory: Path,
    *,
    password: Optional[str] = None,
    recovery_key: Optional[str | bytes | Path] = None,
    allow_plaintext_temp: bool = False,
    allow_plaintext_output: bool = False,
    replace: bool = False,
) -> UnsealResult:
    """Restore one plaintext file using its authenticated encrypted basename."""

    _require_plaintext_output(allow_plaintext_output)
    _require_plaintext_temp(allow_plaintext_temp)
    if replace:
        raise SealedFileError(
            "Rat-Trap Sealed Files never overwrite an existing plaintext "
            "file. Choose a new destination folder or filename."
        )
    path_argument = Path(path)
    _reject_reparse(path_argument, label="Sealed input")
    path = path_argument.resolve()
    output_directory_argument = Path(output_directory)
    _reject_reparse(
        output_directory_argument,
        label="Plaintext destination folder",
    )
    if output_directory_argument.exists():
        if not output_directory_argument.is_dir():
            raise SealedFileError(
                f"Plaintext destination is not a folder: "
                f"{output_directory_argument}"
            )
    output_directory = output_directory_argument.resolve()
    with _materialized_inner(
        path,
        password=password,
        recovery_key=recovery_key,
        allow_plaintext_temp=True,
    ) as (inner, decrypted):
        try:
            _validate_inner_metadata(
                path,
                solid_engine.read_metadata(inner),
            )
            entry = solid_engine.inspect_single_file(inner)
        except (OSError, ValueError) as exc:
            raise SealedFileError(
                "Encrypted payload is not a valid Rat-Trap Sealed File"
            ) from exc
        _validate_inner(path, entry)
        output_directory.mkdir(parents=True, exist_ok=True)
        destination = (output_directory / entry.name).resolve()
        try:
            destination.relative_to(output_directory)
        except ValueError as exc:
            raise SealedFileError(
                "Encrypted original filename escapes the destination"
            ) from exc
        if _paths_alias(path, destination):
            raise SealedFileError(
                "Plaintext output must not replace the Sealed File"
            )
        _reject_reparse(destination, label="Plaintext output")
        if (
            len(str(destination).encode("utf-16-le")) // 2
            > 32_767
        ):
            raise SealedFileError(
                "Plaintext destination exceeds the Windows path limit"
            )
        if destination.exists():
            raise SealedFileError(
                f"Plaintext destination already exists: {destination}"
            )
        try:
            restored = solid_engine.extract_single_file(
                inner,
                destination,
                expected=entry,
                replace=False,
            )
        except (OSError, ValueError) as exc:
            raise SealedFileError(
                f"Could not restore the authenticated plaintext file: {exc}"
            ) from exc
    outer = dataclasses.replace(
        decrypted.secure_file,
        path=str(path),
        verified=True,
    )
    info = dataclasses.replace(
        _locked_info(path, outer),
        profile_format=SEALED_PROFILE_FORMAT,
        profile_schema_version=SEALED_PROFILE_SCHEMA_VERSION,
        original_name=restored.name,
        original_size=restored.size,
        original_sha256=restored.sha256,
        modified_at_ns=int(restored.mtime * 1_000_000_000),
        mode=restored.mode,
        compressor=restored.metadata.compressor,
        compression_level=restored.metadata.compression_level,
        profile_verified=True,
        content_verified=True,
    )
    return UnsealResult(
        sealed_file=info,
        output=str(destination),
        plaintext_sha256=restored.sha256,
        sealed_source_retained=True,
    )


def _path_within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _inventory_regular_files(root: Path) -> list[_BulkCandidate]:
    files: list[_BulkCandidate] = []

    def walk_error(error: OSError) -> None:
        raise SealedFileError(
            f"Could not inspect the complete bulk source tree: {error}"
        ) from error

    for current, directory_names, file_names in os.walk(
        root,
        topdown=True,
        onerror=walk_error,
        followlinks=False,
    ):
        current_path = Path(current)
        _reject_reparse(current_path, label="Bulk source folder")
        resolved_current = current_path.resolve()
        if not _path_within(resolved_current, root):
            raise SealedFileError(
                "Bulk source traversal escaped the selected source tree"
            )
        directory_names.sort()
        file_names.sort()
        for name in list(directory_names):
            candidate = current_path / name
            _reject_reparse(candidate, label="Bulk source folder")
            resolved_candidate = candidate.resolve()
            if (
                not _path_within(resolved_candidate, root)
                or not resolved_candidate.is_dir()
            ):
                raise SealedFileError(
                    "Bulk sealing found an unsafe or changed source folder: "
                    f"{candidate}"
                )
        for name in file_names:
            candidate = current_path / name
            validated = _validate_source(candidate)
            if not _path_within(validated, root):
                raise SealedFileError(
                    "Bulk source traversal escaped the selected source tree"
                )
            files.append(
                _BulkCandidate(
                    path=validated,
                    relative_source=validated.relative_to(root).as_posix(),
                    identity=_SourceIdentity.read(validated),
                )
            )
    files.sort(key=lambda value: value.relative_source)
    return files


def _require_bulk_candidate_unchanged(
    candidate: _BulkCandidate,
    root: Path,
) -> None:
    current = _validate_source(candidate.path)
    if (
        not _path_within(current, root)
        or current != candidate.path
        or _SourceIdentity.read(current) != candidate.identity
    ):
        raise SealedFileError(
            "Bulk source changed after preflight: "
            f"{candidate.relative_source}"
        )


def seal_folder(
    source_directory: Path,
    output_directory: Path,
    recovery_directory: Path,
    *,
    password: str,
    allow_plaintext_temp: bool = False,
    progress: Optional[Callable[[int, int, Path], None]] = None,
    continue_on_error: bool = True,
    cancel_requested: Optional[Callable[[], bool]] = None,
) -> BulkSealResult:
    """Copy-seal every regular file as an independent opaque ``.rtsf``.

    This beta deliberately does not claim Private Space semantics: directory
    relationships are not stored in a shared catalogue, and every output has
    its own recovery key. Originals are always retained.
    """

    _require_plaintext_temp(allow_plaintext_temp)
    if type(continue_on_error) is not bool:
        raise TypeError("continue_on_error must be a boolean")
    if cancel_requested is not None and not callable(cancel_requested):
        raise TypeError("cancel_requested must be callable or None")
    _validate_new_password(password)
    source_argument = Path(source_directory)
    _reject_reparse(source_argument, label="Bulk source")
    source = source_argument.resolve()
    if not source.is_dir():
        raise SealedFileError(f"Bulk source folder not found: {source}")
    output_argument = Path(output_directory)
    recovery_argument = Path(recovery_directory)
    _reject_reparse(output_argument, label="Bulk sealed output")
    _reject_reparse(recovery_argument, label="Bulk recovery-key output")
    output = output_argument.resolve()
    recovery = recovery_argument.resolve()
    if (
        output == recovery
        or _path_within(output, recovery)
        or _path_within(recovery, output)
    ):
        raise SealedFileError(
            "Bulk sealed output and recovery-key folders must be separate "
            "trees that do not contain one another"
        )
    if output.exists() or recovery.exists():
        raise SealedFileError(
            "Bulk output and recovery folders must both be new"
        )
    if any(
        _path_within(candidate, source)
        for candidate in (output, recovery)
    ):
        raise SealedFileError(
            "Bulk output and recovery folders must be outside the source tree"
        )
    if _path_within(source, output) or _path_within(source, recovery):
        raise SealedFileError(
            "Bulk source must not be inside an output or recovery tree"
        )
    files = _inventory_regular_files(source)
    if not files:
        raise SealedFileError("Bulk source folder contains no regular files")
    source_identity = _directory_identity(source)
    plans = [
        (candidate, uuid.uuid4().hex)
        for candidate in files
    ]
    if _directory_identity(source) != source_identity:
        raise SealedFileError(
            "Bulk source folder changed during preflight"
        )
    output.mkdir(parents=True)
    try:
        recovery.mkdir(parents=True)
    except Exception:
        try:
            output.rmdir()
        except OSError:
            pass
        raise
    items: list[BulkSealItem] = []
    stopped = False
    stop_reason = ""
    next_index = 0
    for index, (candidate, opaque_id) in enumerate(plans, start=1):
        next_index = index
        sealed_path = output / f"RT-{opaque_id}{SEALED_EXTENSION}"
        recovery_path = recovery / f"RT-{opaque_id}.rtrk"
        if cancel_requested is not None and cancel_requested():
            stopped = True
            stop_reason = "Bulk operation was cancelled"
            next_index = index - 1
            break
        try:
            _require_bulk_candidate_unchanged(candidate, source)
            seal_file(
                candidate.path,
                sealed_path,
                password=password,
                recovery_key_output=recovery_path,
                allow_plaintext_temp=True,
            )
        except Exception as exc:
            has_output = sealed_path.is_file()
            has_recovery = recovery_path.is_file()
            status = (
                "orphan-recovery"
                if has_recovery and not has_output
                else "failed"
            )
            items.append(
                BulkSealItem(
                    source=str(candidate.path),
                    relative_source=candidate.relative_source,
                    output=str(sealed_path) if has_output else None,
                    recovery_key_path=(
                        str(recovery_path) if has_recovery else None
                    ),
                    status=status,
                    error=str(exc),
                )
            )
            if not continue_on_error:
                stopped = True
                stop_reason = (
                    "Bulk operation stopped after an earlier failure"
                )
                break
        else:
            items.append(
                BulkSealItem(
                    source=str(candidate.path),
                    relative_source=candidate.relative_source,
                    output=str(sealed_path),
                    recovery_key_path=str(recovery_path),
                    status="sealed",
                )
            )
        if progress is not None:
            progress(index, len(plans), candidate.path)

    if stopped:
        for candidate, _opaque_id in plans[next_index:]:
            items.append(
                BulkSealItem(
                    source=str(candidate.path),
                    relative_source=candidate.relative_source,
                    output=None,
                    recovery_key_path=None,
                    status="unprocessed",
                    error=stop_reason,
                )
            )

    reconciliation_error: Optional[str] = None
    try:
        if _directory_identity(source) != source_identity:
            raise SealedFileError(
                "Bulk source folder identity changed during the operation"
            )
        final_files = _inventory_regular_files(source)
        initial_by_path = {
            item.relative_source: item.identity
            for item in files
        }
        final_by_path = {
            item.relative_source: item.identity
            for item in final_files
        }
        for candidate in files:
            if candidate.relative_source not in final_by_path:
                items.append(
                    BulkSealItem(
                        source=str(candidate.path),
                        relative_source=candidate.relative_source,
                        output=None,
                        recovery_key_path=None,
                        status="unprocessed",
                        error="Source was removed after bulk preflight",
                    )
                )
        for candidate in final_files:
            if (
                initial_by_path.get(candidate.relative_source)
                != candidate.identity
            ):
                items.append(
                    BulkSealItem(
                        source=str(candidate.path),
                        relative_source=candidate.relative_source,
                        output=None,
                        recovery_key_path=None,
                        status="unprocessed",
                        error=(
                            "Source was added or changed after bulk preflight"
                        ),
                    )
                )
    except Exception as exc:
        reconciliation_error = str(exc)

    completed = (
        reconciliation_error is None
        and len(items) == len(files)
        and all(item.status == "sealed" for item in items)
    )
    return BulkSealResult(
        source_directory=str(source),
        output_directory=str(output),
        recovery_directory=str(recovery),
        items=tuple(items),
        completed=completed,
        source_retained=True,
        reconciliation_error=reconciliation_error,
    )


__all__ = [
    "BulkSealItem",
    "BulkSealResult",
    "DEFAULT_MAX_INNER_BYTES",
    "DEFAULT_MAX_ORIGINAL_BYTES",
    "PLAINTEXT_OUTPUT_WARNING",
    "PLAINTEXT_TEMP_WARNING",
    "SEALED_EXTENSION",
    "SEALED_PROFILE",
    "SEALED_PROFILE_FORMAT",
    "SEALED_PROFILE_SCHEMA_VERSION",
    "SealResult",
    "SealedFileError",
    "SealedFileInfo",
    "UnsealResult",
    "default_sealed_name",
    "inspect_sealed_file",
    "read_locked_info",
    "seal_file",
    "seal_folder",
    "unseal_file",
    "verify_sealed_file",
]
