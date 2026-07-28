"""Deprecated compatibility facade for the historical v4 module path.

The old standalone implementation duplicated the GMW-SQLITE-1 reader and
could process unknown SQLite families or unsafe stored paths. Keeping that
implementation installed would leave a second, weaker extraction route.

Imports of ``rat_trap.gmw_tool_v4`` now delegate to the maintained reader while
preserving v4's default of creating a fixed-block SQLite archive.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    from . import gmw_tool as _current
except ImportError:  # Allows direct execution while developing.
    import gmw_tool as _current  # type: ignore


HAS_ZSTD = _current.HAS_ZSTD
_CHUNK_SIZE = 512 * 1024
_DEFAULT_COMPRESSOR = "zstd" if HAS_ZSTD else "zlib"
_LEGACY_METADATA_KEYS = frozenset(
    {
        "format",
        "chunk_size",
        "compressor",
        "checksum",
        "checksum_algorithm",
        "created_at",
        "elapsed_seconds",
        "file_count",
        "total_bytes",
    }
)


@dataclass
class Metadata:
    """The original nine-field v4 metadata API."""

    format: str
    chunk_size: int
    compressor: str
    checksum: Optional[str]
    checksum_algorithm: str
    created_at: float
    elapsed_seconds: float
    file_count: int
    total_bytes: int

    def as_dict(self) -> Dict[str, object]:
        return dataclasses.asdict(self)


def _legacy_metadata(metadata: "_current.Metadata") -> Metadata:
    return Metadata(
        format=metadata.format,
        chunk_size=metadata.chunk_size,
        compressor=metadata.compressor,
        checksum=metadata.checksum,
        checksum_algorithm=metadata.checksum_algorithm,
        created_at=metadata.created_at,
        elapsed_seconds=metadata.elapsed_seconds,
        file_count=metadata.file_count,
        total_bytes=metadata.total_bytes,
    )


def compress_folder(
    folder: Path,
    output: Path,
    *,
    chunk_size: int = _CHUNK_SIZE,
    compressor: str = _DEFAULT_COMPRESSOR,
    zstd_level: int = 3,
    checksum_algorithm: str = "sha256",
) -> Metadata:
    # Use the maintained low-level writer so the historical v4 arguments
    # (including zlib and an explicit Zstandard level) retain their meaning.
    output = Path(output)
    current_metadata = _current._compress_chunked_folder(
        Path(folder),
        output,
        chunk_size=chunk_size,
        compressor=compressor,
        zstd_level=zstd_level,
        checksum_algorithm=checksum_algorithm,
        metadata_keys=_LEGACY_METADATA_KEYS,
    )
    return _legacy_metadata(current_metadata)


def extract_archive(archive: Path, output_dir: Path) -> Metadata:
    return _legacy_metadata(
        _current.extract_archive(Path(archive), Path(output_dir))
    )


def read_metadata(archive: Path) -> Metadata:
    return _legacy_metadata(_current.read_metadata(Path(archive)))


def serve_archive(archive: Path, host: str, port: int) -> None:
    _current.serve_archive(Path(archive), host, port)


def _cmd_compress(args: argparse.Namespace) -> None:
    compressor = "zlib" if args.no_zstd else _DEFAULT_COMPRESSOR
    metadata = compress_folder(
        Path(args.folder),
        Path(args.output),
        chunk_size=args.chunk_size,
        compressor=compressor,
        zstd_level=args.zstd_level,
        checksum_algorithm=args.checksum,
    )
    print(json.dumps(metadata.as_dict(), indent=2))


def _cmd_extract(args: argparse.Namespace) -> None:
    print(
        json.dumps(
            extract_archive(Path(args.archive), Path(args.output)).as_dict(),
            indent=2,
        )
    )


def _cmd_info(args: argparse.Namespace) -> None:
    print(json.dumps(read_metadata(Path(args.archive)).as_dict(), indent=2))


def _cmd_serve(args: argparse.Namespace) -> None:
    serve_archive(Path(args.archive), args.host, args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deprecated Rat-Trap v4 compatibility interface"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    compress = subcommands.add_parser("compress")
    compress.add_argument("folder")
    compress.add_argument("output")
    compress.add_argument("--chunk-size", type=int, default=_CHUNK_SIZE)
    compress.add_argument("--no-zstd", action="store_true")
    compress.add_argument("--zstd-level", type=int, default=3)
    compress.add_argument(
        "--checksum", choices=["sha256", "none"], default="sha256"
    )
    compress.set_defaults(func=_cmd_compress)

    extract = subcommands.add_parser("extract")
    extract.add_argument("archive")
    extract.add_argument("output")
    extract.set_defaults(func=_cmd_extract)

    info = subcommands.add_parser("info")
    info.add_argument("archive")
    info.set_defaults(func=_cmd_info)

    serve = subcommands.add_parser("serve")
    serve.add_argument("archive")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


__all__ = [
    "HAS_ZSTD",
    "Metadata",
    "build_parser",
    "compress_folder",
    "extract_archive",
    "main",
    "read_metadata",
    "serve_archive",
]


if __name__ == "__main__":
    main()
