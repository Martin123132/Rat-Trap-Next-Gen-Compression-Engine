"""Immutable, deduplicated snapshot repositories for Rat-Trap.

The repository is deliberately separate from the portable ``.gmw`` formats.
Canonical state consists of sealed SQLite object packs and hash-named JSON
snapshot manifests. ``catalog.sqlite3`` is a disposable acceleration index
that can always be rebuilt from those immutable files.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from collections import Counter, OrderedDict
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterable, Iterator, Optional, Sequence

import zstandard as zstd
from pyfastcdc import FastCDC


REPOSITORY_FORMAT = "RAT-TRAP-REPOSITORY-1"
REPOSITORY_SCHEMA_VERSION = 1
PACK_FORMAT = "RAT-TRAP-PACK-1"
PACK_SCHEMA_VERSION = 1
SNAPSHOT_FORMAT = "RAT-TRAP-SNAPSHOT-1"
SNAPSHOT_SCHEMA_VERSION = 1
CATALOG_FORMAT = "RAT-TRAP-CATALOG-1"
CATALOG_SCHEMA_VERSION = 2
WRITER_VERSION = "5.7.0"

DEFAULT_CHUNK_MIN = 256 * 1024
DEFAULT_CHUNK_AVG = 1024 * 1024
DEFAULT_CHUNK_MAX = 4 * 1024 * 1024
DEFAULT_ZSTD_LEVEL = 6
MAX_OBJECT_SIZE = 16 * 1024 * 1024
PACK_APPLICATION_ID = 0x52545031  # RTP1

_CONFIG_NAME = "repository.json"
_CATALOG_NAME = "catalog.sqlite3"
_KNOWN_FEATURES = {"fastcdc-2020-hybrid-1", "zstd-or-raw-1"}
_HEX = frozenset("0123456789abcdef")
_FILE_ATTRIBUTE_SPARSE_FILE = 0x0200
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_FILE_ATTRIBUTE_COMPRESSED = 0x0800
_FILE_ATTRIBUTE_ENCRYPTED = 0x4000
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
class RepositoryError(ValueError):
    """Base error for invalid or unsafe repository operations."""


class RepositoryLockedError(RepositoryError):
    """Raised when another repository operation holds the lifecycle lock."""


class SourceChangedError(RepositoryError):
    """Raised when a source changes while a capture is being prepared."""


class _JsonDataclass:
    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class RepositoryInfo(_JsonDataclass):
    path: str
    repository_id: str
    created_at_ns: int
    snapshot_count: int
    pack_count: int
    object_count: int
    object_payload_bytes: int
    pack_file_bytes: int
    repository_file_bytes: int
    trash_file_bytes: int
    issue_count: int


@dataclass(frozen=True)
class RepositoryIssue(_JsonDataclass):
    kind: str
    relpath: str
    message: str


@dataclass(frozen=True)
class IncompleteJobInfo(_JsonDataclass):
    job_id: str
    source_id: str
    source_path: str
    label: str
    created_at_ns: int
    status: str
    total_files: int
    completed_files: int
    staged_object_count: int
    staged_object_payload_bytes: int


@dataclass(frozen=True)
class AbandonJobResult(_JsonDataclass):
    job_id: str
    source_path: str
    trash_path: str


@dataclass(frozen=True)
class SnapshotInfo(_JsonDataclass):
    snapshot_id: str
    manifest_sha256: str
    created_at_ns: int
    source_id: str
    source_path: str
    label: str
    parent_snapshot_id: Optional[str]
    file_count: int
    directory_count: int
    total_bytes: int
    changed_file_count: int
    unchanged_file_count: int
    deleted_file_count: int
    new_object_count: int
    new_object_raw_bytes: int
    new_object_payload_bytes: int
    new_pack_file_bytes: int
    reused_bytes: int
    pinned: bool = False
    resumed: bool = False


@dataclass(frozen=True)
class HistoryEntry(_JsonDataclass):
    snapshot_id: str
    created_at_ns: int
    label: str
    path: str
    kind: str
    size: int
    sha256: Optional[str]


@dataclass(frozen=True)
class RestoreResult(_JsonDataclass):
    snapshot_id: str
    destination: str
    file_count: int
    directory_count: int
    restored_bytes: int


@dataclass(frozen=True)
class VerifyResult(_JsonDataclass):
    snapshot_count: int
    pack_count: int
    file_count: int
    object_count: int
    logical_bytes: int
    object_payload_bytes: int
    pack_file_bytes: int
    repository_file_bytes: int
    trash_file_bytes: int
    unreferenced_object_count: int
    unreferenced_raw_bytes: int
    orphan_pack_count: int
    full_data_verified: bool


@dataclass(frozen=True)
class RetentionPolicy(_JsonDataclass):
    keep_last: int = 10
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 12

    def validate(self) -> None:
        values = (
            self.keep_last,
            self.keep_daily,
            self.keep_weekly,
            self.keep_monthly,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise RepositoryError("Retention values must be non-negative integers")


@dataclass(frozen=True)
class RetentionPlan(_JsonDataclass):
    plan_id: str
    state_fingerprint: str
    created_at_ns: int
    policy: RetentionPolicy
    keep_snapshot_ids: tuple[str, ...]
    remove_snapshot_ids: tuple[str, ...]
    logical_bytes_removed: int
    fully_reclaimable_pack_bytes: int
    unreclaimed_dead_object_raw_bytes: int


@dataclass(frozen=True)
class PruneResult(_JsonDataclass):
    plan: RetentionPlan
    applied: bool
    trash_path: Optional[str]
    moved_manifest_count: int
    moved_pack_count: int
    moved_to_trash_pack_bytes: int
    reclaimed_pack_bytes: int


@dataclass(frozen=True)
class ExportResult(_JsonDataclass):
    snapshot_id: str
    output: str
    profile: str
    archive_bytes: int
    archive_sha256: str
    encrypted: bool = False
    encryption_format: str = ""
    recovery_key_path: Optional[str] = None


def _canonical_json(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RepositoryError("Repository metadata is not canonical JSON") from exc
    return text.encode("utf-8") + b"\n"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in _HEX for character in value)
    )


def _fsync_file(path: Path) -> None:
    # Windows requires a writable descriptor for FlushFileBuffers/os.fsync.
    with open(path, "r+b") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _move_new(source: Path, destination: Path) -> None:
    """Publish one new file without replacing an existing canonical file."""
    if destination.exists():
        raise RepositoryError(f"Refusing to replace published file '{destination}'")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import ctypes

        move_file = ctypes.windll.kernel32.MoveFileExW
        move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        move_file.restype = ctypes.c_int
        move_write_through = 0x00000008
        if not move_file(str(source), str(destination), move_write_through):
            raise ctypes.WinError()
    else:
        os.rename(source, destination)
        _fsync_directory(destination.parent)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".rat-trap-write", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(path, _canonical_json(value))


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RepositoryError(f"Invalid JSON metadata: {path}") from exc
    if not isinstance(value, dict):
        raise RepositoryError(f"Repository metadata must be an object: {path}")
    return value


def _read_canonical_json(path: Path) -> dict[str, object]:
    value = _read_json(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RepositoryError(f"Could not read repository metadata: {path}") from exc
    if raw != _canonical_json(value):
        raise RepositoryError(f"Repository metadata is not canonical JSON: {path}")
    return value


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _normalise_stored_path(stored_path: object) -> str:
    if not isinstance(stored_path, str) or not stored_path or "\0" in stored_path:
        raise RepositoryError("Snapshot contains an invalid empty path")
    windows = PureWindowsPath(stored_path)
    portable = PurePosixPath(stored_path.replace("\\", "/"))
    if windows.drive or windows.is_absolute() or portable.is_absolute():
        raise RepositoryError(f"Snapshot contains an absolute path: {stored_path!r}")
    if not portable.parts or any(part in {"", ".", ".."} for part in portable.parts):
        raise RepositoryError(f"Snapshot contains an unsafe path: {stored_path!r}")
    for part in portable.parts:
        if (
            part != part.rstrip(" .")
            or any(ord(character) < 32 for character in part)
            or any(character in '<>:"|?*' for character in part)
        ):
            raise RepositoryError(f"Snapshot path is not Windows-portable: {stored_path!r}")
        base = part.split(".", 1)[0].upper()
        if base in _WINDOWS_RESERVED:
            raise RepositoryError(f"Snapshot path uses a reserved name: {stored_path!r}")
    return PurePosixPath(*portable.parts).as_posix()


def _safe_destination(root: Path, stored_path: str) -> Path:
    relative = _normalise_stored_path(stored_path)
    destination = (root.resolve() / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise RepositoryError(
            f"Snapshot path escapes the destination: {stored_path!r}"
        ) from exc
    return destination


def _validate_chunking(minimum: int, average: int, maximum: int) -> None:
    if any(type(value) is not int for value in (minimum, average, maximum)):
        raise RepositoryError("Chunk sizes must be integers")
    if not 64 <= minimum <= 1024 * 1024:
        raise RepositoryError(
            "The FastCDC minimum chunk size must be from 64 bytes to 1 MiB"
        )
    if not 256 <= average <= 4 * 1024 * 1024:
        raise RepositoryError(
            "The FastCDC average chunk size must be from 256 bytes to 4 MiB"
        )
    if not 1024 <= maximum <= MAX_OBJECT_SIZE:
        raise RepositoryError(
            "The FastCDC maximum chunk size must be from 1 KiB to 16 MiB"
        )
    if not minimum <= average <= maximum:
        raise RepositoryError(
            "Chunk sizes must satisfy minimum <= average <= maximum"
        )
    if average & (average - 1):
        raise RepositoryError("The average content-defined chunk size must be a power of two")


def _iter_content_chunks(
    source, minimum: int, average: int, maximum: int
) -> Iterator[bytes]:
    chunker = FastCDC(
        avg_size=average,
        min_size=minimum,
        max_size=maximum,
        normalized_chunking=1,
        seed=0,
    )
    for chunk in chunker.cut_stream(source):
        # cut_stream reuses its backing buffer after advancing the iterator.
        # Materialise each chunk before yielding it to hashing/compression.
        raw = bytes(chunk.data)
        sample_step = max(1, len(raw) // 4096)
        low_entropy_sample = raw[::sample_step]
        if len(raw) == maximum and len(set(low_entropy_sample)) <= 8:
            # Gear hashes can run to the hard maximum on very low-entropy
            # streams. Deterministic content markers subdivide that exceptional
            # chunk so a small insertion does not invalidate every 4 MiB block.
            remainder = raw
            while remainder:
                if len(remainder) <= minimum:
                    yield remainder
                    break
                sample = remainder[
                    minimum : min(len(remainder), minimum + 4096)
                ]
                counts = Counter(sample)
                least_frequent = min(counts.values())
                marker_byte = min(
                    value
                    for value, count in counts.items()
                    if count == least_frequent
                )
                index = remainder.find(
                    bytes((marker_byte,)), minimum
                )
                cut = index + 1
                yield remainder[:cut]
                remainder = remainder[cut:]
        else:
            yield raw


def _entry_sort_key(entry: dict[str, object]) -> bytes:
    return str(entry["path"]).encode("utf-8")


def _stat_entry(path: Path, relative: str, kind: str) -> dict[str, object]:
    file_stat = path.lstat()
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return {
        "path": relative,
        "kind": kind,
        "size": int(file_stat.st_size) if kind == "file" else 0,
        "mtime_ns": int(file_stat.st_mtime_ns),
        "mode": int(stat.S_IMODE(file_stat.st_mode)),
        "attributes": attributes,
        "identity": f"{int(file_stat.st_dev)}:{int(file_stat.st_ino)}",
    }


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction and is_junction():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    # Python before 3.12 has no Path.is_junction(). Reject every Windows
    # reparse point rather than risk traversing a mount point or silently
    # changing another reparse-point semantic.
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _alternate_data_streams(path: Path) -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    import ctypes
    from ctypes import wintypes

    class _StreamData(ctypes.Structure):
        _fields_ = [
            ("stream_size", ctypes.c_longlong),
            ("stream_name", ctypes.c_wchar * 296),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    find_first = kernel32.FindFirstStreamW
    find_first.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(_StreamData),
        wintypes.DWORD,
    ]
    find_first.restype = wintypes.HANDLE
    find_next = kernel32.FindNextStreamW
    find_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_StreamData)]
    find_next.restype = wintypes.BOOL
    find_close = kernel32.FindClose
    find_close.argtypes = [wintypes.HANDLE]
    find_close.restype = wintypes.BOOL

    data = _StreamData()
    handle = find_first(str(path), 0, ctypes.byref(data), 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        if error in {1, 38, 50, 87}:
            return ()
        raise OSError(error, f"Could not enumerate data streams for '{path}'")
    names: list[str] = []
    try:
        while True:
            name = str(data.stream_name)
            if name and name != "::$DATA":
                names.append(name)
            if find_next(handle, ctypes.byref(data)):
                continue
            error = ctypes.get_last_error()
            if error != 38:
                raise OSError(
                    error, f"Could not enumerate data streams for '{path}'"
                )
            break
    finally:
        find_close(handle)
    return tuple(names)


def _reject_alternate_data_streams(path: Path) -> None:
    streams = _alternate_data_streams(path)
    if streams:
        raise RepositoryError(
            "NTFS alternate data streams are not supported in repository "
            f"schema 1: {path} ({', '.join(streams)})"
        )


def _reject_unsupported_windows_attributes(
    path: Path, file_stat: os.stat_result
) -> None:
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    if attributes & _FILE_ATTRIBUTE_ENCRYPTED:
        raise RepositoryError(
            "NTFS EFS-encrypted files and folders are not supported in "
            "repository schema 1. Rat-Trap refuses to copy decrypted "
            f"plaintext into an unencrypted repository: {path}"
        )
    if attributes & _FILE_ATTRIBUTE_COMPRESSED:
        raise RepositoryError(
            "NTFS-compressed files and folders are not supported in "
            "repository schema 1 and cannot be restored without changing "
            f"their allocation semantics: {path}"
        )
    if attributes & _FILE_ATTRIBUTE_SPARSE_FILE:
        raise RepositoryError(
            "NTFS sparse files are not supported in repository schema 1 "
            "and cannot be backed up without losing allocation semantics: "
            f"{path}"
        )


def _enumerate_source(source: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    source = source.resolve()
    if not source.is_dir():
        raise RepositoryError(f"Source folder '{source}' not found")
    if _is_link_or_junction(source):
        raise RepositoryError("A repository source cannot be a symbolic link or junction")
    _reject_alternate_data_streams(source)

    root_stat = source.lstat()
    _reject_unsupported_windows_attributes(source, root_stat)
    root = {
        "mtime_ns": int(root_stat.st_mtime_ns),
        "mode": int(stat.S_IMODE(root_stat.st_mode)),
        "attributes": int(getattr(root_stat, "st_file_attributes", 0)),
        "identity": f"{int(root_stat.st_dev)}:{int(root_stat.st_ino)}",
    }
    entries: list[dict[str, object]] = []
    casefolded_paths: dict[str, str] = {}

    def walk_error(error: OSError) -> None:
        raise RepositoryError(
            f"Could not enumerate source folder '{source}': {error}"
        ) from error

    for current, directory_names, file_names in os.walk(
        source, followlinks=False, onerror=walk_error
    ):
        directory_names.sort(key=lambda value: (value.casefold(), value))
        file_names.sort(key=lambda value: (value.casefold(), value))
        current_path = Path(current)

        for name in list(directory_names):
            path = current_path / name
            if _is_link_or_junction(path):
                raise RepositoryError(f"Symbolic links and junctions are not supported: {path}")
            _reject_alternate_data_streams(path)
            directory_stat = path.lstat()
            _reject_unsupported_windows_attributes(path, directory_stat)
            relative = _normalise_stored_path(path.relative_to(source).as_posix())
            entry = _stat_entry(path, relative, "directory")
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise RepositoryError(f"Source entry is not a normal directory: {path}")
            entries.append(entry)

        for name in file_names:
            path = current_path / name
            if _is_link_or_junction(path):
                raise RepositoryError(f"Symbolic links and junctions are not supported: {path}")
            _reject_alternate_data_streams(path)
            file_stat = path.lstat()
            if not stat.S_ISREG(file_stat.st_mode):
                raise RepositoryError(f"Source entry is not a regular file: {path}")
            _reject_unsupported_windows_attributes(path, file_stat)
            relative = _normalise_stored_path(path.relative_to(source).as_posix())
            entries.append(_stat_entry(path, relative, "file"))

    entries.sort(key=_entry_sort_key)
    for entry in entries:
        stored_path = str(entry["path"])
        folded = stored_path.casefold()
        previous = casefolded_paths.get(folded)
        if previous is not None and previous != stored_path:
            raise RepositoryError(
                f"Source contains paths that collide on Windows: {previous!r}, {stored_path!r}"
            )
        casefolded_paths[folded] = stored_path
    file_identities: dict[str, str] = {}
    for entry in entries:
        if entry["kind"] != "file":
            continue
        identity = str(entry["identity"])
        previous = file_identities.get(identity)
        if previous is not None:
            raise RepositoryError(
                "Hard-linked files are not supported in repository schema 1 "
                f"and would restore as independent copies: {previous!r}, "
                f"{entry['path']!r}"
            )
        file_identities[identity] = str(entry["path"])
    return root, entries


def _plan_digest(root: dict[str, object], entries: Sequence[dict[str, object]]) -> str:
    return _sha256_bytes(_canonical_json({"root": root, "entries": list(entries)}))


def _source_id(source: Path) -> str:
    normalised = os.path.normcase(str(source.resolve())).replace("\\", "/")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:32]


def _new_snapshot_id() -> str:
    return uuid.uuid4().hex


def _new_pack_id() -> str:
    return uuid.uuid4().hex


def _utc_folder(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def _repository_directories(root: Path) -> tuple[Path, ...]:
    return (
        root / "manifests",
        root / "packs",
        root / "locks",
        root / "staging" / "jobs",
        root / "refs" / "pins",
        root / "trash",
    )


def _config_payload(
    repository_id: str,
    created_at_ns: int,
    chunk_min: int,
    chunk_avg: int,
    chunk_max: int,
    zstd_level: int,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "format": REPOSITORY_FORMAT,
        "schema_version": REPOSITORY_SCHEMA_VERSION,
        "repository_id": repository_id,
        "created_at_ns": created_at_ns,
        "object_hash": "sha256",
        "chunking": {
            "algorithm": "fastcdc-2020-hybrid-1",
            "minimum": chunk_min,
            "average": chunk_avg,
            "maximum": chunk_max,
            "normalized_chunking": 1,
            "seed": 0,
        },
        "compression": {"algorithm": "zstd-or-raw-1", "zstd_level": zstd_level},
        "required_features": sorted(_KNOWN_FEATURES),
    }
    payload["config_sha256"] = _sha256_bytes(_canonical_json(payload))
    return payload


def _load_config(root: Path) -> dict[str, object]:
    path = root / _CONFIG_NAME
    if not path.is_file():
        raise RepositoryError(f"Rat-Trap repository not found: {root}")
    config = _read_canonical_json(path)
    checksum = config.get("config_sha256")
    without_checksum = dict(config)
    without_checksum.pop("config_sha256", None)
    if not _is_hex(checksum, 64) or checksum != _sha256_bytes(
        _canonical_json(without_checksum)
    ):
        raise RepositoryError("Repository configuration checksum failed")
    if (
        config.get("format") != REPOSITORY_FORMAT
        or config.get("schema_version") != REPOSITORY_SCHEMA_VERSION
        or not _is_hex(config.get("repository_id"), 32)
        or type(config.get("created_at_ns")) is not int
        or config.get("object_hash") != "sha256"
    ):
        raise RepositoryError("Unsupported Rat-Trap repository format")
    features = config.get("required_features")
    if (
        not isinstance(features, list)
        or any(not isinstance(item, str) for item in features)
        or not set(features).issubset(_KNOWN_FEATURES)
    ):
        raise RepositoryError("Repository requires unsupported features")
    chunking = config.get("chunking")
    compression = config.get("compression")
    if (
        not isinstance(chunking, dict)
        or chunking.get("algorithm") != "fastcdc-2020-hybrid-1"
        or chunking.get("normalized_chunking") != 1
        or chunking.get("seed") != 0
        or not isinstance(compression, dict)
        or compression.get("algorithm") != "zstd-or-raw-1"
    ):
        raise RepositoryError("Unsupported repository chunking or compression")
    _validate_chunking(
        chunking.get("minimum"),  # type: ignore[arg-type]
        chunking.get("average"),  # type: ignore[arg-type]
        chunking.get("maximum"),  # type: ignore[arg-type]
    )
    level = compression.get("zstd_level")
    if type(level) is not int or not -7 <= level <= 22:
        raise RepositoryError("Repository contains an invalid Zstandard level")
    for directory in _repository_directories(root):
        if not directory.is_dir():
            raise RepositoryError(f"Repository directory is missing: {directory}")
    return config


@contextmanager
def _repository_lock(root: Path):
    """Serialize repository operations with an OS-released byte-range lock."""
    lock_path = root / "locks" / "repository.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RepositoryLockedError(
                "Another Rat-Trap operation is using this repository"
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _failpoint(name: str) -> None:
    """No-op seam patched by crash-consistency tests."""
    return


def _open_sqlite_readonly(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    path = path.resolve()
    if not path.is_file():
        raise RepositoryError(f"Repository database not found: {path}")
    suffix = "?mode=ro"
    if immutable:
        suffix += "&immutable=1"
    connection = sqlite3.connect(f"{path.as_uri()}{suffix}", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _create_catalog_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE catalog_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE catalog_issues (
            kind TEXT NOT NULL,
            relpath TEXT NOT NULL,
            message TEXT NOT NULL,
            PRIMARY KEY(kind, relpath)
        );
        CREATE TABLE packs (
            pack_id TEXT PRIMARY KEY,
            relpath TEXT NOT NULL UNIQUE,
            created_at_ns INTEGER NOT NULL,
            object_count INTEGER NOT NULL,
            raw_bytes INTEGER NOT NULL,
            stored_bytes INTEGER NOT NULL,
            inventory_sha256 TEXT NOT NULL,
            file_bytes INTEGER NOT NULL
        );
        CREATE TABLE object_locations (
            object_id TEXT NOT NULL,
            pack_id TEXT NOT NULL REFERENCES packs(pack_id) ON DELETE CASCADE,
            raw_size INTEGER NOT NULL,
            payload_size INTEGER NOT NULL,
            PRIMARY KEY(object_id, pack_id)
        );
        CREATE INDEX object_locations_object ON object_locations(object_id);
        CREATE TABLE snapshots (
            snapshot_id TEXT PRIMARY KEY,
            manifest_sha256 TEXT NOT NULL UNIQUE,
            manifest_relpath TEXT NOT NULL UNIQUE,
            created_at_ns INTEGER NOT NULL,
            source_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            label TEXT NOT NULL,
            parent_snapshot_id TEXT,
            file_count INTEGER NOT NULL,
            directory_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            changed_file_count INTEGER NOT NULL,
            unchanged_file_count INTEGER NOT NULL,
            deleted_file_count INTEGER NOT NULL,
            new_object_count INTEGER NOT NULL,
            new_object_raw_bytes INTEGER NOT NULL,
            new_object_payload_bytes INTEGER NOT NULL,
            new_pack_file_bytes INTEGER NOT NULL,
            reused_bytes INTEGER NOT NULL
        );
        CREATE INDEX snapshots_source_created
            ON snapshots(source_id, created_at_ns DESC);
        CREATE TABLE entries (
            snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id)
                ON DELETE CASCADE,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            mode INTEGER NOT NULL,
            attributes INTEGER NOT NULL,
            sha256 TEXT,
            chunks_json TEXT NOT NULL,
            PRIMARY KEY(snapshot_id, path)
        );
        CREATE INDEX entries_path ON entries(path);
        """
    )


def _repository_signature(root: Path) -> str:
    records: list[tuple[str, int, int]] = []
    for base in (root / "manifests", root / "packs"):
        for path in sorted(
            (item for item in base.rglob("*") if item.is_file()),
            key=lambda value: value.relative_to(root).as_posix().encode("utf-8"),
        ):
            file_stat = path.stat()
            records.append(
                (
                    path.relative_to(root).as_posix(),
                    int(file_stat.st_size),
                    int(file_stat.st_mtime_ns),
                )
            )
    return _sha256_bytes(_canonical_json(records))


def _pack_inventory_digest(
    rows: Sequence[tuple[str, int, str, int, str]]
) -> str:
    return _pack_inventory_digest_sorted(
        sorted(rows, key=lambda item: item[0])
    )


class _PackInventoryHasher:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._digest.update(b"[")
        self._first = True
        self._finished = False

    def add(self, row: tuple[str, int, str, int, str]) -> None:
        if self._finished:
            raise RuntimeError("Pack inventory hash is already finalized")
        if not self._first:
            self._digest.update(b",")
        self._digest.update(
            json.dumps(
                list(row),
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        self._first = False

    def hexdigest(self) -> str:
        if not self._finished:
            self._digest.update(b"]\n")
            self._finished = True
        return self._digest.hexdigest()


def _pack_inventory_digest_sorted(
    rows: Iterable[tuple[str, int, str, int, str]]
) -> str:
    """Hash the canonical inventory array without retaining every row."""
    hasher = _PackInventoryHasher()
    for row in rows:
        hasher.add(row)
    return hasher.hexdigest()


def _pack_path(root: Path, pack_id: str) -> Path:
    if not _is_hex(pack_id, 32):
        raise RepositoryError("Pack id is invalid")
    return root / "packs" / pack_id[:2] / f"{pack_id}.rtpack"


def _load_pack_index(
    path: Path,
    config: dict[str, object],
    *,
    full: bool = False,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    with closing(_open_sqlite_readonly(path, immutable=True)) as connection:
        try:
            application_id = int(
                connection.execute("PRAGMA application_id").fetchone()[0]
            )
            user_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            info_rows = list(connection.execute("SELECT * FROM pack_info"))
            info_row = info_rows[0] if len(info_rows) == 1 else None
            object_rows = connection.execute(
                "SELECT object_id, raw_size, codec, payload_size, "
                "payload_sha256"
                + (", data" if full else "")
                + " FROM objects ORDER BY object_id"
            )
        except sqlite3.DatabaseError as exc:
            raise RepositoryError(f"Invalid Rat-Trap pack database: {path}") from exc
        if (
            application_id != PACK_APPLICATION_ID
            or user_version != PACK_SCHEMA_VERSION
            or info_row is None
        ):
            raise RepositoryError(f"Unsupported Rat-Trap pack format: {path}")
        info = dict(info_row)
        if (
            info.get("format") != PACK_FORMAT
            or info.get("schema_version") != PACK_SCHEMA_VERSION
            or info.get("repository_id") != config["repository_id"]
            or not _is_hex(info.get("pack_id"), 32)
            or type(info.get("created_at_ns")) is not int
            or type(info.get("object_count")) is not int
            or type(info.get("raw_bytes")) is not int
            or type(info.get("stored_bytes")) is not int
            or not _is_hex(info.get("inventory_sha256"), 64)
            or info.get("sealed") != 1
        ):
            raise RepositoryError(f"Pack metadata is invalid: {path}")
        expected_name = f"{info['pack_id']}.rtpack"
        if path.name != expected_name:
            raise RepositoryError(f"Pack filename does not match its id: {path}")

        inventory_hasher = _PackInventoryHasher()
        objects: list[dict[str, object]] = []
        raw_bytes = 0
        stored_bytes = 0
        decompressor = zstd.ZstdDecompressor()
        for row in object_rows:
            item = dict(row)
            object_id = item.get("object_id")
            raw_size = item.get("raw_size")
            codec = item.get("codec")
            payload_size = item.get("payload_size")
            payload_sha256 = item.get("payload_sha256")
            if (
                not _is_hex(object_id, 64)
                or type(raw_size) is not int
                or not 0 < raw_size <= MAX_OBJECT_SIZE
                or codec not in {"zstd", "raw"}
                or type(payload_size) is not int
                or payload_size <= 0
                or payload_size > raw_size
                or (codec == "raw" and payload_size != raw_size)
                or (codec == "zstd" and payload_size >= raw_size)
                or not _is_hex(payload_sha256, 64)
            ):
                raise RepositoryError(f"Pack object metadata is invalid: {path}")
            if full:
                payload = bytes(item["data"])
                if len(payload) != payload_size:
                    raise RepositoryError(f"Pack object is truncated: {object_id}")
                if _sha256_bytes(payload) != payload_sha256:
                    raise RepositoryError(
                        f"Pack object payload checksum failed: {object_id}"
                    )
                try:
                    raw = (
                        payload
                        if codec == "raw"
                        else decompressor.decompress(
                            payload, max_output_size=raw_size
                        )
                    )
                except zstd.ZstdError as exc:
                    raise RepositoryError(
                        f"Pack object decompression failed: {object_id}"
                    ) from exc
                if len(raw) != raw_size or _sha256_bytes(raw) != object_id:
                    raise RepositoryError(
                        f"Pack object content checksum failed: {object_id}"
                    )
                item.pop("data", None)
            inventory_hasher.add(
                (object_id, raw_size, codec, payload_size, payload_sha256)
            )
            raw_bytes += raw_size
            stored_bytes += payload_size
            objects.append(item)
        if (
            len(objects) != info["object_count"]
            or raw_bytes != info["raw_bytes"]
            or stored_bytes != info["stored_bytes"]
            or inventory_hasher.hexdigest() != info["inventory_sha256"]
        ):
            raise RepositoryError(f"Pack inventory checksum failed: {path}")
        return info, objects


def _manifest_hash(payload: dict[str, object]) -> str:
    return _sha256_bytes(_canonical_json(payload))


def _validate_filesystem_metadata(
    metadata: dict[str, object], context: str
) -> None:
    mtime_ns = metadata.get("mtime_ns")
    mode = metadata.get("mode")
    attributes = metadata.get("attributes")
    if (
        type(mtime_ns) is not int
        or not -(1 << 63) <= mtime_ns < (1 << 63)
        or type(mode) is not int
        or not 0 <= mode <= 0o7777
        or type(attributes) is not int
        or not 0 <= attributes <= 0xFFFFFFFF
    ):
        raise RepositoryError(f"{context} filesystem metadata is invalid")


def _validate_manifest(
    payload: dict[str, object],
    config: dict[str, object],
    *,
    expected_hash: Optional[str] = None,
) -> tuple[str, dict[str, object]]:
    if (
        payload.get("format") != SNAPSHOT_FORMAT
        or payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
        or payload.get("repository_id") != config["repository_id"]
        or not _is_hex(payload.get("snapshot_id"), 32)
        or type(payload.get("created_at_ns")) is not int
        or payload.get("created_at_ns", -1) < 0
    ):
        raise RepositoryError("Unsupported Rat-Trap snapshot manifest")
    source = payload.get("source")
    writer = payload.get("writer")
    chunking = payload.get("chunking")
    root_metadata = payload.get("root")
    inventory = payload.get("inventory")
    stats = payload.get("stats")
    entries = payload.get("entries")
    if (
        not isinstance(source, dict)
        or not _is_hex(source.get("id"), 32)
        or not isinstance(source.get("path"), str)
        or not isinstance(source.get("label"), str)
        or not isinstance(writer, dict)
        or writer.get("name") != "rat-trap"
        or not isinstance(writer.get("version"), str)
        or not isinstance(chunking, dict)
        or chunking.get("algorithm") != "fastcdc-2020-hybrid-1"
        or chunking.get("normalized_chunking") != 1
        or chunking.get("seed") != 0
        or not isinstance(root_metadata, dict)
        or not isinstance(inventory, dict)
        or not isinstance(stats, dict)
        or not isinstance(entries, list)
    ):
        raise RepositoryError("Snapshot manifest metadata is invalid")
    _validate_chunking(
        chunking.get("minimum"),  # type: ignore[arg-type]
        chunking.get("average"),  # type: ignore[arg-type]
        chunking.get("maximum"),  # type: ignore[arg-type]
    )
    if chunking.get("object_hash") != "sha256":
        raise RepositoryError("Snapshot uses an unsupported object hash")
    configured_chunking = config["chunking"]
    assert isinstance(configured_chunking, dict)
    if any(
        chunking.get(key) != configured_chunking.get(key)
        for key in (
            "algorithm",
            "minimum",
            "average",
            "maximum",
            "normalized_chunking",
            "seed",
        )
    ):
        raise RepositoryError("Snapshot chunking does not match its repository")
    parent_snapshot_id = payload.get("parent_snapshot_id")
    if parent_snapshot_id is not None and not _is_hex(parent_snapshot_id, 32):
        raise RepositoryError("Snapshot parent id is invalid")
    _validate_filesystem_metadata(root_metadata, "Snapshot root")
    for key in (
        "changed_file_count",
        "unchanged_file_count",
        "deleted_file_count",
        "new_object_count",
        "new_object_raw_bytes",
        "new_object_payload_bytes",
        "new_pack_file_bytes",
        "reused_bytes",
    ):
        if type(stats.get(key)) is not int or stats[key] < 0:
            raise RepositoryError("Snapshot statistics are invalid")

    normalised_entries: list[dict[str, object]] = []
    seen: dict[str, str] = {}
    file_count = 0
    directory_count = 0
    total_bytes = 0
    object_references = 0
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise RepositoryError("Snapshot entry is invalid")
        entry = dict(raw_entry)
        stored_path = _normalise_stored_path(entry.get("path"))
        entry["path"] = stored_path
        folded = stored_path.casefold()
        if folded in seen:
            raise RepositoryError(
                f"Snapshot contains a duplicate or case-colliding path: {stored_path!r}"
            )
        seen[folded] = stored_path
        kind = entry.get("kind")
        if kind not in {"file", "directory"}:
            raise RepositoryError(f"Snapshot entry has an invalid kind: {stored_path}")
        if type(entry.get("size")) is not int:
            raise RepositoryError(f"Snapshot entry metadata is invalid: {stored_path}")
        _validate_filesystem_metadata(entry, f"Snapshot entry {stored_path!r}")
        if entry["size"] < 0:
            raise RepositoryError(f"Snapshot entry size is invalid: {stored_path}")
        chunks = entry.get("chunks")
        sha256 = entry.get("sha256")
        if kind == "directory":
            if entry["size"] != 0 or chunks not in (None, []) or sha256 is not None:
                raise RepositoryError(
                    f"Snapshot directory metadata is invalid: {stored_path}"
                )
            entry["chunks"] = []
            entry["sha256"] = None
            directory_count += 1
        else:
            if not _is_hex(sha256, 64) or not isinstance(chunks, list):
                raise RepositoryError(f"Snapshot file metadata is invalid: {stored_path}")
            chunk_total = 0
            for chunk in chunks:
                if (
                    not isinstance(chunk, list)
                    or len(chunk) != 2
                    or not _is_hex(chunk[0], 64)
                    or type(chunk[1]) is not int
                    or not 0 < chunk[1] <= MAX_OBJECT_SIZE
                ):
                    raise RepositoryError(
                        f"Snapshot chunk metadata is invalid: {stored_path}"
                    )
                chunk_total += chunk[1]
            if chunk_total != entry["size"]:
                raise RepositoryError(
                    f"Snapshot file size does not match its chunks: {stored_path}"
                )
            file_count += 1
            total_bytes += entry["size"]
            object_references += len(chunks)
        normalised_entries.append(entry)
    if normalised_entries != sorted(normalised_entries, key=_entry_sort_key):
        raise RepositoryError("Snapshot entries are not in canonical path order")
    tree_sha256 = _sha256_bytes(_canonical_json(normalised_entries))
    if (
        inventory.get("file_count") != file_count
        or inventory.get("directory_count") != directory_count
        or inventory.get("total_bytes") != total_bytes
        or inventory.get("object_reference_count") != object_references
        or inventory.get("tree_sha256") != tree_sha256
    ):
        raise RepositoryError("Snapshot inventory checksum failed")
    if stats["changed_file_count"] + stats["unchanged_file_count"] != file_count:
        raise RepositoryError("Snapshot file-change statistics are inconsistent")
    if stats["new_object_raw_bytes"] > total_bytes:
        raise RepositoryError("Snapshot new-object statistics are inconsistent")
    if (
        stats["new_object_payload_bytes"] > stats["new_object_raw_bytes"]
        or stats["new_pack_file_bytes"] < stats["new_object_payload_bytes"]
        or (
            stats["new_object_count"] == 0
            and (
                stats["new_object_raw_bytes"] != 0
                or stats["new_object_payload_bytes"] != 0
                or stats["new_pack_file_bytes"] != 0
            )
        )
    ):
        raise RepositoryError("Snapshot physical-storage statistics are inconsistent")
    digest = _manifest_hash(payload)
    if expected_hash is not None and digest != expected_hash:
        raise RepositoryError("Snapshot manifest filename checksum failed")
    return digest, payload


def _load_manifest_path(
    path: Path, config: dict[str, object]
) -> tuple[str, dict[str, object]]:
    name = path.name
    suffix = ".rtsnap.json"
    if not name.endswith(suffix):
        raise RepositoryError(f"Unsupported snapshot manifest filename: {path}")
    expected_hash = name[: -len(suffix)]
    if not _is_hex(expected_hash, 64):
        raise RepositoryError(f"Invalid snapshot manifest filename: {path}")
    return _validate_manifest(
        _read_canonical_json(path), config, expected_hash=expected_hash
    )


def _catalog_insert_manifest(
    connection: sqlite3.Connection,
    root: Path,
    manifest_hash: str,
    manifest: dict[str, object],
) -> None:
    source = manifest["source"]
    inventory = manifest["inventory"]
    stats = manifest["stats"]
    assert isinstance(source, dict)
    assert isinstance(inventory, dict)
    assert isinstance(stats, dict)
    manifest_path = root / "manifests" / f"{manifest_hash}.rtsnap.json"
    connection.execute(
        """
        INSERT INTO snapshots(
            snapshot_id, manifest_sha256, manifest_relpath, created_at_ns,
            source_id, source_path, label, parent_snapshot_id, file_count,
            directory_count, total_bytes, changed_file_count,
            unchanged_file_count, deleted_file_count, new_object_count,
            new_object_raw_bytes, new_object_payload_bytes,
            new_pack_file_bytes, reused_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            manifest["snapshot_id"],
            manifest_hash,
            manifest_path.relative_to(root).as_posix(),
            manifest["created_at_ns"],
            source["id"],
            source["path"],
            source["label"],
            manifest.get("parent_snapshot_id"),
            inventory["file_count"],
            inventory["directory_count"],
            inventory["total_bytes"],
            stats["changed_file_count"],
            stats["unchanged_file_count"],
            stats["deleted_file_count"],
            stats["new_object_count"],
            stats["new_object_raw_bytes"],
            stats["new_object_payload_bytes"],
            stats["new_pack_file_bytes"],
            stats["reused_bytes"],
        ),
    )
    for entry in manifest["entries"]:
        connection.execute(
            """
            INSERT INTO entries(
                snapshot_id, path, kind, size, mtime_ns, mode, attributes,
                sha256, chunks_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                manifest["snapshot_id"],
                entry["path"],
                entry["kind"],
                entry["size"],
                entry["mtime_ns"],
                entry["mode"],
                entry["attributes"],
                entry.get("sha256"),
                json.dumps(entry.get("chunks", []), separators=(",", ":")),
            ),
        )


def _rebuild_catalog_locked(root: Path, config: dict[str, object]) -> None:
    staging = root / "staging" / f"catalog-{uuid.uuid4().hex}.sqlite3"
    try:
        with closing(sqlite3.connect(staging)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
            _create_catalog_schema(connection)

            for pack_path in sorted(
                (root / "packs").rglob("*.rtpack"),
                key=lambda value: value.relative_to(root).as_posix(),
            ):
                relative = pack_path.relative_to(root).as_posix()
                connection.execute("SAVEPOINT catalog_artifact")
                try:
                    info, objects = _load_pack_index(
                        pack_path, config, full=False
                    )
                    if pack_path.resolve() != _pack_path(
                        root, str(info["pack_id"])
                    ).resolve():
                        raise RepositoryError(
                            "Object pack is outside its canonical location: "
                            f"{pack_path}"
                        )
                    connection.execute(
                        "INSERT INTO packs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            info["pack_id"],
                            relative,
                            info["created_at_ns"],
                            info["object_count"],
                            info["raw_bytes"],
                            info["stored_bytes"],
                            info["inventory_sha256"],
                            pack_path.stat().st_size,
                        ),
                    )
                    for item in objects:
                        existing = connection.execute(
                            """
                            SELECT raw_size FROM object_locations
                            WHERE object_id = ? LIMIT 1
                            """,
                            (item["object_id"],),
                        ).fetchone()
                        if (
                            existing is not None
                            and existing["raw_size"] != item["raw_size"]
                        ):
                            raise RepositoryError(
                                "Object id has conflicting sizes: "
                                f"{item['object_id']}"
                            )
                        connection.execute(
                            "INSERT INTO object_locations VALUES (?, ?, ?, ?)",
                            (
                                item["object_id"],
                                info["pack_id"],
                                item["raw_size"],
                                item["payload_size"],
                            ),
                        )
                except (RepositoryError, OSError, sqlite3.DatabaseError) as exc:
                    connection.execute("ROLLBACK TO catalog_artifact")
                    connection.execute("RELEASE catalog_artifact")
                    connection.execute(
                        "INSERT INTO catalog_issues VALUES (?, ?, ?)",
                        ("pack", relative, str(exc)),
                    )
                else:
                    connection.execute("RELEASE catalog_artifact")

            for manifest_path in sorted((root / "manifests").glob("*.rtsnap.json")):
                relative = manifest_path.relative_to(root).as_posix()
                connection.execute("SAVEPOINT catalog_artifact")
                try:
                    digest, manifest = _load_manifest_path(
                        manifest_path, config
                    )
                    _catalog_insert_manifest(
                        connection, root, digest, manifest
                    )
                except (RepositoryError, OSError, sqlite3.DatabaseError) as exc:
                    connection.execute("ROLLBACK TO catalog_artifact")
                    connection.execute("RELEASE catalog_artifact")
                    connection.execute(
                        "INSERT INTO catalog_issues VALUES (?, ?, ?)",
                        ("manifest", relative, str(exc)),
                    )
                else:
                    connection.execute("RELEASE catalog_artifact")

            missing_by_snapshot: dict[str, tuple[int, str, str]] = {}
            for row in connection.execute(
                """
                SELECT snapshot_id, path, chunks_json
                FROM entries WHERE kind = 'file'
                """
            ):
                for object_id, raw_size in json.loads(row["chunks_json"]):
                    location = connection.execute(
                        """
                        SELECT 1 FROM object_locations
                        WHERE object_id = ? AND raw_size = ?
                        LIMIT 1
                        """,
                        (object_id, raw_size),
                    ).fetchone()
                    if location is not None:
                        continue
                    snapshot_id = str(row["snapshot_id"])
                    previous = missing_by_snapshot.get(snapshot_id)
                    if previous is None:
                        missing_by_snapshot[snapshot_id] = (
                            1,
                            str(row["path"]),
                            str(object_id),
                        )
                    else:
                        missing_by_snapshot[snapshot_id] = (
                            previous[0] + 1,
                            previous[1],
                            previous[2],
                        )
            for snapshot_id, (count, first_path, first_object) in sorted(
                missing_by_snapshot.items()
            ):
                snapshot = connection.execute(
                    """
                    SELECT manifest_relpath FROM snapshots
                    WHERE snapshot_id = ?
                    """,
                    (snapshot_id,),
                ).fetchone()
                assert snapshot is not None
                connection.execute(
                    "INSERT INTO catalog_issues VALUES (?, ?, ?)",
                    (
                        "snapshot-objects",
                        snapshot["manifest_relpath"],
                        f"Snapshot {snapshot_id} has {count} missing object "
                        f"reference(s); first is {first_object} for {first_path}",
                    ),
                )

            metadata = {
                "format": CATALOG_FORMAT,
                "schema_version": CATALOG_SCHEMA_VERSION,
                "repository_id": config["repository_id"],
                "state_fingerprint": _repository_signature(root),
            }
            connection.executemany(
                "INSERT INTO catalog_meta(key, value) VALUES (?, ?)",
                ((key, json.dumps(value)) for key, value in metadata.items()),
            )
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RepositoryError(f"Rebuilt catalog failed integrity check: {result}")
            connection.commit()
        _fsync_file(staging)
        os.replace(staging, root / _CATALOG_NAME)
        _fsync_directory(root)
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass


def _catalog_is_current(root: Path, config: dict[str, object]) -> bool:
    path = root / _CATALOG_NAME
    if not path.is_file():
        return False
    try:
        with closing(_open_sqlite_readonly(path)) as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return False
            metadata = {
                row["key"]: json.loads(row["value"])
                for row in connection.execute("SELECT key, value FROM catalog_meta")
            }
            return (
                metadata.get("format") == CATALOG_FORMAT
                and metadata.get("schema_version") == CATALOG_SCHEMA_VERSION
                and metadata.get("repository_id") == config["repository_id"]
                and metadata.get("state_fingerprint") == _repository_signature(root)
            )
    except (OSError, sqlite3.DatabaseError, json.JSONDecodeError, RepositoryError):
        return False


def _ensure_catalog_locked(root: Path, config: dict[str, object]) -> None:
    if not _catalog_is_current(root, config):
        _rebuild_catalog_locked(root, config)


def rebuild_catalog(repository: Path) -> RepositoryInfo:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _rebuild_catalog_locked(root, config)
        return _repository_info_locked(root, config)


def _create_job_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = DELETE;
        PRAGMA synchronous = FULL;
        CREATE TABLE job_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE plan_entries (
            path TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            mode INTEGER NOT NULL,
            attributes INTEGER NOT NULL,
            identity TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT,
            chunks_json TEXT
        );
        CREATE TABLE objects (
            object_id TEXT PRIMARY KEY,
            raw_size INTEGER NOT NULL,
            codec TEXT NOT NULL,
            payload_size INTEGER NOT NULL,
            payload_sha256 TEXT NOT NULL,
            data BLOB NOT NULL
        );
        """
    )


def _job_meta_get(connection: sqlite3.Connection, key: str) -> object:
    row = connection.execute(
        "SELECT value FROM job_meta WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        raise RepositoryError(f"Snapshot job metadata is missing '{key}'")
    try:
        return json.loads(row[0])
    except json.JSONDecodeError as exc:
        raise RepositoryError(f"Snapshot job metadata is invalid: {key}") from exc


def _job_meta_set(connection: sqlite3.Connection, key: str, value: object) -> None:
    connection.execute(
        """
        INSERT INTO job_meta(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, json.dumps(value, sort_keys=True, separators=(",", ":"))),
    )


def _open_job(job_directory: Path) -> sqlite3.Connection:
    path = job_directory / "work.sqlite3"
    if not path.is_file():
        raise RepositoryError(f"Snapshot job database is missing: {job_directory}")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RepositoryError(f"Snapshot job database failed integrity check: {result}")
        if _job_meta_get(connection, "format") != "RAT-TRAP-SNAPSHOT-JOB-1":
            raise RepositoryError(f"Unsupported snapshot job: {job_directory}")
    except sqlite3.DatabaseError as exc:
        connection.close()
        raise RepositoryError(
            f"Snapshot job database is damaged: {job_directory}"
        ) from exc
    except Exception:
        connection.close()
        raise
    return connection


def _incomplete_job_info(
    job_directory: Path, connection: sqlite3.Connection
) -> IncompleteJobInfo:
    counts = connection.execute(
        """
        SELECT COUNT(*) AS total_files,
               COALESCE(SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END), 0)
                   AS completed_files
        FROM plan_entries WHERE kind = 'file'
        """
    ).fetchone()
    objects = connection.execute(
        """
        SELECT COUNT(*) AS object_count,
               COALESCE(SUM(payload_size), 0) AS payload_bytes
        FROM objects
        """
    ).fetchone()
    source_id = _job_meta_get(connection, "source_id")
    source_path = _job_meta_get(connection, "source_path")
    label = _job_meta_get(connection, "label")
    created_at_ns = _job_meta_get(connection, "created_at_ns")
    status = _job_meta_get(connection, "status")
    if (
        not _is_hex(job_directory.name, 32)
        or not _is_hex(source_id, 32)
        or not isinstance(source_path, str)
        or not isinstance(label, str)
        or type(created_at_ns) is not int
        or status not in {"processing", "ready"}
    ):
        raise RepositoryError(
            f"Snapshot job metadata is invalid: {job_directory}"
        )
    return IncompleteJobInfo(
        job_id=job_directory.name,
        source_id=source_id,
        source_path=source_path,
        label=label,
        created_at_ns=created_at_ns,
        status=status,
        total_files=int(counts["total_files"]),
        completed_files=int(counts["completed_files"]),
        staged_object_count=int(objects["object_count"]),
        staged_object_payload_bytes=int(objects["payload_bytes"]),
    )


def _move_directory_new(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RepositoryError(f"Refusing to replace '{destination}'")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, destination)
    _fsync_directory(destination.parent)


def _create_job_locked(
    root: Path,
    config: dict[str, object],
    source: Path,
    source_root: dict[str, object],
    entries: Sequence[dict[str, object]],
    *,
    label: str,
    parent_snapshot_id: Optional[str],
) -> Path:
    snapshot_id = _new_snapshot_id()
    final_directory = root / "staging" / "jobs" / snapshot_id
    temporary_directory = (
        root / "staging" / "jobs" / f".new-{snapshot_id}-{uuid.uuid4().hex[:8]}"
    )
    temporary_directory.mkdir(parents=False)
    database = temporary_directory / "work.sqlite3"
    try:
        with closing(sqlite3.connect(database)) as connection:
            _create_job_schema(connection)
            metadata: dict[str, object] = {
                "format": "RAT-TRAP-SNAPSHOT-JOB-1",
                "repository_id": config["repository_id"],
                "snapshot_id": snapshot_id,
                "pack_id": _new_pack_id(),
                "created_at_ns": time.time_ns(),
                "source_id": _source_id(source),
                "source_path": str(source),
                "label": label,
                "parent_snapshot_id": parent_snapshot_id,
                "root": source_root,
                "plan_sha256": _plan_digest(source_root, entries),
                "status": "processing",
            }
            for key, value in metadata.items():
                _job_meta_set(connection, key, value)
            connection.executemany(
                """
                INSERT INTO plan_entries(
                    path, kind, size, mtime_ns, mode, attributes, identity,
                    completed, sha256, chunks_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        entry["path"],
                        entry["kind"],
                        entry["size"],
                        entry["mtime_ns"],
                        entry["mode"],
                        entry["attributes"],
                        entry["identity"],
                        1 if entry["kind"] == "directory" else 0,
                        None,
                        "[]" if entry["kind"] == "directory" else None,
                    )
                    for entry in entries
                ),
            )
            connection.commit()
        _fsync_file(database)
        _move_directory_new(temporary_directory, final_directory)
        return final_directory
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


def _job_plan(
    connection: sqlite3.Connection,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    source_root = _job_meta_get(connection, "root")
    if not isinstance(source_root, dict):
        raise RepositoryError("Snapshot job root metadata is invalid")
    entries = [
        {
            "path": row["path"],
            "kind": row["kind"],
            "size": row["size"],
            "mtime_ns": row["mtime_ns"],
            "mode": row["mode"],
            "attributes": row["attributes"],
            "identity": row["identity"],
        }
        for row in connection.execute(
            """
            SELECT path, kind, size, mtime_ns, mode, attributes, identity
            FROM plan_entries ORDER BY path
            """
        )
    ]
    return source_root, entries


def _job_directories(root: Path) -> Iterator[Path]:
    jobs_root = root / "staging" / "jobs"
    for path in sorted(jobs_root.iterdir(), key=lambda item: item.name):
        if path.is_dir() and not path.name.startswith(".new-"):
            yield path


def _find_job_locked(root: Path, source_id: str) -> Optional[Path]:
    matches: list[Path] = []
    for job_directory in _job_directories(root):
        with closing(_open_job(job_directory)) as connection:
            if _job_meta_get(connection, "repository_id") != _load_config(root)[
                "repository_id"
            ]:
                raise RepositoryError(f"Snapshot job belongs to another repository: {job_directory}")
            status = _job_meta_get(connection, "status")
            if (
                status != "published"
                and _job_meta_get(connection, "source_id") == source_id
            ):
                matches.append(job_directory)
    if len(matches) > 1:
        raise RepositoryError("Multiple unfinished snapshot jobs exist for this source")
    return matches[0] if matches else None


def _abandon_job_locked(root: Path, job_directory: Path, reason: str) -> Path:
    destination = root / "trash" / _utc_folder("incomplete")
    destination.mkdir(parents=True)
    _atomic_write_json(
        destination / "reason.json",
        {"reason": reason, "moved_at_ns": time.time_ns(), "job": job_directory.name},
    )
    moved = destination / job_directory.name
    _move_directory_new(job_directory, moved)
    return moved


def _entry_matches_plan(path: Path, planned: sqlite3.Row) -> bool:
    if not path.exists() or _is_link_or_junction(path):
        return False
    try:
        current = _stat_entry(path, str(planned["path"]), str(planned["kind"]))
    except OSError:
        return False
    return all(
        current[key] == planned[key]
        for key in ("kind", "size", "mtime_ns", "mode", "attributes", "identity")
    )


def _hash_file_stable(path: Path, planned: sqlite3.Row) -> str:
    if not _entry_matches_plan(path, planned):
        raise SourceChangedError(f"Source changed before it could be read: {path}")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if not _entry_matches_plan(path, planned):
        raise SourceChangedError(f"Source changed while it was being read: {path}")
    return digest.hexdigest()


def _validate_job_source(
    connection: sqlite3.Connection,
    source: Path,
    source_root: dict[str, object],
    entries: Sequence[dict[str, object]],
    *,
    rehash_completed: bool = True,
) -> None:
    expected_digest = _job_meta_get(connection, "plan_sha256")
    actual_digest = _plan_digest(source_root, entries)
    if actual_digest != expected_digest:
        raise SourceChangedError(
            "The source changed after this snapshot started; use restart=True "
            "to preserve the incomplete job in trash and begin again"
        )
    if not rehash_completed:
        return
    for row in connection.execute(
        """
        SELECT * FROM plan_entries
        WHERE kind = 'file' AND completed = 1
        ORDER BY path
        """
    ):
        current_hash = _hash_file_stable(
            source / Path(*PurePosixPath(row["path"]).parts), row
        )
        if current_hash != row["sha256"]:
            raise SourceChangedError(
                f"A completed source file changed during resume: {row['path']}"
            )


def _report_progress(
    progress: Optional[Callable[[dict[str, object]], None]], **event: object
) -> None:
    if progress is not None:
        progress(dict(event))


def _process_job_file(
    config: dict[str, object],
    connection: sqlite3.Connection,
    object_reader: "_ObjectReader",
    verified_existing: set[str],
    source: Path,
    row: sqlite3.Row,
) -> None:
    stored_path = str(row["path"])
    path = source / Path(*PurePosixPath(stored_path).parts)
    if not _entry_matches_plan(path, row):
        raise SourceChangedError(f"Source changed before it could be read: {path}")
    chunking = config["chunking"]
    compression = config["compression"]
    assert isinstance(chunking, dict)
    assert isinstance(compression, dict)
    compressor = zstd.ZstdCompressor(level=int(compression["zstd_level"]))
    file_digest = hashlib.sha256()
    chunks: list[list[object]] = []
    try:
        connection.execute("BEGIN IMMEDIATE")
        with open(path, "rb") as handle:
            for raw in _iter_content_chunks(
                handle,
                int(chunking["minimum"]),
                int(chunking["average"]),
                int(chunking["maximum"]),
            ):
                file_digest.update(raw)
                object_id = _sha256_bytes(raw)
                raw_size = len(raw)
                chunks.append([object_id, raw_size])
                local = connection.execute(
                    "SELECT raw_size FROM objects WHERE object_id = ?", (object_id,)
                ).fetchone()
                if local is not None:
                    if local["raw_size"] != raw_size:
                        raise RepositoryError(
                            f"Object id has conflicting sizes: {object_id}"
                        )
                    continue
                existing = object_reader.catalog.execute(
                    """
                    SELECT raw_size FROM object_locations
                    WHERE object_id = ? LIMIT 1
                    """,
                    (object_id,),
                ).fetchone()
                if existing is not None:
                    if existing["raw_size"] != raw_size:
                        raise RepositoryError(
                            f"Object id has conflicting sizes: {object_id}"
                        )
                    if object_id in verified_existing:
                        continue
                    try:
                        stored = object_reader.read(object_id, raw_size)
                    except RepositoryError:
                        # The current source bytes can repair an object whose
                        # previous physical copies no longer verify.
                        pass
                    else:
                        if stored != raw:
                            raise RepositoryError(
                                f"SHA-256 object collision detected: {object_id}"
                            )
                        verified_existing.add(object_id)
                        continue
                compressed = compressor.compress(raw)
                if len(compressed) < len(raw):
                    codec = "zstd"
                    payload = compressed
                else:
                    codec = "raw"
                    payload = raw
                connection.execute(
                    "INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        object_id,
                        raw_size,
                        codec,
                        len(payload),
                        _sha256_bytes(payload),
                        sqlite3.Binary(payload),
                    ),
                )
        if not _entry_matches_plan(path, row):
            raise SourceChangedError(f"Source changed while it was being read: {path}")
        connection.execute(
            """
            UPDATE plan_entries
            SET completed = 1, sha256 = ?, chunks_json = ?
            WHERE path = ?
            """,
            (
                file_digest.hexdigest(),
                json.dumps(chunks, separators=(",", ":")),
                stored_path,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    _failpoint(f"after-file:{stored_path}")


def _build_pack_ready(
    job_directory: Path,
    connection: sqlite3.Connection,
    config: dict[str, object],
) -> Optional[Path]:
    totals = connection.execute(
        """
        SELECT COUNT(*) AS object_count,
               COALESCE(SUM(raw_size), 0) AS raw_bytes,
               COALESCE(SUM(payload_size), 0) AS stored_bytes
        FROM objects
        """
    ).fetchone()
    object_count = int(totals["object_count"])
    if object_count == 0:
        return None
    pack_id = _job_meta_get(connection, "pack_id")
    created_at_ns = _job_meta_get(connection, "created_at_ns")
    if not _is_hex(pack_id, 32) or type(created_at_ns) is not int:
        raise RepositoryError("Snapshot job pack metadata is invalid")
    ready = job_directory / f"{pack_id}.rtpack"
    if ready.exists():
        info, _ = _load_pack_index(ready, config, full=True)
        if info["pack_id"] != pack_id:
            raise RepositoryError("Snapshot job contains the wrong ready pack")
        return ready

    inventory_sha256 = _pack_inventory_digest_sorted(
        (
            (
                row["object_id"],
                row["raw_size"],
                row["codec"],
                row["payload_size"],
                row["payload_sha256"],
            )
            for row in connection.execute(
                """
                SELECT object_id, raw_size, codec, payload_size, payload_sha256
                FROM objects ORDER BY object_id
                """
            )
        )
    )
    raw_bytes = int(totals["raw_bytes"])
    stored_bytes = int(totals["stored_bytes"])
    temporary = job_directory / f".pack-{uuid.uuid4().hex}.sqlite3"
    try:
        with closing(sqlite3.connect(temporary)) as pack:
            pack.row_factory = sqlite3.Row
            pack.execute(f"PRAGMA application_id = {PACK_APPLICATION_ID}")
            pack.execute(f"PRAGMA user_version = {PACK_SCHEMA_VERSION}")
            pack.execute("PRAGMA journal_mode = DELETE")
            pack.execute("PRAGMA synchronous = FULL")
            pack.executescript(
                """
                CREATE TABLE pack_info (
                    format TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    repository_id TEXT NOT NULL,
                    pack_id TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    object_count INTEGER NOT NULL,
                    raw_bytes INTEGER NOT NULL,
                    stored_bytes INTEGER NOT NULL,
                    inventory_sha256 TEXT NOT NULL,
                    sealed INTEGER NOT NULL
                );
                CREATE TABLE objects (
                    object_id TEXT PRIMARY KEY,
                    raw_size INTEGER NOT NULL,
                    codec TEXT NOT NULL,
                    payload_size INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    data BLOB NOT NULL
                );
                """
            )
            pack.executemany(
                "INSERT INTO objects VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (
                        row["object_id"],
                        row["raw_size"],
                        row["codec"],
                        row["payload_size"],
                        row["payload_sha256"],
                        row["data"],
                    )
                    for row in connection.execute(
                        """
                        SELECT object_id, raw_size, codec, payload_size,
                               payload_sha256, data
                        FROM objects ORDER BY object_id
                        """
                    )
                ),
            )
            pack.execute(
                "INSERT INTO pack_info VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    PACK_FORMAT,
                    PACK_SCHEMA_VERSION,
                    config["repository_id"],
                    pack_id,
                    created_at_ns,
                    object_count,
                    raw_bytes,
                    stored_bytes,
                    inventory_sha256,
                ),
            )
            result = pack.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RepositoryError(f"New object pack failed integrity check: {result}")
            pack.commit()
        _fsync_file(temporary)
        _move_new(temporary, ready)
        _load_pack_index(ready, config, full=True)
        return ready
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _parent_file_hashes_locked(
    root: Path, parent_snapshot_id: Optional[str]
) -> dict[str, str]:
    if parent_snapshot_id is None:
        return {}
    with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
        return {
            row["path"]: row["sha256"]
            for row in catalog.execute(
                """
                SELECT path, sha256 FROM entries
                WHERE snapshot_id = ? AND kind = 'file'
                """,
                (parent_snapshot_id,),
            )
        }


def _reconcile_job_objects_locked(
    root: Path,
    job_directory: Path,
    connection: sqlite3.Connection,
) -> int:
    """Drop staged objects that another snapshot published while this job paused."""
    removable: list[str] = []
    with _ObjectReader(root) as reader:
        for row in connection.execute(
            "SELECT object_id, raw_size FROM objects ORDER BY object_id"
        ):
            try:
                reader.read(str(row["object_id"]), int(row["raw_size"]))
            except RepositoryError:
                # Missing or corrupt canonical copies must be repaired from the
                # source-derived staged object rather than silently discarded.
                continue
            removable.append(str(row["object_id"]))
    if not removable:
        return 0

    pack_id = _job_meta_get(connection, "pack_id")
    if not _is_hex(pack_id, 32):
        raise RepositoryError("Snapshot job pack metadata is invalid")
    # Derived files must be invalidated before the durable row deletion. If a
    # process stops between these steps, the next resume can safely derive them
    # again from the still-complete staging database.
    for derived in (
        job_directory / f"{pack_id}.rtpack",
        job_directory / "manifest.ready",
    ):
        try:
            derived.unlink()
        except FileNotFoundError:
            pass
    _fsync_directory(job_directory)

    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "DELETE FROM objects WHERE object_id = ?",
            ((object_id,) for object_id in removable),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    _fsync_file(job_directory / "work.sqlite3")
    return len(removable)


def _prepare_job_manifest(
    root: Path,
    job_directory: Path,
    connection: sqlite3.Connection,
    config: dict[str, object],
    source: Path,
) -> tuple[str, dict[str, object]]:
    incomplete = int(
        connection.execute(
            "SELECT COUNT(*) FROM plan_entries WHERE completed = 0"
        ).fetchone()[0]
    )
    if incomplete:
        raise RepositoryError("Cannot seal an incomplete snapshot job")
    _reconcile_job_objects_locked(root, job_directory, connection)
    ready_pack = _build_pack_ready(job_directory, connection, config)
    new_pack_file_bytes = 0 if ready_pack is None else ready_pack.stat().st_size

    entries: list[dict[str, object]] = []
    object_reference_count = 0
    for row in connection.execute("SELECT * FROM plan_entries ORDER BY path"):
        chunks = json.loads(row["chunks_json"] or "[]")
        entry = {
            "path": row["path"],
            "kind": row["kind"],
            "size": row["size"],
            "mtime_ns": row["mtime_ns"],
            "mode": row["mode"],
            "attributes": row["attributes"],
            "sha256": row["sha256"],
            "chunks": chunks,
        }
        object_reference_count += len(chunks)
        entries.append(entry)
    files = [entry for entry in entries if entry["kind"] == "file"]
    directories = [entry for entry in entries if entry["kind"] == "directory"]
    total_bytes = sum(int(entry["size"]) for entry in files)
    parent_snapshot_id = _job_meta_get(connection, "parent_snapshot_id")
    if parent_snapshot_id is not None and not _is_hex(parent_snapshot_id, 32):
        raise RepositoryError("Snapshot job parent id is invalid")
    parent_hashes = _parent_file_hashes_locked(root, parent_snapshot_id)
    current_hashes = {str(entry["path"]): str(entry["sha256"]) for entry in files}
    unchanged_count = sum(
        1 for path, digest in current_hashes.items() if parent_hashes.get(path) == digest
    )
    new_object_row = connection.execute(
        """
        SELECT COUNT(*) AS object_count,
               COALESCE(SUM(raw_size), 0) AS raw_bytes,
               COALESCE(SUM(payload_size), 0) AS payload_bytes
        FROM objects
        """
    ).fetchone()
    new_raw_bytes = int(new_object_row["raw_bytes"])
    source_root = _job_meta_get(connection, "root")
    assert isinstance(source_root, dict)
    configured_chunking = config["chunking"]
    assert isinstance(configured_chunking, dict)
    manifest: dict[str, object] = {
        "format": SNAPSHOT_FORMAT,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "repository_id": config["repository_id"],
        "snapshot_id": _job_meta_get(connection, "snapshot_id"),
        "created_at_ns": _job_meta_get(connection, "created_at_ns"),
        "parent_snapshot_id": parent_snapshot_id,
        "source": {
            "id": _job_meta_get(connection, "source_id"),
            "path": str(source),
            "label": _job_meta_get(connection, "label"),
        },
        "writer": {"name": "rat-trap", "version": WRITER_VERSION},
        "chunking": {
            "algorithm": "fastcdc-2020-hybrid-1",
            "minimum": configured_chunking["minimum"],
            "average": configured_chunking["average"],
            "maximum": configured_chunking["maximum"],
            "normalized_chunking": configured_chunking[
                "normalized_chunking"
            ],
            "seed": configured_chunking["seed"],
            "object_hash": "sha256",
        },
        "root": {
            "mtime_ns": source_root["mtime_ns"],
            "mode": source_root["mode"],
            "attributes": source_root["attributes"],
        },
        "inventory": {
            "file_count": len(files),
            "directory_count": len(directories),
            "total_bytes": total_bytes,
            "object_reference_count": object_reference_count,
            "tree_sha256": _sha256_bytes(_canonical_json(entries)),
        },
        "stats": {
            "changed_file_count": len(files) - unchanged_count,
            "unchanged_file_count": unchanged_count,
            "deleted_file_count": len(set(parent_hashes) - set(current_hashes)),
            "new_object_count": int(new_object_row["object_count"]),
            "new_object_raw_bytes": new_raw_bytes,
            "new_object_payload_bytes": int(new_object_row["payload_bytes"]),
            "new_pack_file_bytes": new_pack_file_bytes,
            "reused_bytes": max(0, total_bytes - new_raw_bytes),
        },
        "entries": entries,
    }
    digest, manifest = _validate_manifest(manifest, config)
    ready = job_directory / "manifest.ready"
    if ready.exists():
        existing_digest, existing = _validate_manifest(
            _read_canonical_json(ready), config
        )
        if existing_digest != digest or existing != manifest:
            raise RepositoryError("Snapshot job ready manifest is inconsistent")
    else:
        _atomic_write_json(ready, manifest)
    _job_meta_set(connection, "manifest_sha256", digest)
    _job_meta_set(connection, "status", "ready")
    connection.commit()
    _fsync_file(job_directory / "work.sqlite3")
    return digest, manifest


def _snapshot_info_from_row(row: sqlite3.Row, *, pinned: bool = False) -> SnapshotInfo:
    return SnapshotInfo(
        snapshot_id=row["snapshot_id"],
        manifest_sha256=row["manifest_sha256"],
        created_at_ns=row["created_at_ns"],
        source_id=row["source_id"],
        source_path=row["source_path"],
        label=row["label"],
        parent_snapshot_id=row["parent_snapshot_id"],
        file_count=row["file_count"],
        directory_count=row["directory_count"],
        total_bytes=row["total_bytes"],
        changed_file_count=row["changed_file_count"],
        unchanged_file_count=row["unchanged_file_count"],
        deleted_file_count=row["deleted_file_count"],
        new_object_count=row["new_object_count"],
        new_object_raw_bytes=row["new_object_raw_bytes"],
        new_object_payload_bytes=row["new_object_payload_bytes"],
        new_pack_file_bytes=row["new_pack_file_bytes"],
        reused_bytes=row["reused_bytes"],
        pinned=pinned,
    )


def _snapshot_info_locked(
    root: Path, snapshot_id: str, *, resumed: bool = False
) -> SnapshotInfo:
    with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
        row = catalog.execute(
            "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
    if row is None:
        raise RepositoryError(f"Snapshot not found: {snapshot_id}")
    info = _snapshot_info_from_row(
        row, pinned=snapshot_id in _pinned_snapshot_ids_locked(root)
    )
    if resumed:
        info = dataclasses.replace(info, resumed=True)
    return info


def _finalize_job_locked(
    root: Path,
    config: dict[str, object],
    job_directory: Path,
    *,
    resumed: bool,
) -> SnapshotInfo:
    with closing(_open_job(job_directory)) as connection:
        status = _job_meta_get(connection, "status")
        if status != "ready":
            raise RepositoryError("Snapshot job is not ready to publish")
        manifest_hash = _job_meta_get(connection, "manifest_sha256")
        snapshot_id = _job_meta_get(connection, "snapshot_id")
        pack_id = _job_meta_get(connection, "pack_id")
        if (
            not _is_hex(manifest_hash, 64)
            or not _is_hex(snapshot_id, 32)
            or not _is_hex(pack_id, 32)
        ):
            raise RepositoryError("Snapshot job publication metadata is invalid")
        manifest_destination = (
            root / "manifests" / f"{manifest_hash}.rtsnap.json"
        )
        ready_manifest = job_directory / "manifest.ready"
        if ready_manifest.exists():
            _, manifest = _validate_manifest(
                _read_canonical_json(ready_manifest),
                config,
                expected_hash=manifest_hash,
            )
        elif manifest_destination.exists():
            _, manifest = _load_manifest_path(manifest_destination, config)
        else:
            raise RepositoryError("Snapshot job manifest disappeared before publication")

        object_count = int(
            connection.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        )
        if object_count:
            pack_destination = _pack_path(root, pack_id)
            ready_pack = job_directory / f"{pack_id}.rtpack"
            if pack_destination.exists():
                info, _ = _load_pack_index(pack_destination, config, full=True)
                if info["pack_id"] != pack_id:
                    raise RepositoryError("Published pack id is inconsistent")
            else:
                if not ready_pack.exists():
                    raise RepositoryError("Snapshot job pack disappeared before publication")
                _move_new(ready_pack, pack_destination)
            _failpoint("after-pack-publish")

        _rebuild_catalog_locked(root, config)
        with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
            for entry in manifest["entries"]:
                for object_id, raw_size in entry.get("chunks", []):
                    found = catalog.execute(
                        """
                        SELECT 1 FROM object_locations
                        WHERE object_id = ? AND raw_size = ? LIMIT 1
                        """,
                        (object_id, raw_size),
                    ).fetchone()
                    if found is None:
                        raise RepositoryError(
                            f"Cannot publish snapshot with missing object: {object_id}"
                        )

        if not manifest_destination.exists():
            _move_new(ready_manifest, manifest_destination)
        else:
            _load_manifest_path(manifest_destination, config)
        _failpoint("after-manifest-publish")
        _rebuild_catalog_locked(root, config)
        info = _snapshot_info_locked(root, str(snapshot_id), resumed=resumed)
        _job_meta_set(connection, "status", "published")
        connection.commit()
    try:
        shutil.rmtree(job_directory)
    except OSError:
        # The canonical snapshot is already durable. Antivirus/indexer handles
        # must not turn successful publication into a reported backup failure.
        pass
    return info


def _recover_ready_jobs_locked(
    root: Path, config: dict[str, object]
) -> dict[str, SnapshotInfo]:
    recovered: dict[str, SnapshotInfo] = {}
    for job_directory in list(_job_directories(root)):
        try:
            with closing(_open_job(job_directory)) as connection:
                status = _job_meta_get(connection, "status")
                source_id = _job_meta_get(connection, "source_id")
                snapshot_id = _job_meta_get(connection, "snapshot_id")
        except RepositoryError as exc:
            _abandon_job_locked(root, job_directory, str(exc))
            continue
        if status == "ready":
            try:
                info = _finalize_job_locked(
                    root, config, job_directory, resumed=True
                )
            except (RepositoryError, OSError, sqlite3.DatabaseError) as exc:
                if job_directory.exists():
                    _abandon_job_locked(
                        root,
                        job_directory,
                        "Ready snapshot job could not be safely published: "
                        f"{exc}",
                    )
                _ensure_catalog_locked(root, config)
                continue
            recovered[str(source_id)] = info
        elif status == "published":
            _ensure_catalog_locked(root, config)
            _snapshot_info_locked(root, str(snapshot_id), resumed=True)
            try:
                shutil.rmtree(job_directory)
            except OSError:
                pass
    return recovered


def _directory_file_bytes(directory: Path) -> int:
    if not directory.exists():
        return 0
    total = 0
    for path in directory.rglob("*"):
        if _is_link_or_junction(path) or not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError as exc:
            raise RepositoryError(
                f"Could not measure repository file '{path}': {exc}"
            ) from exc
    return total


def _repository_info_locked(
    root: Path, config: dict[str, object]
) -> RepositoryInfo:
    _ensure_catalog_locked(root, config)
    with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
        snapshot_count = int(
            catalog.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        )
        pack_count = int(catalog.execute("SELECT COUNT(*) FROM packs").fetchone()[0])
        object_count = int(
            catalog.execute(
                "SELECT COUNT(DISTINCT object_id) FROM object_locations"
            ).fetchone()[0]
        )
        object_payload_bytes = int(
            catalog.execute(
                "SELECT COALESCE(SUM(stored_bytes), 0) FROM packs"
            ).fetchone()[0]
        )
        issue_count = int(
            catalog.execute("SELECT COUNT(*) FROM catalog_issues").fetchone()[0]
        )
    pack_file_bytes = _directory_file_bytes(root / "packs")
    trash_file_bytes = _directory_file_bytes(root / "trash")
    repository_file_bytes = _directory_file_bytes(root)
    return RepositoryInfo(
        path=str(root),
        repository_id=str(config["repository_id"]),
        created_at_ns=int(config["created_at_ns"]),
        snapshot_count=snapshot_count,
        pack_count=pack_count,
        object_count=object_count,
        object_payload_bytes=object_payload_bytes,
        pack_file_bytes=pack_file_bytes,
        repository_file_bytes=repository_file_bytes,
        trash_file_bytes=trash_file_bytes,
        issue_count=issue_count,
    )


def _is_partial_repository_skeleton(
    root: Path,
    *,
    allow_config_write_staging: bool = False,
) -> bool:
    allowed_directories = {
        "manifests",
        "packs",
        "locks",
        "staging",
        "staging/jobs",
        "refs",
        "refs/pins",
        "trash",
    }
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if allow_config_write_staging and relative == _CONFIG_NAME:
            if _is_link_or_junction(path):
                return False
            if not path.exists() or path.is_file():
                continue
            return False
        if (
            allow_config_write_staging
            and path.parent == root
            and path.name.startswith(f".{_CONFIG_NAME}.")
            and path.name.endswith(".rat-trap-write")
        ):
            if _is_link_or_junction(path):
                return False
            # os.replace() can publish the configuration between rglob()
            # yielding the staging name and this classification.
            if not path.exists() or path.is_file():
                continue
            return False
        if relative == "locks/repository.lock":
            if path.is_file() and not _is_link_or_junction(path):
                continue
            return False
        if (
            not path.is_dir()
            or _is_link_or_junction(path)
            or relative not in allowed_directories
        ):
            return False
    return True


def _validate_requested_repository_settings(
    config: dict[str, object],
    chunk_min: int,
    chunk_avg: int,
    chunk_max: int,
    zstd_level: int,
) -> None:
    chunking = config["chunking"]
    compression = config["compression"]
    assert isinstance(chunking, dict)
    assert isinstance(compression, dict)
    requested = (chunk_min, chunk_avg, chunk_max, zstd_level)
    existing = (
        chunking["minimum"],
        chunking["average"],
        chunking["maximum"],
        compression["zstd_level"],
    )
    if requested != existing:
        raise RepositoryError(
            "Repository already exists with different chunking or "
            "compression settings"
        )


def init_repository(
    repository: Path,
    *,
    chunk_min: int = DEFAULT_CHUNK_MIN,
    chunk_avg: int = DEFAULT_CHUNK_AVG,
    chunk_max: int = DEFAULT_CHUNK_MAX,
    zstd_level: int = DEFAULT_ZSTD_LEVEL,
) -> RepositoryInfo:
    root = Path(repository).resolve()
    _validate_chunking(chunk_min, chunk_avg, chunk_max)
    if type(zstd_level) is not int or not -7 <= zstd_level <= 22:
        raise RepositoryError("Zstandard level must be an integer from -7 to 22")
    if root.exists() and not root.is_dir():
        raise RepositoryError(f"Repository path is not a folder: {root}")
    if (root / _CONFIG_NAME).exists():
        config = _load_config(root)
        with _repository_lock(root):
            config = _load_config(root)
            _validate_requested_repository_settings(
                config,
                chunk_min,
                chunk_avg,
                chunk_max,
                zstd_level,
            )
            return _repository_info_locked(root, config)
    if (
        root.exists()
        and any(root.iterdir())
        and not _is_partial_repository_skeleton(
            root,
            allow_config_write_staging=True,
        )
        # A competing initializer can publish repository.json after the
        # first existence check but while the skeleton is being inspected.
        and not (root / _CONFIG_NAME).exists()
    ):
        raise RepositoryError(
            "Repository initialization requires a new or empty folder"
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "locks").mkdir(parents=True, exist_ok=True)
    with _repository_lock(root):
        # Another initializer may have won the race before this process
        # acquired the lifecycle lock. Reuse its durable identity and never
        # overwrite it with a losing process's configuration.
        if (root / _CONFIG_NAME).exists():
            config = _load_config(root)
            _validate_requested_repository_settings(
                config,
                chunk_min,
                chunk_avg,
                chunk_max,
                zstd_level,
            )
            return _repository_info_locked(root, config)
        if not _is_partial_repository_skeleton(root):
            raise RepositoryError(
                "Repository initialization requires a new or empty folder"
            )
        for directory in _repository_directories(root):
            directory.mkdir(parents=True, exist_ok=True)
        config = _config_payload(
            uuid.uuid4().hex,
            time.time_ns(),
            chunk_min,
            chunk_avg,
            chunk_max,
            zstd_level,
        )
        _atomic_write_json(root / _CONFIG_NAME, config)
        _rebuild_catalog_locked(root, config)
        return _repository_info_locked(root, config)


def repository_info(repository: Path) -> RepositoryInfo:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        return _repository_info_locked(root, config)


def list_repository_issues(repository: Path) -> list[RepositoryIssue]:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        _ensure_catalog_locked(root, config)
        with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
            rows = list(
                catalog.execute(
                    """
                    SELECT kind, relpath, message FROM catalog_issues
                    ORDER BY kind, relpath
                    """
                )
            )
        return [
            RepositoryIssue(
                kind=str(row["kind"]),
                relpath=str(row["relpath"]),
                message=str(row["message"]),
            )
            for row in rows
        ]


def list_incomplete_jobs(repository: Path) -> list[IncompleteJobInfo]:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        jobs: list[IncompleteJobInfo] = []
        for job_directory in _job_directories(root):
            with closing(_open_job(job_directory)) as connection:
                if _job_meta_get(connection, "status") == "published":
                    continue
                jobs.append(_incomplete_job_info(job_directory, connection))
        return sorted(
            jobs, key=lambda item: (item.created_at_ns, item.job_id)
        )


def abandon_incomplete_job(
    repository: Path, job_id: str
) -> AbandonJobResult:
    root = Path(repository).resolve()
    config = _load_config(root)
    if not _is_hex(job_id, 32):
        raise RepositoryError("Incomplete job id is invalid")
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        job_directory = root / "staging" / "jobs" / job_id
        if not job_directory.is_dir():
            raise RepositoryError(f"Incomplete snapshot job not found: {job_id}")
        with closing(_open_job(job_directory)) as connection:
            if _job_meta_get(connection, "repository_id") != config[
                "repository_id"
            ]:
                raise RepositoryError(
                    "Incomplete snapshot job belongs to another repository"
                )
            info = _incomplete_job_info(job_directory, connection)
        trash = _abandon_job_locked(
            root,
            job_directory,
            "User explicitly abandoned this incomplete snapshot job",
        )
        _ensure_catalog_locked(root, config)
        return AbandonJobResult(
            job_id=job_id,
            source_path=info.source_path,
            trash_path=str(trash),
        )


def _latest_snapshot_id_locked(root: Path, source_id: str) -> Optional[str]:
    with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
        row = catalog.execute(
            """
            SELECT snapshot_id FROM snapshots
            WHERE source_id = ?
            ORDER BY created_at_ns DESC, snapshot_id DESC LIMIT 1
            """,
            (source_id,),
        ).fetchone()
    return None if row is None else str(row["snapshot_id"])


def create_snapshot(
    repository: Path,
    source: Path,
    *,
    label: str = "",
    restart: bool = False,
    progress: Optional[Callable[[dict[str, object]], None]] = None,
) -> SnapshotInfo:
    root = Path(repository).resolve()
    source_argument = Path(source)
    if _is_link_or_junction(source_argument):
        raise RepositoryError(
            "A repository source cannot be a symbolic link or junction"
        )
    source = source_argument.resolve()
    if not isinstance(label, str) or len(label) > 500:
        raise RepositoryError("Snapshot label must contain at most 500 characters")
    config = _load_config(root)
    if _path_is_within(root, source) or _path_is_within(source, root):
        raise RepositoryError("Repository and source folders must not overlap")
    source_id = _source_id(source)
    with _repository_lock(root):
        _ensure_catalog_locked(root, config)
        recovered = _recover_ready_jobs_locked(root, config)
        if source_id in recovered:
            return recovered[source_id]
        source_root, entries = _enumerate_source(source)
        job_directory = _find_job_locked(root, source_id)
        resumed = job_directory is not None
        if job_directory is not None:
            if restart:
                _abandon_job_locked(
                    root,
                    job_directory,
                    "User explicitly restarted the incomplete snapshot",
                )
                job_directory = None
                resumed = False
            else:
                with closing(_open_job(job_directory)) as connection:
                    _validate_job_source(
                        connection, source, source_root, entries
                    )
        if job_directory is None:
            parent = _latest_snapshot_id_locked(root, source_id)
            job_directory = _create_job_locked(
                root,
                config,
                source,
                source_root,
                entries,
                label=label,
                parent_snapshot_id=parent,
            )

        with closing(_open_job(job_directory)) as connection:
            file_total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM plan_entries WHERE kind = 'file'"
                ).fetchone()[0]
            )
            completed = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM plan_entries
                    WHERE kind = 'file' AND completed = 1
                    """
                ).fetchone()[0]
            )
            _report_progress(
                progress,
                phase="snapshot",
                completed_files=completed,
                total_files=file_total,
                resumed=resumed,
            )
            verified_existing: set[str] = set()
            with _ObjectReader(root) as object_reader:
                while True:
                    row = connection.execute(
                        """
                        SELECT * FROM plan_entries
                        WHERE kind = 'file' AND completed = 0
                        ORDER BY path LIMIT 1
                        """
                    ).fetchone()
                    if row is None:
                        break
                    _process_job_file(
                        config,
                        connection,
                        object_reader,
                        verified_existing,
                        source,
                        row,
                    )
                    completed += 1
                    _report_progress(
                        progress,
                        phase="snapshot",
                        path=row["path"],
                        completed_files=completed,
                        total_files=file_total,
                        resumed=resumed,
                    )
            final_root, final_entries = _enumerate_source(source)
            _validate_job_source(
                connection,
                source,
                final_root,
                final_entries,
                rehash_completed=False,
            )
            _prepare_job_manifest(
                root, job_directory, connection, config, source
            )
        _report_progress(
            progress,
            phase="publish",
            completed_files=file_total,
            total_files=file_total,
            resumed=resumed,
        )
        return _finalize_job_locked(
            root, config, job_directory, resumed=resumed
        )


def _pinned_snapshot_ids_locked(root: Path) -> set[str]:
    pins: set[str] = set()
    repository_id = _load_config(root)["repository_id"]
    for path in sorted((root / "refs" / "pins").glob("*.json")):
        snapshot_id = path.stem
        marker = _read_canonical_json(path)
        checksum = marker.get("checksum_sha256")
        unsigned = dict(marker)
        unsigned.pop("checksum_sha256", None)
        if (
            not _is_hex(snapshot_id, 32)
            or marker.get("format") != "RAT-TRAP-SNAPSHOT-PIN-1"
            or marker.get("repository_id") != repository_id
            or marker.get("snapshot_id") != snapshot_id
            or not _is_hex(marker.get("manifest_sha256"), 64)
            or type(marker.get("created_at_ns")) is not int
            or not _is_hex(checksum, 64)
            or checksum != _sha256_bytes(_canonical_json(unsigned))
        ):
            raise RepositoryError(f"Invalid snapshot pin: {path}")
        pins.add(snapshot_id)
    return pins


def pin_snapshot(
    repository: Path, snapshot_id: str, *, pinned: bool = True
) -> SnapshotInfo:
    root = Path(repository).resolve()
    config = _load_config(root)
    if not _is_hex(snapshot_id, 32):
        raise RepositoryError("Snapshot id is invalid")
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        _ensure_catalog_locked(root, config)
        info = _snapshot_info_locked(root, snapshot_id)
        path = root / "refs" / "pins" / f"{snapshot_id}.json"
        if pinned:
            marker: dict[str, object] = {
                "format": "RAT-TRAP-SNAPSHOT-PIN-1",
                "repository_id": config["repository_id"],
                "snapshot_id": snapshot_id,
                "manifest_sha256": info.manifest_sha256,
                "created_at_ns": time.time_ns(),
            }
            marker["checksum_sha256"] = _sha256_bytes(_canonical_json(marker))
            _atomic_write_json(path, marker)
        elif path.exists():
            path.unlink()
            _fsync_directory(path.parent)
        return dataclasses.replace(info, pinned=pinned)


def list_snapshots(repository: Path) -> list[SnapshotInfo]:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        _ensure_catalog_locked(root, config)
        pins = _pinned_snapshot_ids_locked(root)
        with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
            rows = list(
                catalog.execute(
                    """
                    SELECT * FROM snapshots
                    ORDER BY created_at_ns DESC, snapshot_id DESC
                    """
                )
            )
        return [
            _snapshot_info_from_row(row, pinned=row["snapshot_id"] in pins)
            for row in rows
        ]


def search_history(
    repository: Path, query: str, *, limit: int = 100
) -> list[HistoryEntry]:
    if not isinstance(query, str) or not query.strip():
        raise RepositoryError("History search requires a non-empty query")
    if type(limit) is not int or not 1 <= limit <= 10_000:
        raise RepositoryError("History search limit must be from 1 to 10000")
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        _ensure_catalog_locked(root, config)
        with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
            rows = list(
                catalog.execute(
                    """
                    SELECT s.snapshot_id, s.created_at_ns, s.label,
                           e.path, e.kind, e.size, e.sha256
                    FROM entries AS e
                    JOIN snapshots AS s USING(snapshot_id)
                    WHERE instr(lower(e.path), lower(?)) > 0
                       OR instr(lower(s.label), lower(?)) > 0
                    ORDER BY s.created_at_ns DESC, e.path
                    LIMIT ?
                    """,
                    (query, query, limit),
                )
            )
    return [
        HistoryEntry(
            snapshot_id=row["snapshot_id"],
            created_at_ns=row["created_at_ns"],
            label=row["label"],
            path=row["path"],
            kind=row["kind"],
            size=row["size"],
            sha256=row["sha256"],
        )
        for row in rows
    ]


def _snapshot_manifest_locked(
    root: Path, config: dict[str, object], snapshot_id: str
) -> dict[str, object]:
    if not _is_hex(snapshot_id, 32):
        raise RepositoryError("Snapshot id is invalid")
    with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
        row = catalog.execute(
            """
            SELECT manifest_relpath, manifest_sha256 FROM snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
    if row is None:
        matching_paths: list[Path] = []
        for candidate_path in sorted(
            (root / "manifests").glob("*.rtsnap.json")
        ):
            try:
                candidate = _read_json(candidate_path)
            except RepositoryError:
                continue
            if candidate.get("snapshot_id") == snapshot_id:
                matching_paths.append(candidate_path)
        if len(matching_paths) == 1:
            # Surface the precise validation error for a requested degraded
            # snapshot instead of disguising it as unrelated missing history.
            return _load_manifest_path(matching_paths[0], config)[1]
        if len(matching_paths) > 1:
            raise RepositoryError(
                f"Snapshot id is ambiguous in damaged history: {snapshot_id}"
            )
        raise RepositoryError(f"Snapshot not found: {snapshot_id}")
    path = (root / row["manifest_relpath"]).resolve()
    if not _path_is_within(path, root / "manifests"):
        raise RepositoryError("Catalog contains an unsafe manifest path")
    digest, manifest = _load_manifest_path(path, config)
    if digest != row["manifest_sha256"]:
        raise RepositoryError("Catalog and snapshot manifest disagree")
    return manifest


class _ObjectReader:
    def __init__(self, root: Path):
        self.root = root
        self.catalog = _open_sqlite_readonly(root / _CATALOG_NAME)
        self.packs: OrderedDict[str, sqlite3.Connection] = OrderedDict()
        self.decompressor = zstd.ZstdDecompressor()

    def close(self) -> None:
        for connection in self.packs.values():
            connection.close()
        self.packs.clear()
        self.catalog.close()

    def __enter__(self) -> "_ObjectReader":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _pack(self, relpath: str) -> sqlite3.Connection:
        connection = self.packs.get(relpath)
        if connection is not None:
            self.packs.move_to_end(relpath)
            return connection
        path = (self.root / relpath).resolve()
        if not _path_is_within(path, self.root / "packs"):
            raise RepositoryError("Catalog contains an unsafe object-pack path")
        connection = _open_sqlite_readonly(path, immutable=True)
        self.packs[relpath] = connection
        if len(self.packs) > 64:
            _, oldest = self.packs.popitem(last=False)
            oldest.close()
        return connection

    def read(self, object_id: str, expected_size: int) -> bytes:
        locations = list(
            self.catalog.execute(
                """
                SELECT p.relpath, o.raw_size
                FROM object_locations AS o
                JOIN packs AS p USING(pack_id)
                WHERE o.object_id = ?
                ORDER BY p.created_at_ns, p.pack_id
                """,
                (object_id,),
            )
        )
        if not locations:
            raise RepositoryError(f"Snapshot object is missing: {object_id}")
        failures: list[str] = []
        for location in locations:
            if location["raw_size"] != expected_size:
                failures.append(f"{location['relpath']}: size metadata")
                continue
            try:
                row = self._pack(location["relpath"]).execute(
                    """
                    SELECT raw_size, codec, payload_size, payload_sha256, data
                    FROM objects WHERE object_id = ?
                    """,
                    (object_id,),
                ).fetchone()
                if row is None:
                    raise RepositoryError("object row missing")
                payload = bytes(row["data"])
                if (
                    row["raw_size"] != expected_size
                    or len(payload) != row["payload_size"]
                    or _sha256_bytes(payload) != row["payload_sha256"]
                ):
                    raise RepositoryError("payload metadata or checksum failed")
                if row["codec"] == "raw":
                    raw = payload
                elif row["codec"] == "zstd":
                    raw = self.decompressor.decompress(
                        payload, max_output_size=expected_size
                    )
                else:
                    raise RepositoryError("unsupported object codec")
                if len(raw) != expected_size or _sha256_bytes(raw) != object_id:
                    raise RepositoryError("content checksum failed")
                return raw
            except (RepositoryError, sqlite3.DatabaseError, zstd.ZstdError, OSError) as exc:
                failures.append(f"{location['relpath']}: {exc}")
        raise RepositoryError(
            f"Every copy of snapshot object {object_id} failed verification: "
            + "; ".join(failures)
        )


def _apply_restored_metadata(
    path: Path, *, mode: int, mtime_ns: int, attributes: int
) -> None:
    try:
        os.chmod(path, mode)
        os.utime(path, ns=(mtime_ns, mtime_ns))
        if os.name == "nt":
            import ctypes

            portable_attributes = attributes & (0x1 | 0x2 | 0x4 | 0x20 | 0x2000)
            if portable_attributes == 0:
                portable_attributes = 0x80
            if not ctypes.windll.kernel32.SetFileAttributesW(
                str(path), portable_attributes
            ):
                raise ctypes.WinError()
    except (OSError, OverflowError, ValueError) as exc:
        raise RepositoryError(f"Could not restore metadata for '{path}': {exc}") from exc


def restore_snapshot(
    repository: Path,
    snapshot_id: str,
    destination: Path,
) -> RestoreResult:
    root = Path(repository).resolve()
    destination = Path(destination).resolve()
    config = _load_config(root)
    if destination.exists():
        raise RepositoryError(
            "Restore destination must not already exist; Rat-Trap never merges "
            "a verified snapshot into an existing folder"
        )
    if _path_is_within(destination, root) or _path_is_within(root, destination):
        raise RepositoryError("Restore destination and repository must not overlap")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.rat-trap-restore-",
            dir=destination.parent,
        )
    )
    published = False
    try:
        with _repository_lock(root):
            _recover_ready_jobs_locked(root, config)
            _ensure_catalog_locked(root, config)
            manifest = _snapshot_manifest_locked(root, config, snapshot_id)
            entries = manifest["entries"]
            assert isinstance(entries, list)
            directories = [
                entry for entry in entries if entry["kind"] == "directory"
            ]
            files = [entry for entry in entries if entry["kind"] == "file"]
            for entry in directories:
                _safe_destination(temporary, str(entry["path"])).mkdir(
                    parents=True, exist_ok=False
                )
            with _ObjectReader(root) as reader:
                for entry in files:
                    output = _safe_destination(temporary, str(entry["path"]))
                    output.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with open(output, "xb") as handle:
                        for object_id, raw_size in entry["chunks"]:
                            raw = reader.read(object_id, raw_size)
                            handle.write(raw)
                            digest.update(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    if (
                        output.stat().st_size != entry["size"]
                        or digest.hexdigest() != entry["sha256"]
                    ):
                        raise RepositoryError(
                            f"Restored file checksum failed: {entry['path']}"
                        )
            for entry in files:
                output = _safe_destination(temporary, str(entry["path"]))
                _apply_restored_metadata(
                    output,
                    mode=int(entry["mode"]),
                    mtime_ns=int(entry["mtime_ns"]),
                    attributes=int(entry["attributes"]),
                )
            for entry in sorted(
                directories,
                key=lambda item: len(PurePosixPath(str(item["path"])).parts),
                reverse=True,
            ):
                output = _safe_destination(temporary, str(entry["path"]))
                _apply_restored_metadata(
                    output,
                    mode=int(entry["mode"]),
                    mtime_ns=int(entry["mtime_ns"]),
                    attributes=int(entry["attributes"]),
                )
            root_metadata = manifest["root"]
            assert isinstance(root_metadata, dict)
            _apply_restored_metadata(
                temporary,
                mode=int(root_metadata["mode"]),
                mtime_ns=int(root_metadata["mtime_ns"]),
                attributes=int(root_metadata["attributes"]),
            )
            if destination.exists():
                raise RepositoryError("Restore destination appeared during restore")
            _move_directory_new(temporary, destination)
            published = True
        inventory = manifest["inventory"]
        assert isinstance(inventory, dict)
        return RestoreResult(
            snapshot_id=snapshot_id,
            destination=str(destination),
            file_count=int(inventory["file_count"]),
            directory_count=int(inventory["directory_count"]),
            restored_bytes=int(inventory["total_bytes"]),
        )
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def verify_repository(
    repository: Path, *, full: bool = True
) -> VerifyResult:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        _ensure_catalog_locked(root, config)
        manifests = [
            _load_manifest_path(path, config)[1]
            for path in sorted((root / "manifests").glob("*.rtsnap.json"))
        ]
        pins = _pinned_snapshot_ids_locked(root)
        snapshot_ids = {str(item["snapshot_id"]) for item in manifests}
        if not pins.issubset(snapshot_ids):
            raise RepositoryError(
                "Repository contains a pin for missing snapshot history"
            )
        pack_indexes: list[
            tuple[dict[str, object], list[dict[str, object]]]
        ] = []
        for path in sorted((root / "packs").rglob("*.rtpack")):
            pack_indexes.append(_load_pack_index(path, config, full=full))

        referenced: dict[str, int] = {}
        file_count = 0
        logical_bytes = 0
        for manifest in manifests:
            inventory = manifest["inventory"]
            assert isinstance(inventory, dict)
            file_count += int(inventory["file_count"])
            logical_bytes += int(inventory["total_bytes"])
            for entry in manifest["entries"]:
                for object_id, raw_size in entry.get("chunks", []):
                    previous = referenced.get(object_id)
                    if previous is not None and previous != raw_size:
                        raise RepositoryError(
                            f"Object id has conflicting manifest sizes: {object_id}"
                        )
                    referenced[object_id] = raw_size

        all_objects: dict[str, int] = {}
        pack_object_ids: dict[str, set[str]] = {}
        object_payload_bytes = 0
        for info, objects in pack_indexes:
            pack_ids: set[str] = set()
            object_payload_bytes += int(info["stored_bytes"])
            for item in objects:
                object_id = str(item["object_id"])
                raw_size = int(item["raw_size"])
                if object_id in all_objects and all_objects[object_id] != raw_size:
                    raise RepositoryError(
                        f"Object id has conflicting pack sizes: {object_id}"
                    )
                all_objects[object_id] = raw_size
                pack_ids.add(object_id)
            pack_object_ids[str(info["pack_id"])] = pack_ids
        missing = set(referenced) - set(all_objects)
        if missing:
            raise RepositoryError(
                f"Repository is missing {len(missing)} referenced object(s)"
            )

        if full:
            with _ObjectReader(root) as reader:
                for manifest in manifests:
                    for entry in manifest["entries"]:
                        if entry["kind"] != "file":
                            continue
                        digest = hashlib.sha256()
                        size = 0
                        for object_id, raw_size in entry["chunks"]:
                            raw = reader.read(object_id, raw_size)
                            digest.update(raw)
                            size += len(raw)
                        if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                            raise RepositoryError(
                                "Snapshot file checksum failed during verification: "
                                f"{entry['path']}"
                            )

        unreferenced = set(all_objects) - set(referenced)
        orphan_pack_count = sum(
            1
            for object_ids in pack_object_ids.values()
            if not (object_ids & set(referenced))
        )
        return VerifyResult(
            snapshot_count=len(manifests),
            pack_count=len(pack_indexes),
            file_count=file_count,
            object_count=len(all_objects),
            logical_bytes=logical_bytes,
            object_payload_bytes=object_payload_bytes,
            pack_file_bytes=_directory_file_bytes(root / "packs"),
            repository_file_bytes=_directory_file_bytes(root),
            trash_file_bytes=_directory_file_bytes(root / "trash"),
            unreferenced_object_count=len(unreferenced),
            unreferenced_raw_bytes=sum(all_objects[item] for item in unreferenced),
            orphan_pack_count=orphan_pack_count,
            full_data_verified=full,
        )


def _retention_state_fingerprint(root: Path) -> str:
    pins = [
        (path.name, _sha256_bytes(path.read_bytes()))
        for path in sorted((root / "refs" / "pins").glob("*.json"))
    ]
    return _sha256_bytes(
        _canonical_json(
            {"repository": _repository_signature(root), "pins": pins}
        )
    )


def _retention_keep_ids(
    rows: Sequence[sqlite3.Row],
    pins: set[str],
    policy: RetentionPolicy,
) -> set[str]:
    keep = set(pins)
    by_source: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_source.setdefault(str(row["source_id"]), []).append(row)
    for source_rows in by_source.values():
        source_rows.sort(
            key=lambda row: (int(row["created_at_ns"]), str(row["snapshot_id"])),
            reverse=True,
        )
        if not source_rows:
            continue
        keep.add(str(source_rows[0]["snapshot_id"]))
        keep.update(
            str(row["snapshot_id"]) for row in source_rows[: policy.keep_last]
        )
        bucket_specs = (
            (
                policy.keep_daily,
                lambda value: (value.year, value.month, value.day),
            ),
            (
                policy.keep_weekly,
                lambda value: tuple(value.isocalendar()[:2]),
            ),
            (
                policy.keep_monthly,
                lambda value: (value.year, value.month),
            ),
        )
        for count, bucket_for in bucket_specs:
            selected_buckets: set[tuple[int, ...]] = set()
            for row in source_rows:
                if len(selected_buckets) >= count:
                    break
                created = datetime.fromtimestamp(
                    int(row["created_at_ns"]) / 1_000_000_000,
                    tz=timezone.utc,
                )
                bucket = bucket_for(created)
                if bucket not in selected_buckets:
                    selected_buckets.add(bucket)
                    keep.add(str(row["snapshot_id"]))
    return keep


def _object_ids_for_snapshots(
    catalog: sqlite3.Connection, snapshot_ids: set[str]
) -> set[str]:
    if not snapshot_ids:
        return set()
    object_ids: set[str] = set()
    for row in catalog.execute(
        "SELECT snapshot_id, chunks_json FROM entries WHERE kind = 'file'"
    ):
        if row["snapshot_id"] not in snapshot_ids:
            continue
        for object_id, _ in json.loads(row["chunks_json"]):
            object_ids.add(object_id)
    return object_ids


def _dead_pack_metrics(
    catalog: sqlite3.Connection, kept_objects: set[str]
) -> tuple[set[str], int, int]:
    pack_objects: dict[str, set[str]] = {}
    object_sizes: dict[str, int] = {}
    for row in catalog.execute(
        "SELECT pack_id, object_id, raw_size FROM object_locations"
    ):
        pack_objects.setdefault(row["pack_id"], set()).add(row["object_id"])
        object_sizes.setdefault(row["object_id"], int(row["raw_size"]))
    fully_dead = {
        pack_id
        for pack_id, object_ids in pack_objects.items()
        if not (object_ids & kept_objects)
    }
    if fully_dead:
        placeholders = ",".join("?" for _ in fully_dead)
        reclaimable = int(
            catalog.execute(
                f"""
                SELECT COALESCE(SUM(file_bytes), 0) FROM packs
                WHERE pack_id IN ({placeholders})
                """,
                tuple(sorted(fully_dead)),
            ).fetchone()[0]
        )
    else:
        reclaimable = 0
    dead_objects_in_mixed_packs: set[str] = set()
    for pack_id, object_ids in pack_objects.items():
        if pack_id not in fully_dead:
            dead_objects_in_mixed_packs.update(object_ids - kept_objects)
    unreclaimed = sum(
        object_sizes[object_id] for object_id in dead_objects_in_mixed_packs
    )
    return fully_dead, reclaimable, unreclaimed


def _plan_retention_locked(
    root: Path, policy: RetentionPolicy
) -> tuple[RetentionPlan, set[str]]:
    policy.validate()
    unfinished_jobs: list[str] = []
    for job_directory in _job_directories(root):
        with closing(_open_job(job_directory)) as connection:
            if _job_meta_get(connection, "status") == "processing":
                unfinished_jobs.append(job_directory.name)
    if unfinished_jobs:
        raise RepositoryError(
            "Retention is blocked while an interrupted snapshot is unfinished; "
            "resume or explicitly restart that backup first"
        )
    with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
        issue_count = int(
            catalog.execute("SELECT COUNT(*) FROM catalog_issues").fetchone()[0]
        )
        if issue_count:
            raise RepositoryError(
                "Retention is blocked because the repository has "
                f"{issue_count} unresolved integrity issue(s); "
                "run repository verification before cleanup"
            )
        rows = list(
            catalog.execute(
                """
                SELECT snapshot_id, source_id, created_at_ns, total_bytes
                FROM snapshots
                ORDER BY created_at_ns DESC, snapshot_id DESC
                """
            )
        )
        all_ids = {str(row["snapshot_id"]) for row in rows}
        pins = _pinned_snapshot_ids_locked(root)
        missing_pins = pins - all_ids
        if missing_pins:
            raise RepositoryError(
                "Snapshot pin refers to missing history: "
                + ", ".join(sorted(missing_pins))
            )
        keep = _retention_keep_ids(rows, pins, policy)
        remove = all_ids - keep
        kept_objects = _object_ids_for_snapshots(catalog, keep)
        fully_dead, reclaimable, unreclaimed = _dead_pack_metrics(
            catalog, kept_objects
        )
        logical_removed = sum(
            int(row["total_bytes"])
            for row in rows
            if row["snapshot_id"] in remove
        )
    state_fingerprint = _retention_state_fingerprint(root)
    plan_payload = {
        "state_fingerprint": state_fingerprint,
        "policy": policy.as_dict(),
        "keep_snapshot_ids": sorted(keep),
        "remove_snapshot_ids": sorted(remove),
        "logical_bytes_removed": logical_removed,
        "fully_reclaimable_pack_bytes": reclaimable,
        "unreclaimed_dead_object_raw_bytes": unreclaimed,
    }
    plan = RetentionPlan(
        plan_id=_sha256_bytes(_canonical_json(plan_payload)),
        state_fingerprint=state_fingerprint,
        created_at_ns=time.time_ns(),
        policy=policy,
        keep_snapshot_ids=tuple(sorted(keep)),
        remove_snapshot_ids=tuple(sorted(remove)),
        logical_bytes_removed=logical_removed,
        fully_reclaimable_pack_bytes=reclaimable,
        unreclaimed_dead_object_raw_bytes=unreclaimed,
    )
    return plan, fully_dead


def plan_retention(
    repository: Path, policy: RetentionPolicy
) -> RetentionPlan:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        _ensure_catalog_locked(root, config)
        plan, _ = _plan_retention_locked(root, policy)
        return plan


def prune_repository(
    repository: Path,
    policy: RetentionPolicy,
    *,
    apply: bool = False,
    expected_plan_id: Optional[str] = None,
) -> RetentionPlan | PruneResult:
    root = Path(repository).resolve()
    config = _load_config(root)
    with _repository_lock(root):
        _recover_ready_jobs_locked(root, config)
        _ensure_catalog_locked(root, config)
        plan, fully_dead = _plan_retention_locked(root, policy)
        if not apply:
            if expected_plan_id is not None:
                raise RepositoryError(
                    "A plan id is only valid when applying retention"
                )
            return plan
        if not _is_hex(expected_plan_id, 64):
            raise RepositoryError(
                "Applying retention requires a valid plan id from a fresh preview"
            )
        if expected_plan_id != plan.plan_id:
            raise RepositoryError(
                "Repository history changed after the retention preview; "
                "review a new dry-run plan before applying"
            )
        if not plan.remove_snapshot_ids and not fully_dead:
            return PruneResult(
                plan=plan,
                applied=True,
                trash_path=None,
                moved_manifest_count=0,
                moved_pack_count=0,
                moved_to_trash_pack_bytes=0,
                reclaimed_pack_bytes=0,
            )

        trash = root / "trash" / _utc_folder("prune")
        trash.mkdir(parents=True)
        _atomic_write_json(trash / "retention-plan.json", plan.as_dict())
        moved_manifests = 0
        moved_packs = 0
        reclaimed_bytes = 0
        with closing(_open_sqlite_readonly(root / _CATALOG_NAME)) as catalog:
            for snapshot_id in plan.remove_snapshot_ids:
                row = catalog.execute(
                    """
                    SELECT manifest_relpath FROM snapshots
                    WHERE snapshot_id = ?
                    """,
                    (snapshot_id,),
                ).fetchone()
                if row is None:
                    raise RepositoryError(
                        f"Retention snapshot disappeared: {snapshot_id}"
                    )
                source = (root / row["manifest_relpath"]).resolve()
                if not _path_is_within(source, root / "manifests"):
                    raise RepositoryError("Catalog contains an unsafe manifest path")
                destination = trash / "manifests" / source.name
                _move_new(source, destination)
                moved_manifests += 1
            _failpoint("after-prune-manifests")
            for pack_id in sorted(fully_dead):
                row = catalog.execute(
                    "SELECT relpath, file_bytes FROM packs WHERE pack_id = ?",
                    (pack_id,),
                ).fetchone()
                if row is None:
                    raise RepositoryError(f"Retention pack disappeared: {pack_id}")
                source = (root / row["relpath"]).resolve()
                if not _path_is_within(source, root / "packs"):
                    raise RepositoryError("Catalog contains an unsafe pack path")
                relative = source.relative_to(root / "packs")
                destination = trash / "packs" / relative
                _move_new(source, destination)
                moved_packs += 1
                reclaimed_bytes += int(row["file_bytes"])
        _failpoint("after-prune-packs")
        _rebuild_catalog_locked(root, config)
        result = PruneResult(
            plan=plan,
            applied=True,
            trash_path=str(trash),
            moved_manifest_count=moved_manifests,
            moved_pack_count=moved_packs,
            moved_to_trash_pack_bytes=reclaimed_bytes,
            reclaimed_pack_bytes=0,
        )
        _atomic_write_json(trash / "retention-result.json", result.as_dict())
        return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def export_snapshot(
    repository: Path,
    snapshot_id: str,
    output: Path,
    *,
    profile: str = "balanced",
    encryption_password: Optional[str] = None,
    recovery_key_output: Optional[Path] = None,
    allow_plaintext_temp: bool = False,
) -> ExportResult:
    root = Path(repository).resolve()
    output = Path(output).resolve()
    _load_config(root)
    if output.exists():
        raise RepositoryError(f"Export destination already exists: {output}")
    if _path_is_within(output, root):
        raise RepositoryError("Portable archives cannot be exported inside a repository")
    if (encryption_password is None) != (recovery_key_output is None):
        raise RepositoryError(
            "Encrypted portable export requires both a password and a new "
            "recovery-key output path"
        )
    recovery_output = (
        Path(recovery_key_output).resolve()
        if recovery_key_output is not None
        else None
    )
    if recovery_output is not None:
        if recovery_output in {output, root} or _path_is_within(
            recovery_output, root
        ):
            raise RepositoryError(
                "The recovery key must be outside the repository and archive"
            )
        if recovery_output.exists():
            raise RepositoryError(
                f"Recovery key destination already exists: {recovery_output}"
            )
    from . import gmw_tool, secure_engine

    if encryption_password is not None and not allow_plaintext_temp:
        raise RepositoryError(
            f"{gmw_tool.PLAINTEXT_TEMP_WARNING} "
            "Re-run with explicit acknowledgement."
        )
    if profile not in gmw_tool.COMPRESSION_PROFILES:
        raise RepositoryError(f"Unknown portable archive profile: {profile}")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".rat-trap-export",
        dir=output.parent,
    )
    os.close(descriptor)
    staged_output = Path(staged_name)
    staged_output.unlink()
    try:
        # Restored source material stays in the operating-system temporary
        # directory. Only the portable archive staging file is adjacent to the
        # destination, which keeps final publication on one filesystem.
        with tempfile.TemporaryDirectory(
            prefix="rat-trap-export-"
        ) as temporary_name:
            temporary = Path(temporary_name)
            restored = temporary / "snapshot"
            restore_snapshot(root, snapshot_id, restored)
            try:
                gmw_tool.compress_folder(
                    restored,
                    staged_output,
                    profile=profile,
                    encryption_password=encryption_password,
                    recovery_key_output=recovery_output,
                    allow_plaintext_temp=allow_plaintext_temp,
                )
                if encryption_password is None:
                    gmw_tool.read_metadata(staged_output)
                else:
                    secure_engine.verify_encrypted_file(
                        staged_output, password=encryption_password
                    )
            except (OSError, ValueError, sqlite3.DatabaseError, zstd.ZstdError) as exc:
                raise RepositoryError(
                    f"Could not create portable archive: {exc}"
                ) from exc
            archive_bytes = staged_output.stat().st_size
            archive_sha256 = _sha256_file(staged_output)
            _move_new(staged_output, output)
    finally:
        try:
            staged_output.unlink()
        except FileNotFoundError:
            pass
    return ExportResult(
        snapshot_id=snapshot_id,
        output=str(output),
        profile=profile,
        archive_bytes=archive_bytes,
        archive_sha256=archive_sha256,
        encrypted=encryption_password is not None,
        encryption_format=(
            secure_engine.SECURE_FORMAT
            if encryption_password is not None
            else ""
        ),
        recovery_key_path=(
            str(recovery_output) if recovery_output is not None else None
        ),
    )


__all__ = [
    "AbandonJobResult",
    "DEFAULT_CHUNK_AVG",
    "DEFAULT_CHUNK_MAX",
    "DEFAULT_CHUNK_MIN",
    "DEFAULT_ZSTD_LEVEL",
    "ExportResult",
    "HistoryEntry",
    "IncompleteJobInfo",
    "PruneResult",
    "RepositoryError",
    "RepositoryInfo",
    "RepositoryIssue",
    "RepositoryLockedError",
    "RestoreResult",
    "RetentionPlan",
    "RetentionPolicy",
    "SnapshotInfo",
    "SourceChangedError",
    "VerifyResult",
    "abandon_incomplete_job",
    "create_snapshot",
    "export_snapshot",
    "init_repository",
    "list_incomplete_jobs",
    "list_repository_issues",
    "list_snapshots",
    "pin_snapshot",
    "plan_retention",
    "prune_repository",
    "rebuild_catalog",
    "repository_info",
    "restore_snapshot",
    "search_history",
    "verify_repository",
]
