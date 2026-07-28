"""GMW Tool v4: SQLite-backed content lake for LLM ingestion.

This generation converts the archive into a miniature content lake
backed by SQLite.  Every chunk is stored as a row so downstream systems
can fetch just the shards they need; metadata lives alongside the
payload, enabling zero-copy streaming or HTTP serving without first
materialising tarballs.

Why SQLite?
    * Embedding metadata queries (`SELECT * FROM files WHERE path LIKE`) directly
      into the container makes integration trivial.
    * Fine-grained chunk access lets retrieval pipelines pull samples in
      parallel or resume interrupted transfers without replaying the entire
      archive.
    * SQLite ships with Python which keeps the distribution self-contained.

In addition to ``compress`` / ``extract`` / ``info`` the tool exposes a
``serve`` command that spins up a very small HTTP API for remote chunk
streaming.  This makes benchmarking over the network straightforward and
is a stepping stone toward new data-transfer topologies for model
training clusters.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import http.server
import json
import os
import socketserver
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Iterator, List, Optional

try:
    from . import solid_engine, vault_engine
except ImportError:  # Allows direct execution while developing.
    import solid_engine  # type: ignore
    import vault_engine  # type: ignore

try:
    import zstandard as zstd

    HAS_ZSTD = True
except Exception:  # pragma: no cover - optional dependency
    zstd = None  # type: ignore
    HAS_ZSTD = False

import sys
import zlib
import zipfile

_CHUNK_SIZE = 512 * 1024
_DEFAULT_COMPRESSOR = "zstd" if HAS_ZSTD else "zlib"
_SQLITE_MAGIC = b"SQLite format 3\x00"
_LEGACY_SQLITE_FORMAT = "GMW-SQLITE-1"
_LEGACY_SQLITE_SCHEMA = {
    "metadata": frozenset({"key", "value"}),
    "chunks": frozenset({"id", "compressor", "raw_size", "data"}),
    "files": frozenset(
        {"path", "size", "mtime", "mode", "ordering", "chunk_ids", "chunk_sizes"}
    ),
}


@dataclass
class Metadata:
    format: str
    chunk_size: int
    compressor: str
    checksum: Optional[str]
    checksum_algorithm: str
    created_at: float
    elapsed_seconds: float
    file_count: int
    total_bytes: int
    compression_level: Optional[int] = None
    profile: str = "deduplicate"
    payload_bytes: Optional[int] = None
    directory_count: int = 0
    entry_order: str = "path"
    zstd_window_log: Optional[int] = None
    zstd_long_distance: bool = False
    whole_file_dedup: bool = False
    duplicate_file_count: int = 0
    schema_version: int = 0
    object_count: int = 0
    indexed_file_count: int = 0
    deduplicated_bytes: int = 0
    structured_source_count: int = 0
    structured_row_count: int = 0

    def as_dict(self) -> Dict[str, object]:
        return dataclasses.asdict(self)


def _iter_files(folder: Path) -> Iterator[Path]:
    for root, _, files in os.walk(folder):
        root_path = Path(root)
        for name in sorted(files):
            yield root_path / name


def _compress_block(data: bytes, compressor: str, level: int) -> bytes:
    if compressor == "zstd" and HAS_ZSTD:
        assert zstd is not None
        return zstd.ZstdCompressor(level=level).compress(data)
    if compressor == "zlib":
        return zlib.compress(data, 6)
    raise ValueError(f"Unsupported compressor '{compressor}'")


def _decompress_block(data: bytes, compressor: str, expected_size: int) -> bytes:
    """Decompress one chunk while enforcing the size recorded in the archive."""
    if expected_size < 0:
        raise ValueError("Archive contains a negative chunk size")
    if compressor == "zstd" and HAS_ZSTD:
        assert zstd is not None
        block = zstd.ZstdDecompressor().decompress(data, max_output_size=expected_size)
    elif compressor == "zstd":
        raise RuntimeError(
            "Archive requires Zstandard support. Install the 'zstandard' package "
            "or decompress on a system with it available."
        )
    elif compressor == "zlib":
        decompressor = zlib.decompressobj()
        block = decompressor.decompress(data, expected_size + 1)
        if decompressor.unconsumed_tail or len(block) > expected_size:
            raise ValueError("Compressed chunk expands beyond its recorded size")
        block += decompressor.flush()
    else:
        raise ValueError(f"Unsupported compressor '{compressor}'")

    if len(block) != expected_size:
        raise ValueError(
            f"Chunk size mismatch: expected {expected_size} bytes, got {len(block)}"
        )
    return block


def _archive_relative_path(stored_path: str) -> Path:
    """Return a portable relative path, rejecting traversal and drive paths."""
    if not stored_path or "\0" in stored_path:
        raise ValueError("Archive contains an invalid empty file path")

    windows_path = PureWindowsPath(stored_path)
    portable_path = PurePosixPath(stored_path.replace("\\", "/"))
    if windows_path.drive or windows_path.is_absolute() or portable_path.is_absolute():
        raise ValueError(f"Archive contains an absolute file path: {stored_path!r}")
    if not portable_path.parts or any(part in {"", ".", ".."} for part in portable_path.parts):
        raise ValueError(f"Archive contains an unsafe file path: {stored_path!r}")
    return Path(*portable_path.parts)


def _safe_destination(output_dir: Path, stored_path: str) -> Path:
    root = output_dir.resolve()
    destination = (root / _archive_relative_path(stored_path)).resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Archive path escapes the destination: {stored_path!r}") from exc
    return destination


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            compressor TEXT NOT NULL,
            raw_size INTEGER NOT NULL,
            data BLOB NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            size INTEGER,
            mtime REAL,
            mode INTEGER,
            ordering INTEGER,
            chunk_ids TEXT,
            chunk_sizes TEXT
        )
        """
    )


def _compress_chunked_folder(
    folder: Path,
    output: Path,
    *,
    chunk_size: int = _CHUNK_SIZE,
    compressor: str = _DEFAULT_COMPRESSOR,
    zstd_level: int = 3,
    checksum_algorithm: str = "sha256",
    metadata_keys: Optional[frozenset[str]] = None,
) -> Metadata:
    if not folder.is_dir():
        raise ValueError(f"Input folder '{folder}' not found")
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than zero")
    if compressor not in {"zstd", "zlib"}:
        raise ValueError(f"Unsupported compressor '{compressor}'")
    if compressor == "zstd" and not HAS_ZSTD:
        raise RuntimeError("Zstandard support is unavailable")
    if checksum_algorithm not in {"sha256", "none"}:
        raise ValueError(f"Unsupported checksum algorithm '{checksum_algorithm}'")
    folder = folder.resolve()
    output = output.resolve()
    try:
        output.relative_to(folder)
    except ValueError:
        pass
    else:
        raise ValueError("The output archive must be saved outside the source folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_dir():
        raise ValueError(f"Output path '{output}' is a folder")

    start = time.time()
    checksum = hashlib.sha256() if checksum_algorithm == "sha256" else None
    with tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".rat-trap-build", dir=output.parent, delete=False
    ) as staging_file:
        staging_path = Path(staging_file.name)
    try:
        with closing(sqlite3.connect(staging_path)) as conn:
            _ensure_db(conn)
            cache: Dict[str, None] = {}
            total_bytes = 0
            file_count = 0
            ordering = 0
            for path in _iter_files(folder):
                rel = path.relative_to(folder)
                st = path.stat()
                chunk_ids: List[str] = []
                chunk_sizes: List[int] = []
                with open(path, "rb") as fp:
                    while True:
                        block = fp.read(chunk_size)
                        if not block:
                            break
                        digest = hashlib.blake2b(block, digest_size=16).hexdigest()
                        if digest not in cache:
                            comp = _compress_block(block, compressor, zstd_level)
                            conn.execute(
                                "INSERT OR IGNORE INTO chunks(id, compressor, raw_size, data) VALUES (?, ?, ?, ?)",
                                (digest, compressor, len(block), sqlite3.Binary(comp)),
                            )
                            cache[digest] = None
                            if checksum is not None:
                                checksum.update(comp)
                        chunk_ids.append(digest)
                        chunk_sizes.append(len(block))
                conn.execute(
                    "INSERT INTO files(path, size, mtime, mode, ordering, chunk_ids, chunk_sizes) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(rel),
                        st.st_size,
                        st.st_mtime,
                        stat.S_IMODE(st.st_mode),
                        ordering,
                        json.dumps(chunk_ids),
                        json.dumps(chunk_sizes),
                    ),
                )
                ordering += 1
                total_bytes += st.st_size
                file_count += 1
            meta = Metadata(
                format="GMW-SQLITE-1",
                chunk_size=chunk_size,
                compressor=compressor,
                checksum=checksum.hexdigest() if checksum is not None else None,
                checksum_algorithm=checksum_algorithm,
                created_at=start,
                elapsed_seconds=time.time() - start,
                file_count=file_count,
                total_bytes=total_bytes,
                compression_level=zstd_level if compressor == "zstd" else 6,
                profile="deduplicate",
            )
            for key, value in meta.as_dict().items():
                if metadata_keys is not None and key not in metadata_keys:
                    continue
                conn.execute(
                    "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)),
                )
            conn.commit()
        os.replace(staging_path, output)
        return meta
    finally:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass


def _open_db(path: Path) -> sqlite3.Connection:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"Archive '{path}' not found")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_metadata(conn: sqlite3.Connection) -> Metadata:
    try:
        rows = {
            row["key"]: json.loads(row["value"])
            for row in conn.execute("SELECT key, value FROM metadata")
        }
        metadata = Metadata(**rows)  # type: ignore[arg-type]
    except (sqlite3.DatabaseError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("File is not a valid Rat-Trap legacy SQLite archive") from exc
    if metadata.format != _LEGACY_SQLITE_FORMAT:
        raise ValueError(f"Unsupported Rat-Trap SQLite format '{metadata.format}'")
    if (
        not isinstance(metadata.chunk_size, int)
        or metadata.chunk_size <= 0
        or metadata.compressor not in {"zstd", "zlib"}
        or metadata.checksum_algorithm not in {"sha256", "none"}
        or not isinstance(metadata.file_count, int)
        or not isinstance(metadata.total_bytes, int)
        or metadata.file_count < 0
        or metadata.total_bytes < 0
    ):
        raise ValueError("Legacy archive contains invalid format metadata")
    return metadata


def is_chunked_archive(path: Path) -> bool:
    """Return true only for a structurally valid GMW-SQLITE-1 archive."""
    path = Path(path)
    try:
        with open(path, "rb") as source:
            if source.read(len(_SQLITE_MAGIC)) != _SQLITE_MAGIC:
                return False
        with closing(_open_db(path)) as connection:
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            # A database must identify as exactly one archive family. This
            # prevents a corrupt or deliberately ambiguous Vault/legacy hybrid
            # from falling through to the less expressive legacy reader.
            if "vault_metadata" in tables:
                return False
            if not set(_LEGACY_SQLITE_SCHEMA).issubset(tables):
                return False
            for table, required_columns in _LEGACY_SQLITE_SCHEMA.items():
                actual_columns = {
                    str(row["name"])
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                }
                if not required_columns.issubset(actual_columns):
                    return False
            return _load_metadata(connection).format == _LEGACY_SQLITE_FORMAT
    except (OSError, sqlite3.DatabaseError, ValueError):
        return False


def _unsupported_archive(path: Path) -> ValueError:
    if not Path(path).is_file():
        return ValueError(f"Archive '{Path(path)}' not found")
    return ValueError(
        f"'{Path(path)}' is not a supported Rat-Trap archive "
        f"({_LEGACY_SQLITE_FORMAT}, GMW-SOLID-2, or GMW-VAULT-1)"
    )


def _validate_chunked_inventory(
    connection: sqlite3.Connection, metadata: Metadata
) -> None:
    file_count = 0
    total_bytes = 0
    for row in connection.execute("SELECT size FROM files"):
        size = row["size"]
        if not isinstance(size, int) or size < 0:
            raise ValueError("Legacy archive contains invalid file size metadata")
        file_count += 1
        total_bytes += size
    if (
        file_count != metadata.file_count
        or total_bytes != metadata.total_bytes
    ):
        raise ValueError(
            "Legacy archive file inventory does not match its metadata"
        )


def _chunked_file_layout(row: sqlite3.Row) -> tuple[List[str], List[int]]:
    try:
        chunk_ids = json.loads(row["chunk_ids"])
        chunk_sizes = json.loads(row["chunk_sizes"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            f"Archive has invalid chunk metadata for {row['path']!r}"
        ) from exc
    if not isinstance(chunk_ids, list) or not isinstance(chunk_sizes, list):
        raise ValueError(
            f"Archive has invalid chunk metadata for {row['path']!r}"
        )
    if len(chunk_ids) != len(chunk_sizes):
        raise ValueError(
            f"Archive has inconsistent chunk metadata for {row['path']!r}"
        )
    if (
        not isinstance(row["size"], int)
        or row["size"] < 0
        or any(not isinstance(size, int) or size < 0 for size in chunk_sizes)
        or sum(chunk_sizes) != row["size"]
        or any(not isinstance(chunk_id, str) for chunk_id in chunk_ids)
    ):
        raise ValueError(f"Archive has invalid file size metadata for {row['path']!r}")
    return chunk_ids, chunk_sizes


def _read_chunked_block(
    connection: sqlite3.Connection,
    chunk_id: str,
    stored_size: int,
    stored_path: str,
) -> bytes:
    chunk_row = connection.execute(
        "SELECT compressor, raw_size, data FROM chunks WHERE id = ?",
        (chunk_id,),
    ).fetchone()
    if chunk_row is None:
        raise ValueError(f"Missing chunk '{chunk_id}' in archive")
    raw_size = chunk_row["raw_size"]
    if (
        not isinstance(raw_size, int)
        or raw_size < 0
        or stored_size > raw_size
    ):
        raise ValueError(f"Invalid chunk length for {stored_path!r}")
    block = _decompress_block(
        chunk_row["data"], chunk_row["compressor"], raw_size
    )
    actual_id = hashlib.blake2b(block, digest_size=16).hexdigest()
    if actual_id != chunk_id:
        raise ValueError(f"Chunk '{chunk_id}' failed its content digest check")
    return block[:stored_size]


def _extract_chunked_archive(archive: Path, output_dir: Path) -> Metadata:
    archive = archive.resolve()
    if not archive.is_file():
        raise ValueError(f"Archive '{archive}' not found")
    with closing(_open_db(archive)) as conn:
        meta = _load_metadata(conn)
        _validate_chunked_inventory(conn, meta)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = output_dir.resolve()
        cur = conn.execute("SELECT * FROM files ORDER BY ordering")
        for row in cur:
            dest = _safe_destination(output_dir, row["path"])
            if dest == archive:
                raise ValueError("Archive contents would overwrite the archive itself")
            dest.parent.mkdir(parents=True, exist_ok=True)
            chunk_ids, chunk_sizes = _chunked_file_layout(row)
            temporary_name: Optional[str] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", prefix=f".{dest.name}.", suffix=".rat-trap-part",
                    dir=dest.parent, delete=False,
                ) as out_fp:
                    temporary_name = out_fp.name
                    for chunk_id, size in zip(chunk_ids, chunk_sizes):
                        out_fp.write(
                            _read_chunked_block(
                                conn, chunk_id, size, row["path"]
                            )
                        )
                os.replace(temporary_name, dest)
                temporary_name = None
            finally:
                if temporary_name:
                    try:
                        os.unlink(temporary_name)
                    except FileNotFoundError:
                        pass
            try:
                os.utime(dest, (row["mtime"], row["mtime"]))
                os.chmod(dest, row["mode"])
            except OSError:
                pass
    return meta




def _export_chunked_zip(archive: Path, output_zip: Path) -> Metadata:
    archive = archive.resolve()
    if not archive.is_file():
        raise ValueError(f"Archive '{archive}' not found")
    output_zip = output_zip.resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.is_dir():
        raise ValueError(f"Output path '{output_zip}' is a folder")
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_zip.name}.", suffix=".rat-trap-build", dir=output_zip.parent, delete=False
    ) as staging_file:
        staging_path = Path(staging_file.name)
    try:
        with closing(_open_db(archive)) as conn:
            meta = _load_metadata(conn)
            _validate_chunked_inventory(conn, meta)
            with zipfile.ZipFile(staging_path, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:
                cur = conn.execute("SELECT * FROM files ORDER BY ordering")
                for row in cur:
                    chunk_ids, chunk_sizes = _chunked_file_layout(row)
                    zip_name = _archive_relative_path(row["path"]).as_posix()
                    zi = zipfile.ZipInfo(zip_name)
                    zi.external_attr = (int(row["mode"]) & 0xFFFF) << 16
                    date_time = time.localtime(float(row["mtime"]))[:6]
                    if date_time[0] >= 1980:
                        zi.date_time = date_time
                    with out_zip.open(zi, "w", force_zip64=True) as out_fp:
                        for chunk_id, size in zip(chunk_ids, chunk_sizes):
                            out_fp.write(
                                _read_chunked_block(
                                    conn, chunk_id, size, row["path"]
                                )
                            )
        os.replace(staging_path, output_zip)
        return meta
    finally:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass

def _read_chunked_metadata(archive: Path) -> Metadata:
    with closing(_open_db(archive)) as conn:
        return _load_metadata(conn)


COMPRESSION_PROFILES: Dict[str, Dict[str, object]] = {
    "fast": {
        "archive_mode": "solid",
        "compressor": "zstd",
        "level": 3,
        "threads": 0,
        "whole_file_dedup": False,
    },
    "balanced": {
        "archive_mode": "solid",
        "compressor": "zstd",
        "level": 6,
        "threads": 0,
        "whole_file_dedup": True,
    },
    "smallest": {
        "archive_mode": "solid",
        "compressor": "zstd",
        "level": 19,
        "threads": 0,
        "whole_file_dedup": True,
    },
    "deduplicate": {
        "archive_mode": "chunked",
        "compressor": "zstd",
        "level": 6,
        "threads": 0,
        "whole_file_dedup": False,
    },
    "legacy-blocks": {
        "archive_mode": "chunked",
        "compressor": "zstd",
        "level": 6,
        "threads": 0,
        "whole_file_dedup": False,
    },
    "vault": {
        "archive_mode": "vault",
        "compressor": "zstd",
        "level": 6,
        "threads": 0,
        "whole_file_dedup": False,
        "chunk_size": vault_engine.DEFAULT_CHUNK_SIZE,
    },
}


def _solid_metadata(metadata: "solid_engine.SolidMetadata") -> Metadata:
    return Metadata(
        format=metadata.format,
        chunk_size=0,
        compressor=metadata.compressor,
        checksum=metadata.checksum,
        checksum_algorithm=metadata.checksum_algorithm,
        created_at=metadata.created_at,
        elapsed_seconds=metadata.elapsed_seconds,
        file_count=metadata.file_count,
        total_bytes=metadata.total_bytes,
        compression_level=metadata.compression_level,
        profile=metadata.profile,
        payload_bytes=metadata.payload_bytes,
        directory_count=metadata.directory_count,
        entry_order=metadata.entry_order,
        zstd_window_log=metadata.zstd_window_log,
        zstd_long_distance=metadata.zstd_long_distance,
        whole_file_dedup=metadata.whole_file_dedup,
        duplicate_file_count=metadata.duplicate_file_count,
    )


def _vault_metadata(metadata: "vault_engine.VaultMetadata") -> Metadata:
    return Metadata(
        format=metadata.format,
        chunk_size=metadata.chunk_size,
        compressor=metadata.compressor,
        checksum=None,
        checksum_algorithm="sha256-objects-and-files",
        created_at=metadata.created_at,
        elapsed_seconds=metadata.elapsed_seconds,
        file_count=metadata.file_count,
        total_bytes=metadata.total_bytes,
        compression_level=metadata.compression_level,
        profile=metadata.profile,
        payload_bytes=metadata.compressed_object_bytes,
        directory_count=metadata.directory_count,
        duplicate_file_count=metadata.duplicate_file_count,
        schema_version=metadata.schema_version,
        object_count=metadata.object_count,
        indexed_file_count=metadata.indexed_file_count,
        deduplicated_bytes=metadata.deduplicated_bytes,
        structured_source_count=metadata.structured_source_count,
        structured_row_count=metadata.structured_row_count,
    )


def compress_folder(
    folder: Path,
    output: Path,
    *,
    chunk_size: int = _CHUNK_SIZE,
    compressor: str = _DEFAULT_COMPRESSOR,
    zstd_level: int = 6,
    checksum_algorithm: str = "sha256",
    archive_mode: str = "solid",
    profile: Optional[str] = None,
    threads: int = 0,
    entry_order: str = "path",
    zstd_window_log: Optional[int] = None,
    zstd_long_distance: bool = False,
    whole_file_dedup: bool = False,
    index_limit: int = vault_engine.DEFAULT_INDEX_LIMIT,
) -> Metadata:
    """Create a GMW archive using a named profile or explicit engine options.

    Solid archives use the benchmark-winning streaming design, optionally
    replacing exact duplicate files with safe archive references. Legacy
    chunked archives retain v4's fixed-block SQLite layout.
    """
    if profile is not None:
        try:
            selected = COMPRESSION_PROFILES[profile]
        except KeyError as exc:
            choices = ", ".join(sorted(COMPRESSION_PROFILES))
            raise ValueError(f"Unknown compression profile '{profile}'. Choose: {choices}") from exc
        archive_mode = str(selected["archive_mode"])
        compressor = str(selected["compressor"])
        zstd_level = int(selected["level"])
        threads = int(selected["threads"])
        whole_file_dedup = bool(selected.get("whole_file_dedup", False))
        chunk_size = int(selected.get("chunk_size", chunk_size))
    else:
        profile = "custom"

    # Zlib is kept as a legacy chunked option because the solid format is
    # intentionally limited to the benchmark-winning Zstandard and XZ codecs.
    if compressor == "zlib":
        archive_mode = "chunked"
    if archive_mode == "vault":
        return _vault_metadata(
            vault_engine.create_vault(
                folder,
                output,
                level=zstd_level,
                chunk_size=chunk_size,
                index_limit=index_limit,
                profile=profile,
            )
        )
    if archive_mode == "chunked":
        metadata = _compress_chunked_folder(
            folder,
            output,
            chunk_size=chunk_size,
            compressor=compressor,
            zstd_level=zstd_level,
            checksum_algorithm=checksum_algorithm,
        )
        metadata.profile = profile
        return metadata
    if archive_mode != "solid":
        raise ValueError(f"Unsupported archive mode '{archive_mode}'")
    metadata = solid_engine.compress_folder(
        folder,
        output,
        compressor=compressor,
        level=zstd_level,
        profile=profile,
        threads=threads,
        entry_order=entry_order,
        zstd_window_log=zstd_window_log,
        zstd_long_distance=zstd_long_distance,
        whole_file_dedup=whole_file_dedup,
    )
    return _solid_metadata(metadata)


def extract_archive(archive: Path, output_dir: Path) -> Metadata:
    if solid_engine.is_solid_archive(Path(archive)):
        return _solid_metadata(solid_engine.extract_archive(Path(archive), Path(output_dir)))
    if vault_engine.is_vault_archive(Path(archive)):
        return _vault_metadata(vault_engine.extract_vault(Path(archive), Path(output_dir)))
    if is_chunked_archive(Path(archive)):
        return _extract_chunked_archive(Path(archive), Path(output_dir))
    raise _unsupported_archive(Path(archive))


def export_zip(archive: Path, output_zip: Path) -> Metadata:
    if solid_engine.is_solid_archive(Path(archive)):
        return _solid_metadata(solid_engine.export_zip(Path(archive), Path(output_zip)))
    if vault_engine.is_vault_archive(Path(archive)):
        return _vault_metadata(vault_engine.export_zip(Path(archive), Path(output_zip)))
    if is_chunked_archive(Path(archive)):
        return _export_chunked_zip(Path(archive), Path(output_zip))
    raise _unsupported_archive(Path(archive))


def read_metadata(archive: Path) -> Metadata:
    if solid_engine.is_solid_archive(Path(archive)):
        return _solid_metadata(solid_engine.read_metadata(Path(archive)))
    if vault_engine.is_vault_archive(Path(archive)):
        return _vault_metadata(vault_engine.read_metadata(Path(archive)))
    if is_chunked_archive(Path(archive)):
        return _read_chunked_metadata(Path(archive))
    raise _unsupported_archive(Path(archive))


def is_vault_archive(archive: Path) -> bool:
    return vault_engine.is_vault_archive(Path(archive))


def search_vault(
    archive: Path, query: str = "", *, extension: str = "", limit: int = 200
) -> list["vault_engine.VaultFile"]:
    return vault_engine.search_vault(
        Path(archive), query, extension=extension, limit=limit
    )


def preview_vault_file(archive: Path, stored_path: str, *, limit: int = 256 * 1024) -> str:
    return vault_engine.preview_text(Path(archive), stored_path, limit=limit)


def extract_vault_files(
    archive: Path, output_dir: Path, paths: List[str]
) -> Metadata:
    return _vault_metadata(
        vault_engine.extract_vault(Path(archive), Path(output_dir), paths=paths)
    )


def verify_vault(archive: Path) -> Metadata:
    return _vault_metadata(vault_engine.verify_vault(Path(archive)))


def list_structured_sources(
    archive: Path,
) -> list["vault_engine.structured_data.StructuredSource"]:
    return vault_engine.list_structured_sources(Path(archive))


def list_structured_columns(
    archive: Path, source_id: int
) -> list["vault_engine.structured_data.StructuredColumn"]:
    return vault_engine.list_structured_columns(Path(archive), source_id)


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
) -> "vault_engine.structured_data.StructuredQueryResult":
    return vault_engine.query_structured_source(
        Path(archive),
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
) -> "vault_engine.structured_data.StructuredQueryResult":
    return vault_engine.execute_structured_sql(Path(archive), sql, limit=limit)


def export_structured_result(result, output: Path) -> None:
    vault_engine.export_structured_result(result, Path(output))


def _cmd_compress(args: argparse.Namespace) -> None:
    compressor = _DEFAULT_COMPRESSOR if not args.no_zstd else "zlib"
    if compressor == "zstd" and not HAS_ZSTD:
        print(
            "Zstandard support is unavailable; falling back to zlib compression.",
            file=sys.stderr,
        )
        compressor = "zlib"
    meta = compress_folder(
        Path(args.folder),
        Path(args.output),
        chunk_size=args.chunk_size,
        compressor=compressor,
        zstd_level=args.zstd_level,
        checksum_algorithm=args.checksum,
        profile=None if args.no_zstd else args.profile,
    )
    print(json.dumps(meta.as_dict(), indent=2))


def _cmd_vault_create(args: argparse.Namespace) -> None:
    metadata = vault_engine.create_vault(
        Path(args.folder),
        Path(args.output),
        level=args.zstd_level,
        chunk_size=args.chunk_size,
        index_limit=args.index_limit,
        profile="vault",
    )
    print(json.dumps(metadata.as_dict(), indent=2))


def _cmd_vault_search(args: argparse.Namespace) -> None:
    results = search_vault(
        Path(args.archive), args.query, extension=args.extension, limit=args.limit
    )
    print(json.dumps([dataclasses.asdict(result) for result in results], indent=2))


def _cmd_vault_extract(args: argparse.Namespace) -> None:
    paths = args.paths or None
    metadata = vault_engine.extract_vault(
        Path(args.archive), Path(args.output), paths=paths
    )
    print(json.dumps(metadata.as_dict(), indent=2))


def _cmd_vault_verify(args: argparse.Namespace) -> None:
    metadata = vault_engine.verify_vault(Path(args.archive))
    print(json.dumps(metadata.as_dict(), indent=2))


def _structured_result_payload(result) -> Dict[str, object]:
    return {
        "columns": list(result.columns),
        "rows": [list(row) for row in result.rows],
        "truncated": result.truncated,
        "source_id": result.source_id,
    }


def _cmd_vault_tables(args: argparse.Namespace) -> None:
    sources = list_structured_sources(Path(args.archive))
    payload = []
    for source in sources:
        item = dataclasses.asdict(source)
        item["columns"] = [
            dataclasses.asdict(column)
            for column in list_structured_columns(Path(args.archive), source.id)
        ]
        payload.append(item)
    print(json.dumps(payload, indent=2))


def _cmd_vault_query(args: argparse.Namespace) -> None:
    result = query_structured_source(
        Path(args.archive),
        args.source_id,
        search=args.find,
        column=args.column,
        sort_by=args.sort,
        descending=args.descending,
        limit=args.limit,
    )
    if args.output:
        export_structured_result(result, Path(args.output))
    else:
        print(json.dumps(_structured_result_payload(result), indent=2))


def _cmd_vault_sql(args: argparse.Namespace) -> None:
    result = execute_structured_sql(Path(args.archive), args.sql, limit=args.limit)
    if args.output:
        export_structured_result(result, Path(args.output))
    else:
        print(json.dumps(_structured_result_payload(result), indent=2))


def _cmd_extract(args: argparse.Namespace) -> None:
    meta = extract_archive(Path(args.archive), Path(args.output))
    print(json.dumps(meta.as_dict(), indent=2))


def _cmd_info(args: argparse.Namespace) -> None:
    meta = read_metadata(Path(args.archive))
    print(json.dumps(meta.as_dict(), indent=2))


def _cmd_export_zip(args: argparse.Namespace) -> None:
    meta = export_zip(Path(args.archive), Path(args.output_zip))
    print(json.dumps(meta.as_dict(), indent=2))


class _ChunkHandler(http.server.BaseHTTPRequestHandler):
    def _chunk_server(self) -> "_ChunkServer":
        from typing import cast
        return cast("_ChunkServer", super().server)

    def do_GET(self) -> None:  # pragma: no cover - networking
        if self.path == "/manifest":
            srv = self._chunk_server()
            manifest = {
                "metadata": srv.metadata.as_dict(),
                "files": [
                    {
                        "path": row["path"],
                        "size": row["size"],
                        "mtime": row["mtime"],
                        "mode": row["mode"],
                        "chunk_ids": json.loads(row["chunk_ids"]),
                        "chunk_sizes": json.loads(row["chunk_sizes"]),
                    }
                    for row in srv.conn.execute("SELECT * FROM files ORDER BY ordering")
                ],
            }
            payload = json.dumps(manifest).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.startswith("/chunks/"):
            chunk_id = self.path.split("/", 2)[2]
            row = self._chunk_server().conn.execute(
                "SELECT compressor, data FROM chunks WHERE id = ?",
                (chunk_id,),
            ).fetchone()
            if row is None:
                self.send_error(404, "Chunk not found")
                return
            data = row["data"]
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Chunk-Compressor", row["compressor"])
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404, "Unknown endpoint")

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - quiet server
        return


class _ChunkServer(socketserver.TCPServer):  # pragma: no cover - networking
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, conn, metadata):
        super().__init__(server_address, RequestHandlerClass)
        self.conn = conn
        self.metadata = metadata


def serve_archive(archive: Path, host: str, port: int) -> None:
    if solid_engine.is_solid_archive(Path(archive)):
        raise ValueError(
            "HTTP chunk serving is available only for Deduplicate (SQLite) archives"
        )
    if vault_engine.is_vault_archive(Path(archive)):
        raise ValueError("HTTP serving for searchable Vaults is not available yet")
    if not is_chunked_archive(Path(archive)):
        raise _unsupported_archive(Path(archive))
    conn = _open_db(archive)
    metadata = _load_metadata(conn)
    server = _ChunkServer((host, port), _ChunkHandler, conn, metadata)
    print(f"Serving {archive} on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        conn.close()


def _cmd_serve(args: argparse.Namespace) -> None:
    serve_archive(Path(args.archive), args.host, args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rat-Trap GMW archive tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p_comp = sub.add_parser("compress", help="Compress a folder into a GMW archive")
    p_comp.add_argument("folder", help="Folder to archive")
    p_comp.add_argument("output", help="Destination .gmw file")
    p_comp.add_argument("--chunk-size", type=int, default=_CHUNK_SIZE, help="Chunk size in bytes (default: 512KiB)")
    p_comp.add_argument("--no-zstd", action="store_true", help="Disable Zstandard compression")
    p_comp.add_argument("--zstd-level", type=int, default=6, help="Custom Zstandard level")
    p_comp.add_argument(
        "--profile",
        choices=sorted(COMPRESSION_PROFILES),
        default=None,
        help="Named profile; without this option, solid Zstandard level 6 is used",
    )
    p_comp.add_argument("--checksum", choices=["sha256", "none"], default="sha256", help="Checksum algorithm")
    p_comp.set_defaults(func=_cmd_compress)

    p_vault = sub.add_parser("vault-create", help="Create a searchable SQLite Vault")
    p_vault.add_argument("folder", help="Folder to ingest")
    p_vault.add_argument("output", help="Destination Vault .gmw file")
    p_vault.add_argument(
        "--chunk-size",
        type=int,
        default=vault_engine.DEFAULT_CHUNK_SIZE,
        help="Content-addressed object size in bytes (default: 4 MiB)",
    )
    p_vault.add_argument("--zstd-level", type=int, default=6)
    p_vault.add_argument(
        "--index-limit",
        type=int,
        default=vault_engine.DEFAULT_INDEX_LIMIT,
        help="Maximum text-like file size indexed by FTS5 (default: 16 MiB)",
    )
    p_vault.set_defaults(func=_cmd_vault_create)

    p_search = sub.add_parser("vault-search", help="Search filenames and indexed text")
    p_search.add_argument("archive", help="Queryable Vault .gmw file")
    p_search.add_argument("query", nargs="?", default="", help="Words to find")
    p_search.add_argument("--extension", default="", help="Optional extension filter")
    p_search.add_argument("--limit", type=int, default=200)
    p_search.set_defaults(func=_cmd_vault_search)

    p_vault_extract = sub.add_parser(
        "vault-extract", help="Extract all or selected Vault paths"
    )
    p_vault_extract.add_argument("archive", help="Queryable Vault .gmw file")
    p_vault_extract.add_argument("output", help="Destination directory")
    p_vault_extract.add_argument("paths", nargs="*", help="Optional stored paths")
    p_vault_extract.set_defaults(func=_cmd_vault_extract)

    p_verify = sub.add_parser("vault-verify", help="Verify SQLite and every stored object")
    p_verify.add_argument("archive", help="Queryable Vault .gmw file")
    p_verify.set_defaults(func=_cmd_vault_verify)

    p_tables = sub.add_parser("vault-tables", help="List relational tables in a Vault")
    p_tables.add_argument("archive", help="Queryable Vault .gmw file")
    p_tables.set_defaults(func=_cmd_vault_tables)

    p_query = sub.add_parser("vault-query", help="Filter rows from one Vault data table")
    p_query.add_argument("archive", help="Queryable Vault .gmw file")
    p_query.add_argument("source_id", type=int, help="Source id from vault-tables")
    p_query.add_argument("--find", default="", help="Text contained in matching values")
    p_query.add_argument("--column", default="", help="Safe column name to search")
    p_query.add_argument("--sort", default="", help="Safe column name to sort")
    p_query.add_argument("--descending", action="store_true")
    p_query.add_argument("--limit", type=int, default=1000)
    p_query.add_argument("--output", help="Optional .csv, .tsv, or .json export")
    p_query.set_defaults(func=_cmd_vault_query)

    p_sql = sub.add_parser("vault-sql", help="Run a read-only SELECT against a Vault")
    p_sql.add_argument("archive", help="Queryable Vault .gmw file")
    p_sql.add_argument("sql", help="One SELECT or WITH statement")
    p_sql.add_argument("--limit", type=int, default=1000)
    p_sql.add_argument("--output", help="Optional .csv, .tsv, or .json export")
    p_sql.set_defaults(func=_cmd_vault_sql)

    p_ext = sub.add_parser("extract", help="Extract archive contents")
    p_ext.add_argument("archive", help="SQLite archive")
    p_ext.add_argument("output", help="Destination directory")
    p_ext.set_defaults(func=_cmd_extract)

    p_info = sub.add_parser("info", help="Show archive metadata")
    p_info.add_argument("archive", help="SQLite archive")
    p_info.set_defaults(func=_cmd_info)

    p_zip = sub.add_parser("export-zip", help="Export a .gmw archive to a standard .zip file")
    p_zip.add_argument("archive", help="SQLite archive")
    p_zip.add_argument("output_zip", help="Destination .zip file")
    p_zip.set_defaults(func=_cmd_export_zip)

    p_srv = sub.add_parser("serve", help="Expose archive over HTTP for remote streaming")
    p_srv.add_argument("archive", help="SQLite archive")
    p_srv.add_argument("--host", default="127.0.0.1", help="Host to bind")
    p_srv.add_argument("--port", type=int, default=8000, help="Port to bind")
    p_srv.set_defaults(func=_cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
