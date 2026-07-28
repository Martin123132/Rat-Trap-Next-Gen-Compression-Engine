"""Streaming solid-compression engine for Rat-Trap GMW archives.

The repository's v2 experiment had the strongest practical architecture: a
tar stream fed directly into a compressor.  This module turns that experiment
into a versioned, bounded-memory, safely extractable archive implementation.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import lzma
import os
import stat
import struct
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Iterator, Optional

try:
    import zstandard as zstd

    HAS_ZSTD = True
except Exception:  # pragma: no cover - optional outside packaged builds
    zstd = None  # type: ignore[assignment]
    HAS_ZSTD = False


MAGIC = b"RATGMW2\n"
FOOTER_MAGIC = b"GMWMETA2"
_LENGTH = struct.Struct("<Q")
_BUFFER_SIZE = 1024 * 1024
_MAX_METADATA_SIZE = 16 * 1024 * 1024
_MIN_DEDUP_BYTES = 4096
_PAX_ORIGINAL_SIZE = "rat_trap.original_size"
_PAX_DEDUP_REPRESENTATIVE = "rat_trap.dedup_representative"


@dataclass
class SolidMetadata:
    format: str
    compressor: str
    compression_level: int
    checksum: str
    checksum_algorithm: str
    created_at: float
    elapsed_seconds: float
    file_count: int
    directory_count: int
    total_bytes: int
    payload_bytes: int
    profile: str
    entry_order: str = "path"
    zstd_window_log: Optional[int] = None
    zstd_long_distance: bool = False
    whole_file_dedup: bool = False
    duplicate_file_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "SolidMetadata":
        try:
            values = json.loads(blob.decode("utf-8"))
            return cls(**values)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Archive has invalid Rat-Trap metadata") from exc


class _HashingSink:
    def __init__(self, raw: BinaryIO) -> None:
        self.raw = raw
        self.hasher = hashlib.sha256()
        self.bytes_written = 0

    def write(self, data: bytes | bytearray | memoryview) -> int:
        view = memoryview(data)
        self.hasher.update(view)
        written = self.raw.write(view)
        if written is None:
            written = len(view)
        if written != len(view):
            raise OSError("Short write while creating archive")
        self.bytes_written += written
        return written

    def flush(self) -> None:
        self.raw.flush()


class _LzmaWriter:
    def __init__(self, sink: _HashingSink, preset: int) -> None:
        self.sink = sink
        self.compressor = lzma.LZMACompressor(format=lzma.FORMAT_XZ, preset=preset)
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.closed:
            raise ValueError("write to closed compressor")
        compressed = self.compressor.compress(data)
        if compressed:
            self.sink.write(compressed)
        return len(data)

    def flush(self) -> None:
        self.sink.flush()

    def close(self) -> None:
        if not self.closed:
            tail = self.compressor.flush()
            if tail:
                self.sink.write(tail)
            self.sink.flush()
            self.closed = True

    def __enter__(self) -> "_LzmaWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.close()


class _LimitedHashingReader:
    def __init__(self, raw: BinaryIO, limit: int) -> None:
        self.raw = raw
        self.remaining = limit
        self.hasher = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        if size is None or size < 0 or size > self.remaining:
            size = self.remaining
        data = self.raw.read(size)
        self.remaining -= len(data)
        self.hasher.update(data)
        return data

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def is_solid_archive(path: Path) -> bool:
    try:
        with open(path, "rb") as fp:
            return fp.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _normalise_member_path(stored_path: str) -> Path:
    if not stored_path or "\0" in stored_path:
        raise ValueError("Archive contains an invalid empty path")
    windows_path = PureWindowsPath(stored_path)
    portable = PurePosixPath(stored_path.replace("\\", "/"))
    if windows_path.drive or windows_path.is_absolute() or portable.is_absolute():
        raise ValueError(f"Archive contains an absolute path: {stored_path!r}")
    if not portable.parts or any(part in {"", ".", ".."} for part in portable.parts):
        raise ValueError(f"Archive contains an unsafe path: {stored_path!r}")
    return Path(*portable.parts)


def _safe_destination(root: Path, stored_path: str) -> Path:
    resolved_root = root.resolve()
    destination = (resolved_root / _normalise_member_path(stored_path)).resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Archive path escapes the destination: {stored_path!r}") from exc
    return destination


def _iter_entries(folder: Path) -> Iterator[Path]:
    for current, dir_names, file_names in os.walk(folder, followlinks=False):
        dir_names.sort()
        file_names.sort()
        current_path = Path(current)
        for name in dir_names:
            yield current_path / name
        for name in file_names:
            yield current_path / name


def _inventory(folder: Path, entry_order: str = "path") -> tuple[list[Path], int, int, int]:
    entries = list(_iter_entries(folder))
    file_count = 0
    directory_count = 0
    total_bytes = 0
    for path in entries:
        if path.is_symlink():
            raise ValueError(f"Symbolic links are not supported: {path}")
        if path.is_dir():
            directory_count += 1
        elif path.is_file():
            file_count += 1
            total_bytes += path.stat().st_size
        else:
            raise ValueError(f"Unsupported filesystem entry: {path}")
    if entry_order == "extension":
        directories = [path for path in entries if path.is_dir()]
        files = [path for path in entries if path.is_file()]
        files.sort(
            key=lambda path: (
                path.suffix.lower(),
                path.relative_to(folder).as_posix().lower(),
            )
        )
        entries = directories + files
    elif entry_order != "path":
        raise ValueError(f"Unsupported solid archive entry order '{entry_order}'")
    return entries, file_count, directory_count, total_bytes


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            block = fp.read(_BUFFER_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _find_duplicate_files(entries: list[Path]) -> dict[Path, Path]:
    by_size: dict[int, list[Path]] = {}
    for path in entries:
        if path.is_file() and path.stat().st_size >= _MIN_DEDUP_BYTES:
            by_size.setdefault(path.stat().st_size, []).append(path)

    duplicates: dict[Path, Path] = {}
    for candidates in by_size.values():
        if len(candidates) < 2:
            continue
        representatives: dict[str, Path] = {}
        for path in candidates:
            digest = _digest_file(path)
            representative = representatives.setdefault(digest, path)
            if representative != path:
                duplicates[path] = representative
    return duplicates


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
        raise ValueError("The output archive must be saved outside the source folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_dir():
        raise ValueError(f"Output path '{output}' is a folder")
    return folder, output


def compress_folder(
    folder: Path,
    output: Path,
    *,
    compressor: str = "zstd",
    level: int = 6,
    profile: str = "balanced",
    threads: int = 0,
    entry_order: str = "path",
    zstd_window_log: Optional[int] = None,
    zstd_long_distance: bool = False,
    whole_file_dedup: bool = False,
) -> SolidMetadata:
    folder, output = _validate_create_paths(Path(folder), Path(output))
    if compressor == "zstd":
        if not HAS_ZSTD:
            raise RuntimeError("Zstandard support is unavailable")
        if not -7 <= level <= 22:
            raise ValueError("Zstandard level must be between -7 and 22")
        if zstd_window_log is not None and not 10 <= zstd_window_log <= 31:
            raise ValueError("Zstandard window log must be between 10 and 31")
    elif compressor == "xz":
        if not 0 <= level <= 9:
            raise ValueError("XZ level must be between 0 and 9")
    else:
        raise ValueError(f"Unsupported solid compressor '{compressor}'")

    started = time.time()
    entries, file_count, directory_count, total_bytes = _inventory(folder, entry_order)
    duplicate_files = _find_duplicate_files(entries) if whole_file_dedup else {}
    duplicate_representatives = set(duplicate_files.values())
    with tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".rat-trap-build", dir=output.parent, delete=False
    ) as staging_file:
        staging_path = Path(staging_file.name)

    try:
        with open(staging_path, "wb") as raw_out:
            raw_out.write(MAGIC)
            sink = _HashingSink(raw_out)
            if compressor == "zstd":
                assert zstd is not None
                if zstd_window_log is not None or zstd_long_distance:
                    parameter_overrides: dict[str, object] = {}
                    if zstd_window_log is not None:
                        parameter_overrides["window_log"] = zstd_window_log
                    if zstd_long_distance:
                        parameter_overrides["enable_ldm"] = True
                    parameters = zstd.ZstdCompressionParameters.from_level(
                        level, **parameter_overrides
                    )
                    compressor_context = zstd.ZstdCompressor(
                        compression_params=parameters, threads=threads
                    )
                else:
                    compressor_context = zstd.ZstdCompressor(level=level, threads=threads)
                stream = compressor_context.stream_writer(sink, closefd=False)
            else:
                stream = _LzmaWriter(sink, level)

            with stream:
                with tarfile.open(fileobj=stream, mode="w|", format=tarfile.PAX_FORMAT) as tf:
                    for path in entries:
                        archive_name = path.relative_to(folder).as_posix()
                        representative = duplicate_files.get(path)
                        if representative is not None:
                            info = tf.gettarinfo(str(path), arcname=archive_name)
                            info.type = tarfile.LNKTYPE
                            info.linkname = representative.relative_to(folder).as_posix()
                            info.size = 0
                            info.pax_headers[_PAX_ORIGINAL_SIZE] = str(path.stat().st_size)
                            tf.addfile(info)
                        elif path in duplicate_representatives:
                            info = tf.gettarinfo(str(path), arcname=archive_name)
                            info.pax_headers[_PAX_DEDUP_REPRESENTATIVE] = "1"
                            with open(path, "rb") as source:
                                tf.addfile(info, source)
                        else:
                            tf.add(path, arcname=archive_name, recursive=False)

            metadata = SolidMetadata(
                format="GMW-SOLID-2",
                compressor=compressor,
                compression_level=level,
                checksum=sink.hasher.hexdigest(),
                checksum_algorithm="sha256",
                created_at=started,
                elapsed_seconds=time.time() - started,
                file_count=file_count,
                directory_count=directory_count,
                total_bytes=total_bytes,
                payload_bytes=sink.bytes_written,
                profile=profile,
                entry_order=entry_order,
                zstd_window_log=zstd_window_log,
                zstd_long_distance=zstd_long_distance,
                whole_file_dedup=whole_file_dedup,
                duplicate_file_count=len(duplicate_files),
            )
            metadata_blob = json.dumps(
                metadata.as_dict(), separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            raw_out.write(metadata_blob)
            raw_out.write(_LENGTH.pack(len(metadata_blob)))
            raw_out.write(FOOTER_MAGIC)
            raw_out.flush()
            os.fsync(raw_out.fileno())
        os.replace(staging_path, output)
        return metadata
    finally:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass


def _read_layout(fp: BinaryIO) -> tuple[SolidMetadata, int]:
    fp.seek(0, os.SEEK_END)
    archive_size = fp.tell()
    minimum = len(MAGIC) + _LENGTH.size + len(FOOTER_MAGIC) + 2
    if archive_size < minimum:
        raise ValueError("File is too small to be a Rat-Trap solid archive")
    fp.seek(0)
    if fp.read(len(MAGIC)) != MAGIC:
        raise ValueError("File is not a Rat-Trap solid archive")
    fp.seek(-(_LENGTH.size + len(FOOTER_MAGIC)), os.SEEK_END)
    metadata_size = _LENGTH.unpack(fp.read(_LENGTH.size))[0]
    if fp.read(len(FOOTER_MAGIC)) != FOOTER_MAGIC:
        raise ValueError("Archive metadata footer is missing or damaged")
    if not 0 < metadata_size <= _MAX_METADATA_SIZE:
        raise ValueError("Archive metadata length is invalid")
    metadata_offset = archive_size - _LENGTH.size - len(FOOTER_MAGIC) - metadata_size
    if metadata_offset < len(MAGIC):
        raise ValueError("Archive metadata overlaps its payload")
    payload_size = metadata_offset - len(MAGIC)
    fp.seek(metadata_offset)
    metadata = SolidMetadata.from_bytes(fp.read(metadata_size))
    if metadata.format != "GMW-SOLID-2":
        raise ValueError(f"Unsupported Rat-Trap format '{metadata.format}'")
    if metadata.payload_bytes != payload_size:
        raise ValueError("Archive payload length does not match its metadata")
    if metadata.compressor not in {"zstd", "xz"}:
        raise ValueError(f"Unsupported archive compressor '{metadata.compressor}'")
    return metadata, payload_size


def read_metadata(path: Path) -> SolidMetadata:
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"Archive '{path}' not found")
    with open(path, "rb") as fp:
        metadata, _ = _read_layout(fp)
    return metadata


def _open_tar_stream(
    fp: BinaryIO, metadata: SolidMetadata, payload_size: int
) -> tuple[_LimitedHashingReader, BinaryIO, tarfile.TarFile]:
    fp.seek(len(MAGIC))
    limited = _LimitedHashingReader(fp, payload_size)
    if metadata.compressor == "zstd":
        if not HAS_ZSTD:
            raise RuntimeError("Archive requires Zstandard support")
        assert zstd is not None
        decompressed = zstd.ZstdDecompressor().stream_reader(limited, closefd=False)
    else:
        decompressed = lzma.LZMAFile(limited, mode="rb")
    tf = tarfile.open(fileobj=decompressed, mode="r|")
    return limited, decompressed, tf


def _finish_read(
    limited: _LimitedHashingReader, decompressed: BinaryIO, metadata: SolidMetadata
) -> None:
    while decompressed.read(_BUFFER_SIZE):
        pass
    if limited.remaining:
        raise ValueError("Archive contains unread or trailing payload bytes")
    digest = limited.hasher.hexdigest()
    if digest != metadata.checksum:
        raise ValueError("Archive checksum verification failed")


def _validate_tar_member(member: tarfile.TarInfo, *, allow_hardlinks: bool = False) -> None:
    if member.issym() or (member.islnk() and not allow_hardlinks):
        raise ValueError(f"Archive contains an unsupported link: {member.name!r}")
    if not (member.isfile() or member.isdir() or (allow_hardlinks and member.islnk())):
        raise ValueError(f"Archive contains an unsupported entry: {member.name!r}")


def _hardlink_size(member: tarfile.TarInfo) -> int:
    try:
        size = int(member.pax_headers[_PAX_ORIGINAL_SIZE])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Deduplicated file has invalid size metadata: {member.name!r}") from exc
    if size < 0:
        raise ValueError(f"Deduplicated file has a negative size: {member.name!r}")
    return size


def extract_archive(archive: Path, output_dir: Path) -> SolidMetadata:
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise ValueError(f"Archive '{archive}' not found")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()

    extracted_files = 0
    extracted_bytes = 0
    with open(archive, "rb") as fp:
        metadata, payload_size = _read_layout(fp)
        limited, decompressed, tf = _open_tar_stream(fp, metadata, payload_size)
        try:
            for member in tf:
                _validate_tar_member(member, allow_hardlinks=metadata.whole_file_dedup)
                destination = _safe_destination(output_dir, member.name)
                if destination == archive:
                    raise ValueError("Archive contents would overwrite the archive itself")
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                member_size = _hardlink_size(member) if member.islnk() else member.size
                if member_size < 0 or extracted_bytes + member_size > metadata.total_bytes:
                    raise ValueError("Archive expands beyond its declared size")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if member.islnk():
                    source_path = _safe_destination(output_dir, member.linkname)
                    if source_path.is_symlink() or not source_path.is_file():
                        raise ValueError(
                            f"Deduplicated file target is missing or unsafe: {member.linkname!r}"
                        )
                    if source_path.stat().st_size != member_size:
                        raise ValueError(
                            f"Deduplicated file target has the wrong size: {member.linkname!r}"
                        )
                    source = open(source_path, "rb")
                else:
                    source = tf.extractfile(member)
                    if source is None:
                        raise ValueError(f"Could not read archived file {member.name!r}")
                temporary_name: Optional[str] = None
                copied = 0
                try:
                    with source, tempfile.NamedTemporaryFile(
                        mode="wb",
                        prefix=f".{destination.name}.",
                        suffix=".rat-trap-part",
                        dir=destination.parent,
                        delete=False,
                    ) as out_fp:
                        temporary_name = out_fp.name
                        while True:
                            block = source.read(_BUFFER_SIZE)
                            if not block:
                                break
                            copied += len(block)
                            if copied > member_size:
                                raise ValueError(f"Archived file exceeds declared size: {member.name!r}")
                            out_fp.write(block)
                    if copied != member_size:
                        raise ValueError(f"Archived file is truncated: {member.name!r}")
                    os.replace(temporary_name, destination)
                    temporary_name = None
                finally:
                    if temporary_name:
                        try:
                            os.unlink(temporary_name)
                        except FileNotFoundError:
                            pass
                extracted_files += 1
                extracted_bytes += copied
                try:
                    os.utime(destination, (member.mtime, member.mtime))
                    os.chmod(destination, stat.S_IMODE(member.mode))
                except OSError:
                    pass
            _finish_read(limited, decompressed, metadata)
        finally:
            tf.close()
            decompressed.close()

    if extracted_files != metadata.file_count or extracted_bytes != metadata.total_bytes:
        raise ValueError("Archive contents do not match the declared inventory")
    return metadata


def export_zip(archive: Path, output_zip: Path) -> SolidMetadata:
    archive = Path(archive).resolve()
    output_zip = Path(output_zip).resolve()
    if not archive.is_file():
        raise ValueError(f"Archive '{archive}' not found")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.is_dir():
        raise ValueError(f"Output path '{output_zip}' is a folder")
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_zip.name}.", suffix=".rat-trap-build", dir=output_zip.parent, delete=False
    ) as staging_file:
        staging_path = Path(staging_file.name)

    try:
        file_count = 0
        total_bytes = 0
        with tempfile.TemporaryDirectory(prefix="rat-trap-export-cache-") as cache_name, open(
            archive, "rb"
        ) as fp, zipfile.ZipFile(
            staging_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as out_zip:
            cache_root = Path(cache_name)
            dedup_sources: dict[str, Path] = {}
            metadata, payload_size = _read_layout(fp)
            limited, decompressed, tf = _open_tar_stream(fp, metadata, payload_size)
            try:
                for member in tf:
                    _validate_tar_member(member, allow_hardlinks=metadata.whole_file_dedup)
                    if member.isdir():
                        continue
                    safe_name = _normalise_member_path(member.name).as_posix()
                    member_size = _hardlink_size(member) if member.islnk() else member.size
                    if member.islnk():
                        link_name = _normalise_member_path(member.linkname).as_posix()
                        cached_source = dedup_sources.get(link_name)
                        if cached_source is None or not cached_source.is_file():
                            raise ValueError(
                                f"Deduplicated file target is missing or unsafe: {member.linkname!r}"
                            )
                        if cached_source.stat().st_size != member_size:
                            raise ValueError(
                                f"Deduplicated file target has the wrong size: {member.linkname!r}"
                            )
                        source = open(cached_source, "rb")
                    else:
                        source = tf.extractfile(member)
                        if source is None:
                            raise ValueError(f"Could not read archived file {member.name!r}")
                    info = zipfile.ZipInfo(safe_name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (stat.S_IMODE(member.mode) & 0xFFFF) << 16
                    date_time = time.localtime(float(member.mtime))[:6]
                    if date_time[0] >= 1980:
                        info.date_time = date_time
                    copied = 0
                    cache_target: Optional[BinaryIO] = None
                    cache_path: Optional[Path] = None
                    if member.pax_headers.get(_PAX_DEDUP_REPRESENTATIVE) == "1":
                        cache_path = cache_root / f"representative-{len(dedup_sources):08d}.bin"
                        cache_target = open(cache_path, "wb")
                    try:
                        with source, out_zip.open(info, "w", force_zip64=True) as target:
                            while True:
                                block = source.read(_BUFFER_SIZE)
                                if not block:
                                    break
                                copied += len(block)
                                if copied > member_size:
                                    raise ValueError(
                                        f"Archived file exceeds declared size: {member.name!r}"
                                    )
                                target.write(block)
                                if cache_target is not None:
                                    cache_target.write(block)
                    finally:
                        if cache_target is not None:
                            cache_target.close()
                    if copied != member_size:
                        raise ValueError(f"Archived file is truncated: {member.name!r}")
                    if cache_path is not None:
                        dedup_sources[safe_name] = cache_path
                    file_count += 1
                    total_bytes += copied
                _finish_read(limited, decompressed, metadata)
            finally:
                tf.close()
                decompressed.close()
        if file_count != metadata.file_count or total_bytes != metadata.total_bytes:
            raise ValueError("Archive contents do not match the declared inventory")
        os.replace(staging_path, output_zip)
        return metadata
    finally:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass
