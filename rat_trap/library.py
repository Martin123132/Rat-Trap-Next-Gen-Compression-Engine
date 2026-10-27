"""Local, explicitly populated Rat-Trap Library and project timeline.

The catalogue is UNENCRYPTED metadata: paths, labels, project names and user
notes are readable by the signed-in account. It does not collect credentials,
archive contents, inner filenames or decrypted metadata. User-entered labels
and notes must not contain secrets; they are stored as ordinary text.
Registering/refreshing only reads the selected storage; it never changes it.
Repository manifests are checked, not repository payloads: registration is
not a substitute for the engine's Verify operation or an independent backup.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from .repository_engine import SnapshotInfo

APPLICATION_ID = 0x52544C31  # RTL1, distinct from every archive/repository family.
SCHEMA_VERSION = 1
MAX_SNAPSHOTS = 10000
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_INSPECTION_BYTES = 128 * 1024 * 1024
MAX_CATALOG_BYTES = 256 * 1024 * 1024
_INIT_LOCK = threading.RLock()
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REPARSE = 0x400


class LibraryError(ValueError):
    """Invalid, unsupported or unsafe Library operation; originals unchanged."""


class IdentityMismatchError(LibraryError):
    """The selected storage is not the originally registered object."""


class _Record:
    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Project(_Record):
    id: str
    name: str
    description: str
    created_at: str


@dataclass(frozen=True)
class LibraryItem(_Record):
    id: str
    path: str
    label: str
    kind: str
    identity: str
    project_id: str | None
    status: str
    size_bytes: int
    protected: bool
    added_at: str
    last_checked_at: str


@dataclass(frozen=True)
class TimelineEvent(_Record):
    id: str
    item_id: str | None
    project_id: str | None
    kind: str
    occurred_at: str
    date_source: str
    title: str
    detail: str
    snapshot_id: str | None


@dataclass(frozen=True)
class SnapshotRecord(_Record):
    snapshot_id: str
    manifest_sha256: str
    occurred_at: str
    label: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True)
class StorageInspection(_Record):
    """Inspected outer storage; repository size_bytes=0 means not measured."""
    kind: str
    identity: str
    size_bytes: int
    protected: bool
    snapshots: tuple[SnapshotRecord, ...] = ()
    # Routing-only metadata, including source paths: returned to the UI on an
    # explicit inspection, never automatically serialized into the catalogue.
    # Manual backup plans separately save explicitly chosen source paths.
    repository_snapshots: tuple[SnapshotInfo, ...] = ()


def default_catalog_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise LibraryError("LOCALAPPDATA is unavailable; choose an explicit Library path")
    return Path(base) / "Two Hands Network Ltd" / "Rat-Trap" / "Library" / "library.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _stored_time(value: object, *, date_ok: bool = False) -> None:
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError
        if date_ok and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
        elif datetime.fromisoformat(value).tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise LibraryError("Library timestamp metadata is damaged") from exc


def _text(value: str, name: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise LibraryError(f"{name} must be text")
    value = value.strip()
    if (not value and not empty) or len(value) > maximum or any(
        ord(char) < 32 and char not in "\n\t" for char in value
    ):
        raise LibraryError(f"{name} must contain {'0' if empty else '1'}–{maximum} characters without control characters")
    return value


def _absolute(path: str | Path) -> Path:
    # Do not resolve links before inspecting them.
    raw = os.fspath(path)
    if not raw or "\x00" in raw:
        raise LibraryError("A valid filesystem path is required")
    result = Path(os.path.abspath(raw))
    if os.name == "nt" and (str(result).startswith("\\\\") or any(":" in p for p in result.parts[1:])):
        raise LibraryError("Use a local drive path, not a network/device path or alternate data stream")
    return result


def _guard_path(path: Path, *, missing_ok: bool = False, catalog: bool = False) -> None:
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if missing_ok:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE:
            raise LibraryError("Links, junctions and reparse points are not supported for Library paths")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise LibraryError("A parent path is not a directory")
        if component == path and not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise LibraryError("Only ordinary files and folders can be registered")
        if catalog and component == path:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise LibraryError("The Library catalogue must be an ordinary, unlinked file")
            if info.st_size > MAX_CATALOG_BYTES:
                raise LibraryError("Library catalogue exceeds this preview's size limit")


def _signature(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_bounded(path: Path, maximum: int) -> bytes:
    _guard_path(path)
    before = _signature(path)
    if before[2] > maximum:
        raise LibraryError("Storage metadata exceeds this preview's inspection limit")
    with path.open("rb") as handle:
        data = handle.read(maximum + 1)
    _guard_path(path)
    if len(data) > maximum or before != _signature(path):
        raise LibraryError("Storage changed during inspection; try again when it is idle")
    return data


def _json_object(data: bytes) -> dict:
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LibraryError("Storage metadata is not valid bounded JSON") from exc
    if not isinstance(value, dict):
        raise LibraryError("Storage metadata must be a JSON object")
    return value


def _readonly_sqlite(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro" + ("&immutable=1" if immutable else ""), uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
    budget = [2000]

    def progress() -> int:
        budget[0] -= 1
        return int(budget[0] <= 0)

    connection.set_progress_handler(progress, 1000)
    return connection


def _inspect_sqlite(path: Path) -> str:
    from . import gmw_tool, vault_engine

    # Immutable mode prevents SQLite creating even an SHM sidecar beside the
    # source. An active WAL/journal cannot be silently ignored.
    for suffix in ("-wal", "-shm", "-journal"):
        if os.path.lexists(str(path) + suffix):
            raise LibraryError("Close the archive's writer before adding or refreshing it")
    connection = _readonly_sqlite(path, immutable=True)
    try:
        definitions = connection.execute("SELECT name,type,sql FROM sqlite_master LIMIT 501").fetchall()
        if len(definitions) > 500 or any(row["type"] in {"view", "trigger"} for row in definitions):
            raise LibraryError("Unsupported archive database schema")
        tables = {row["name"] for row in definitions if row["type"] == "table"}
        metadata_table = "vault_metadata" if "vault_metadata" in tables else "metadata"
        if metadata_table in tables:
            lengths = connection.execute(f'SELECT length(key),length(value) FROM "{metadata_table}" LIMIT 65').fetchall()
            if (len(lengths) > 64 or any(type(row[0]) is not int or type(row[1]) is not int or
                                       row[0] > 128 or row[1] > 16384 for row in lengths)):
                raise LibraryError("Archive metadata exceeds this preview's inspection limit")
        if "vault_metadata" in tables:
            vault_engine._load_metadata(connection)
            return "vault"
        if not set(gmw_tool._LEGACY_SQLITE_SCHEMA).issubset(tables):
            raise LibraryError("This SQLite file is not a supported Rat-Trap archive or Vault")
        for table, columns in gmw_tool._LEGACY_SQLITE_SCHEMA.items():
            actual = {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if not columns.issubset(actual):
                raise LibraryError("Unsupported legacy archive database schema")
        gmw_tool._load_metadata(connection)
        return "archive"
    finally:
        connection.close()


def _inspect_repository(path: Path) -> StorageInspection:
    from . import repository_engine as engine

    config_path = path / "repository.json"
    config_data = _read_bounded(config_path, 64 * 1024)
    config = _json_object(config_data)
    checksum = config.get("config_sha256")
    payload = dict(config)
    payload.pop("config_sha256", None)
    if checksum != hashlib.sha256(engine._canonical_json(payload)).hexdigest():
        raise LibraryError("Repository configuration checksum failed")
    if (config.get("format") != engine.REPOSITORY_FORMAT or
            type(config.get("schema_version")) is not int or config["schema_version"] != 1 or
            not isinstance(config.get("repository_id"), str) or not _HEX32.fullmatch(config["repository_id"]) or
            type(config.get("created_at_ns")) is not int or not 0 <= config["created_at_ns"] <= 2**63 - 1 or
            config.get("object_hash") != "sha256"):
        raise LibraryError("Unsupported Rat-Trap repository configuration")
    features = config.get("required_features")
    if not isinstance(features, list) or any(not isinstance(x, str) or x not in engine._KNOWN_FEATURES for x in features):
        raise LibraryError("Repository requires unsupported features")
    chunking = config.get("chunking")
    compression = config.get("compression")
    if (not isinstance(chunking, dict) or chunking.get("algorithm") != "fastcdc-2020-hybrid-1" or
            chunking.get("normalized_chunking") != 1 or chunking.get("seed") != 0 or
            not isinstance(compression, dict) or compression.get("algorithm") != "zstd-or-raw-1"):
        raise LibraryError("Unsupported repository chunking or compression")
    engine._validate_chunking(chunking.get("minimum"), chunking.get("average"), chunking.get("maximum"))
    if type(compression.get("zstd_level")) is not int or not -7 <= compression["zstd_level"] <= 22:
        raise LibraryError("Invalid repository compression level")
    for directory in engine._repository_directories(path):
        _guard_path(directory)
        if not directory.is_dir():
            raise LibraryError("Repository layout is incomplete")
    manifests: list[Path] = []
    with os.scandir(path / "manifests") as entries:
        for entry in entries:
            # Refuse unrelated directory entries rather than recursively scan.
            if len(manifests) >= MAX_SNAPSHOTS:
                raise LibraryError("Repository exceeds this preview's snapshot limit")
            candidate = Path(entry.path)
            _guard_path(candidate)
            if not candidate.is_file() or not candidate.name.endswith(".rtsnap.json"):
                raise LibraryError("Repository has an unexpected manifest entry")
            manifests.append(candidate)
    snapshots: list[SnapshotRecord] = []
    repository_snapshots = []
    seen: set[str] = set()
    total_read = len(config_data)
    for manifest in sorted(manifests):
        expected_hash = manifest.name[:-len(".rtsnap.json")]
        if not _HEX64.fullmatch(expected_hash):
            raise LibraryError("Invalid repository manifest filename")
        raw = _read_bounded(manifest, min(MAX_MANIFEST_BYTES, MAX_INSPECTION_BYTES - total_read))
        total_read += len(raw)
        value = _json_object(raw)
        if not isinstance(value.get("entries"), list) or len(value["entries"]) > 250000:
            raise LibraryError("Manifest exceeds this preview's entry limit")
        _, value = engine._validate_manifest(value, config, expected_hash=expected_hash)
        snapshot_id = value["snapshot_id"]
        if snapshot_id in seen:
            raise LibraryError("Repository contains ambiguous duplicate snapshot IDs")
        seen.add(snapshot_id)
        timestamp = value["created_at_ns"]
        if not 0 <= timestamp <= 2**63 - 1:
            raise LibraryError("Snapshot timestamp is outside the supported range")
        occurred_at = datetime.fromtimestamp(timestamp / 1e9, timezone.utc).isoformat(timespec="microseconds")
        label = _text(value["source"]["label"], "Snapshot label", 1000, empty=True)
        snapshots.append(SnapshotRecord(snapshot_id, expected_hash, occurred_at, label,
                                        value["inventory"]["file_count"], value["inventory"]["total_bytes"]))
        pin_path = path / "refs" / "pins" / (snapshot_id + ".json")
        pinned = False
        if os.path.lexists(pin_path):
            pin_raw = _read_bounded(pin_path, min(64 * 1024, MAX_INSPECTION_BYTES - total_read))
            total_read += len(pin_raw)
            pin = _json_object(pin_raw)
            unsigned = dict(pin)
            unsigned.pop("checksum_sha256", None)
            if (pin.get("format") != "RAT-TRAP-SNAPSHOT-PIN-1" or pin.get("repository_id") != config["repository_id"] or
                    pin.get("snapshot_id") != snapshot_id or pin.get("manifest_sha256") != expected_hash or
                    pin.get("checksum_sha256") != hashlib.sha256(engine._canonical_json(unsigned)).hexdigest()):
                raise LibraryError("Snapshot pin is damaged or mismatched")
            pinned = True
        repository_snapshots.append(engine.SnapshotInfo(
            snapshot_id=snapshot_id, manifest_sha256=expected_hash, created_at_ns=timestamp,
            source_id=value["source"]["id"], source_path=value["source"]["path"], label=label,
            parent_snapshot_id=value.get("parent_snapshot_id"), file_count=value["inventory"]["file_count"],
            directory_count=value["inventory"]["directory_count"], total_bytes=value["inventory"]["total_bytes"],
            pinned=pinned, **{key: value["stats"][key] for key in (
                "changed_file_count", "unchanged_file_count", "deleted_file_count", "new_object_count",
                "new_object_raw_bytes", "new_object_payload_bytes", "new_pack_file_bytes", "reused_bytes")}))
    if _read_bounded(config_path, 64 * 1024) != config_data:
        raise LibraryError("Repository configuration changed during inspection")
    # No catalogue, lock, packs or stored source paths are opened or copied.
    return StorageInspection("repository", "repository:" + config["repository_id"], 0, False,
                             tuple(snapshots), tuple(repository_snapshots))


def inspect_storage(path: str | Path) -> StorageInspection:
    """Read selected storage without writing it, decrypting it or scanning sources.

    File identities are a streaming SHA-256 of all outer bytes. Repository
    identities are their verified configuration UUID; snapshots use their
    recorded UUID plus verified manifest checksum, never file modification time.
    """
    path = _absolute(path)
    try:
        _guard_path(path)
        if path.is_dir():
            return _inspect_repository(path)
        if path.suffix.casefold() not in {".gmw", ".db", ".rtsf"}:
            raise LibraryError("Choose a .gmw archive, .db Vault, .rtsf protected file or repository folder; never a recovery key")
        before = _signature(path)
        with path.open("rb") as source:
            prefix = source.read(32)
        from . import secure_engine, solid_engine
        protected = prefix.startswith(secure_engine.SECURE_MAGIC)
        if protected:
            secure_engine.read_secure_info(path)  # Header only; unauthenticated until unlocked by the engine.
            kind = "sealed_file" if path.suffix.casefold() == ".rtsf" else "protected_archive"
        elif path.suffix.casefold() == ".rtsf":
            raise LibraryError("This .rtsf file is not a protected Rat-Trap envelope")
        elif prefix.startswith(solid_engine.MAGIC):
            solid_engine.read_metadata(path)
            kind = "archive"
        elif prefix.startswith(b"SQLite format 3\x00"):
            kind = _inspect_sqlite(path)
        else:
            raise LibraryError("The selected file is not a supported Rat-Trap format")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            remaining = before[2]
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise LibraryError("Storage changed during inspection; try again when it is idle")
                digest.update(chunk)
                remaining -= len(chunk)
            if source.read(1):
                raise LibraryError("Storage changed during inspection; try again when it is idle")
        _guard_path(path)
        if before != _signature(path):
            raise LibraryError("Storage changed during inspection; try again when it is idle")
        return StorageInspection(kind, "sha256:" + digest.hexdigest(), before[2], protected)
    except LibraryError:
        raise
    except FileNotFoundError:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, OverflowError, RecursionError) as exc:
        raise LibraryError("Selected storage could not be safely inspected: " + str(exc)) from exc


_SCHEMA = (
    "CREATE TABLE library_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE items (id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, label TEXT NOT NULL, kind TEXT NOT NULL, identity TEXT NOT NULL, project_id TEXT REFERENCES projects(id) ON DELETE SET NULL, status TEXT NOT NULL, size_bytes INTEGER NOT NULL, protected INTEGER NOT NULL, added_at TEXT NOT NULL, last_checked_at TEXT NOT NULL)",
    "CREATE TABLE events (id TEXT PRIMARY KEY, item_id TEXT REFERENCES items(id) ON DELETE CASCADE, project_id TEXT REFERENCES projects(id) ON DELETE SET NULL, kind TEXT NOT NULL, occurred_at TEXT NOT NULL, date_source TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, snapshot_id TEXT, manifest_sha256 TEXT, UNIQUE(item_id, snapshot_id))",
    "CREATE INDEX event_time ON events(occurred_at DESC)",
)
_SCHEMA_SQL = {statement.split()[2]: statement for statement in _SCHEMA}


class LibraryStore:
    """Small thread-safe-by-connection local catalogue; construction does no I/O.

    No method deletes or writes registered storage. ``remove_item`` only forgets
    its catalogue entry and timeline; ``delete_project`` only ungroups its items.
    """

    def __init__(self, path: str | Path | None = None):
        self.catalog_path = _absolute(path if path is not None else default_catalog_path())

    def _guard_catalog(self, *, missing_ok: bool = False) -> None:
        _guard_path(self.catalog_path, missing_ok=missing_ok, catalog=True)
        if self.catalog_path.exists():
            with self.catalog_path.open("rb") as handle:
                header = handle.read(100)
            if header.startswith(b"SQLite format 3\x00") and (header[18:20] != b"\x01\x01"):
                raise LibraryError("Unsupported Library journal format; this preview uses rollback-journal catalogues")
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(self.catalog_path) + suffix)
            _guard_path(sidecar, missing_ok=True, catalog=True)
            if suffix != "-journal" and sidecar.exists():
                raise LibraryError("Unexpected Library WAL/SHM sidecar; close other writers and recover a backup")

    @staticmethod
    def _validate_catalog(connection: sqlite3.Connection) -> None:
        if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise LibraryError("Existing file is not a Rat-Trap Library catalogue; it will not be overwritten")
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise LibraryError("Unsupported Library schema version; use the matching application")
        rows = connection.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 20").fetchall()
        actual = {row["name"]: row["sql"] for row in rows}
        if actual != _SCHEMA_SQL:
            raise LibraryError("Library catalogue schema is damaged or unsupported")
        marker = connection.execute("SELECT value FROM library_meta WHERE key='format'").fetchone()
        if marker is None or marker[0] != "RAT-TRAP-LIBRARY-1":
            raise LibraryError("Library catalogue identity is missing or damaged")

    def _initialize(self) -> None:
        with _INIT_LOCK:
            self._guard_catalog(missing_ok=True)
            if self.catalog_path.exists():
                return
            self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            self._guard_catalog(missing_ok=True)
            # Claim a new file exclusively; never adopt/truncate an existing DB.
            descriptor = os.open(self.catalog_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            connection = sqlite3.connect(str(self.catalog_path), timeout=5)
            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                connection.execute("INSERT INTO library_meta VALUES('format','RAT-TRAP-LIBRARY-1')")
                connection.commit()
            finally:
                connection.close()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection | None]:
        # A rollback journal can disappear between lstat and validation when
        # another local thread commits. Keep checks and the short transaction
        # together; do not weaken the hardlink/reparse-point safety policy.
        # Storage compression and source inspection remain outside this lock.
        with _INIT_LOCK:
            with self._locked_connection(write=write) as connection:
                yield connection

    @contextmanager
    def _locked_connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection | None]:
        connection = None
        try:
            self._guard_catalog(missing_ok=True)
            if not self.catalog_path.exists() and not write:
                yield None
                return
            if write:
                self._initialize()
            self._guard_catalog()
            connection = _readonly_sqlite(self.catalog_path)
            self._validate_catalog(connection)
            if write:
                connection.close()
                connection = sqlite3.connect(self.catalog_path.as_uri() + "?mode=rw", uri=True, timeout=5)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                self._validate_catalog(connection)
            yield connection
            if write:
                connection.commit()
        except sqlite3.Error as exc:
            raise LibraryError("Library catalogue could not be read or updated safely: " + str(exc)) from exc
        finally:
            if connection is not None:
                connection.close()  # Rolls back any unsuccessful transaction.

    @staticmethod
    def _project_exists(connection: sqlite3.Connection, project_id: str | None) -> None:
        if project_id is not None and connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            raise LibraryError("Project not found")

    @staticmethod
    def _item(row: sqlite3.Row) -> LibraryItem:
        values = dict(row)
        if (not isinstance(values["id"], str) or not _HEX32.fullmatch(values["id"]) or
                values["kind"] not in {"archive", "vault", "protected_archive", "sealed_file", "repository"} or
                values["status"] not in {"available", "missing", "changed", "error"} or
                type(values["protected"]) is not int or values["protected"] not in (0, 1) or
                type(values["size_bytes"]) is not int or values["size_bytes"] < 0 or
                not isinstance(values["path"], str) or not Path(values["path"]).is_absolute() or
                not isinstance(values["identity"], str) or
                not re.fullmatch(r"(?:sha256:[0-9a-f]{64}|repository:[0-9a-f]{32})", values["identity"])):
            raise LibraryError("Library item metadata is damaged or unsupported")
        _text(values["label"], "Stored item label", 300)
        _absolute(values["path"])
        _stored_time(values["added_at"])
        _stored_time(values["last_checked_at"])
        if (bool(values["protected"]) != (values["kind"] in {"protected_archive", "sealed_file"}) or
                values["identity"].startswith("repository:") != (values["kind"] == "repository")):
            raise LibraryError("Library format identity metadata is inconsistent")
        if values["project_id"] is not None and (not isinstance(values["project_id"], str) or not _HEX32.fullmatch(values["project_id"])):
            raise LibraryError("Library project reference is damaged")
        values["protected"] = bool(values["protected"])
        return LibraryItem(**values)

    def list_projects(self) -> list[Project]:
        with self._connection() as connection:
            if connection is None:
                return []
            projects = []
            for row in connection.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE,id"):
                if not isinstance(row["id"], str) or not _HEX32.fullmatch(row["id"]):
                    raise LibraryError("Library project identity is damaged")
                _text(row["name"], "Stored project name", 200)
                _text(row["description"], "Stored project description", 4000, empty=True)
                _stored_time(row["created_at"])
                projects.append(Project(**dict(row)))
            return projects

    def create_project(self, name: str, description: str = "") -> Project:
        project = Project(uuid.uuid4().hex, _text(name, "Project name", 200), _text(description, "Project description", 4000, empty=True), _now())
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO projects VALUES(?,?,?,?)", dataclasses.astuple(project))
        return project

    def rename_project(self, project_id: str, name: str, description: str = "") -> Project:
        name = _text(name, "Project name", 200)
        description = _text(description, "Project description", 4000, empty=True)
        with self._connection(write=True) as connection:
            self._project_exists(connection, project_id)
            connection.execute("UPDATE projects SET name=?,description=? WHERE id=?", (name, description, project_id))
            return Project(**dict(connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()))

    def delete_project(self, project_id: str) -> None:
        with self._connection(write=True) as connection:
            self._project_exists(connection, project_id)
            connection.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def list_items(self, project_id: str | None = None, query: str = "") -> list[LibraryItem]:
        query = _text(query, "Search", 500, empty=True).casefold()
        with self._connection() as connection:
            if connection is None:
                return []
            rows = connection.execute("SELECT * FROM items WHERE (? IS NULL OR project_id=?) ORDER BY added_at DESC,id", (project_id, project_id))
            return [self._item(row) for row in rows if not query or query in (row["label"] + "\n" + row["path"]).casefold()]

    def get_item(self, item_id: str) -> LibraryItem:
        with self._connection() as connection:
            row = None if connection is None else connection.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise LibraryError("Library item not found")
            return self._item(row)

    def inspect_item(self, item_id: str) -> StorageInspection:
        """Recheck identity and known snapshot checksums without any catalogue write.

        Use immediately before opening the existing archive/history workspace.
        A missing historical snapshot is not silently replaced by a newer one;
        callers must check that an explicitly requested snapshot is returned.
        """
        item = self.get_item(item_id)
        inspection = inspect_storage(item.path)
        if inspection.identity != item.identity or inspection.kind != item.kind:
            raise IdentityMismatchError("Stored files no longer match this Library item")
        current_hashes = {snapshot.snapshot_id: snapshot.manifest_sha256 for snapshot in inspection.snapshots}
        with self._connection() as connection:
            if connection is None:
                raise LibraryError("Library catalogue disappeared during inspection")
            current = connection.execute("SELECT path,identity FROM items WHERE id=?", (item_id,)).fetchone()
            if current is None or tuple(current) != (item.path, item.identity):
                raise LibraryError("Library item changed during inspection; try again")
            for row in connection.execute("SELECT snapshot_id,manifest_sha256 FROM events WHERE item_id=? AND kind='snapshot'", (item_id,)):
                if row["snapshot_id"] in current_hashes and current_hashes[row["snapshot_id"]] != row["manifest_sha256"]:
                    raise LibraryError("A known snapshot ID now has different contents; no replacement version was selected")
        return inspection

    @staticmethod
    def _add_snapshots(connection: sqlite3.Connection, item_id: str, snapshots: tuple[SnapshotRecord, ...]) -> None:
        for snapshot in snapshots:
            existing = connection.execute("SELECT manifest_sha256 FROM events WHERE item_id=? AND snapshot_id=?", (item_id, snapshot.snapshot_id)).fetchone()
            if existing is not None:
                if existing[0] != snapshot.manifest_sha256:
                    raise LibraryError("A known snapshot ID now has different contents; catalogue unchanged")
                continue
            detail = f"{snapshot.file_count:,} files; {snapshot.total_bytes:,} logical bytes. Manifest checked; stored file data not verified."
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (
                uuid.uuid4().hex, item_id, None, "snapshot", snapshot.occurred_at, "repository manifest", snapshot.label or "Saved snapshot", detail, snapshot.snapshot_id, snapshot.manifest_sha256))

    def register(self, path: str | Path, *, label: str | None = None, project_id: str | None = None) -> LibraryItem:
        return self._register(path, label=label, project_id=project_id)

    def record_saved(self, path: str | Path, *, project_id: str, identity: str,
                     snapshot_id: str | None = None) -> LibraryItem:
        """Atomically catalogue an already-published output; never create storage here.

        The workflow supplies the identity it actually saved. Existing projects
        are never silently reassigned. Snapshot events keep their exact IDs.
        """
        return self._register(path, project_id=project_id, saved_identity=identity,
                              saved_snapshot_id=snapshot_id)

    def _register(self, path, *, label=None, project_id=None, saved_identity=None,
                  saved_snapshot_id=None):
        path = _absolute(path)
        if path == self.catalog_path or path in self.catalog_path.parents:
            raise LibraryError("Keep the Library catalogue outside registered storage")
        label = _text(label if label is not None else path.name, "Item label", 300)
        inspection = inspect_storage(path)
        saved = saved_identity is not None
        if saved and inspection.identity != saved_identity:
            raise IdentityMismatchError("Saved output changed before it could be added to Library")
        if saved and inspection.kind == "repository":
            if saved_snapshot_id not in {entry.snapshot_id for entry in inspection.snapshots}:
                raise LibraryError("The saved snapshot is no longer present; Library was not updated")
        elif saved_snapshot_id is not None:
            raise LibraryError("Only a backup repository can have a snapshot ID")
        now = _now()
        item = LibraryItem(uuid.uuid4().hex, str(path), label, inspection.kind, inspection.identity, project_id, "available", inspection.size_bytes, inspection.protected, now, now)
        with self._connection(write=True) as connection:
            self._project_exists(connection, project_id)
            existing = connection.execute("SELECT * FROM items WHERE path=? COLLATE NOCASE", (str(path),)).fetchone()
            if existing is not None:
                if existing["identity"] != inspection.identity:
                    raise IdentityMismatchError("This path now contains different storage; relink the original or add a separate copy at another path")
                if saved:
                    if existing["project_id"] != project_id:
                        raise LibraryError("This storage belongs to a different Library project; use Assign explicitly")
                    self._add_snapshots(connection, existing["id"], inspection.snapshots)
                    connection.execute("UPDATE items SET status='available',last_checked_at=? WHERE id=?", (now, existing["id"]))
                    return self._item(connection.execute("SELECT * FROM items WHERE id=?", (existing["id"],)).fetchone())
                return self._item(existing)
            connection.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?)", dataclasses.astuple(item))
            title = "Archive saved to Library" if saved and inspection.kind != "repository" else "Added to Library"
            detail = ("Created by Store a folder, then registered after publication. Original source files were retained. "
                      "Registration checks identity, not a full restore test."
                      if saved else "Registered a reference; no files were copied or changed.")
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, item.id, None, "registered", now, "Library registration", title, detail, None, None))
            self._add_snapshots(connection, item.id, inspection.snapshots)
        return item

    def refresh(self, item_id: str) -> LibraryItem:
        item = self.get_item(item_id)
        inspection = None
        try:
            inspection = inspect_storage(item.path)
            status = "available" if inspection.identity == item.identity and inspection.kind == item.kind else "changed"
        except FileNotFoundError:
            status = "missing"
        except LibraryError:
            status = "error"
        with self._connection(write=True) as connection:
            current = connection.execute("SELECT path,identity FROM items WHERE id=?", (item_id,)).fetchone()
            if current is None or tuple(current) != (item.path, item.identity):
                raise LibraryError("Library item changed during refresh; try again")
            if status == "available":
                self._add_snapshots(connection, item_id, inspection.snapshots)
            connection.execute("UPDATE items SET status=?,last_checked_at=? WHERE id=?", (status, _now(), item_id))
        return self.get_item(item_id)

    def relink(self, item_id: str, new_path: str | Path) -> LibraryItem:
        item = self.get_item(item_id)
        path = _absolute(new_path)
        if path == self.catalog_path or path in self.catalog_path.parents:
            raise LibraryError("Keep the Library catalogue outside registered storage")
        inspection = inspect_storage(path)
        if inspection.identity != item.identity or inspection.kind != item.kind:
            raise IdentityMismatchError("Relink needs the same archive bytes or repository identity; add different storage as a separate Library item")
        with self._connection(write=True) as connection:
            current = connection.execute("SELECT path,identity FROM items WHERE id=?", (item_id,)).fetchone()
            if current is None or tuple(current) != (item.path, item.identity):
                raise LibraryError("Library item changed during relink; try again")
            if connection.execute("SELECT 1 FROM items WHERE path=? COLLATE NOCASE AND id<>?", (str(path), item_id)).fetchone():
                raise LibraryError("That location is already registered")
            self._add_snapshots(connection, item_id, inspection.snapshots)
            connection.execute("UPDATE items SET path=?,status='available',last_checked_at=? WHERE id=?", (str(path), _now(), item_id))
        return self.get_item(item_id)

    def assign_project(self, item_id: str, project_id: str | None) -> LibraryItem:
        with self._connection(write=True) as connection:
            self._project_exists(connection, project_id)
            if connection.execute("UPDATE items SET project_id=? WHERE id=?", (project_id, item_id)).rowcount != 1:
                raise LibraryError("Library item not found")
        return self.get_item(item_id)

    def remove_item(self, item_id: str) -> None:
        with self._connection(write=True) as connection:
            if connection.execute("DELETE FROM items WHERE id=?", (item_id,)).rowcount != 1:
                raise LibraryError("Library item not found")

    def record_health(self, item: LibraryItem, detail: str) -> None:
        """Save a dated historical health receipt, without changing availability.

        Uses a schema-v1 note so existing catalogues need no migration. The
        health module validates its bounded JSON; this transaction pins context.
        """
        detail = _text(detail, "Health receipt", 8000)
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT * FROM items WHERE id=?", (item.id,)).fetchone()
            if row is None or any(row[key] != getattr(item, key) for key in ("path", "identity", "kind", "project_id")):
                raise LibraryError("Library item changed; health receipt was not saved")
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (
                uuid.uuid4().hex, item.id, None, "note", _now(), "Library note time",
                "Library health check", detail, None, None))

    def latest_health_receipts(self) -> dict[str, str]:
        """Read only catalogue notes; never inspect referenced storage at startup."""
        with self._connection() as connection:
            if connection is None:
                return {}
            rows = connection.execute("""SELECT item_id,detail FROM events WHERE rowid IN (
                SELECT MAX(rowid) FROM events WHERE kind='note' AND title='Library health check'
                AND item_id IS NOT NULL GROUP BY item_id)""")
            return {row["item_id"]: _text(row["detail"], "Health receipt", 8000) for row in rows}

    def record_restored(self, item_id: str, *, identity: str, project_id: str | None,
                        member: str, destination: str, sha256: str,
                        snapshot_id: str | None = None) -> TimelineEvent:
        """Record an already-published restore as a v1-compatible receipt note.

        The exact version is in the receipt text, not the unique snapshot-event
        column: repeated restores must not collide with the saved snapshot.
        No source or destination files are written by this operation.
        """
        if not isinstance(sha256, str) or not _HEX64.fullmatch(sha256):
            raise LibraryError("Restored file checksum is invalid")
        if snapshot_id is not None and (not isinstance(snapshot_id, str) or not _HEX32.fullmatch(snapshot_id)):
            raise LibraryError("Restored snapshot ID is invalid")
        member = _text(member, "Restored filename", 4096)
        destination = _text(destination, "Restore destination", 4096)
        detail = _text(f"File: {member}\nRestored to: {destination}\n"
                       f"Source version: {snapshot_id or 'Vault archive'}\n"
                       f"Verified SHA-256: {sha256}\nExisting files were not overwritten.", "Restore receipt", 8000)
        event = TimelineEvent(uuid.uuid4().hex, item_id, None, "note", _now(),
                              "Library note time", "File restored", detail, None)
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT identity,project_id FROM items WHERE id=?", (item_id,)).fetchone()
            if row is None or row["identity"] != identity or row["project_id"] != project_id:
                raise LibraryError("The Library item/project changed after restore; the restored file is safe")
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (*dataclasses.astuple(event), None))
        return event

    def add_note(self, text: str, *, project_id: str | None = None, item_id: str | None = None, event_date: str | None = None) -> TimelineEvent:
        text = _text(text, "Note", 8000)
        if project_id is None and item_id is None:
            raise LibraryError("Choose a project or Library item for this note")
        occurred_at, date_source = _now(), "Library note time"
        if event_date is not None:
            if not isinstance(event_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
                raise LibraryError("Note date must be YYYY-MM-DD")
            try:
                occurred_at = date.fromisoformat(event_date).isoformat()
            except ValueError as exc:
                raise LibraryError("Note date is not a real calendar date") from exc
            date_source = "user-entered date"
        event = TimelineEvent(uuid.uuid4().hex, item_id, project_id, "note", occurred_at, date_source, "Project note", text, None)
        with self._connection(write=True) as connection:
            self._project_exists(connection, project_id)
            if item_id is not None:
                item = connection.execute("SELECT project_id FROM items WHERE id=?", (item_id,)).fetchone()
                if item is None:
                    raise LibraryError("Library item not found")
                if project_id is not None and item[0] != project_id:
                    raise LibraryError("This item does not belong to the selected project")
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", (*dataclasses.astuple(event), None))
        return event

    def timeline(self, *, project_id: str | None = None, item_id: str | None = None,
                 item_ids: list[str] | None = None, limit: int = 500, query: str = "") -> list[TimelineEvent]:
        query = _text(query, "Search", 300, empty=True).casefold()
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise LibraryError("Timeline limit must be between 1 and 5000")
        item_filter = ""
        item_parameters: list[str] = []
        if item_ids is not None:
            if not isinstance(item_ids, list) or len(item_ids) > 10000 or any(
                    not isinstance(value, str) or not _HEX32.fullmatch(value) for value in item_ids):
                raise LibraryError("Timeline item filter must contain at most 10000 valid item IDs")
            if not item_ids:
                return []
            item_parameters = list(dict.fromkeys(item_ids))
            item_filter = " AND e.item_id IN (" + ",".join("?" for _ in item_parameters) + ")"
        with self._connection() as connection:
            if connection is None:
                return []
            connection.create_function("library_casefold", 1, lambda value: str(value).casefold())
            rows = connection.execute("""SELECT e.id,e.item_id,COALESCE(e.project_id,i.project_id) AS project_id,
                e.kind,e.occurred_at,e.date_source,e.title,e.detail,e.snapshot_id
                FROM events e LEFT JOIN items i ON e.item_id=i.id
                WHERE (? IS NULL OR COALESCE(e.project_id,i.project_id)=?)
                  AND (? IS NULL OR e.item_id=?)
                  AND instr(library_casefold(e.title || ' ' || e.detail), ?) > 0""" + item_filter + " ORDER BY e.occurred_at DESC,e.id LIMIT ?",
                (project_id, project_id, item_id, item_id, query, *item_parameters, limit))
            events = []
            for row in rows:
                if (not isinstance(row["id"], str) or not _HEX32.fullmatch(row["id"]) or
                        row["kind"] not in {"note", "snapshot", "registered"} or
                        row["date_source"] not in {"Library note time", "user-entered date", "repository manifest", "Library registration"}):
                    raise LibraryError("Library event metadata is damaged")
                for key in ("item_id", "project_id", "snapshot_id"):
                    if row[key] is not None and (not isinstance(row[key], str) or not _HEX32.fullmatch(row[key])):
                        raise LibraryError("Library event reference is damaged")
                _stored_time(row["occurred_at"], date_ok=row["kind"] == "note")
                _text(row["title"], "Stored event title", 1000)
                _text(row["detail"], "Stored event detail", 8000, empty=True)
                events.append(TimelineEvent(**dict(row)))
            return events


__all__ = ["LibraryError", "IdentityMismatchError", "LibraryStore", "Project", "LibraryItem",
           "TimelineEvent", "SnapshotRecord", "StorageInspection", "default_catalog_path", "inspect_storage"]
