"""Queryable SQLite Vault engine for Rat-Trap.

Vaults trade some archive compactness for indexed discovery and selective
extraction. File payloads are split into content-addressed Zstandard objects;
text-like files are additionally indexed with SQLite FTS5.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import sqlite3
import stat
import tempfile
import time
import zipfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Iterable, Iterator, Optional, Sequence

import zstandard as zstd

try:
    from . import structured_data
except ImportError:  # Allows direct execution while developing.
    import structured_data  # type: ignore


FORMAT = "GMW-VAULT-1"
SCHEMA_VERSION = 2
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
DEFAULT_INDEX_LIMIT = 16 * 1024 * 1024
MAX_CHUNK_SIZE = 64 * 1024 * 1024
_BUFFER_SIZE = 1024 * 1024
_SQLITE_MAGIC = b"SQLite format 3\x00"
_BASE_SCHEMA = {
    "vault_metadata": frozenset({"key", "value"}),
    "directories": frozenset({"path", "mtime", "mode"}),
    "objects": frozenset(
        {"id", "raw_size", "compressed_size", "compressor", "data"}
    ),
    "files": frozenset(
        {
            "id",
            "path",
            "size",
            "mtime",
            "mode",
            "sha256",
            "media_type",
            "indexed",
            "chunk_count",
        }
    ),
    "file_chunks": frozenset({"file_id", "ordinal", "object_id", "raw_size"}),
    "file_search": frozenset({"path", "content"}),
}
_SCHEMA_2_TABLES = {
    "structured_sources": frozenset(
        {
            "id",
            "file_id",
            "path",
            "name",
            "table_name",
            "data_format",
            "row_count",
            "column_count",
        }
    ),
    "structured_columns": frozenset(
        {
            "source_id",
            "ordinal",
            "source_name",
            "column_name",
            "declared_type",
        }
    ),
}

TEXT_EXTENSIONS = {
    ".bat",
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".h",
    ".hpp",
    ".htm",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass
class VaultMetadata:
    format: str
    schema_version: int
    compressor: str
    compression_level: int
    chunk_size: int
    created_at: float
    elapsed_seconds: float
    file_count: int
    directory_count: int
    total_bytes: int
    object_count: int
    compressed_object_bytes: int
    indexed_file_count: int
    duplicate_file_count: int
    deduplicated_bytes: int
    profile: str = "vault"
    structured_source_count: int = 0
    structured_row_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class VaultFile:
    id: int
    path: str
    size: int
    mtime: float
    mode: int
    sha256: str
    media_type: str
    indexed: bool
    chunk_count: int


def _normalise_member_path(stored_path: str) -> Path:
    if not stored_path or "\0" in stored_path:
        raise ValueError("Vault contains an invalid empty path")
    windows_path = PureWindowsPath(stored_path)
    portable = PurePosixPath(stored_path.replace("\\", "/"))
    if windows_path.drive or windows_path.is_absolute() or portable.is_absolute():
        raise ValueError(f"Vault contains an absolute path: {stored_path!r}")
    if not portable.parts or any(part in {"", ".", ".."} for part in portable.parts):
        raise ValueError(f"Vault contains an unsafe path: {stored_path!r}")
    return Path(*portable.parts)


def _safe_destination(root: Path, stored_path: str) -> Path:
    resolved_root = root.resolve()
    destination = (resolved_root / _normalise_member_path(stored_path)).resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Vault path escapes the destination: {stored_path!r}") from exc
    return destination


def _iter_entries(folder: Path) -> Iterator[Path]:
    for current, directory_names, file_names in os.walk(folder, followlinks=False):
        directory_names.sort()
        file_names.sort()
        current_path = Path(current)
        for name in directory_names:
            yield current_path / name
        for name in file_names:
            yield current_path / name


def _validate_create_paths(folder: Path, output: Path) -> tuple[Path, Path]:
    if not folder.is_dir():
        raise ValueError(f"Input folder '{folder}' not found")
    folder = folder.resolve()
    output = output.resolve()
    try:
        output.relative_to(folder)
    except ValueError:
        pass
    else:
        raise ValueError("The Vault must be saved outside the source folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_dir():
        raise ValueError(f"Output path '{output}' is a folder")
    return folder, output


def _configure_build_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA foreign_keys = ON")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE vault_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE directories (
            path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            mode INTEGER NOT NULL
        );

        CREATE TABLE objects (
            id TEXT PRIMARY KEY,
            raw_size INTEGER NOT NULL CHECK(raw_size >= 0),
            compressed_size INTEGER NOT NULL CHECK(compressed_size >= 0),
            compressor TEXT NOT NULL,
            data BLOB NOT NULL
        );

        CREATE TABLE files (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            size INTEGER NOT NULL CHECK(size >= 0),
            mtime REAL NOT NULL,
            mode INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            media_type TEXT NOT NULL,
            indexed INTEGER NOT NULL CHECK(indexed IN (0, 1)),
            chunk_count INTEGER NOT NULL CHECK(chunk_count >= 0)
        );

        CREATE TABLE file_chunks (
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            object_id TEXT NOT NULL REFERENCES objects(id),
            raw_size INTEGER NOT NULL CHECK(raw_size >= 0),
            PRIMARY KEY(file_id, ordinal)
        );

        CREATE INDEX file_chunks_object_id ON file_chunks(object_id);
        CREATE INDEX files_media_type ON files(media_type);
        """
    )
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE file_search USING fts5("
            "path, content, content='', tokenize='unicode61 remove_diacritics 2')"
        )
    except sqlite3.OperationalError as exc:
        raise RuntimeError("This SQLite build does not include FTS5 search support") from exc
    structured_data.create_schema(connection)


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _is_indexable(path: Path, size: int, media_type: str, limit: int) -> bool:
    # Extensions and MIME guesses are useful labels, but real datasets often
    # store plain text in extensionless files or names such as `adult.data`.
    # Content validation below rejects binary candidates before indexing.
    return size <= limit


def _decode_index_text(data: bytes) -> Optional[str]:
    if b"\0" in data:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if not text:
        return ""
    control_count = sum(ord(character) < 32 and character not in "\n\r\t" for character in text)
    if control_count / len(text) > 0.01:
        return None
    return text


def create_vault(
    folder: Path,
    output: Path,
    *,
    level: int = 6,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    index_limit: int = DEFAULT_INDEX_LIMIT,
    profile: str = "vault",
) -> VaultMetadata:
    folder, output = _validate_create_paths(Path(folder), Path(output))
    if not -7 <= level <= 22:
        raise ValueError("Zstandard level must be between -7 and 22")
    if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise ValueError("Vault chunk size must be between 1 byte and 64 MiB")
    if index_limit < 0:
        raise ValueError("Vault text index limit cannot be negative")

    started = time.time()
    with tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".rat-trap-vault-build", dir=output.parent, delete=False
    ) as staging_file:
        staging_path = Path(staging_file.name)

    compressor = zstd.ZstdCompressor(level=level)
    file_count = 0
    directory_count = 0
    total_bytes = 0
    object_count = 0
    compressed_object_bytes = 0
    indexed_file_count = 0
    duplicate_file_count = 0
    deduplicated_bytes = 0
    structured_source_count = 0
    structured_row_count = 0
    seen_file_hashes: set[str] = set()

    try:
        with closing(sqlite3.connect(staging_path)) as connection:
            _configure_build_connection(connection)
            _create_schema(connection)

            for path in _iter_entries(folder):
                if path.is_symlink():
                    raise ValueError(f"Symbolic links are not supported: {path}")
                relative = path.relative_to(folder).as_posix()
                file_stat = path.stat()
                if path.is_dir():
                    connection.execute(
                        "INSERT INTO directories(path, mtime, mode) VALUES (?, ?, ?)",
                        (relative, file_stat.st_mtime, stat.S_IMODE(file_stat.st_mode)),
                    )
                    directory_count += 1
                    continue
                if not path.is_file():
                    raise ValueError(f"Unsupported filesystem entry: {path}")

                media_type = _media_type(path)
                collect_text = _is_indexable(path, file_stat.st_size, media_type, index_limit)
                text_parts: list[bytes] = []
                chunks: list[tuple[int, str, int]] = []
                file_digest = hashlib.sha256()

                with open(path, "rb") as source:
                    ordinal = 0
                    while True:
                        block = source.read(chunk_size)
                        if not block:
                            break
                        file_digest.update(block)
                        if collect_text:
                            text_parts.append(block)
                        object_id = hashlib.sha256(block).hexdigest()
                        exists = connection.execute(
                            "SELECT 1 FROM objects WHERE id = ?", (object_id,)
                        ).fetchone()
                        if exists is None:
                            compressed = compressor.compress(block)
                            connection.execute(
                                "INSERT INTO objects(id, raw_size, compressed_size, compressor, data) "
                                "VALUES (?, ?, ?, 'zstd', ?)",
                                (object_id, len(block), len(compressed), sqlite3.Binary(compressed)),
                            )
                            object_count += 1
                            compressed_object_bytes += len(compressed)
                        else:
                            deduplicated_bytes += len(block)
                        chunks.append((ordinal, object_id, len(block)))
                        ordinal += 1

                sha256 = file_digest.hexdigest()
                if sha256 in seen_file_hashes:
                    duplicate_file_count += 1
                else:
                    seen_file_hashes.add(sha256)

                indexed_text = _decode_index_text(b"".join(text_parts)) if collect_text else None
                indexed = indexed_text is not None
                cursor = connection.execute(
                    "INSERT INTO files(path, size, mtime, mode, sha256, media_type, indexed, chunk_count) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        relative,
                        file_stat.st_size,
                        file_stat.st_mtime,
                        stat.S_IMODE(file_stat.st_mode),
                        sha256,
                        media_type,
                        int(indexed),
                        len(chunks),
                    ),
                )
                file_id = int(cursor.lastrowid)
                connection.executemany(
                    "INSERT INTO file_chunks(file_id, ordinal, object_id, raw_size) "
                    "VALUES (?, ?, ?, ?)",
                    ((file_id, ordinal, object_id, raw_size) for ordinal, object_id, raw_size in chunks),
                )
                connection.execute(
                    "INSERT INTO file_search(rowid, path, content) VALUES (?, ?, ?)",
                    (file_id, relative, indexed_text or ""),
                )
                structured_source = structured_data.ingest_file(
                    connection, file_id, relative, path
                )
                if structured_source is not None:
                    structured_source_count += 1
                    structured_row_count += structured_source.row_count
                if indexed:
                    indexed_file_count += 1
                file_count += 1
                total_bytes += file_stat.st_size

            metadata = VaultMetadata(
                format=FORMAT,
                schema_version=SCHEMA_VERSION,
                compressor="zstd",
                compression_level=level,
                chunk_size=chunk_size,
                created_at=started,
                elapsed_seconds=time.time() - started,
                file_count=file_count,
                directory_count=directory_count,
                total_bytes=total_bytes,
                object_count=object_count,
                compressed_object_bytes=compressed_object_bytes,
                indexed_file_count=indexed_file_count,
                duplicate_file_count=duplicate_file_count,
                deduplicated_bytes=deduplicated_bytes,
                profile=profile,
                structured_source_count=structured_source_count,
                structured_row_count=structured_row_count,
            )
            for key, value in metadata.as_dict().items():
                connection.execute(
                    "INSERT INTO vault_metadata(key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            connection.commit()
            connection.execute("PRAGMA optimize")
            connection.execute("VACUUM")
            metadata.elapsed_seconds = time.time() - started
            connection.execute(
                "UPDATE vault_metadata SET value = ? WHERE key = 'elapsed_seconds'",
                (json.dumps(metadata.elapsed_seconds),),
            )
            connection.commit()

        with open(staging_path, "r+b") as finished:
            os.fsync(finished.fileno())
        os.replace(staging_path, output)
        return metadata
    finally:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass


def _open_readonly(path: Path) -> sqlite3.Connection:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"Vault '{path}' not found")
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _load_metadata(connection: sqlite3.Connection) -> VaultMetadata:
    try:
        values = {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("SELECT key, value FROM vault_metadata")
        }
        metadata = VaultMetadata(**values)
    except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("File is not a valid Rat-Trap Vault") from exc
    if metadata.format != FORMAT:
        raise ValueError(f"Unsupported Vault format '{metadata.format}'")
    if (
        isinstance(metadata.schema_version, int)
        and not isinstance(metadata.schema_version, bool)
        and not 1 <= metadata.schema_version <= SCHEMA_VERSION
    ):
        raise ValueError(
            f"Unsupported Vault format '{metadata.format}' "
            f"schema {metadata.schema_version}"
        )
    integer_fields = (
        metadata.schema_version,
        metadata.compression_level,
        metadata.chunk_size,
        metadata.file_count,
        metadata.directory_count,
        metadata.total_bytes,
        metadata.object_count,
        metadata.compressed_object_bytes,
        metadata.indexed_file_count,
        metadata.duplicate_file_count,
        metadata.deduplicated_bytes,
        metadata.structured_source_count,
        metadata.structured_row_count,
    )
    numeric_totals = (
        metadata.file_count,
        metadata.directory_count,
        metadata.total_bytes,
        metadata.object_count,
        metadata.compressed_object_bytes,
        metadata.indexed_file_count,
        metadata.duplicate_file_count,
        metadata.deduplicated_bytes,
        metadata.structured_source_count,
        metadata.structured_row_count,
    )
    if (
        not isinstance(metadata.schema_version, int)
        or isinstance(metadata.schema_version, bool)
        or metadata.schema_version < 1
        or metadata.schema_version > SCHEMA_VERSION
        or any(not isinstance(value, int) or isinstance(value, bool) for value in integer_fields)
        or not isinstance(metadata.created_at, (int, float))
        or isinstance(metadata.created_at, bool)
        or not math.isfinite(metadata.created_at)
        or metadata.created_at < 0
        or not isinstance(metadata.elapsed_seconds, (int, float))
        or isinstance(metadata.elapsed_seconds, bool)
        or not math.isfinite(metadata.elapsed_seconds)
        or metadata.elapsed_seconds < 0
        or not isinstance(metadata.profile, str)
        or not metadata.profile
        or metadata.compressor != "zstd"
        or not -7 <= metadata.compression_level <= 22
        or not 1 <= metadata.chunk_size <= MAX_CHUNK_SIZE
        or any(value < 0 for value in numeric_totals)
        or metadata.indexed_file_count > metadata.file_count
        or metadata.duplicate_file_count > metadata.file_count
        or metadata.structured_source_count > metadata.file_count
        or (
            metadata.schema_version >= 2
            and not {
                "structured_source_count",
                "structured_row_count",
            }.issubset(values)
        )
        or (
            metadata.schema_version == 1
            and (
                metadata.structured_source_count != 0
                or metadata.structured_row_count != 0
            )
        )
    ):
        raise ValueError("Vault contains invalid format metadata")
    _validate_schema(connection, metadata.schema_version)
    return metadata


def _validate_schema(
    connection: sqlite3.Connection, schema_version: int
) -> None:
    tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if {"metadata", "chunks"}.issubset(tables):
        raise ValueError("SQLite database contains ambiguous Rat-Trap families")
    required_schema = dict(_BASE_SCHEMA)
    if schema_version >= 2:
        required_schema.update(_SCHEMA_2_TABLES)
    for table, required_columns in required_schema.items():
        if table not in tables:
            raise ValueError(f"Vault is missing required table '{table}'")
        actual_columns = {
            str(row["name"])
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        if not required_columns.issubset(actual_columns):
            raise ValueError(f"Vault table '{table}' has an unsupported schema")
    fts_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'file_search'"
    ).fetchone()
    if (
        fts_sql_row is None
        or not isinstance(fts_sql_row["sql"], str)
        or "using fts5" not in fts_sql_row["sql"].lower()
    ):
        raise ValueError("Vault search table is not an FTS5 index")


def is_vault_archive(path: Path) -> bool:
    path = Path(path)
    try:
        with open(path, "rb") as source:
            if source.read(len(_SQLITE_MAGIC)) != _SQLITE_MAGIC:
                return False
        with closing(_open_readonly(path)) as connection:
            return _load_metadata(connection).format == FORMAT
    except (OSError, sqlite3.DatabaseError, ValueError):
        return False


def read_metadata(path: Path) -> VaultMetadata:
    with closing(_open_readonly(Path(path))) as connection:
        return _load_metadata(connection)


def _row_to_file(row: sqlite3.Row) -> VaultFile:
    return VaultFile(
        id=int(row["id"]),
        path=str(row["path"]),
        size=int(row["size"]),
        mtime=float(row["mtime"]),
        mode=int(row["mode"]),
        sha256=str(row["sha256"]),
        media_type=str(row["media_type"]),
        indexed=bool(row["indexed"]),
        chunk_count=int(row["chunk_count"]),
    )


def _fts_expression(query: str) -> str:
    tokens = re.findall(r"[\w.-]+", query, flags=re.UNICODE)
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def search_vault(
    archive: Path,
    query: str = "",
    *,
    extension: str = "",
    limit: int = 200,
) -> list[VaultFile]:
    if not 1 <= limit <= 5000:
        raise ValueError("Search result limit must be between 1 and 5000")
    suffix = extension.strip().lower()
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    with closing(_open_readonly(Path(archive))) as connection:
        _load_metadata(connection)
        expression = _fts_expression(query)
        parameters: list[object] = []
        if expression:
            sql = (
                "SELECT f.* FROM file_search s JOIN files f ON f.id = s.rowid "
                "WHERE file_search MATCH ?"
            )
            parameters.append(expression)
        else:
            sql = "SELECT f.* FROM files f WHERE 1 = 1"
        if suffix:
            sql += " AND lower(f.path) LIKE ?"
            parameters.append(f"%{suffix}")
        sql += " ORDER BY lower(f.path) LIMIT ?"
        parameters.append(limit)
        return [_row_to_file(row) for row in connection.execute(sql, parameters)]


def list_structured_sources(archive: Path) -> list["structured_data.StructuredSource"]:
    with closing(_open_readonly(Path(archive))) as connection:
        _load_metadata(connection)
        return structured_data.list_sources(connection)


def list_structured_columns(
    archive: Path, source_id: int
) -> list["structured_data.StructuredColumn"]:
    with closing(_open_readonly(Path(archive))) as connection:
        _load_metadata(connection)
        return structured_data.list_columns(connection, source_id)


def query_structured_source(
    archive: Path,
    source_id: int,
    *,
    search: str = "",
    column: str = "",
    sort_by: str = "",
    descending: bool = False,
    limit: int = 1000,
    offset: int = 0,
) -> "structured_data.StructuredQueryResult":
    with closing(_open_readonly(Path(archive))) as connection:
        _load_metadata(connection)
        return structured_data.query_source(
            connection,
            source_id,
            search=search,
            column=column,
            sort_by=sort_by,
            descending=descending,
            limit=limit,
            offset=offset,
        )


def execute_structured_sql(
    archive: Path, sql: str, *, limit: int = 1000
) -> "structured_data.StructuredQueryResult":
    with closing(_open_readonly(Path(archive))) as connection:
        _load_metadata(connection)
        return structured_data.execute_sql(connection, sql, limit=limit)


def export_structured_result(
    result: "structured_data.StructuredQueryResult", output: Path
) -> None:
    structured_data.export_result(result, Path(output))


def _stream_file(
    connection: sqlite3.Connection,
    vault_file: VaultFile,
    destination: BinaryIO,
    *,
    max_chunk_size: int,
    collect_limit: int = 0,
) -> bytes:
    decompressor = zstd.ZstdDecompressor()
    file_digest = hashlib.sha256()
    written = 0
    collected = bytearray()
    rows = connection.execute(
        "SELECT fc.ordinal, fc.object_id, fc.raw_size, o.raw_size AS object_raw_size, "
        "o.compressed_size, o.compressor, o.data "
        "FROM file_chunks fc JOIN objects o ON o.id = fc.object_id "
        "WHERE fc.file_id = ? ORDER BY fc.ordinal",
        (vault_file.id,),
    )
    chunk_count = 0
    for row in rows:
        if int(row["ordinal"]) != chunk_count:
            raise ValueError(f"Vault file has invalid chunk ordering: {vault_file.path!r}")
        if row["compressor"] != "zstd":
            raise ValueError(f"Unsupported Vault object compressor '{row['compressor']}'")
        raw_size = int(row["raw_size"])
        if (
            raw_size != int(row["object_raw_size"])
            or raw_size <= 0
            or raw_size > max_chunk_size
            or written + raw_size > vault_file.size
        ):
            raise ValueError(f"Vault object has invalid size metadata for {vault_file.path!r}")
        compressed = bytes(row["data"])
        if len(compressed) != int(row["compressed_size"]):
            raise ValueError(f"Vault object is truncated for {vault_file.path!r}")
        block = decompressor.decompress(compressed, max_output_size=raw_size)
        if len(block) != raw_size:
            raise ValueError(f"Vault object has the wrong size for {vault_file.path!r}")
        if hashlib.sha256(block).hexdigest() != row["object_id"]:
            raise ValueError(f"Vault object checksum failed for {vault_file.path!r}")
        destination.write(block)
        file_digest.update(block)
        written += len(block)
        if collect_limit and len(collected) < collect_limit:
            collected.extend(block[: collect_limit - len(collected)])
        chunk_count += 1
    if (
        chunk_count != vault_file.chunk_count
        or written != vault_file.size
        or file_digest.hexdigest() != vault_file.sha256
    ):
        raise ValueError(f"Vault file checksum failed for {vault_file.path!r}")
    return bytes(collected)


class _NullWriter:
    def write(self, data: bytes) -> int:
        return len(data)


def read_file(archive: Path, stored_path: str, *, limit: int = 256 * 1024) -> tuple[bytes, bool]:
    if limit <= 0:
        raise ValueError("Preview limit must be greater than zero")
    portable_path = _normalise_member_path(stored_path).as_posix()
    with closing(_open_readonly(Path(archive))) as connection:
        metadata = _load_metadata(connection)
        row = connection.execute("SELECT * FROM files WHERE path = ?", (portable_path,)).fetchone()
        if row is None:
            raise ValueError(f"Vault file not found: {stored_path}")
        vault_file = _row_to_file(row)
        data = _stream_file(
            connection,
            vault_file,
            _NullWriter(),
            max_chunk_size=metadata.chunk_size,
            collect_limit=limit,
        )
        return data, vault_file.size > len(data)


def preview_text(archive: Path, stored_path: str, *, limit: int = 256 * 1024) -> str:
    data, truncated = read_file(archive, stored_path, limit=limit)
    text = _decode_index_text(data)
    if text is None:
        return "[Binary preview unavailable]"
    if truncated:
        text += "\n\n[Preview truncated]"
    return text


def extract_vault(
    archive: Path,
    output_dir: Path,
    *,
    paths: Optional[Sequence[str]] = None,
) -> VaultMetadata:
    archive = Path(archive).resolve()
    output_dir = Path(output_dir)
    selected = None if paths is None else {_normalise_member_path(path).as_posix() for path in paths}

    with closing(_open_readonly(archive)) as connection:
        metadata = _load_metadata(connection)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = output_dir.resolve()
        if selected is None:
            for row in connection.execute("SELECT path, mtime, mode FROM directories ORDER BY path"):
                destination = _safe_destination(output_dir, row["path"])
                destination.mkdir(parents=True, exist_ok=True)
                try:
                    os.utime(destination, (row["mtime"], row["mtime"]))
                    os.chmod(destination, row["mode"])
                except OSError:
                    pass
            rows: Iterable[sqlite3.Row] = connection.execute("SELECT * FROM files ORDER BY path")
        elif selected:
            placeholders = ",".join("?" for _ in selected)
            rows = connection.execute(
                f"SELECT * FROM files WHERE path IN ({placeholders}) ORDER BY path", tuple(selected)
            )
        else:
            rows = []

        extracted_paths: set[str] = set()
        extracted_bytes = 0
        extracted_files = 0
        for row in rows:
            vault_file = _row_to_file(row)
            destination = _safe_destination(output_dir, vault_file.path)
            if destination == archive:
                raise ValueError("Vault contents would overwrite the Vault itself")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_name: Optional[str] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{destination.name}.",
                    suffix=".rat-trap-vault-part",
                    dir=destination.parent,
                    delete=False,
                ) as target:
                    temporary_name = target.name
                    _stream_file(
                        connection,
                        vault_file,
                        target,
                        max_chunk_size=metadata.chunk_size,
                    )
                os.replace(temporary_name, destination)
                temporary_name = None
            finally:
                if temporary_name:
                    try:
                        os.unlink(temporary_name)
                    except FileNotFoundError:
                        pass
            try:
                os.utime(destination, (vault_file.mtime, vault_file.mtime))
                os.chmod(destination, vault_file.mode)
            except OSError:
                pass
            extracted_paths.add(vault_file.path)
            extracted_bytes += vault_file.size
            extracted_files += 1

        if selected is not None:
            missing = selected - extracted_paths
            if missing:
                raise ValueError(f"Vault files not found: {', '.join(sorted(missing))}")
        elif extracted_files != metadata.file_count or extracted_bytes != metadata.total_bytes:
            raise ValueError("Vault contents do not match the declared inventory")
        return metadata


def export_zip(archive: Path, output_zip: Path) -> VaultMetadata:
    archive = Path(archive).resolve()
    output_zip = Path(output_zip).resolve()
    if not archive.is_file():
        raise ValueError(f"Vault '{archive}' not found")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.is_dir():
        raise ValueError(f"Output path '{output_zip}' is a folder")
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_zip.name}.", suffix=".rat-trap-vault-zip", dir=output_zip.parent, delete=False
    ) as staging_file:
        staging_path = Path(staging_file.name)
    try:
        with closing(_open_readonly(archive)) as connection, zipfile.ZipFile(
            staging_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as output:
            metadata = _load_metadata(connection)
            for row in connection.execute("SELECT * FROM files ORDER BY path"):
                vault_file = _row_to_file(row)
                info = zipfile.ZipInfo(_normalise_member_path(vault_file.path).as_posix())
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (vault_file.mode & 0xFFFF) << 16
                date_time = time.localtime(vault_file.mtime)[:6]
                if date_time[0] >= 1980:
                    info.date_time = date_time
                with output.open(info, "w", force_zip64=True) as target:
                    _stream_file(
                        connection,
                        vault_file,
                        target,
                        max_chunk_size=metadata.chunk_size,
                    )
        os.replace(staging_path, output_zip)
        return metadata
    finally:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass


def verify_vault(archive: Path) -> VaultMetadata:
    with closing(_open_readonly(Path(archive))) as connection:
        metadata = _load_metadata(connection)
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"Vault database integrity check failed: {result}")
        file_count = 0
        total_bytes = 0
        for row in connection.execute("SELECT * FROM files ORDER BY id"):
            vault_file = _row_to_file(row)
            _stream_file(
                connection,
                vault_file,
                _NullWriter(),
                max_chunk_size=metadata.chunk_size,
            )
            file_count += 1
            total_bytes += vault_file.size
        if file_count != metadata.file_count or total_bytes != metadata.total_bytes:
            raise ValueError("Vault inventory does not match its metadata")
        structured_data.validate_catalog(
            connection,
            metadata.structured_source_count,
            metadata.structured_row_count,
        )
        return metadata
