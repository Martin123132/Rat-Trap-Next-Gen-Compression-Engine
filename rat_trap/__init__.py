"""Rat-Trap compression toolkit."""
try:
    from .gmw_tool import (
    Metadata,
    build_parser,
    compress_folder,
    extract_archive,
    main,
    read_metadata,
    serve_archive,
)
except ImportError:
    from gmw_tool import (
    Metadata, 
    build_parser,
    compress_folder,
    extract_archive,
    main,
    read_metadata,
    serve_archive,
)
__all__ = [
    "Metadata",
    "build_parser",
    "compress_folder",
    "extract_archive",
    "main",
    "read_metadata",
    "serve_archive",
]